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


def main():
    p = argparse.ArgumentParser(); p.add_argument("--synthetic", action="store_true"); p.add_argument("--forecast-only", action="store_true")
    p.add_argument("--n-after", type=int, default=0); a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    cfg, snow, defs = RegionConfig.load(), SnowConfig.load(), load_indices()
    K = cfg.K_quintile
    season = snow.raw["season"]
    locked = tuple(season["locked_final_exam_winters"]); t0, t1 = season["test_winters"]
    y0, y1 = int(t0[:4]), int(t1[:4])
    test_winters = [f"{y}/{str(y + 1)[-2:]}" for y in range(y0, y1 + 1)]
    val_winter = season["duet_validation_winter"]
    keys = ["MOI", "SJI", "SHI", "EAT"] if a.synthetic else list(defs)
    if not a.synthetic:
        log.error("real state/ backtest not wired yet: needs S2S members and CDS truth in state/ (see the TODO list)"); return 2
    results, duet_results, site_skill, cdfs_by_lead = [], [], {}, {}
    for lead in cfg.time.leads:
        truth, sources = synthetic_sources(lead, keys)
        gt_delta = cfg.time.gt_delta(lead)
        per_source = {}
        for src in sources:
            cdfs, O, targets = run_source(src, truth, lead, K, gt_delta, test_winters + [val_winter], locked, n_after=a.n_after)
            per_source[src.name] = (cdfs, O, targets)
            test_t = targets[[season_of(t) in test_winters for t in targets]]
            sub = {m: P.sel(time=test_t) for m, P in cdfs.items()}
            results += score_methods(sub, O, test_t, K, src.name, lead)
        (ca, Oa, ta), (cb, _, _) = per_source["ecmwf"], per_source["jma"]
        vy = int(val_winter[:4])
        d = duet(ca["pbc"], cb["pbc"], Oa, validation=(f"{vy}-12-01", f"{vy + 1}-02-28"), test_start=pd.Timestamp(f"{y0}-12-01"))
        test_t = ta[[season_of(t) in test_winters for t in ta]]
        dsub = {"raw": ca["raw"].sel(time=test_t), "debiased": ca["debiased"].sel(time=test_t), "pbc": d.pred.sel(time=test_t)}
        duet_results += score_methods(dsub, Oa, test_t, K, "duet", lead)
        cdfs_by_lead[lead] = d.pred
        record(f"backtest-{'synthetic' if a.synthetic else 'real'}-lead{lead}", "phase3", "driver exercise", {"n_after": a.n_after, "lead": lead},
               float(np.nanmean([r.rpss['pbc'] for r in duet_results if r.lead == lead])), "RPSS_pbc_duet", notes="synthetic" if a.synthetic else "")
    write_backtest_md(results, duet_results, ROOT / "docs" / "BACKTEST.md", a.synthetic, locked, test_winters, a.n_after)
    site_skill = summarise_for_site(duet_results)
    # a forecast JSON for the last available issue date
    last_t = pd.Timestamp(cdfs_by_lead[19].time.values[-1]); init = (last_t - pd.Timedelta(days=18)).date()
    drivers = {"ao": {"value": 0.0, "date": str(init)}, "mjo": {"phase": 1, "amp": 0.5, "rmm1": None, "rmm2": None, "date": str(init)},
               "vortex": {"u10": 20.0, "state": "normal", "date": str(init)}, "sst_anom": 0.0, "recent_snow": {}}
    d = assemble_forecast(issued=init + dt.timedelta(days=2), init=init, index_cdfs=cdfs_by_lead, index_defs=defs, index_skill=site_skill,
                          snow=None, drivers=drivers)
    d["references"] = render_refs(); d["preview"] = a.synthetic
    rep = check_forecast_json(d); rep.raise_if_failed()
    (ROOT / "state").mkdir(exist_ok=True)
    (ROOT / "state" / "latest.json").write_text(json.dumps(d, indent=1, default=str))
    log.info("wrote docs/BACKTEST.md and state/latest.json (%s)", "SYNTHETIC" if a.synthetic else "real")
    for r in duet_results:
        log.info("duet %s lead %d: pbc RPSS %.3f, lift %+.3f %s", r.target, r.lead, r.rpss["pbc"], r.lifts["pbc"]["lift"], r.lifts["pbc"]["ci"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
