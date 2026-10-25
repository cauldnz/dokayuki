"""Run the Phase 3 backtest (or, with --synthetic, exercise the driver on synthetic sources).

  run_backtest.py --synthetic            # writes docs/BACKTEST.md labelled SYNTHETIC and state/latest.json
  run_backtest.py                        # real state/ (needs S2S members and CDS truth)
  run_backtest.py --forecast-only        # used by daily.py: refit on state and write state/latest.json
"""
import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import numpy as np
import pandas as pd
import xarray as xr
from dokayuki.backtest import SourceData, run_source, score_methods, summarise_for_site, write_backtest_md
from dokayuki.config import RegionConfig, SnowConfig, load_indices
from dokayuki.duet import duet
from dokayuki.experiments import record
from dokayuki.forecast import assemble_forecast
from dokayuki.site.references import render as render_refs
from dokayuki.synth import SynthSpec, make_forecasts, make_truth_weekly
from dokayuki.validate import check_forecast_json
from dokayuki.weekly import season_of

ROOT = Path(__file__).resolve().parents[1]
log = logging.getLogger("backtest")


def synthetic_sources(lead: int, keys):
    spec = SynthSpec(start="1980-01-01", end="2023-02-28", n_targets=len(keys), first_forecast_year=2015, seed=11, skill=0.45)
    truth = make_truth_weekly(spec).assign_coords(target=keys)
    fc, rf = make_forecasts(truth, spec, lead)
    fc = fc.assign_coords(target=keys); rf = rf.assign_coords(target=keys)
    spec2 = SynthSpec(start="1980-01-01", end="2023-02-28", n_targets=len(keys), first_forecast_year=2015, seed=12, skill=0.3, bias=0.5)
    fc2, rf2 = make_forecasts(truth, spec2, lead)
    return truth, [SourceData("ecmwf", fc, rf), SourceData("jma", fc2.assign_coords(target=keys), rf2.assign_coords(target=keys))]


def real_sources(lead: int, root: Path = ROOT) -> tuple[xr.DataArray, list[SourceData], list[str]]:
    """Truth (time, target) from the ERA5 weekly index table and the decoded S2S members for ``lead``.
    Targets are those present on both sides; winters are those with forecast issues in them."""
    tbl = pd.read_parquet(root / "state" / "truth_weekly_indices.parquet")
    sources, keys = [], None
    for origin in ("ecmwf", "jma"):
        fp = root / "state" / "members" / origin / str(lead) / "forecast_idx.nc"
        rp = root / "state" / "members" / origin / str(lead) / "reforecast_idx.nc"
        if not (fp.exists() and rp.exists()):
            continue
        fc, rf = xr.open_dataarray(fp).load(), xr.open_dataarray(rp).load()
        common = [t for t in fc["target"].values if t in tbl.columns and t in rf["target"].values]
        keys = common if keys is None else [k for k in keys if k in common]
        sources.append(SourceData(origin, fc, rf))
    if not sources:
        raise FileNotFoundError("no decoded members in state/members/*/%d" % lead)
    sources = [SourceData(s.name, s.fc.sel(target=keys), s.rf.sel(target=keys)) for s in sources]
    truth = xr.DataArray(tbl[keys].values, dims=("time", "target"), coords={"time": tbl.index.values, "target": keys}).rename("truth")
    return truth, sources, keys


def winters_with_data(fc: xr.DataArray, lead: int, candidates: list[str], min_weeks: int = 10) -> list[str]:
    """Candidate test winters whose DJF target weeks are actually forecast (at least ``min_weeks`` of them)."""
    from dokayuki.weekly import forecast_delta
    t = pd.DatetimeIndex(fc.get_index("issue") + pd.Timedelta(days=forecast_delta(lead)))
    counts = {}
    for ts in t:
        if ts.month in (12, 1, 2):
            counts[season_of(ts)] = counts.get(season_of(ts), 0) + 1
    return [w for w in candidates if counts.get(w, 0) >= min_weeks]


