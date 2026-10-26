"""JMA seasonal hindcasts from CDS (C3S multi-system seasonal forecasts): the second route round
the ECDS S2S reforecast failure, covering the CPS3 era that the sealed winters fall in.

ECDS's own ``s2s-reforecasts`` lists JMA's CPS3 fixed set (model version 2022-09-30) but every
retrieval fails silently (see docs/DATA_NOTES.md); WMC Tokyo's open hindcast directory
(:mod:`dokayuki.fetch.wmc`) only serves CPS4, the system in use since 2026-01-22. CDS's seasonal
datasets carry the same JMA runs under a different convention: one continuous (year, month, day)
start-date axis per ``system`` id, with no separate hindcast/real-time split -- hindcast years
(system 3: 1992-2026, confirmed via the public constraints endpoint, no key needed) and the
real-time operational runs share one system id and one set of fields.

    system 2 = the pre-CPS GEPS system (1981-2022)
    system 3 = CPS3, the system live Feb 2023 - Jan 2026 (this is what the sealed winters need)
    system 4 = CPS4, live since 2026-01-22 (WMC already covers this for free; CDS is a fallback)

Checked 2026-10-26 against ``/api/catalogue/v1/collections/{id}/constraints.json`` (public, no
key): system 3 carries mean_sea_level_pressure, 2m_temperature, total_precipitation,
sea_surface_temperature on single levels and geopotential/temperature/u/v/specific_humidity on
pressure levels 10-925 hPa (10 hPa is there, so U10_60N is possible, unlike WMC). Hindcast years
(pre-2023) only validate a handful of days per month, clustered around each of WMC's 24 S2S
start dates (e.g. 1995: 10-16 and 25-31 in every month) -- wider than the single nominal date,
consistent with JMA's lagged-ensemble hindcast construction. Real-time years (2023+) validate
every day, matching the daily operational schedule since the Feb 2023 CPS switch; that period
duplicates what ECDS's ``s2s-forecasts`` already gave us directly, so only the hindcast years are
useful here.

``data_format`` is not listed as a constrained dimension; requests below ask for ``netcdf``
(unverified against a real pull -- grib is the documented CDS default, so if netcdf is refused
the fallback is grib3 decoded the way :mod:`dokayuki.fetch.wmc` decodes JMA's own GRIB2).

Nothing here touches ECDS; the same ``ECMWF_API_KEY`` used by :func:`dokayuki.fetch.era5.cds_client`
authorises it (one key covers ECDS, CDS and C3S under ECMWF's unified Data Stores).
"""
from __future__ import annotations

import logging
from pathlib import Path

import xarray as xr

from ..config import Box
from ..grid import LAT, LON, domain_lattice
from .wmc import START_MMDD

log = logging.getLogger(__name__)

DATASET_SINGLE = "seasonal-original-single-levels"
DATASET_PRESSURE = "seasonal-original-pressure-levels"
SYSTEM = {"geps": "2", "cps3": "3", "cps4": "4"}

# short -> (CDS variable name, pressure level or None, scale to the S2S convention)
VARIABLES = {
    "msl":    ("mean_sea_level_pressure", None, 1.0),        # Pa
    "t2m":    ("2m_temperature", None, 1.0),                 # K
    "tp":     ("total_precipitation", None, 1.0),            # m (CDS seasonal tp is already m)
    "sst":    ("sea_surface_temperature", None, 1.0),        # K
    "t850":   ("temperature", 850, 1.0),                     # K
    "z500":   ("geopotential", 500, 1.0 / 9.80665),           # m^2/s^2 -> gpm
    "u10hpa": ("u_component_of_wind", 10, 1.0),               # m/s
}
AVAILABLE = frozenset(VARIABLES)
LEADTIME_HOURS = tuple(range(0, 5161, 6))  # 0..215 days, 6-hourly, per SEAS5-family systems


def hindcast_years(system: str, end_year: int = 2022) -> list[int]:
    """Years before the real-time period starts for ``system`` (2023 for cps3, the only one we
    pull from CDS -- cps4's hindcast comes from WMC). Caller still confirms against the live
    constraints endpoint before a real pull; this is a starting point, not a guarantee."""
    start = {"2": 1981, "3": 1992, "4": 1992}[SYSTEM.get(system, system)]
    return list(range(start, end_year + 1))


