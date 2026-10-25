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
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import numpy as np
import pandas as pd
import requests
import xarray as xr
from dokayuki.config import RegionConfig, load_indices
from dokayuki.fetch.s2s import VARIABLES, RequestLog, build_request, ecds_client, fetch, hemi_requests, open_grib_daily
from dokayuki.grid import area_mean
from dokayuki.indices import all_indices
from dokayuki.state import State
from dokayuki.weekly import forecast_delta, weekly_from_member_steps

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


HYEAR_CHUNK = 10


def hyear_chunks(hyears: list[int] | None, size: int = HYEAR_CHUNK) -> list[tuple[list[int] | None, str]]:
    """[(hindcast years for one request, part-name suffix)]; forecasts (no hyears) are one unchunked part."""
    if not hyears:
        return [(None, "")]
    return [(hyears[i:i + size], f"_h{hyears[i]}-{hyears[min(i + size, len(hyears)) - 1]}") for i in range(0, len(hyears), size)]


def join_pieces(arrs: list[xr.DataArray]) -> xr.DataArray:
    """Join the pieces of one variable: files that share their time axis are different member sets
    (control and perturbed) and concatenate on ``number``; files with different time axes are
    hindcast-year chunks (or forecast types that arrived separately) and concatenate on ``time``."""
    if len(arrs) == 1:
        return arrs[0]
    by_time: dict[tuple, list[xr.DataArray]] = {}
    for a in arrs:
        by_time.setdefault(tuple(pd.DatetimeIndex(a["time"].values).astype("int64")), []).append(a)
    groups = [xr.concat(g, dim="number").sortby("number") if len(g) > 1 else g[0] for g in by_time.values()]
    return groups[0] if len(groups) == 1 else xr.concat(groups, dim="time").sortby("time")


def weekly_fields(ds: xr.Dataset, lead: int) -> xr.Dataset:
    out = {}
    for v in ds.data_vars:
        how = "sum" if v in ("tp", "sf") else "mean"
        out[v] = weekly_from_member_steps(ds[v], lead, how, step_dim="step_day")
    return xr.Dataset(out)


def _weekly_parts(parts: dict[str, Path], prefix: str, lead_days) -> dict[int, dict[str, xr.DataArray]]:
    """Open the GRIBs whose part name (after the forecast-type prefix) starts with ``prefix``, reduce
    each variable to its weekly value per lead at once (float32, in memory), and join the pieces
    (member sets on ``number``, hindcast-year chunks on ``time``). Daily fields are never held for more than one variable, which
    keeps a 220 member-year reforecast month under a gigabyte instead of ten."""
    weekly: dict[int, dict[str, list[xr.DataArray]]] = {lead: {} for lead in lead_days}
    for name, path in parts.items():
        _ft, _, rest = name.partition("_")
        if not rest.startswith(prefix):
            continue
        ds = open_grib_daily(path)
        for v in ds.data_vars:
            how = "sum" if v in ("tp", "sf") else "mean"
            for lead in lead_days:
                wk = weekly_from_member_steps(ds[v], lead, how, step_dim="step_day").astype("float32").load()
                weekly[lead].setdefault(v, []).append(wk)
        ds.close()
    out = {}
    for lead in lead_days:
        out[lead] = {v: join_pieces(arrs) for v, arrs in weekly[lead].items()}
    return out


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


def load_sst_climatology(box, path: Path = Path("state/era5_15_daily.zarr")):
    """(daily box-mean SST, day-of-year climatology) from the ERA5 WB2 pull, or (None, None) if it
    isn't there -- SJI is then skipped (``all_indices(..., skip_missing=True)`` already handles sst=None)."""
    if not path.exists():
        log.warning("%s not found; SJI will be skipped (needs the ERA5 1.5deg pull)", path)
        return None, None
    ds = xr.open_zarr(path)
    daily = area_mean(ds["sst"], box).load().rename("sst")
    clim = daily.groupby("time.dayofyear").mean("time").rename("sst_clim_doy")
    return daily, clim


