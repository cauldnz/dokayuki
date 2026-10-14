"""Build weekly truth from the daily 1.5-degree store: gridded fields and scalar indices."""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from .config import Box, IndexDef, RegionConfig, SnowConfig, load_indices
from .grid import LAT, LON, area_mean, box_mask
from .indices import all_indices, cold_day_precip
from .weekly import weekly_from_daily

log = logging.getLogger(__name__)
AGG = {"msl": "mean", "t2m": "mean", "tp": "sum", "sst": "mean", "t850": "mean", "z500": "mean"}


def open_daily(paths: list[Path]) -> xr.Dataset:
    parts = [xr.open_zarr(p, consolidated=False) for p in paths if p.exists()]
    ds = xr.merge(parts, join="outer")
    return ds.sortby("time")


def sst_doy_climatology(sst_box: xr.DataArray, years: tuple[int, int] = (1991, 2020)) -> xr.DataArray:
    s = sst_box.sel(time=slice(f"{years[0]}-01-01", f"{years[1]}-12-31"))
    return s.groupby("time.dayofyear").mean("time")


def weekly_truth(ds: xr.Dataset, lsm: xr.DataArray, cfg: RegionConfig, defs: dict[str, IndexDef],
                 snow: SnowConfig) -> tuple[xr.Dataset, pd.DataFrame]:
    """Returns (weekly gridded dataset, weekly index table). Indices use weekly-mean fields."""
    ds = ds.load()
    weekly = {}
    for v in ds.data_vars:
        weekly[v] = weekly_from_daily(ds[v], AGG.get(v, "mean"))
    wk = xr.Dataset(weekly)
    fields = {v: wk[v] for v in wk.data_vars}
    sst = None
    if "sst" in fields and "t850" in fields:
        # truth SJI uses the observed weekly SST itself (no persistence needed for truth)
        sst = fields["sst"]
    idx = all_indices(defs, fields, sst=sst, land=lsm)
    table = idx.to_pandas().T if idx.dims[0] == "target" else idx.to_pandas()
    table.index.name = "time"
    # Hokkaido-west precipitation proxies at 1.5 deg (SNOW-W needs 0.25 deg snowfall from CDS)
    box = snow.mask
    if "tp" in ds:
        tp_box = area_mean(ds["tp"], Box(lat=box.lat, lon=box.lon, land_only=False))
        table["tp_box_weekly_mm"] = weekly_from_daily(tp_box, "sum").to_pandas() * 1000.0
        if "t850" in ds:
            t850_box = area_mean(ds["t850"], Box(lat=box.lat, lon=box.lon, land_only=False))
            cdp = cold_day_precip(tp_box, t850_box, 273.15 + float(snow.raw["snow_w"]["alternatives"]["cold_day_precip"]["t850_max_c"]))
            table["cold_day_precip_weekly_mm"] = weekly_from_daily(cdp, "sum").to_pandas() * 1000.0
            table["t850_box_weekly_c"] = weekly_from_daily(t850_box, "mean").to_pandas() - 273.15
    if "sst" in ds:
        sj = defs["SJC"].box if "SJC" in defs else Box(lat=(38.0, 46.0), lon=(132.0, 141.0))
        sst_box = area_mean(ds["sst"], sj)
        clim = sst_doy_climatology(sst_box)
        anom = sst_box.groupby("time.dayofyear") - clim
        table["soj_sst_anom_daily"] = anom.drop_vars("dayofyear").to_pandas().reindex(table.index)
        table["soj_sst_weekly"] = weekly_from_daily(sst_box, "mean").to_pandas()
    return wk, table
