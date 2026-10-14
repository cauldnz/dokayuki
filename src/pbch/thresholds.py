"""Observed (ERA5) and model (hindcast) quantile thresholds q[t, k, target].

Observed thresholds (reference ``era5-percentiles.py``): for target date t, the k/K quantile
of weekly truth values at t shifted by each of the previous ``years`` years and by each day
offset in ``offsets`` (default -4, -2, 0, +2, +4).

Model thresholds (reference ``ecmwf-quintiles.py``): quantiles of the model's own reforecasts
pooled over the 9 base dates around the issuance date (latest reforecast date <= issue, plus
4 before and 4 after), all hindcast years and all members.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr

from .weekly import shift_years

K_DIM = "k"
TIME = "time"


def quantile_levels(K: int) -> np.ndarray:
    return np.arange(1, K) / K


def observed_thresholds(truth: xr.DataArray, K: int, times: pd.DatetimeIndex | None = None,
                        years: int = 20, offsets=(-4, -2, 0, 2, 4)) -> xr.DataArray:
    """q[time, k, target] for the requested ``times`` (default: every time with a full window)."""
    truth = truth.transpose(TIME, ...)
    tindex = truth.get_index(TIME)
    if times is None:
        first = shift_years(tindex[:1], years)[0] + pd.Timedelta(days=max(offsets))
        times = tindex[tindex >= first]
    levels = quantile_levels(K)
    n_t = len(times)
    other = [d for d in truth.dims if d != TIME]
    out = np.full((n_t, K - 1) + tuple(truth.sizes[d] for d in other), np.nan, dtype="float64")
    vals = truth.values
    pos = pd.Series(np.arange(len(tindex)), index=tindex)
    times = pd.DatetimeIndex(times)
    # gather the (years * offsets) sample rows for every target date at once
    rows = np.full((len(times), years * len(offsets)), -1, dtype=int)
    c = 0
    for y in range(-years, 0):
        base = shift_years(times, y)
        for off in offsets:
            d = base + pd.Timedelta(days=off)
            rows[:, c] = pos.reindex(d).fillna(-1).values.astype(int)
            c += 1
    complete = (rows >= 0).all(axis=1)
    for i in np.where(complete)[0]:
        out[i] = np.nanquantile(vals[rows[i]], levels, axis=0)
    coords = {TIME: times, K_DIM: np.arange(1, K)}
    for d in other:
        coords[d] = truth[d]
    return xr.DataArray(out, dims=(TIME, K_DIM) + tuple(other), coords=coords, name="threshold")


def model_thresholds(reforecast: xr.DataArray, K: int, issue_dates: pd.DatetimeIndex,
                     n_before: int = 4, n_after: int = 4) -> xr.DataArray:
    """q[issue, k, target] from pooled reforecasts.

    ``reforecast`` has dims (issue, hyear, member, target) with ``issue`` the reforecast base
    date (real-time issuance date whose on-the-fly reforecasts these are, or the fixed
    hindcast date for JMA) — weekly values for one lead.
    """
    base_dates = reforecast.get_index("issue")
    levels = quantile_levels(K)
    out = []
    kept = []
    for t in issue_dates:
        preceding = base_dates[base_dates <= t]
        if len(preceding) == 0:
            continue
        mid = base_dates.get_loc(preceding.max())
        lo, hi = max(0, mid - n_before), min(len(base_dates), mid + n_after + 1)
        if hi - lo < n_before + n_after + 1:
            continue
        pool = reforecast.isel(issue=slice(lo, hi)).stack(sample=("issue", "hyear", "member"))
        q = np.nanquantile(pool.transpose("sample", ...).values, levels, axis=0)
        out.append(q)
        kept.append(t)
    other = [d for d in reforecast.dims if d not in ("issue", "hyear", "member")]
    coords = {"issue": pd.DatetimeIndex(kept), K_DIM: np.arange(1, K)}
    for d in other:
        coords[d] = reforecast[d]
    arr = np.stack(out) if out else np.empty((0, K - 1) + tuple(reforecast.sizes[d] for d in other))
    return xr.DataArray(arr, dims=("issue", K_DIM) + tuple(other), coords=coords, name="threshold")


def indicators(truth: xr.DataArray, thr: xr.DataArray) -> xr.DataArray:
    """O[t, k, target] = 1[y < q(k)], NaN where either is missing."""
    y, q = xr.align(truth, thr.sel({TIME: thr[TIME]}), join="inner")
    o = (y < q).astype("float64")
    return o.where(y.notnull() & q.notnull()).transpose(TIME, K_DIM, ...)
