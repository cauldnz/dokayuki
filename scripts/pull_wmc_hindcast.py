"""JMA CPS4 one-month hindcast from WMC Tokyo: the open copy of the S2S CPS4 fixed reforecast.

Downloads the per-(start date, hindcast year, field) GRIB2 files under state/wmc/ and writes one
NetCDF per start date with daily member fields on the 1.5 deg domain lattice,
state/wmc_daily/cps4/<MMDD>.nc, dims (number, time=hindcast init, step_day, latitude, longitude).
Nothing is decoded into state/members/ yet: that join (weekly indices, lagged-ensemble pairing
with the ECDS real-time JMA members) is the follow-up once the daily-mean vs 00 UTC instant
question in docs/DATA_NOTES.md is settled.

Usage: pull_wmc_hindcast.py [--fields msl,t2m,tp,t850,z500] [--months 10,11,12,1,2,3]
                            [--hyears 1991-2020] [--estimate] [--max-gb 20] [--delete-grib]
"""
import argparse
import logging
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pandas as pd
import xarray as xr
from dokayuki.config import RegionConfig
from dokayuki.fetch import wmc

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "state" / "wmc"
OUT = ROOT / "state" / "wmc_daily"
log = logging.getLogger("wmc")


def parse_years(s: str) -> list[int]:
    a, _, b = s.partition("-")
    return list(range(int(a), int(b or a) + 1))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--fields", default="msl,t2m,tp,t850,z500")
    p.add_argument("--months", default="10,11,12,1,2,3")
    p.add_argument("--hyears", default="1991-2020")
    p.add_argument("--system", default="cps4", choices=sorted(wmc.SYSTEMS))
    p.add_argument("--estimate", action="store_true", help="print the volume and stop")
    p.add_argument("--max-gb", type=float, default=20.0, help="refuse to start a pull above this (the stop-and-ask line)")
    p.add_argument("--delete-grib", action="store_true", help="remove each GRIB once its start date is written")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    fields = [f for f in a.fields.split(",") if f]
    unknown = sorted(set(fields) - wmc.AVAILABLE)
    if unknown:
        log.warning("not on WMC (needs ECDS): %s", unknown)
    fields = [f for f in fields if f in wmc.AVAILABLE]
    mmdds = wmc.start_dates(tuple(int(m) for m in a.months.split(",")))
    hyears = parse_years(a.hyears)
    est = wmc.estimate_pull(fields, mmdds, hyears)
    log.info("%d files, %.1f GB for %s x %d start dates x %d years", est["files"], est["gb"], fields, len(mmdds), len(hyears))
    if a.estimate:
        return 0
    if est["gb"] > a.max_gb:
        log.error("%.1f GB exceeds --max-gb %.0f: narrow --months/--fields/--hyears or raise the limit deliberately", est["gb"], a.max_gb)
        return 2
    cfg = RegionConfig.load()
    import requests
    session = requests.Session()
    for mmdd in mmdds:
        target = OUT / a.system / f"{mmdd}.nc"
        if target.exists():
            log.info("%s done", target.name)
            continue
        per_field: dict[str, list[xr.DataArray]] = {f: [] for f in fields}
        paths = []
        for hy in hyears:
            init = pd.Timestamp(f"{hy}-{mmdd[:2]}-{mmdd[2:]}")
            for f in fields:
                path = wmc.download(wmc.url(mmdd, hy, f, a.system), RAW / a.system / mmdd / str(hy) / wmc.file_name(mmdd, hy, f, a.system), session=session)
                paths.append(path)
                per_field[f].append(wmc.to_lattice(wmc.open_wmc_daily(path, f, init), cfg.domain).astype("float32").load())
        ds = xr.Dataset({f: xr.concat(arrs, dim="time") for f, arrs in per_field.items()})
        ds.attrs.update(source="JMA WMC Tokyo one-month hindcast", system=a.system, credit="気象庁提供 (Source: Japan Meteorological Agency)",
                        note="daily means (precip: 24-h totals in m); ECDS real-time msl/z500/t850 are 00 UTC instants")
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp.nc")
        ds.to_netcdf(tmp); tmp.replace(target)
        log.info("wrote %s (%d inits)", target, ds.sizes["time"])
        if a.delete_grib:
            for path in paths:
                path.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
