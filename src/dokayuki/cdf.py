"""Ensemble members -> cumulative probabilities F(k) = mean_m 1[yhat_m < q(k)].

Also builds JMA-style lagged ensembles (pool the last N daily runs) and places reforecast
CDFs at their hindcast target dates so forecasts and reforecasts share one ``time`` axis.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr

from .thresholds import K_DIM, TIME
from .weekly import forecast_delta

MEMBER = "member"


def members_to_cdf(members: xr.DataArray, thr: xr.DataArray) -> xr.DataArray:
    """F[time, k, target] from members[time, member, target] and thresholds[time, k, target].

    NaN members are ignored (mean over available members); a time with no valid member is NaN.
    """
    m, q = xr.align(members, thr, join="inner")
    below = (m < q).where(m.notnull())
    f = below.mean(MEMBER, skipna=True)
    return f.transpose(TIME, K_DIM, ...).rename("cdf")


def members_to_cdf_by_issue(members: xr.DataArray, thr_by_issue: xr.DataArray) -> xr.DataArray:
    """F[time, k, target] for rows that carry an ``issue`` coordinate (reforecast rows placed on a
    time axis with duplicates): thresholds are looked up per row by its issuance date (model
    thresholds), so no alignment on ``time`` is needed."""
    iss = members["issue"].values
    have = thr_by_issue.get_index("issue")
    keep = np.isin(iss, have.values)
    m = members.isel({TIME: keep})
    q = thr_by_issue.sel(issue=xr.DataArray(m["issue"].values, dims=[TIME]))     # (time, k, target)
    q = q.drop_vars("issue", errors="ignore").assign_coords({TIME: m[TIME].values})
    mv = m.transpose(TIME, MEMBER, ...).values[:, :, None, :]
    qv = q.transpose(TIME, K_DIM, ...).values[:, None, :, :]
    below = (mv < qv).astype("float64")
    below[np.isnan(mv).repeat(qv.shape[2], axis=2)] = np.nan
    with np.errstate(invalid="ignore"):
        f = np.nanmean(below, axis=1)
    out = xr.DataArray(f, dims=(TIME, K_DIM) + tuple(d for d in m.dims if d not in (TIME, MEMBER)),
                       coords={TIME: m[TIME].values, K_DIM: thr_by_issue[K_DIM].values, **{d: m[d] for d in m.dims if d not in (TIME, MEMBER)}})
    for c in ("origin", "issue"):
        if c in m.coords:
            out = out.assign_coords({c: (TIME, m[c].values)})
    return out.rename("cdf")


def reforecast_to_time(reforecast: xr.DataArray, lead: int) -> xr.DataArray:
    """(issue, hyear, member, target) -> (time, member, target) with time = hindcast target start.

    ``hyear`` holds the (negative) year delta relative to the issue year, as in the reference
    (``year_delta`` = -20..-1), or absolute hindcast years (>= 1900). Feb 29 -> Feb 28.
    """
    issues = reforecast.get_index("issue")
    hy = reforecast["hyear"].values.astype(int)
    iy = np.repeat(issues.year.values, len(hy)); im = np.repeat(issues.month.values, len(hy))
    idd = np.repeat(issues.day.values, len(hy))
    hyt = np.tile(hy, len(issues))
    year = np.where(hyt >= 1900, hyt, iy + hyt)
    leap = (year % 4 == 0) & ((year % 100 != 0) | (year % 400 == 0))
    day = np.where((im == 2) & (idd == 29) & ~leap, 28, idd)
    hind_init = pd.to_datetime(pd.DataFrame({"year": year, "month": im, "day": day}))
    t = pd.DatetimeIndex(hind_init) + pd.Timedelta(days=forecast_delta(lead))
    da = reforecast.stack({TIME: ("issue", "hyear")}).transpose(TIME, ...)
    issue_rt = np.repeat(issues.values, len(hy))
    da = da.drop_vars(["issue", "hyear", TIME]).assign_coords({TIME: t.values})
    da = da.assign_coords(origin=(TIME, np.array(["reforecast"] * len(t))), issue=(TIME, issue_rt))
    da = da.dropna(TIME, how="all")
    return da.sortby(TIME)


def forecast_to_time(forecast: xr.DataArray, lead: int) -> xr.DataArray:
    """(issue, member, target) -> (time, member, target) with time = issue + lead - 1."""
    t = pd.DatetimeIndex((forecast.get_index("issue") + pd.Timedelta(days=forecast_delta(lead))).values)
    issue = forecast.get_index("issue").values
    da = forecast.rename({"issue": TIME}).assign_coords({TIME: t.values})
    return da.assign_coords(origin=(TIME, np.array(["forecast"] * len(t))), issue=(TIME, issue)).sortby(TIME)


def combine_forecast_reforecast(fc: xr.DataArray | None, rf: xr.DataArray | None,
                                prefer: str = "forecast", reforecast_keep: str = "first") -> xr.DataArray:
    """Union on time with one entry per time.

    Where a forecast and a reforecast share a target start, keep ``prefer`` (reference: the real
    forecast). Where several reforecasts share a hindcast target start (same month-day issued
    in different years), keep the one from the earliest (``"first"``, Debias++ reference) or
    latest (``"last"``, Persistence++ reference) issuance. Reforecasts must be ordered by issue.
    """
    parts = [p for p in (fc, rf) if p is not None]
    if not parts:
        raise ValueError("nothing to combine")
    allt = xr.concat(parts, dim=TIME) if len(parts) > 1 else parts[0]
    origins = allt["origin"].values if "origin" in allt.coords else np.array(["forecast"] * allt.sizes[TIME])
    idx = allt.get_index(TIME)
    # rank: preferred origin first, then issuance order (position) ascending or descending
    pos = np.arange(len(idx))
    pref = (origins != prefer).astype(int)
    order_key = pos if reforecast_keep == "first" else -pos
    order = np.lexsort((order_key, pref, idx.values))
    sorted_times = idx.values[order]
    first_of_time = np.concatenate([[True], sorted_times[1:] != sorted_times[:-1]])
    keep_idx = np.sort(order[first_of_time])
    return allt.isel({TIME: keep_idx})


def lagged_ensemble(members_by_issue: xr.DataArray, n_runs: int, lead: int) -> xr.DataArray:
    """Pool the last ``n_runs`` daily runs (issue, member, target) into one super-ensemble.

    Each older run is used at a longer lead so that all members verify on the same target
    week: run issued d days earlier contributes its ``lead + d`` week. ``members_by_issue``
    must carry a ``lead`` dimension covering lead..lead+n_runs-1. Output: (issue, member', target)
    for the newest issue date in each pool, with time = newest issue + lead - 1.
    """
    issues = members_by_issue.get_index("issue")
    out, kept = [], []
    for t in issues:
        parts = []
        for d in range(n_runs):
            ti = t - pd.Timedelta(days=d)
            if ti in issues and (lead + d) in members_by_issue["lead"].values:
                parts.append(members_by_issue.sel(issue=ti, lead=lead + d, drop=True))
        if not parts:
            continue
        pooled = xr.concat(parts, dim=MEMBER)
        pooled = pooled.assign_coords({MEMBER: np.arange(pooled.sizes[MEMBER])})
        out.append(pooled)
        kept.append(t)
    da = xr.concat(out, dim="issue").assign_coords(issue=pd.DatetimeIndex(kept))
    return da


def climatology_cdf(K: int, like: xr.DataArray) -> xr.DataArray:
    """The constant k/K climatological CDF with the shape of ``like`` (time, k, target)."""
    levels = xr.DataArray(np.arange(1, K) / K, dims=[K_DIM], coords={K_DIM: np.arange(1, K)})
    return (xr.zeros_like(like) + levels).transpose(TIME, K_DIM, ...)