def request(short: str, years: list[int], mmdd: str, system: str = "cps3", area: list[float] | None = None,
            domain: Box | None = None, leadtime_hour: list[int] | None = None, data_format: str = "netcdf") -> dict:
    """One CDS seasonal request for ``short`` at the S2S start date ``mmdd`` (e.g. ``"0116"``),
    across ``years``. ``domain`` sets the request area when ``area`` isn't given explicitly."""
    if mmdd not in START_MMDD:
        raise ValueError(f"{mmdd} is not one of the 24 S2S start dates; one of {START_MMDD}")
    var, level, _scale = VARIABLES[short]
    if area is None:
        if domain is None:
            raise ValueError("one of area or domain is required")
        area = [domain.lat[1], domain.lon[0], domain.lat[0], domain.lon[1]]
    req = {
        "originating_centre": "jma",
        "system": SYSTEM.get(system, system),
        "variable": [var],
        "year": [str(y) for y in years],
        "month": mmdd[:2],
        "day": mmdd[2:],
        "leadtime_hour": [str(h) for h in (leadtime_hour or LEADTIME_HOURS)],
        "area": area,
        "data_format": data_format,
    }
    if level is not None:
        req["pressure_level"] = str(level)
    return req


def requests_for(fields: list[str], years: list[int], mmdds: list[str], system: str = "cps3",
                 domain: Box | None = None, area: list[float] | None = None) -> list[tuple[str, dict]]:
    """[(dataset, request)] for every (field, start date) combination; one request per field and
    date carries all ``years`` (CDS accepts a year list, confirmed against the constraints
    endpoint), matching ECDS's own one-request-per-month-not-per-day economy."""
    out = []
    for mmdd in mmdds:
        for f in fields:
            if f not in AVAILABLE:
                continue
            dataset = DATASET_PRESSURE if VARIABLES[f][1] is not None else DATASET_SINGLE
            out.append((dataset, request(f, years, mmdd, system, area=area, domain=domain)))
    return out


def download(dataset: str, req: dict, target: Path, client=None) -> Path:
    """Submit and block on one CDS seasonal request, atomic write. Skipped when ``target``
    already exists and is non-empty. Unlike ECDS, this client has no submit/poll/download split
    (``cdsapi``'s legacy client's ``retrieve`` does all three and blocks until done) -- measured
    2026-10-26: ~2.5 h for one field/start-date/31-years request, of which the actual transfer
    (190 MB) was under 10 min, so the wait is server-side queueing, not bandwidth. Call this from
    a thread pool (one client per thread; the client itself isn't documented as thread-safe) to
    let CDS process several requests concurrently -- submitting serially would take the full
    84-request pull the better part of a week."""
    if target.exists() and target.stat().st_size > 0:
        return target
    from .era5 import cds_client
    client = client or cds_client()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    client.retrieve(dataset, req, str(tmp))
    tmp.replace(target)
    log.info("fetched %s (%.1f MiB)", target.name, target.stat().st_size / 2**20)
    return target


# ----------------------------------------------------------------------------- decode
def open_seasonal(path: Path, short: str) -> xr.DataArray:
    """One downloaded file (netcdf, one field, possibly several years and the 24 ensemble/lagged
    members CDS reports for JMA's lagged construction) -> (number, time, step_day, lat, lon),
    matching :func:`dokayuki.fetch.wmc.assemble`'s layout. ``time`` is the real start date
    (year varies; month/day fixed to the file's ``mmdd``), ``step_day`` is lead day 1..N from
    6-hourly ``leadtime_hour`` reduced by daily mean (precip: daily sum from the 6-hourly
    decumulated field, done by the caller before this if needed -- CDS seasonal tp is already a
    running total from the forecast start, same convention as ECDS)."""
    ds = xr.open_dataset(path)
    var, _level, scale = VARIABLES[short]
    name = next((v for v in ds.data_vars if v not in ("number", "forecast_reference_time")), None)
    if name is None:
        raise ValueError(f"no data variable found in {path}")
    da = ds[name] * scale
    time_dim = next((d for d in da.dims if d in ("forecast_reference_time", "indexing_time", "time")), None)
    if time_dim is None:
        raise ValueError(f"no start-date dimension found in {path}: dims {da.dims}")
    hours = da["leadtime_hour"].values.astype("int64") if "leadtime_hour" in da.coords else da["step"].values
    day = hours // 24 + 1
    da = da.assign_coords(step_day=("leadtime_hour", day)).groupby("step_day").mean("leadtime_hour")
    rename = {time_dim: "time"}
    if "number" not in da.dims and "realization" in da.dims:
        rename["realization"] = "number"
    da = da.rename(rename).transpose("number", "time", "step_day", ...)
    return da.rename(short)


def to_lattice(da: xr.DataArray, domain: Box, resolution: float = 1.5) -> xr.DataArray:
    """Bilinear interpolation onto the reference lattice, same convention as ``wmc.to_lattice``."""
    lat_t, lon_t = domain_lattice(domain, resolution)
    src = da.sortby(LAT) if float(da[LAT][0]) > float(da[LAT][-1]) else da
    lon_src = src[LON].values % 360.0
    src = src.assign_coords({LON: lon_src}).sortby(LON)
    return src.interp({LAT: lat_t, LON: lon_t}, method="linear", assume_sorted=True)
