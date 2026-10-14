"""ERA5 truth.

Two paths:
1. **Bulk history, no key**: the WeatherBench2 / ARCO 1.5-degree 6-hourly ERA5 store
   (1959-01-01 .. 2023-01-10, exactly the reference lattice, chunks of 8 steps x globe). Cheap
   for 2-D fields (~0.6 MB per 2-day chunk) and moderate for 3-D fields (~7.8 MB per chunk, all
   13 levels in one chunk). No snowfall and no 10 hPa level in this store.
2. **Keyed, current**: Copernicus CDS (``CDSAPI_URL``/``CDSAPI_KEY``) for everything after
   2023-01-10, for the 0.25-degree snowfall over the SNOW-W mask (daily-statistics dataset) and
   for 10 hPa zonal wind. ERA5T lands ~5 days behind real time.

The hourly 0.25-degree ARCO store is one global field per hour (4 MB surface, 150 MB for the
37-level fields), so it is not used for bulk pulls (see docs/DATA_NOTES.md).
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from ..config import Box

log = logging.getLogger(__name__)

WB2_15 = "https://storage.googleapis.com/weatherbench2/datasets/era5/1959-2023_01_10-6h-240x121_equiangular_with_poles_conservative.zarr"
ARCO_15 = "https://storage.googleapis.com/gcp-public-data-arco-era5/ar/1959-2022-6h-240x121_equiangular_with_poles_conservative.zarr"

# our short names -> (store variable, level or None, daily aggregation of the 6-hourly values)
FIELDS_15 = {
    "msl":  ("mean_sea_level_pressure", None, "mean"),
    "t2m":  ("2m_temperature", None, "mean"),
    "tp":   ("total_precipitation_6hr", None, "sum"),
    "sst":  ("sea_surface_temperature", None, "mean"),
    "t850": ("temperature", 850, "mean"),
    "z500": ("geopotential", 500, "mean"),   # geopotential (m2 s-2) -> height by /g
    "u850": ("u_component_of_wind", 850, "mean"),
    "v850": ("v_component_of_wind", 850, "mean"),
    # u 10 hPa is not in the 13-level 1.5-degree store: CDS only
}
G0 = 9.80665


def open_wb2(url: str = WB2_15) -> xr.Dataset:
    return xr.open_zarr(url, consolidated=True, chunks=None)


def months_mask(times: pd.DatetimeIndex, months: tuple[int, ...] | None) -> np.ndarray:
    if not months:
        return np.ones(len(times), dtype=bool)
    return np.isin(times.month, months)


def estimate_pull(fields: list[str], start: str, end: str, months: tuple[int, ...] | None) -> dict:
    """Rough download size in GB for the 1.5-degree store (chunk = 8 six-hourly steps)."""
    per_chunk_mb = {"msl": 0.55, "t2m": 0.62, "tp": 0.83, "sst": 0.14, "t850": 7.8, "z500": 7.7, "u850": 7.8, "v850": 7.8}
    days = pd.date_range(start, end, freq="D")
    n_days = int(months_mask(days, months).sum())
    n_chunks = n_days / 2.0
    gb = {f: n_chunks * per_chunk_mb[f] / 1024 for f in fields}
    return {"chunks": n_chunks, "gb_by_field": gb, "gb_total": float(sum(gb.values())),
            "minutes_at_50MBps": float(sum(gb.values()) * 1024 / 50 / 60)}


def pull_daily_domain(fields: list[str], domain: Box, start: str, end: str, out: Path,
                      months: tuple[int, ...] | None = None, url: str = WB2_15,
                      chunk_days: int = 16, snow_box: Box | None = None) -> Path:
    """Daily domain fields from the 1.5-degree store, appended to a Zarr store ``out``.

    Resumable: days already present in ``out`` are skipped. Values are stored as float32 with
    our short names; z500 is converted to geopotential height (m). Time = day (00 UTC label).
    """
    ds = open_wb2(url)
    lat_sl = slice(domain.lat[0], domain.lat[1]) if float(ds.latitude[0]) < float(ds.latitude[-1]) else slice(domain.lat[1], domain.lat[0])
    lon_sl = slice(domain.lon[0], domain.lon[1])
    all_days = pd.date_range(start, end, freq="D")
    all_days = all_days[months_mask(all_days, months)]
    done = set()
    if out.exists():
        try:
            done = set(pd.DatetimeIndex(xr.open_zarr(out, consolidated=False).time.values))
        except Exception:  # noqa: BLE001
            done = set()
    todo = [d for d in all_days if d not in done]
    log.info("ERA5 1.5deg pull: %d days requested, %d already stored, %d to do", len(all_days), len(done), len(todo))
    if not todo:
        return out
    # group consecutive days into blocks of chunk_days
    blocks, cur = [], [todo[0]]
    for d in todo[1:]:
        if (d - cur[-1]).days == 1 and len(cur) < chunk_days:
            cur.append(d)
        else:
            blocks.append(cur); cur = [d]
    blocks.append(cur)
    t0 = time.time()
    for bi, blk in enumerate(blocks):
        d0, d1 = blk[0], blk[-1]
        parts = {}
        for f in fields:
            var, level, agg = FIELDS_15[f]
            da = ds[var].sel(time=slice(d0, d1 + pd.Timedelta(hours=18)), latitude=lat_sl, longitude=lon_sl)
            if level is not None:
                da = da.sel(level=level, drop=True)
            da = da.load()
            daily = da.resample(time="1D").mean() if agg == "mean" else da.resample(time="1D").sum()
            if f == "z500":
                daily = daily / G0
            parts[f] = daily.astype("float32").transpose("time", "latitude", "longitude")
        block_ds = xr.Dataset(parts).sortby("latitude")
        block_ds = block_ds.sel(time=block_ds.time.isin(np.array(blk, dtype="datetime64[ns]")))
        block_ds = block_ds.drop_vars([c for c in block_ds.coords if c not in ("time", "latitude", "longitude")])
        for v in list(block_ds.data_vars) + list(block_ds.coords):
            block_ds[v].encoding = {}
        if out.exists() and done:
            block_ds.to_zarr(out, mode="a", append_dim="time", consolidated=False)
        else:
            enc = {v: {"chunks": (64, block_ds.sizes["latitude"], block_ds.sizes["longitude"])} for v in block_ds.data_vars}
            block_ds.to_zarr(out, mode="w", consolidated=False, encoding=enc)
            done = {pd.Timestamp(blk[0])}
        if bi % 20 == 0:
            log.info("  block %d/%d %s..%s (%.0fs)", bi + 1, len(blocks), d0.date(), d1.date(), time.time() - t0)
    return out


def pull_land_sea_mask(domain: Box, out: Path, url: str = WB2_15) -> xr.DataArray:
    ds = open_wb2(url)
    lat_sl = slice(domain.lat[0], domain.lat[1])
    lsm = ds["land_sea_mask"].sel(latitude=lat_sl, longitude=slice(domain.lon[0], domain.lon[1])).load()
    lsm = lsm.transpose("latitude", "longitude").sortby("latitude").rename("lsm")
    out.parent.mkdir(parents=True, exist_ok=True)
    lsm.to_netcdf(out)
    return lsm


# ----------------------------------------------------------------------------- CDS (keyed)
def cds_client():
    """A cdsapi client from CDSAPI_URL / CDSAPI_KEY (raises if missing)."""
    import os
    import cdsapi  # noqa: WPS433
    url = os.environ.get("CDSAPI_URL", "https://cds.climate.copernicus.eu/api")
    key = os.environ.get("CDSAPI_KEY")
    if not key:
        raise RuntimeError("CDSAPI_KEY not set")
    return cdsapi.Client(url=url, key=key, quiet=True)


def cds_daily_snowfall_request(year: int, box: Box, months: list[str]) -> dict:
    """Request for the ERA5 daily-statistics derived dataset: daily snowfall (water equivalent) sum
    over the SNOW-W box at native 0.25 degrees."""
    n, s = box.lat[1] + 0.5, box.lat[0] - 0.5
    w, e = box.lon[0] - 0.5, box.lon[1] + 0.5
    return {
        "product_type": "reanalysis",
        "variable": ["snowfall"],
        "year": str(year),
        "month": months,
        "day": [f"{d:02d}" for d in range(1, 32)],
        "daily_statistic": "daily_sum",
        "time_zone": "utc+00:00",
        "frequency": "1_hourly",
        "area": [n, w, s, e],
    }


def cds_daily_request(variable: str, year: int, domain: Box, months: list[str], level: int | None = None,
                      statistic: str = "daily_mean") -> dict:
    req = {
        "product_type": "reanalysis",
        "variable": [variable],
        "year": str(year),
        "month": months,
        "day": [f"{d:02d}" for d in range(1, 32)],
        "daily_statistic": statistic,
        "time_zone": "utc+00:00",
        "frequency": "6_hourly",
        "area": [domain.lat[1], domain.lon[0], domain.lat[0], domain.lon[1]],
        "grid": [1.5, 1.5],
    }
    if level is not None:
        req["pressure_level"] = [str(level)]
    return req
