"""JMA CPS3 seasonal hindcast from CDS: the CDS-side route round ECDS's silent s2s-reforecasts
failure, covering the sealed winters' system (system 3, live Feb 2023 - Jan 2026).

Downloads one NetCDF per (field, start date) under state/cds_seasonal/, each carrying every
requested hindcast year at once (CDS accepts a year list in one request, confirmed against the
constraints endpoint). Each request is slow -- ~2.5 h measured for one field/date/31-years, almost
all of it server-side queueing rather than transfer -- so requests run in a thread pool; nothing
in cdsapi documents the client as thread-safe, so each thread gets its own.

Usage: pull_cds_seasonal.py [--fields msl,t2m,tp,sst,t850,z500,u10hpa] [--months 10,11,12,1,2,3]
                            [--end-year 2022] [--system cps3] [--max-days-lead 33]
                            [--parallel 6] [--estimate] [--max-gb 20]
"""
import argparse
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from dokayuki.config import RegionConfig
from dokayuki.fetch import cds_seasonal as cs
from dokayuki.fetch.era5 import cds_client
from dokayuki.fetch.wmc import start_dates

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "state" / "cds_seasonal"
log = logging.getLogger("cds_seasonal")

# measured 2026-10-26: one field/date/31-years request, netcdf, 33-day leadtime
SIZE_MIB_PER_FIELD_DATE_YEARS = 190.0 / 31  # ~6.1 MiB per (field, date, year)


def target_path(short: str, mmdd: str, system: str) -> Path:
    return OUT / system / f"{short}_{mmdd}.nc"


def estimate(fields: list[str], mmdds: list[str], years: list[int]) -> dict:
    n = len(fields) * len(mmdds)
    mib = SIZE_MIB_PER_FIELD_DATE_YEARS * len(years) * n
    return {"files": n, "gb": round(mib / 1024, 2)}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--fields", default="msl,t2m,tp,sst,t850,z500,u10hpa")
    p.add_argument("--months", default="10,11,12,1,2,3")
    p.add_argument("--end-year", type=int, default=2022, help="last hindcast year before the real-time period")
    p.add_argument("--system", default="cps3", choices=sorted(cs.SYSTEM))
    p.add_argument("--max-days-lead", type=int, default=33, help="weeks 3-4 only need ~33 days, not the full 215-day seasonal range")
    p.add_argument("--parallel", type=int, default=6, help="CDS requests in flight at once (each blocks for ~2.5h; this is queueing concurrency, not bandwidth)")
    p.add_argument("--estimate", action="store_true")
    p.add_argument("--max-gb", type=float, default=20.0)
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    fields = [f for f in a.fields.split(",") if f]
    unknown = sorted(set(fields) - cs.AVAILABLE)
    if unknown:
        log.warning("not on CDS seasonal: %s", unknown)
    fields = [f for f in fields if f in cs.AVAILABLE]
    mmdds = start_dates(tuple(int(m) for m in a.months.split(",")))
    years = cs.hindcast_years(a.system, a.end_year)
    est = estimate(fields, mmdds, years)
    log.info("%d files, ~%.1f GB for %s x %d start dates x %d years (%d-%d)", est["files"], est["gb"], fields,
             len(mmdds), len(years), years[0], years[-1])
    if a.estimate:
        return 0
    if est["gb"] > a.max_gb:
        log.error("~%.1f GB exceeds --max-gb %.0f: narrow --fields/--months/--end-year or raise the limit deliberately", est["gb"], a.max_gb)
        return 2
    cfg = RegionConfig.load()
    lead = [str(h) for h in range(0, a.max_days_lead * 24 + 1, 6)]
    jobs = []
    for mmdd in mmdds:
        for f in fields:
            target = target_path(f, mmdd, a.system)
            dataset = cs.DATASET_PRESSURE if cs.VARIABLES[f][1] is not None else cs.DATASET_SINGLE
            req = cs.request(f, years, mmdd, a.system, domain=cfg.domain, leadtime_hour=lead)
            jobs.append((f, mmdd, dataset, req, target))
    todo = [j for j in jobs if not (j[4].exists() and j[4].stat().st_size > 0)]
    log.info("%d/%d files already present; %d to fetch", len(jobs) - len(todo), len(jobs), len(todo))
    import threading
    local = threading.local()

    def client_for_thread():
        if not hasattr(local, "client"):
            local.client = cds_client()
        return local.client

    def fetch_one(f, mmdd, dataset, req, target):
        t0 = time.time()
        cs.download(dataset, req, target, client=client_for_thread())
        log.info("%s %s done in %.0f min", f, mmdd, (time.time() - t0) / 60)

    with ThreadPoolExecutor(max_workers=a.parallel) as pool:
        futs = {pool.submit(fetch_one, *j): j for j in todo}
        for fut in as_completed(futs):
            f, mmdd, _dataset, _req, _target = futs[fut]
            try:
                fut.result()
            except Exception as e:  # noqa: BLE001
                log.error("%s %s failed: %r", f, mmdd, e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