def main():
    p = argparse.ArgumentParser(); p.add_argument("--synthetic", action="store_true"); p.add_argument("--forecast-only", action="store_true")
    p.add_argument("--n-after", type=int, default=0)
    p.add_argument("--output-root", default=None, help="write docs/BACKTEST.md, state/latest.json and "
                   "experiments/log.csv under this root instead of the repo root (tests use a tmp_path "
                   "so a test run never touches the real files)")
    a = p.parse_args()
    out_root = Path(a.output_root) if a.output_root else ROOT
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    cfg, snow, defs = RegionConfig.load(), SnowConfig.load(), load_indices()
    K = cfg.K_quintile
    season = snow.raw["season"]
    locked = tuple(season["locked_final_exam_winters"]); t0, t1 = season["test_winters"]
    y0, y1 = int(t0[:4]), int(t1[:4])
    test_winters = [f"{y}/{str(y + 1)[-2:]}" for y in range(y0, y1 + 1)]
    val_winter = season["duet_validation_winter"]
    keys = ["MOI", "SJI", "SHI", "EAT"] if a.synthetic else None
    results, duet_results, site_skill, cdfs_by_lead = [], [], {}, {}
    for lead in cfg.time.leads:
        if a.synthetic:
            truth, sources = synthetic_sources(lead, keys)
        else:
            truth, sources, keys = real_sources(lead)
            have = winters_with_data(sources[0].fc, lead, test_winters)
            if have != test_winters:
                log.warning("lead %d: forecasts cover %s of the configured test winters %s; scoring those", lead, have, test_winters)
                test_winters = have
            log.info("lead %d: targets %s, sources %s, test winters %s", lead, keys, [s.name for s in sources], test_winters)
        gt_delta = cfg.time.gt_delta(lead)
        per_source = {}
        for src in sources:
            cdfs, O, targets = run_source(src, truth, lead, K, gt_delta, test_winters + [val_winter], locked, n_after=a.n_after)
            per_source[src.name] = (cdfs, O, targets)
            test_t = targets[[season_of(t) in test_winters for t in targets]]
            sub = {m: P.sel(time=test_t) for m, P in cdfs.items()}
            results += score_methods(sub, O, test_t, K, src.name, lead)
        (ca, Oa, ta) = per_source["ecmwf"]
        test_t = ta[[season_of(t) in test_winters for t in ta]]
        if "jma" in per_source:
            (cb, _, _) = per_source["jma"]
            vy = int(val_winter[:4])
            d = duet(ca["pbc"], cb["pbc"], Oa, validation=(f"{vy}-12-01", f"{vy + 1}-02-28"), test_start=pd.Timestamp(f"{y0}-12-01"))
            dsub = {"raw": ca["raw"].sel(time=test_t), "debiased": ca["debiased"].sel(time=test_t), "pbc": d.pred.sel(time=test_t)}
            duet_results += score_methods(dsub, Oa, test_t, K, "duet", lead)
            cdfs_by_lead[lead] = d.pred
        else:
            cdfs_by_lead[lead] = ca["pbc"]   # one source: no Duet, the ECMWF PBC stands alone
        headline = duet_results if duet_results else [r for r in results if r.source == "ecmwf"]
        record(f"backtest-{'synthetic' if a.synthetic else 'real'}-lead{lead}", "phase3", "driver exercise", {"n_after": a.n_after, "lead": lead},
               float(np.nanmean([r.rpss['pbc'] for r in headline if r.lead == lead])), "RPSS_pbc_duet" if duet_results else "RPSS_pbc_ecmwf",
               notes="synthetic" if a.synthetic else f"real; winters {test_winters}; targets {[str(k) for k in keys]}",
               log=out_root / "experiments" / "log.csv")
    (out_root / "docs").mkdir(parents=True, exist_ok=True)
    write_backtest_md(results, duet_results, out_root / "docs" / "BACKTEST.md", a.synthetic, locked, test_winters, a.n_after)
    site_skill = summarise_for_site(duet_results if duet_results else results, prefer_source="duet" if duet_results else "ecmwf")
    # a forecast JSON for the last available issue date
    from dokayuki.weekly import forecast_delta
    inits = [set(pd.DatetimeIndex(P.time.values) - pd.Timedelta(days=forecast_delta(lead))) for lead, P in cdfs_by_lead.items()]
    init = max(set.intersection(*inits)).date()   # the latest issue that has both leads scored
    drivers = {"ao": {"value": 0.0, "date": str(init)}, "mjo": {"phase": 1, "amp": 0.5, "rmm1": None, "rmm2": None, "date": str(init)},
               "vortex": {"u10": 20.0, "state": "normal", "date": str(init)}, "sst_anom": 0.0, "recent_snow": {}}
    d = assemble_forecast(issued=init + dt.timedelta(days=2), init=init, index_cdfs=cdfs_by_lead, index_defs=defs, index_skill=site_skill,
                          snow=None, drivers=drivers)
    d["references"] = render_refs(); d["preview"] = a.synthetic
    rep = check_forecast_json(d); rep.raise_if_failed()
    (out_root / "state").mkdir(parents=True, exist_ok=True)
    (out_root / "state" / "latest.json").write_text(json.dumps(d, indent=1, default=str))
    log.info("wrote docs/BACKTEST.md and state/latest.json (%s)%s", "SYNTHETIC" if a.synthetic else "real",
             f" under {out_root}" if out_root != ROOT else "")
    for r in (duet_results or results):
        log.info("%s %s lead %d: n %d, debiased RPSS %.3f, raw %.3f, pbc %.3f, lift %+.3f %s%s", r.source, r.target, r.lead, r.n_weeks,
                 r.rpss.get("debiased", float("nan")), r.rpss.get("raw", float("nan")), r.rpss["pbc"], r.lifts["pbc"]["lift"], r.lifts["pbc"]["ci"],
                 "  IMPLAUSIBLE" if r.implausible else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
