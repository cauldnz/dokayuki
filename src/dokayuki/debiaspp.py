"""Debias++ (Algorithm 1 of Guan, Mouatadid et al. 2026) and its (s, d*) tuner.

For a target week start t* and quantile k:
    S  = training dates t <= t* - gt_delta with floor((t*-t) mod 365.242199) within ``margin``
         of 0 and floor((t*-t)/365.242199) < years
    P  = clip( Fbar[t*](k) + mean_{t in S} (O[t](k) - Fbar[t](k)), 0, 1 )
where Fbar is F averaged over the last d* available issuance dates (d* = 1 -> F itself).

All quantiles k and all targets are handled at once: F and O are (time, k, target).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import xarray as xr

from .thresholds import K_DIM, TIME
from .weekly import training_mask

CANDIDATES = ((14, 1), (28, 1), (35, 1))


def rolling_issuance_mean(F: xr.DataArray, days: int) -> xr.DataArray:
    """Average F over the last ``days`` calendar days of available issuances (reference ``-d``)."""
    if days <= 1:
        return F
    avail = F[TIME]
    daily = F.resample({TIME: "1D"}).mean()
    r = daily.rolling({TIME: int(days)}, min_periods=1, center=False).mean()
    return r.sel({TIME: avail})


def debiaspp(F: xr.DataArray, O: xr.DataArray, targets: pd.DatetimeIndex, gt_delta: int,
             margin_in_days: int | None = 35, years: int | None = 20, days: int = 1,
             fit_intercept: bool = True, causal_issuance: bool = True, lead: int | None = None) -> xr.DataArray:
    """Debias++ predictions P[time=targets, k, target]. Targets without F are NaN.

    ``causal_issuance`` drops training rows whose model run (``F.issue``) was issued after the
    target's init date (requires ``lead``); set False to reproduce the reference repo exactly.
    """
    if causal_issuance and (lead is None or "issue" not in F.coords):
        raise ValueError("causal_issuance needs lead and an F.issue coordinate")
    F = rolling_issuance_mean(F.transpose(TIME, K_DIM, ...), days)
    O = O.transpose(TIME, K_DIM, ...)
    Fa, Oa = xr.align(F, O, join="inner")
    bias = (Oa - Fa)
    btimes = bias.get_index(TIME)
    bvals = bias.values
    bissue = Fa["issue"].values if causal_issuance else None
    fdelta = (lead - 1) if causal_issuance else None
    ftimes = F.get_index(TIME)
    fvals = F.values
    out = np.full((len(targets),) + fvals.shape[1:], np.nan)
    for i, t in enumerate(targets):
        if t not in ftimes:
            continue
        j = ftimes.get_loc(t)
        if causal_issuance and F["issue"].values[j] > np.datetime64(t - pd.Timedelta(days=fdelta)):
            continue  # the only model run for this target was issued after its init date
        pred = fvals[j].copy()
        if fit_intercept:
            m = training_mask(t, btimes, gt_delta, margin_in_days, years, bissue, fdelta)
            if not m.any():
                continue
            with np.errstate(invalid="ignore"):
                pred = pred + np.nanmean(bvals[m], axis=0)
        out[i] = np.clip(pred, 0.0, 1.0)
    coords = {TIME: targets, K_DIM: F[K_DIM]}
    for d in F.dims[2:]:
        coords[d] = F[d]
    return xr.DataArray(out, dims=F.dims, coords=coords, name="debiaspp")


@dataclass
class TunedDebias:
    pred: xr.DataArray            # (time, k, target)
    choice: xr.DataArray          # (time, k[, target]) index into candidates
    candidates: tuple


def tune_debiaspp(F: xr.DataArray, O: xr.DataArray, targets: pd.DatetimeIndex, gt_delta: int,
                  candidates=CANDIDATES, years: int = 20, tune_years: int = 3,
                  scope: str = "pooled", weights: xr.DataArray | None = None,
                  causal_issuance: bool = True, lead: int | None = None) -> TunedDebias:
    """Pick (margin, days) per target date and k by the lowest mean Brier score over the previous
    ``tune_years`` years (reference tuner). ``scope`` is "pooled" (one choice for all targets,
    cos-lat weighted if ``weights`` is given — the reference behaviour for maps) or "per_target".
    """
    F = F.transpose(TIME, K_DIM, ...)
    O = O.transpose(TIME, K_DIM, ...)
    ftimes = F.get_index(TIME)
    first_tune = min(targets) - pd.DateOffset(years=tune_years) - pd.Timedelta(days=gt_delta + 40)
    eval_times = ftimes[(ftimes >= first_tune)]
    all_times = eval_times.union(pd.DatetimeIndex(targets))
    preds = [debiaspp(F, O, all_times, gt_delta, margin_in_days=s, years=years, days=d,
                      causal_issuance=causal_issuance, lead=lead)
             for (s, d) in candidates]
    # tuning scores: a candidate's Brier at an evaluation date is only usable once that date's
    # truth is observed (handled by training_mask) and, causally, once its model run was issued
    eissue = F.reindex({TIME: all_times})["issue"].values if causal_issuance else None
    fdelta = (lead - 1) if causal_issuance else None
    Oe = O.reindex({TIME: all_times})
    briers = [((p - Oe) ** 2) for p in preds]  # (time, k, target)
    if scope == "pooled":
        if weights is not None:
            briers = [b.weighted(weights.fillna(0)).mean(F.dims[2:]) for b in briers]
        else:
            briers = [b.mean(F.dims[2:], skipna=True) for b in briers]
    B = xr.concat(briers, dim="cand")  # (cand, time, k[, target])
    btimes = B.get_index(TIME)
    bvals = B.values
    P = xr.concat(preds, dim="cand").values  # (cand, time, k, target)
    out = np.full(P.shape[1:], np.nan)
    choice = np.full(bvals.shape[1:], -1, dtype=int)
    for t in targets:
        i = all_times.get_loc(t)
        m = training_mask(t, btimes, gt_delta, None, tune_years, eissue, fdelta)
        if not m.any():
            continue
        with np.errstate(invalid="ignore"):
            score = np.nanmean(bvals[:, m], axis=1)  # (cand, k[, target])
        score = np.where(np.isnan(score), np.inf, score)
        best = np.argmin(score, axis=0)
        choice[i] = best
        if scope == "pooled":
            for kk in range(P.shape[2]):
                out[i, kk] = P[best[kk], i, kk]
        else:
            out[i] = np.take_along_axis(P[:, i], best[None], axis=0)[0]
    sel = np.array([all_times.get_loc(t) for t in targets])
    pred = xr.DataArray(out[sel], dims=F.dims, coords={**{TIME: targets, K_DIM: F[K_DIM]},
                                                      **{d: F[d] for d in F.dims[2:]}}, name="debiaspp_tuned")
    ch_dims = (TIME, K_DIM) + (tuple(F.dims[2:]) if scope != "pooled" else ())
    ch = xr.DataArray(choice[sel], dims=ch_dims, coords={d: pred[d] for d in ch_dims})
    return TunedDebias(pred=pred, choice=ch, candidates=tuple(candidates))
