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
from .grid import LAT, LON, area_mean, cos_weights, nearest_cell


def index_value(idx: IndexDef, fields: dict[str, xr.DataArray], sst: xr.DataArray | None = None,
                land: xr.DataArray | None = None, aux: dict | None = None) -> xr.DataArray:
    """Evaluate one index from a dict of fields (short name -> DataArray in SI units).

    SJI needs ``sst`` (same leading dims as the t850 field, or broadcastable) as the SST to pair
    with the forecast T850; the caller decides what SST to persist. ``aux`` carries what the
    special forms need: ``v850`` (NWF), ``z500_clim_doy`` (UBI), ``ao_loading``/``ao_std`` (AO),
    ``sji13`` (a precomputed SJI13 series from daily data).
    """
    aux = aux or {}
    f = fields[idx.field]
    x = idx.extra
    if x.get("nw_flow"):
        v = nw_flow(f, aux["v850"], idx.box, land)
    elif x.get("sji_days"):
        v = aux["sji13"]
    elif x.get("zonal_mean_lat") is not None:
        v = zonal_mean_at(f, float(x["zonal_mean_lat"]))
    elif x.get("anomaly"):
        v = ural_blocking(f, aux["z500_clim_doy"], idx.box, land)
    elif x.get("ao_projection"):
        v = ao_projection(f, aux["ao_loading"], aux.get("ao_std", 1.0))
    elif idx.box is not None and not idx.sst_minus:
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


NEEDS = {"nw_flow": "v850", "sji_days": "sji13", "anomaly": "z500_clim_doy", "ao_projection": "ao_loading"}


def all_indices(defs: dict[str, IndexDef], fields: dict[str, xr.DataArray], sst: xr.DataArray | None = None,
                land: xr.DataArray | None = None, skip_missing: bool = True, aux: dict | None = None) -> xr.DataArray:
    """Stack every computable index on a ``target`` dimension (skips what its inputs don't allow)."""
    aux = aux or {}
    out = []
    for key, idx in defs.items():
        need = [NEEDS[k] for k in NEEDS if idx.extra.get(k)]
        missing = idx.field not in fields or (idx.sst_minus and sst is None) or any(n not in aux for n in need)
        if missing:
            if skip_missing:
                continue
            raise KeyError(f"inputs missing for {key}")
        out.append(index_value(idx, fields, sst, land, aux).expand_dims(target=[key]))
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


# ----------------------------------------------------------------------------- spec update 1 ingredients
def nw_flow(u850: xr.DataArray, v850: xr.DataArray, box, land=None) -> xr.DataArray:
    """Mean 850 hPa wind component *from* the northwest (315 deg) over the box, m/s.

    A wind blowing from 315 deg has u > 0 (eastward) and v < 0 (southward); the component of the
    wind vector along the direction it is blowing *towards* (135 deg) is (u - v) / sqrt(2).
    """
    comp = (u850 - v850) / np.sqrt(2.0)
    return area_mean(comp, box, land).rename("NWF")


def sji_days(sst_daily: xr.DataArray, t850_daily: xr.DataArray, box, threshold_c: float = 13.0,
             land=None, window: int = 7) -> xr.DataArray:
    """Days in each 7-day window with box-mean (SST - T850) >= threshold, labelled by week start.

    Inputs are daily fields (or daily box means) with a ``time`` dimension; for members the SST
    is the persisted observed value (a scalar per target week) broadcast against member T850.
    """
    s = area_mean(sst_daily, box, land) if "latitude" in sst_daily.dims else sst_daily
    t = area_mean(t850_daily, box, land) if "latitude" in t850_daily.dims else t850_daily
    hit = ((s - t) >= threshold_c).astype("float64")
    from .weekly import weekly_from_daily
    return weekly_from_daily(hit, "sum", days=window).rename("SJI13")


def sji_days_from_steps(sst_week: xr.DataArray, t850_steps_box: xr.DataArray, threshold_c: float = 13.0,
                        step_dim: str = "step_day") -> xr.DataArray:
    """Member version: count of forecast days (over the week's steps) with SST - T850 >= threshold."""
    hit = ((sst_week - t850_steps_box) >= threshold_c).astype("float64")
    return hit.sum(step_dim).rename("SJI13")


def zonal_mean_at(da: xr.DataArray, lat: float) -> xr.DataArray:
    """Zonal mean at the lattice latitude nearest ``lat`` (e.g. 10 hPa u at 60N)."""
    return da.sel({LAT: lat}, method="nearest").mean(LON)


def ural_blocking(z500_weekly: xr.DataArray, z500_clim_doy: xr.DataArray, box, land=None) -> xr.DataArray:
    """500 hPa height anomaly (weekly minus day-of-year climatology) averaged over the Ural box, m."""
    anom = z500_weekly.groupby("time.dayofyear") - z500_clim_doy
    anom = anom.drop_vars("dayofyear", errors="ignore")
    return area_mean(anom, box, land).rename("UBI")


def ao_projection(msl_anom: xr.DataArray, loading: xr.DataArray, std: float = 1.0) -> xr.DataArray:
    """Project an MSLP (or Z1000) anomaly field (20-90N) onto the AO loading pattern.

    ``loading`` is the CPC EOF1 pattern on the same lattice; the projection is cos-lat weighted and
    divided by ``std`` (the standard deviation of the projected observed daily/weekly series over
    the base period) so that the result is in AO standard-deviation units.
    """
    w = cos_weights(msl_anom[LAT])
    num = (msl_anom * loading).weighted(w).sum((LAT, LON), skipna=True)
    den = (loading ** 2).weighted(w).sum((LAT, LON), skipna=True)
    return (num / den / std).rename("AO")