def sst_for_time(t: pd.DatetimeIndex, lead: int, sst_clim) -> xr.DataArray | None:
    """Persisted-SST series (one scalar per issue, the real calendar date) for one lead's time
    coordinate; NaN past the ERA5 pull's range rather than silently reusing a stale nearest value.

    Vectorised (numpy, not per-issue ``xr.DataArray.sel``): a reforecast month's ``time`` axis
    can carry hundreds of entries (one per hindcast year x issue), and xarray's label-based
    ``.sel`` has enough per-call overhead that a Python loop over it dominated decode time."""
    daily, clim = sst_clim
    if daily is None:
        return None
    order = np.argsort(daily["time"].values)
    dates, vals_by_date = daily["time"].values[order], daily.values[order]
    lo, hi = dates[0], dates[-1]
    clim_by_doy = np.full(367, np.nan)
    clim_by_doy[clim["dayofyear"].values.astype(int)] = clim.values

    obs_days = (t - pd.Timedelta(days=7)).values
    idx = np.clip(np.searchsorted(dates, obs_days), 1, len(dates) - 1)
    nearest = np.where(np.abs(dates[idx] - obs_days) < np.abs(dates[idx - 1] - obs_days), idx, idx - 1)
    anom = vals_by_date[nearest] - clim_by_doy[pd.DatetimeIndex(obs_days).dayofyear.values]

    target_doys = np.stack([(t + pd.Timedelta(days=i)).dayofyear.values for i in range(forecast_delta(lead), forecast_delta(lead) + 7)], axis=1)
    persisted = clim_by_doy[target_doys].mean(axis=1) + anom
    return xr.DataArray(np.where((obs_days < lo) | (obs_days > hi), np.nan, persisted), dims="time", coords={"time": t})


def decode(parts: dict[str, Path], defs, lead_days=(19, 26), sst_clim=(None, None)) -> dict[int, xr.DataArray]:
    """{part: grib path} for one (origin, month), both forecast types -> {lead: DataArray(number, time, target)}."""
    dom = _weekly_parts(parts, "dom", lead_days)
    hemi = {k: _weekly_parts(parts, k, lead_days) for k in ("ao", "ural", "u10")}
    out = {}
    for lead in lead_days:
        pieces = []
        if dom[lead]:
            t = pd.DatetimeIndex(next(iter(dom[lead].values()))["time"].values)
            sst = sst_for_time(t, lead, sst_clim)
            aux = {"v850": dom[lead]["v850"]} if "v850" in dom[lead] else {}
            pieces.append(all_indices({k: v for k, v in defs.items() if k not in STAGE1}, dom[lead],
                                       sst=sst, skip_missing=True, aux=aux))
        hf = {}
        for k in hemi:
            hf.update(hemi[k][lead])
        if hf:
            pieces.append(all_indices({k: v for k, v in defs.items() if k in STAGE1}, hf, skip_missing=True))
        out[lead] = xr.concat(pieces, dim="target")
    return out


