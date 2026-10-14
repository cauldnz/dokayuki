"""Circulation indices and SNOW-W from gridded fields: truth and per-member alike.

Every function takes a DataArray with (latitude, longitude) plus any leading dims (time,
member, step, ...) and returns the same leading dims. Indices are computed on **weekly** fields
(mean over the week) except where the definition says otherwise; computing the weekly field
first and then the area mean is identical for linear operations.
"""
from __future__ import annotations

import numpy as np
import xarray as xr

from .config import IndexDef
from .grid import LAT, LON, area_mean, nearest_cell


def index_value(idx: IndexDef, fields: dict[str, xr.DataArray], sst: xr.DataArray | None = None,
                land: xr.DataArray | None = None) -> xr.DataArray:
    """Evaluate one index from a dict of fields (short name -> DataArray in SI units).

    SJI needs ``sst`` (same leading dims as the t850 field, or broadcastable) as the SST to pair
    with the forecast T850; the caller decides what SST to persist.
    """
    f = fields[idx.field]
    if idx.box is not None and not idx.sst_minus:
        v = area_mean(f, idx.box, land)
    elif idx.sst_minus:
        if sst is None:
            raise ValueError(f"{idx.key} needs sst")
        t850 = area_mean(f, idx.box, land)
        s = area_mean(sst, idx.box, land) if (LAT in sst.dims) else sst
        v = s - t850
    elif idx.point_difference is not None:
        a, b = idx.point_difference["a"], idx.point_difference["b"]
        v = nearest_cell(f, a["lat"], a["lon"]) - nearest_cell(f, b["lat"], b["lon"])
        v = v.drop_vars([c for c in (LAT, LON) if c in v.coords])
    elif idx.box_difference is not None:
        v = area_mean(f, idx.box_difference["a"], land) - area_mean(f, idx.box_difference["b"], land)
    else:
        raise ValueError(f"index {idx.key} has no geometry")
    return (idx.sign * idx.scale * (v - idx.offset)).rename(idx.key)


def all_indices(defs: dict[str, IndexDef], fields: dict[str, xr.DataArray], sst: xr.DataArray | None = None,
                land: xr.DataArray | None = None, skip_missing: bool = True) -> xr.DataArray:
    """Stack every computable index on a ``target`` dimension."""
    out = []
    for key, idx in defs.items():
        if idx.field not in fields or (idx.sst_minus and sst is None):
            if skip_missing:
                continue
            raise KeyError(f"field {idx.field} missing for {key}")
        out.append(index_value(idx, fields, sst, land).expand_dims(target=[key]))
    return xr.concat(out, dim="target")


def snow_w(snowfall_daily: xr.DataArray, mask: xr.DataArray) -> xr.DataArray:
    """Daily SNOW-W (m w.e. per day) = area mean of snowfall over the mask at native resolution.

    ``mask`` is boolean (lat, lon) on the same grid as ``snowfall_daily`` (0.25 deg). Weekly
    SNOW-W is the 7-day sum of this series (use weekly.weekly_from_daily(..., "sum")).
    """
    w = np.cos(np.deg2rad(snowfall_daily[LAT])) * mask
    return snowfall_daily.weighted(w.fillna(0)).mean((LAT, LON)).rename("snow_w")


def cold_day_precip(tp_daily: xr.DataArray, t850_daily_box_mean: xr.DataArray, t850_max_k: float = 273.15 - 6.0) -> xr.DataArray:
    """Alternative SNOW-W: daily precipitation counted only on days with box-mean T850 <= threshold."""
    cold = t850_daily_box_mean <= t850_max_k
    return tp_daily.where(cold, 0.0).rename("cold_day_precip")


def persisted_sst(sst_obs_daily_box: xr.DataArray, sst_clim_doy: xr.DataArray, issue, target_week_start, lag_days: int = 7) -> float:
    """SST for SJI: the latest observed box-mean SST anomaly (at issue - lag_days) persisted onto the
    target week's climatology. ``sst_clim_doy`` is indexed by dayofyear (1..366)."""
    import pandas as pd
    obs_day = pd.Timestamp(issue) - pd.Timedelta(days=lag_days)
    anom = float(sst_obs_daily_box.sel(time=obs_day, method="nearest")) - float(sst_clim_doy.sel(dayofyear=obs_day.dayofyear))
    doys = [(pd.Timestamp(target_week_start) + pd.Timedelta(days=i)).dayofyear for i in range(7)]
    return float(sst_clim_doy.sel(dayofyear=doys).mean()) + anom
