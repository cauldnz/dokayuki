"""Persistence++ (Algorithm 2): one rolling least-squares regression per (target, k, lead).

Features for target week t (reference ``perpp_ecmwf/batch_predict.py``):
    O[t - gt_delta], O[t - (gt_delta + lead - 1)], F[t], C[t], 1
where C is the 20-year rolling probabilistic climatology of O. Training rows are all weeks
t' <= t* - gt_delta with every feature and the label observed. Sufficient statistics X'X and
X'y are accumulated as target dates advance; solve with np.linalg.solve, fall back to lstsq.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr

from .thresholds import K_DIM, TIME

FEATURES = ("lag1", "lag2", "model", "clim", "ones")


def rolling_climatology(O: xr.DataArray, K: int, years: int = 20, margin: int = 4) -> xr.DataArray:
    """20-year rolling climatology of the indicator O (time, k, target), reference semantics:

    pad back to Jan 1 of (first_year - years + 1) with k/K, drop Feb 29, for each month-day take
    the rolling mean over ``years`` years (full windows only), shift forward one year so a date
    only sees prior years, then a centred (2*margin+1)-day positional mean (full windows only).
    """
    O = O.transpose(TIME, K_DIM, ...)
    tindex = O.get_index(TIME)
    first = tindex[0].replace(year=tindex[0].year - (years - 1), month=1, day=1)
    full = pd.date_range(first, tindex[-1], freq="D")
    fill = (O[K_DIM].astype("float64") / K)
    padded = O.reindex({TIME: full})
    padded = padded.where(padded.notnull(), fill)  # missing -> k/K
    keep = ~((full.month == 2) & (full.day == 29))
    padded = padded.isel({TIME: keep})
    t = padded.get_index(TIME)
    md = t.strftime("%m-%d")
    vals = padded.values
    rolled = np.full_like(vals, np.nan)
    for key in np.unique(md):
        idx = np.where(md == key)[0]
        x = vals[idx]
        # rolling mean over the year axis with full windows
        cs = np.cumsum(np.concatenate([np.zeros((1,) + x.shape[1:]), x], axis=0), axis=0)
        if len(idx) >= years:
            r = (cs[years:] - cs[:-years]) / years
            rolled[idx[years - 1:]] = r
    # shift forward one year: value computed at date d is used for d + 1 year
    shifted_times = pd.DatetimeIndex([d.replace(year=d.year + 1) for d in t])
    clim = xr.DataArray(rolled, dims=padded.dims, coords={**padded.coords, TIME: shifted_times})
    clim = clim.dropna(TIME, how="all")
    # centred positional rolling mean over 2*margin+1 entries (no Feb 29 in the index)
    w = 2 * margin + 1
    v = clim.values
    cs = np.cumsum(np.concatenate([np.zeros((1,) + v.shape[1:]), v], axis=0), axis=0)
    sm = np.full_like(v, np.nan)
    if len(v) >= w:
        sm[margin:len(v) - margin] = (cs[w:] - cs[:-w]) / w
    out = xr.DataArray(sm, dims=clim.dims, coords=clim.coords, name="clim").dropna(TIME, how="all")
    return out


def _shifted(O: xr.DataArray, shift_days: int) -> xr.DataArray:
    """Value observed ``shift_days`` before each time, placed at that time."""
    t = O.get_index(TIME) + pd.Timedelta(days=shift_days)
    return O.assign_coords({TIME: t})


def build_features(F: xr.DataArray, O: xr.DataArray, C: xr.DataArray, gt_delta: int, lead: int) -> xr.DataArray:
    """Design array X[time, k, target, feature] on the union of times; NaN where unavailable."""
    F = F.transpose(TIME, K_DIM, ...)
    O = O.transpose(TIME, K_DIM, ...)
    lag1 = _shifted(O, gt_delta)
    lag2 = _shifted(O, gt_delta + lead - 1)
    # reference: features are joined with how="right" on the lags, inner on F; here we use an
    # outer join and let NaN rows drop at fit/predict time, which is equivalent.
    parts = xr.align(lag1, lag2, F, C.transpose(TIME, K_DIM, ...), join="outer")
    X = xr.concat(list(parts) + [xr.ones_like(parts[2])], dim="feature")
    X = X.assign_coords(feature=list(FEATURES)).transpose(TIME, K_DIM, ..., "feature")
    return X


def persistpp(F: xr.DataArray, O: xr.DataArray, targets: pd.DatetimeIndex, gt_delta: int, lead: int,
              K: int, clim_years: int = 20, clim_margin: int = 4,
              C: xr.DataArray | None = None, return_coefs: bool = False, causal_issuance: bool = True):
    """Persistence++ predictions P[time=targets, k, target] (clipped to [0, 1]).

    A training row at week t is "ready" for target t* once t <= t* - gt_delta and, with
    ``causal_issuance``, once its model run was issued on or before t*'s init date.
    """
    if C is None:
        C = rolling_climatology(O, K, years=clim_years, margin=clim_margin)
    X = build_features(F, O, C, gt_delta, lead)
    y = O.reindex({TIME: X[TIME]}).transpose(TIME, K_DIM, ...)
    xt = X.get_index(TIME)
    ready = (xt + pd.Timedelta(days=gt_delta)).values
    if causal_issuance:
        if "issue" not in F.coords:
            raise ValueError("causal_issuance needs an F.issue coordinate")
        issue = F.reindex({TIME: xt})["issue"].values
        issue_ready = issue + np.timedelta64(lead - 1, "D")
        ready = np.where(np.isnat(issue), ready, np.maximum(ready, issue_ready))
    Xv = X.values                                  # (T, k, target, p)
    yv = y.values                                  # (T, k, target)
    T, nk, nt, p = Xv.shape
    valid_x = ~np.isnan(Xv).any(axis=-1)           # (T, k, target)
    valid_row = valid_x & ~np.isnan(yv)
    Xz = np.where(valid_row[..., None], Xv, 0.0)
    yz = np.where(valid_row, yv, 0.0)
    XtX = np.zeros((nk, nt, p, p))
    Xty = np.zeros((nk, nt, p))
    n_train = np.zeros((nk, nt), dtype=int)
    targets = pd.DatetimeIndex(sorted(targets))
    out = np.full((len(targets), nk, nt), np.nan)
    coefs = np.full((len(targets), nk, nt, p), np.nan)
    last_stored = None
    for i, t in enumerate(targets):
        t64 = np.datetime64(t)
        block = (ready <= t64) if last_stored is None else ((ready <= t64) & (ready > last_stored))
        last_stored = t64
        if block.any():
            Xb, yb = Xz[block], yz[block]
            XtX += np.einsum("tkgi,tkgj->kgij", Xb, Xb)
            Xty += np.einsum("tkgi,tkg->kgi", Xb, yb)
            n_train += valid_row[block].sum(axis=0)
        if t not in xt:
            continue
        if causal_issuance and issue_ready[xt.get_loc(t)] > t64:
            continue  # model run for this target issued after its init date
        xrow = Xv[xt.get_loc(t)]                   # (k, target, p)
        for kk in range(nk):
            for g in range(nt):
                if n_train[kk, g] == 0 or not valid_x[xt.get_loc(t), kk, g]:
                    continue
                try:
                    coef = np.linalg.solve(XtX[kk, g], Xty[kk, g])
                except np.linalg.LinAlgError:
                    coef = np.linalg.lstsq(XtX[kk, g], Xty[kk, g], rcond=None)[0]
                coefs[i, kk, g] = coef
                out[i, kk, g] = float(xrow[kk, g] @ coef)
    out = np.clip(out, 0.0, 1.0)
    coords = {TIME: targets, K_DIM: X[K_DIM], **{d: X[d] for d in X.dims[2:-1]}}
    pred = xr.DataArray(out, dims=X.dims[:-1], coords=coords, name="persistpp")
    if return_coefs:
        cf = xr.DataArray(coefs, dims=X.dims, coords={**coords, "feature": list(FEATURES)})
        return pred, cf
    return pred
