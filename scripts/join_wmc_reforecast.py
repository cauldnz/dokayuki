"""Join the WMC Tokyo CPS4 hindcast (state/wmc_daily/cps4/*.nc) into state/members/jma/ as a
real reforecast climatology, in the same (issue, hyear, member, target) layout
dokayuki.fetch.s2s.to_members produces for ECDS reforecasts.

ECDS's own JMA reforecast sets fail on every retrieval (docs/DATA_NOTES.md); WMC covers the
CPS4 era (real-time since 2026-01-22) for free, no key. The CPS3 era (the sealed winters) comes
from CDS instead (scripts/pull_cds_seasonal.py), joined the same way by a sibling script once
that pull lands.

The WMC files carry msl, t2m, tp, t850, z500 only (no u850/v850, no sst) -- NWF is therefore
never computable for JMA from this source, and SJI needs the same persisted-SST series already
used for ECMWF's reforecasts (dokayuki.indices.load_sst_climatology/sst_for_time), since the
persisted SST is an *observed* series, not model output.

issue is tagged with CPS4's model-version year (2026, per the S2S Confluence wiki's "model
version date 2026-01-31") and the real month/day of each WMC start date, so every hindcast year
entry at one start date shares one issue and differs only by hyear -- the same shape ECMWF's
own reforecast issue/hyear split takes, even though JMA's real model-version date is a single
fixed tag rather than one per calendar year.

Usage: join_wmc_reforecast.py [--mmdds 0116,0131,...] [--leads 19,26]
"""
import argparse
import logging
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import numpy as np
import pandas as pd
import xarray as xr
from dokayuki.config import RegionConfig, load_indices
from dokayuki.indices import all_indices, load_sst_climatology, sst_for_time
from dokayuki.state import State
from dokayuki.weekly import weekly_from_member_steps

ROOT = Path(__file__).resolve().parents[1]
STATE = State(ROOT / "state")
WMC_DAILY = ROOT / "state" / "wmc_daily" / "cps4"
STAGE1 = {"U10_60N", "UBI", "AO"}  # need hemispheric fields WMC doesn't carry; never computable here
CPS4_ISSUE_YEAR = 2026
log = logging.getLogger("join_wmc_reforecast")


def to_members_reforecast(idx: xr.DataArray, issue_year: int) -> xr.DataArray:
    """(number, time, target) -> (issue, hyear, member, target), same convention as
    dokayuki.fetch.s2s.to_members for reforecasts: issue shares ``issue_year`` with the real
    month/day of ``time``; hyear is time's own year."""
    idx = idx.rename({"number": "member"})
    t = pd.DatetimeIndex(idx["time"].values)
    issue = pd.to_datetime(pd.DataFrame({"year": issue_year, "month": t.month, "day": t.day}))
    idx = idx.assign_coords(issue=("time", issue.values), hyear=("time", t.year.values))
    idx = idx.set_index(time=["issue", "hyear"]).unstack("time")
    return idx.transpose("issue", "hyear", "member", "target")


def decode_one_mmdd(ds: xr.Dataset, defs, lead_days: tuple[int, ...], sst_clim) -> dict[int, xr.DataArray]:
    """One WMC start date's Dataset -> {lead: DataArray(number, time, target)}."""
    out = {}
    for lead in lead_days:
        fields = {f: weekly_from_member_steps(ds[f], lead, "sum" if f == "tp" else "mean", step_dim="step_day")
                  for f in ds.data_vars}
        t = pd.DatetimeIndex(fields["msl"]["time"].values)
        sst = sst_for_time(t, lead, sst_clim)
        idx = all_indices({k: v for k, v in defs.items() if k not in STAGE1}, fields, sst=sst, skip_missing=True)
        out[lead] = idx
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--mmdds", default=None, help="comma-separated MMDD start dates; default: every file under state/wmc_daily/cps4/")
    p.add_argument("--leads", default="19,26")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    cfg, defs = RegionConfig.load(), load_indices()
    sst_clim = load_sst_climatology(defs["SJI"].box)
    if sst_clim[0] is None:
        log.warning("no ERA5 SST climatology found; SJI will be all-NaN for JMA too")
    lead_days = tuple(int(x) for x in a.leads.split(","))
    mmdds = a.mmdds.split(",") if a.mmdds else sorted(p.stem for p in WMC_DAILY.glob("*.nc"))
    if not mmdds:
        log.error("no files under %s; run pull_wmc_hindcast.py first", WMC_DAILY)
        return 2
    log.info("%d start dates: %s", len(mmdds), mmdds)
    by_lead: dict[int, list[xr.DataArray]] = {lead: [] for lead in lead_days}
    for mmdd in mmdds:
        path = WMC_DAILY / f"{mmdd}.nc"
        if not path.exists():
            log.warning("%s missing, skipped", path)
            continue
        ds = xr.open_dataset(path)
        dec = decode_one_mmdd(ds, defs, lead_days, sst_clim)
        for lead, idx in dec.items():
            by_lead[lead].append(to_members_reforecast(idx, CPS4_ISSUE_YEAR))
        ds.close()
        log.info("%s decoded", mmdd)
    for lead, pieces in by_lead.items():
        if not pieces:
            continue
        da = xr.concat(pieces, dim="issue").sortby("issue")
        path = STATE.write_members("jma", lead, "reforecast_idx", da)
        log.info("wrote %s: %d issues, %d hyears, %d members, targets %s", path, da.sizes["issue"],
                 da.sizes["hyear"], da.sizes["member"], list(da["target"].values))
    return 0


if __name__ == "__main__":
    sys.exit(main())