def main():
    p = argparse.ArgumentParser(); p.add_argument("--origins", default="ecmwf,jma"); p.add_argument("--start", default="2015-01-01")
    p.add_argument("--end", default=None); p.add_argument("--recent", action="store_true"); p.add_argument("--budget-s", type=float, default=3600)
    p.add_argument("--dry-run", action="store_true"); p.add_argument("--months", default="10,11,12,1,2,3,4")
    p.add_argument("--no-reforecasts", action="store_true"); p.add_argument("--delete-grib", action="store_true")
    p.add_argument("--parallel", type=int, default=4, help="requests in flight at once on ECDS")
    p.add_argument("--priority-reforecast-end", default=None,
                    help="pull reforecast jobs with init month <= this date first, ahead of the rest of the queue")
    p.add_argument("--redecode", action="store_true",
                    help="reprocess dates already in state/members/ too (e.g. a new target was added to "
                         "config/indices.yaml); fetch() still returns at once for GRIB already on disk, "
                         "so this is a local re-decode, not a re-pull")
    a = p.parse_args(); logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    cfg, defs = RegionConfig.load(), load_indices()
    sst_clim = load_sst_climatology(defs["SJI"].box)
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
            done = set() if a.redecode else (set(pd.DatetimeIndex(have["issue"].values)) if have is not None else set())
            for (y, m), grp in dates.to_series().groupby([dates.year, dates.month]):
                days = sorted({d.day for d in grp if d not in done})   # already decoded dates are not re-pulled
                if not days:
                    continue
                init = pd.Timestamp(int(y), int(m), days[0])
                hy = list(range(int(y) - 20, int(y))) if (is_rf and origin == "ecmwf") else (list(range(1991, 2021)) if is_rf else None)
                parts = []   # control and perturbed members in one request (ECDS time is mostly per request)
                ft = ["control_forecast", "perturbed_forecast"]
                # ECDS refuses a reforecast request over about 10 hindcast years for a multi-variable or
                # large-area part ("cost limits exceeded"), so hindcast years go in chunks; the decoder
                # joins the chunks on time
                for hy_chunk, suffix in hyear_chunks(hy):
                    for req in build_request(origin, init, FIELDS_DOMAIN, cfg.domain, ft, reforecast=is_rf, hyears=hy_chunk, days=days):
                        parts.append((f"both_dom_{part_name(req)}{suffix}", req))
                    parts += [(f"both_{part}{suffix}", req) for part, req in hemi_requests(origin, init, ft, reforecast=is_rf, hyears=hy_chunk, days=days)]
                tag = f"{origin}_{coll[4:6]}_{y}{int(m):02d}"
                jobs.append((coll, tag, is_rf, [(part, req, RAW / origin / f"{tag}_{part}.grib") for part, req in parts]))
    if a.priority_reforecast_end:
        cutoff = pd.Timestamp(a.priority_reforecast_end)

        def prio(job: tuple) -> int:
            _coll, tag, is_rf, _parts = job
            ym = tag[-6:]
            return 0 if (is_rf and pd.Timestamp(int(ym[:4]), int(ym[4:]), 1) <= cutoff) else 1

        jobs.sort(key=prio)   # stable: priority reforecasts keep their chronological order, so does the rest
    todo = jobs   # fetch() returns at once for a GRIB already on disk, so a job with every part present only decodes
    n_req = sum(len(j[3]) for j in jobs)
    n_fetch = sum(1 for j in jobs for _, _, t in j[3] if not t.exists())
    log.info("%d jobs (%d requests) planned, %d requests to fetch", len(jobs), n_req, n_fetch)
    if a.dry_run:
        for coll, tag, is_rf, parts in todo[:2]:
            for part, req, t in parts:
                log.info("%s %s -> %s", coll, {k: (v if k != "leadtime_hour" else len(v)) for k, v in req.items()}, t.name)
        return 0
    t0 = time.time()
    local = threading.local()

    def client_for_thread():
        if not hasattr(local, "client"):
            local.client = ecds_client()
        return local.client

    def fetch_part(coll, req, target):
        budget = max(60, a.budget_s - (time.time() - t0))
        return fetch(coll, req, target, reqlog, client=client_for_thread(), budget_s=budget)

    # all parts of all jobs go to the pool in job order; up to --parallel requests in flight at
    # once; each job decodes as soon as its own parts are in
    pool = ThreadPoolExecutor(max_workers=a.parallel)
    futures = {tag: [(part, pool.submit(fetch_part, coll, req, target)) for part, req, target in parts]
               for coll, tag, is_rf, parts in todo}
    try:
        for coll, tag, is_rf, parts in todo:
            got = {}
            for part, fut in futures[tag]:
                try:
                    path = fut.result()
                except Exception as e:  # noqa: BLE001
                    log.error("%s %s: fetch raised %s", tag, part, e)
                    path = None
                if path is not None:
                    got[part] = path
            if len(got) < len(parts):
                log.warning("%s incomplete (%d/%d parts); will resume", tag, len(got), len(parts))
                continue
            size_mb = sum(p.stat().st_size for p in got.values()) / 1e6
            t1 = time.time()
            try:
                dec = decode(got, defs, sst_clim=sst_clim)
            except Exception as e:  # noqa: BLE001
                log.exception("%s: decode failed (%s); GRIB kept for a rerun", tag, e)
                continue
            origin = parts[0][1]["origin"]
            for lead, idx in dec.items():
                da = to_members(idx, parts[0][1], is_rf)
                STATE.write_members(origin, lead, "reforecast_idx" if is_rf else "forecast_idx", da)
            log.info("%s: %.0f MB, decoded in %.0fs, %s; %.0f min elapsed", tag, size_mb, time.time() - t1,
                     {k: int(v) for k, v in dec[19].sizes.items()}, (time.time() - t0) / 60)
            if a.delete_grib:
                for p_ in got.values():
                    p_.unlink()
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
