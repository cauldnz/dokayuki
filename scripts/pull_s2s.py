"""S2S members from ECDS: ECMWF and JMA, forecasts and reforecasts, one job per month (control
and perturbed together), one request per level type (ECDS accepts a list of init days; the GRIB then carries a ``time`` axis), days 18-33,
the domain box plus three small hemispheric parts for the stage-1 targets. Resumable (request ids
in state/requests.json). GRIB is decoded to weekly per-member index values appended to
state/members/; the GRIB files stay under state/grib/ unless --delete-grib.

Usage: pull_s2s.py --origins ecmwf,jma [--start 2015-01-01] [--end ...] [--recent] [--budget-s N] [--dry-run]
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
from dokayuki.fetch.s2s import VARIABLES, RequestLog, build_request, ecds_client, fetch, hemi_requests, open_grib_daily
from dokayuki.indices import all_indices
from dokayuki.state import State
from dokayuki.weekly import weekly_from_member_steps

ROOT = Path(__file__).resolve().parents[1]; STATE = State(ROOT / "state"); RAW = ROOT / "state" / "grib"
FIELDS_DOMAIN = ["msl", "t2m", "tp", "sf", "sst", "t850", "z500", "u850", "v850"]
STAGE1 = {"U10_60N", "UBI", "AO"}
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


KIND_OF = {v[1]: v[3] for v in VARIABLES.values()}


def part_name(req: dict) -> str:
    lev = "".join(l.split("_")[0] for l in req.get("level_value", []))
    return f"{req['level_type'][:4]}{lev}_{KIND_OF.get(req['variable'][0], 'instant')[:3]}"


def weekly_fields(ds: xr.Dataset, lead: int) -> xr.Dataset:
    out = {}
    for v in ds.data_vars:
        how = "sum" if v in ("tp", "sf") else "mean"
        out[v] = weekly_from_member_steps(ds[v], lead, how, step_dim="step_day")
    return xr.Dataset(out)


def to_members(idx: xr.DataArray, req: dict, reforecast: bool) -> xr.DataArray:
    """(number, time, target) -> forecasts (issue, member, target); reforecasts (issue, hyear, member, target)
    where ``issue`` is the model-version date (request year, hindcast month-day) and ``hyear`` the hindcast year."""
    idx = idx.rename({"number": "member"})
    t = pd.DatetimeIndex(idx["time"].values)
    if not reforecast:
        return idx.rename({"time": "issue"}).transpose("issue", "member", "target")
    issue = pd.to_datetime(pd.DataFrame({"year": int(req["year"]), "month": t.month, "day": t.day}))
    idx = idx.assign_coords(issue=("time", issue.values), hyear=("time", t.year.values))
    idx = idx.set_index(time=["issue", "hyear"]).unstack("time")
    return idx.transpose("issue", "hyear", "member", "target")


def _open_parts(parts: dict[str, Path], prefix: str) -> xr.Dataset | None:
    """Open the GRIBs whose part name starts with ``prefix`` (any forecast type) and concatenate
    control (number 0) and perturbed (1..N) members on ``number``."""
    by_suffix: dict[str, list[xr.Dataset]] = {}
    for name, path in parts.items():
        ft, _, rest = name.partition("_")
        if rest.startswith(prefix):
            by_suffix.setdefault(rest, []).append(open_grib_daily(path))
    if not by_suffix:
        return None
    merged = [xr.concat(dss, dim="number").sortby("number") if len(dss) > 1 else dss[0] for dss in by_suffix.values()]
    return xr.merge(merged)


def decode(parts: dict[str, Path], defs, lead_days=(19, 26)) -> dict[int, xr.DataArray]:
    """{part: grib path} for one (origin, month), both forecast types -> {lead: DataArray(number, time, target)}."""
    out = {}
    ds_dom = _open_parts(parts, "dom")
    hemi = {k: _open_parts(parts, k) for k in ("ao", "ural", "u10")}
    for lead in lead_days:
        pieces = []
        if ds_dom is not None:
            wk = weekly_fields(ds_dom, lead)
            pieces.append(all_indices({k: v for k, v in defs.items() if k not in STAGE1}, {v: wk[v] for v in wk.data_vars}, skip_missing=True))
        hf = {}
        for k, ds in hemi.items():
            if ds is not None:
                wk = weekly_fields(ds, lead)
                hf.update({v: wk[v] for v in wk.data_vars})
        if hf:
            pieces.append(all_indices({k: v for k, v in defs.items() if k in STAGE1}, hf, skip_missing=True))
        out[lead] = xr.concat(pieces, dim="target")
    return out


def main():
    p = argparse.ArgumentParser(); p.add_argument("--origins", default="ecmwf,jma"); p.add_argument("--start", default="2015-01-01")
    p.add_argument("--end", default=None); p.add_argument("--recent", action="store_true"); p.add_argument("--budget-s", type=float, default=3600)
    p.add_argument("--dry-run", action="store_true"); p.add_argument("--months", default="10,11,12,1,2,3,4")
    p.add_argument("--no-reforecasts", action="store_true"); p.add_argument("--delete-grib", action="store_true")
    a = p.parse_args(); logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    cfg, defs = RegionConfig.load(), load_indices()
    months = {int(m) for m in a.months.split(",")}
    end = pd.Timestamp(a.end) if a.end else pd.Timestamp.now("UTC").tz_localize(None).normalize() - pd.Timedelta(days=2)
    start = end - pd.Timedelta(days=10) if a.recent else pd.Timestamp(a.start)
    reqlog = RequestLog.load(ROOT / "state" / "requests.json")
    # one job = one (origin, collection, year, month, forecast_type): several requests, one decode
    jobs = []
    for origin in a.origins.split(","):
        for coll, is_rf in (("s2s-forecasts", False), ("s2s-reforecasts", True)):
            if is_rf and a.no_reforecasts:
                continue
            dates = init_dates(coll, origin)
            dates = dates[(dates >= start) & (dates <= end) & dates.month.isin(sorted(months))]
            have = STATE.read_members(origin, 19, "reforecast_idx" if is_rf else "forecast_idx")
            done = set(pd.DatetimeIndex(have["issue"].values)) if have is not None else set()
            for (y, m), grp in dates.to_series().groupby([dates.year, dates.month]):
                days = sorted({d.day for d in grp if d not in done})   # already decoded dates are not re-pulled
                if not days:
                    continue
                init = pd.Timestamp(int(y), int(m), days[0])
                hy = list(range(int(y) - 20, int(y))) if (is_rf and origin == "ecmwf") else (list(range(1991, 2021)) if is_rf else None)
                parts = []   # both forecast types in one job so control and perturbed members land together
                for ft in ("control_forecast", "perturbed_forecast"):
                    for req in build_request(origin, init, FIELDS_DOMAIN, cfg.domain, ft, reforecast=is_rf, hyears=hy, days=days):
                        parts.append((f"{ft[:4]}_dom_{part_name(req)}", req))
                    parts += [(f"{ft[:4]}_{part}", req) for part, req in hemi_requests(origin, init, ft, reforecast=is_rf, hyears=hy, days=days)]
                tag = f"{origin}_{coll[4:6]}_{y}{int(m):02d}"
                jobs.append((coll, tag, is_rf, [(part, req, RAW / origin / f"{tag}_{part}.grib") for part, req in parts]))
    todo = [j for j in jobs if not all(t.exists() for _, _, t in j[3])]
    n_req = sum(len(j[3]) for j in jobs)
    log.info("%d jobs (%d requests) planned, %d jobs to do", len(jobs), n_req, len(todo))
    if a.dry_run:
        for coll, tag, is_rf, parts in todo[:2]:
            for part, req, t in parts:
                log.info("%s %s -> %s", coll, {k: (v if k != "leadtime_hour" else len(v)) for k, v in req.items()}, t.name)
        return 0
    client = ecds_client(); t0 = time.time()
    for coll, tag, is_rf, parts in todo:
        if time.time() - t0 > a.budget_s:
            log.warning("budget exhausted; %d jobs remain (resumable)", len(todo)); break
        got = {}
        for part, req, target in parts:
            path = fetch(coll, req, target, reqlog, client=client, budget_s=max(60, a.budget_s - (time.time() - t0)))
            if path is None:
                break
            got[part] = path
        if len(got) < len(parts):
            log.warning("%s incomplete (%d/%d parts); will resume", tag, len(got), len(parts))
            continue
        size_mb = sum(p.stat().st_size for p in got.values()) / 1e6
        t1 = time.time()
        try:
            dec = decode(got, defs)
        except Exception as e:  # noqa: BLE001
            log.exception("%s: decode failed (%s); GRIB kept for a rerun", tag, e)
            continue
        origin = parts[0][1]["origin"]
        for lead, idx in dec.items():
            da = to_members(idx, parts[0][1], is_rf)
            STATE.write_members(origin, lead, "reforecast_idx" if is_rf else "forecast_idx", da)
        log.info("%s: %.0f MB, decoded in %.0fs, %s", tag, size_mb, time.time() - t1, {k: int(v) for k, v in dec[19].sizes.items()})
        if a.delete_grib:
            for p_ in got.values():
                p_.unlink()
    return 0


if __name__ == "__main__":
    sys.exit(main())
