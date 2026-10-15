"""S2S members from ECDS: ECMWF and JMA, forecasts and reforecasts, domain box, days 18-33, needed
variables; resumable (request ids in state/requests.json); GRIB decoded to weekly per-member index
values and the gridded weekly means, appended to state/members/.

Usage: pull_s2s.py --origins ecmwf,jma [--start 2015-01-01] [--end ...] [--recent] [--budget-s N] [--dry-run]
The ECDS costing endpoint is called before each submission; the total is printed in --dry-run.
"""
import argparse
import logging
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pandas as pd
import requests
import xarray as xr
from dokayuki.config import RegionConfig, load_indices
from dokayuki.fetch.s2s import RequestLog, build_request, ecds_client, fetch, open_grib_daily
from dokayuki.indices import all_indices
from dokayuki.state import State
from dokayuki.weekly import weekly_from_member_steps

ROOT = Path(__file__).resolve().parents[1]; STATE = State(ROOT / "state"); RAW = ROOT / "state" / "grib"
FIELDS = ["msl", "t2m", "tp", "sf", "sst", "t850", "z500", "u850", "v850", "u10hpa"]
CONSTRAINTS = "https://ecds.ecmwf.int/api/catalogue/v1/collections/{c}/constraints.json"
log = logging.getLogger("s2s")


def init_dates(collection: str, origin: str) -> pd.DatetimeIndex:
    cons = requests.get(CONSTRAINTS.format(c=collection), timeout=120).json()
    dates = set()
    for b in cons:
        if origin not in b.get("origin", []):
            continue
        for y in b.get("year", []):
            for m in b.get("month", []):
                for d in b.get("day", []):
                    try:
                        dates.add(pd.Timestamp(int(y), int(m), int(d)))
                    except ValueError:
                        pass
    return pd.DatetimeIndex(sorted(dates))


def decode(path: Path, cfg, defs, lead_days=(19, 26)) -> dict:
    """GRIB -> {lead: {"grid": Dataset(member, lat, lon), "idx": DataArray(member, target)}}"""
    ds = open_grib_daily(path)
    out = {}
    for lead in lead_days:
        weekly = {}
        for v in ds.data_vars:
            how = "sum" if v in ("tp", "sf") else "mean"
            weekly[v] = weekly_from_member_steps(ds[v], lead, how)
        wk = xr.Dataset(weekly)
        idx = all_indices(defs, {v: wk[v] for v in wk.data_vars}, skip_missing=True)
        out[lead] = {"grid": wk, "idx": idx}
    return out


def main():
    p = argparse.ArgumentParser(); p.add_argument("--origins", default="ecmwf,jma"); p.add_argument("--start", default="2015-01-01")
    p.add_argument("--end", default=None); p.add_argument("--recent", action="store_true"); p.add_argument("--budget-s", type=float, default=3600)
    p.add_argument("--dry-run", action="store_true"); p.add_argument("--months", default="10,11,12,1,2,3,4")
    a = p.parse_args(); logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    cfg, defs = RegionConfig.load(), load_indices()
    months = {int(m) for m in a.months.split(",")}
    end = pd.Timestamp(a.end) if a.end else pd.Timestamp.now("UTC").tz_localize(None).normalize() - pd.Timedelta(days=2)
    start = end - pd.Timedelta(days=10) if a.recent else pd.Timestamp(a.start)
    reqlog = RequestLog.load(ROOT / "state" / "requests.json")
    plan = []
    for origin in a.origins.split(","):
        for coll, is_rf in (("s2s-forecasts", False), ("s2s-reforecasts", True)):
            dates = init_dates(coll, origin)
            dates = dates[(dates >= start) & (dates <= end) & dates.month.isin(sorted(months))]
            for d in dates:
                for ft in ("control_forecast", "perturbed_forecast"):
                    hy = list(range(d.year - 20, d.year)) if (is_rf and origin == "ecmwf") else (list(range(1991, 2021)) if is_rf else None)
                    for req in build_request(origin, d, FIELDS, cfg.domain, ft, reforecast=is_rf, hyears=hy):
                        tag = f"{origin}_{coll[4:6]}_{d:%Y%m%d}_{ft[:4]}_{req['level_type'][:4]}_{'acc' if '_' in req['leadtime_hour'][0] else 'ins'}"
                        plan.append((coll, req, RAW / origin / f"{tag}.grib"))
    todo = [x for x in plan if not x[2].exists()]
    log.info("%d requests planned, %d to do", len(plan), len(todo))
    if a.dry_run:
        try:
            client = ecds_client(); cost = sum(client.estimate_costs(c, r).get("cost", {}).get("size", 0) for c, r, _ in todo[:20])
            log.info("ECDS cost estimate for the first 20 requests: %s", cost)
        except Exception as e:  # noqa: BLE001
            log.info("no ECDS key: showing the first requests only (%s)", e)
        for c, r, t in todo[:3]: log.info("%s %s -> %s", c, {k: (v if k != 'leadtime_hour' else len(v)) for k, v in r.items()}, t.name)
        return 0
    client = ecds_client(); t0 = time.time()
    for coll, req, target in todo:
        if time.time() - t0 > a.budget_s:
            log.warning("budget exhausted; %d requests remain (resumable)", len(todo)); break
        got = fetch(coll, req, target, reqlog, client=client, budget_s=max(60, a.budget_s - (time.time() - t0)))
        if got is None:
            continue
        dec = decode(got, cfg, defs)
        origin = req["origin"]; init = pd.Timestamp(f"{req['year']}-{req['month']}-{req['day']}")
        for lead, parts in dec.items():
            idx = parts["idx"].expand_dims(issue=[init]) if "hyear" not in parts["idx"].dims else parts["idx"]
            STATE.write_members(origin, lead, "reforecast_idx" if "hyear" in req else "forecast_idx", idx)
    return 0


if __name__ == "__main__":
    sys.exit(main())
