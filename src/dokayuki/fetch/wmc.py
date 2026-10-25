"""JMA WMC Tokyo one-month hindcast (JMA/MRI-CPS4): the open copy of the S2S CPS4 fixed reforecast.

ECDS lists JMA's fixed reforecast sets but every retrieval of the current ones fails, and the
CPS4 set (model version 2026-01-31) is not catalogued at all (see docs/DATA_NOTES.md). JMA's
World Meteorological Centre Tokyo serves the same hindcast runs directly, no login:

    https://ds.data.jma.go.jp/wmc/data/gpv/model/1mE_Hind_125.CPS4/Daily/<MMDD>/<YYYY>/
        JMACPS_1p25deg_<YYYYMMDD>_<level>_<element>_hind_mb.grb2

Verified from the build container on 2026-10-25 (directory listing, two files decoded):

- 24 start dates a year, the S2S reforecast dates (16/31 Jan, 10/25 Feb, 12/27 Mar, 11/26 Apr,
  16/31 May, 15/30 Jun, 15/30 Jul, 14/29 Aug, 13/28 Sep, 13/28 Oct, 12/27 Nov, 12/27 Dec),
  hindcast years 1991-2020, 00 UTC, 13 members (control + 6 positive + 6 negative pairs,
  GRIB2 ``typeOfEnsembleForecast`` 1/3/2), multi-field GRIB2, 1.25 deg global, 145 x 288.
- Daily means (``stepType`` avg) for days 1..34 as windows 0-24 h .. 792-816 h; precipitation
  is the 24-h accumulation in mm (JMA local table, ``shortName`` unknown), 33 windows from
  24-48 h. One file per (variable, level), 8-22 MiB, all members in the file.
- Fields: surface MSLP (Ppp) and precipitation (Prr); 2 m temperature (h2 Ptt); geopotential
  height, temperature, u, v and (some levels) RH at 1000, 850, 700, 500, 300, 200, 100 hPa.
  No 10 hPa, no SST, no snowfall: ``U10_60N`` and SST-based targets cannot come from here.

Differences from the ECDS path, which the caller must keep in mind when the two are mixed:
the ECDS fields for msl, z500 and t850 are 00 UTC instants, here they are daily means; the grid
is 1.25 deg and is interpolated to the 1.5 deg lattice by :func:`to_lattice`; precipitation is
converted from mm to m to match the S2S convention. t2m is a daily mean on both paths.

Terms: the WMC application page covers password-protected real-time GPV for NMHSs; the hindcast
directory is served without authentication, and JMBSC's readme for the identical product states
the numerical data are not subject to copyright and may be used freely with the credit
気象庁提供 (Source: Japan Meteorological Agency). Recorded as a (verify) item in DATA_NOTES.

Nothing here touches ECDS or needs a key. Decoding needs ``eccodes`` (the ``fetch`` extra);
cfgrib cannot be used because it folds the positive and negative pairs onto one ``number``.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator

import numpy as np
import pandas as pd
import xarray as xr

from ..config import Box
from ..grid import LAT, LON, domain_lattice

log = logging.getLogger(__name__)

BASE = "https://ds.data.jma.go.jp/wmc/data/gpv/model"
SYSTEMS = {
    # name -> (directory, file prefix). GEPS2503 is JMA's previous one-month system; it is not
    # the S2S contribution and is listed only so a side-by-side check is one argument away.
    "cps4": ("1mE_Hind_125.CPS4", "JMACPS"),
    "geps2503": ("1mE_Hind_125.GEPS2503", "JMAGEPS"),
}
START_MMDD = ("0116", "0131", "0210", "0225", "0312", "0327", "0411", "0426", "0516", "0531",
              "0615", "0630", "0715", "0730", "0814", "0829", "0913", "0928", "1013", "1028",
              "1112", "1127", "1212", "1227")
HYEARS = tuple(range(1991, 2021))
N_MEMBERS = 13
N_DAYS = 34
UA = "dokayuki/0.1 (research, non-commercial; https://github.com/cauldnz/dokayuki)"

# short -> (level token, element token, kind, scale to the S2S units)
FILES = {
    "msl":  ("surf", "Ppp", "daily", 1.0),      # Pa
    "tp":   ("surf", "Prr", "accum", 1.0e-3),   # mm per 24 h -> m
    "t2m":  ("h2",   "Ptt", "daily", 1.0),      # K
    "t850": ("p850", "Ptt", "daily", 1.0),      # K
    "z500": ("p500", "Phh", "daily", 1.0),      # gpm
    "u850": ("p850", "Pwu", "daily", 1.0),
    "v850": ("p850", "Pwv", "daily", 1.0),
}
AVAILABLE = frozenset(FILES)
# measured 2026-10-25 for 0116/1991 (MiB); the pull estimate uses these
SIZE_MIB = {"msl": 13.0, "tp": 15.0, "t2m": 15.0, "t850": 14.0, "z500": 9.7, "u850": 18.0, "v850": 18.0}


def file_name(mmdd: str, hyear: int, short: str, system: str = "cps4") -> str:
    level, element, _kind, _scale = FILES[short]
    return f"{SYSTEMS[system][1]}_1p25deg_{hyear}{mmdd}_{level}_{element}_hind_mb.grb2"


def url(mmdd: str, hyear: int, short: str, system: str = "cps4") -> str:
    if mmdd not in START_MMDD:
        raise ValueError(f"{mmdd} is not a CPS hindcast start date; one of {START_MMDD}")
    return f"{BASE}/{SYSTEMS[system][0]}/Daily/{mmdd}/{hyear}/{file_name(mmdd, hyear, short, system)}"


def start_dates(months: tuple[int, ...] | None = None) -> list[str]:
    """The MMDD start dates, optionally only those in ``months`` (e.g. (10, 11, 12, 1, 2, 3))."""
    if months is None:
        return list(START_MMDD)
    return [m for m in START_MMDD if int(m[:2]) in months]


def estimate_pull(fields: list[str], mmdds: list[str], hyears: list[int] | tuple[int, ...] = HYEARS) -> dict:
    """Files and bytes a pull would move, so the ~20 GB stop-and-ask line can be applied first."""
    fields = [f for f in fields if f in AVAILABLE]
    n = len(mmdds) * len(hyears)
    mib = sum(SIZE_MIB[f] for f in fields) * n
    return {"files": n * len(fields), "bytes": int(mib * 2**20), "gb": round(mib / 1024, 2), "fields": fields}


def download(src: str, target: Path, session=None, timeout: int = 300, chunk: int = 1 << 20) -> Path:
    """Fetch one file to ``target`` (atomic rename, skipped when already there and non-empty)."""
    if target.exists() and target.stat().st_size > 0:
        return target
    import requests
    s = session or requests.Session()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    with s.get(src, headers={"User-Agent": UA}, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        with tmp.open("wb") as fh:
            for block in r.iter_content(chunk):
                fh.write(block)
    tmp.replace(target)
    log.info("fetched %s (%.1f MiB)", target.name, target.stat().st_size / 2**20)
    return target


# ----------------------------------------------------------------------------- GRIB -> daily member fields
def member_index(type_of_ensemble: int, perturbation: int) -> int:
    """GRIB2 (typeOfEnsembleForecast, perturbationNumber) -> 0..12.

    JMA encodes the control as type 1 number 0, the six positively perturbed members as type 3
    numbers 1-6 and their negative pairs as type 2 numbers 1-6. Control is 0, positive k is k,
    negative k is 6 + k, so the pair structure survives in the member order.
    """
    if type_of_ensemble == 1 or (type_of_ensemble == 0 and perturbation == 0):
        return 0
    if type_of_ensemble == 3:
        return perturbation
    if type_of_ensemble == 2:
        return 6 + perturbation
    raise ValueError(f"unexpected ensemble coding type={type_of_ensemble} number={perturbation}")


def read_messages(path: Path) -> Iterator[tuple[int, int, int, np.ndarray, np.ndarray, np.ndarray]]:
    """Yield (member, start_hour, end_hour, values[lat, lon], lat, lon) per GRIB field.

    Multi-field GRIB2 support is switched on: a JMA file is one GRIB message carrying 442 fields.
    """
    import eccodes as ec
    ec.codes_grib_multi_support_on()
    with open(path, "rb") as fh:
        while True:
            gid = ec.codes_new_from_file(fh, ec.CODES_PRODUCT_GRIB)
            if gid is None:
                return
            try:
                member = member_index(ec.codes_get(gid, "typeOfEnsembleForecast"), ec.codes_get(gid, "perturbationNumber"))
                start, end = int(ec.codes_get(gid, "startStep")), int(ec.codes_get(gid, "endStep"))
                ni, nj = int(ec.codes_get(gid, "Ni")), int(ec.codes_get(gid, "Nj"))
                lat0, dlat = float(ec.codes_get(gid, "latitudeOfFirstGridPointInDegrees")), float(ec.codes_get(gid, "jDirectionIncrementInDegrees"))
                lon0, dlon = float(ec.codes_get(gid, "longitudeOfFirstGridPointInDegrees")), float(ec.codes_get(gid, "iDirectionIncrementInDegrees"))
                sign = 1.0 if int(ec.codes_get(gid, "jScansPositively")) else -1.0
                lat = lat0 + sign * dlat * np.arange(nj)
                lon = (lon0 + dlon * np.arange(ni)) % 360.0
                vals = ec.codes_get_values(gid).reshape(nj, ni)
            finally:
                ec.codes_release(gid)
            yield member, start, end, vals, lat, lon


def assemble(records: list[tuple[int, int, int, np.ndarray]], lat: np.ndarray, lon: np.ndarray,
             init: pd.Timestamp, short: str) -> xr.DataArray:
    """(member, start_h, end_h, values) records -> (number, time, step_day, latitude, longitude).

    A window a_b hours is the daily value of forecast day b/24 (day 1 = init + 0 days), the same
    labelling as the ECDS decoder in ``fetch.s2s``. Days absent from the file (precipitation has
    no 0-24 h window) are NaN. Values are scaled to the S2S units (precipitation mm -> m).
    """
    scale = FILES[short][3]
    days = sorted({end // 24 for _m, _s, end, _v in records})
    if any((end - start) != 24 for _m, start, end, _v in records):
        raise ValueError(f"{short}: expected 24-h windows, got {sorted({(s, e) for _m, s, e, _v in records})[:5]}")
    out = np.full((N_MEMBERS, 1, len(days), lat.size, lon.size), np.nan, dtype="float32")
    pos = {d: i for i, d in enumerate(days)}
    for member, _start, end, vals in records:
        out[member, 0, pos[end // 24]] = vals * scale
    return xr.DataArray(
        out, dims=("number", "time", "step_day", LAT, LON),
        coords={"number": np.arange(N_MEMBERS), "time": pd.DatetimeIndex([init]), "step_day": days, LAT: lat, LON: lon},
        name=short, attrs={"source": "JMA WMC Tokyo CPS4 one-month hindcast", "kind": FILES[short][2]},
    )


def open_wmc_daily(path: Path, short: str, init: pd.Timestamp) -> xr.DataArray:
    """Decode one WMC hindcast file to daily member fields on the 1.25 deg global grid."""
    records, lat, lon = [], None, None
    for member, start, end, vals, la, lo in read_messages(path):
        records.append((member, start, end, vals))
        lat, lon = la, lo
    if not records:
        raise ValueError(f"no GRIB fields in {path}")
    return assemble(records, lat, lon, init, short)


def to_lattice(da: xr.DataArray, domain: Box, resolution: float = 1.5) -> xr.DataArray:
    """Bilinear interpolation of a 1.25 deg global field onto the reference lattice over ``domain``.

    The domain's longitudes (75-225 E) lie inside the 0..360 source axis, so no wrap is needed;
    the lattice latitudes ascend like the reference grid.
    """
    lat_t, lon_t = domain_lattice(domain, resolution)
    src = da.sortby(LAT)
    return src.interp({LAT: lat_t, LON: lon_t}, method="linear", assume_sorted=True)


def pull(fields: list[str], mmdds: list[str], hyears: list[int] | tuple[int, ...], raw_dir: Path,
         system: str = "cps4", session=None) -> dict[tuple[str, int, str], Path]:
    """Download the files for every (start date, hindcast year, field); returns the paths."""
    out = {}
    for mmdd in mmdds:
        for hy in hyears:
            for f in fields:
                if f not in AVAILABLE:
                    continue
                target = raw_dir / system / mmdd / str(hy) / file_name(mmdd, hy, f, system)
                out[(mmdd, hy, f)] = download(url(mmdd, hy, f, system), target, session=session)
    return out
