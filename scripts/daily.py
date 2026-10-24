"""The daily run: append the newest data, refit, forecast, validate, build. Never publishes garbage:
any failure after a last good forecast exists rebuilds that forecast with the stale banner.

Stages (each timed and logged):
  1. observed indices (AO, MJO)                      -> state/obs_indices.parquet
  2. ERA5T weeks via CDS                              -> state/era5_* (needs ECMWF_API_KEY)
  3. newest ECMWF/JMA runs (+ reforecasts) via ECDS   -> state/members/* (needs ECMWF_API_KEY; resumable)
  4. refit PBC per index and lead, Duet              (all fits are small)
  5. Stage-3 snow model (only if the backtest says it is skilful)
  6. assemble + validate the forecast JSON           -> state/latest.json
  7. build the site                                  -> site/build/latest
"""
import argparse
import json
import logging
import sys
import time
import traceback
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from dokayuki.site.build import build
from dokayuki.validate import check_forecast_json

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state"
log = logging.getLogger("daily")


def stage(name):
    def deco(fn):
        def wrapped(*a, **k):
            t0 = time.time(); log.info("== %s", name)
            try:
                return fn(*a, **k)
            finally:
                log.info("== %s done in %.0fs", name, time.time() - t0)
        return wrapped
    return deco


@stage("observed indices")
def obs_indices():
    from dokayuki.fetch.obs_indices import fetch_ao, fetch_rmm, mjo_features
    import pandas as pd
    ao = fetch_ao(STATE / "ao.parquet"); rmm = fetch_rmm(STATE / "rmm.parquet")
    df = pd.concat([ao, mjo_features(rmm)], axis=1).sort_index(); df.index.name = "time"
    df.to_parquet(STATE / "obs_indices.parquet")


@stage("ERA5T weeks (CDS)")
def era5_update(budget_s):
    import subprocess
    subprocess.run([sys.executable, str(ROOT / "scripts" / "pull_cds.py"), "--recent", "--budget-s", str(int(budget_s))],
                    check=True, timeout=budget_s + 60)


@stage("S2S runs (ECDS)")
def s2s_update(budget_s):
    # pull_s2s.py's own --budget-s only bounds new ECDS submissions, not an in-flight decode
    # (CY48R1's 101-member live inits can take 20-30 min to decode on their own); enforce the
    # wall-clock limit here too so one slow month can't blow the whole daily run's time budget.
    import subprocess
    subprocess.run([sys.executable, str(ROOT / "scripts" / "pull_s2s.py"), "--recent", "--budget-s", str(int(budget_s))],
                    check=True, timeout=budget_s + 60)


@stage("refit + forecast")
def refit_and_forecast():
    import subprocess
    subprocess.run([sys.executable, str(ROOT / "scripts" / "run_backtest.py"), "--forecast-only"], check=True)
    d = json.loads((STATE / "latest.json").read_text())
    check_forecast_json(d).raise_if_failed()
    return d


def rebuild_stale(reason: str):
    last = STATE / "last_good.json"
    if not last.exists():
        log.error("no last good forecast to fall back on: %s", reason); return 2
    d = json.loads(last.read_text())
    d["stale"] = True; d["stale_since"] = d.get("issued")
    d["headline"] = f"Outlook is stale (data behind since {d['stale_since']}); showing the last good run."
    build(d, ROOT / "site" / "build" / "latest")
    log.warning("built the last good forecast with the stale banner (%s)", reason)
    return 0


def main():
    p = argparse.ArgumentParser(); p.add_argument("--budget-min", type=float, default=30); p.add_argument("--offline", action="store_true")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    STATE.mkdir(exist_ok=True)
    t0 = time.time(); budget = a.budget_min * 60
    try:
        if not a.offline:
            obs_indices()
            # ERA5 update fails fast on the current CDS cost-limit bug (see pull_cds.py), so it
            # never needs much of the budget; S2S gets the rest, since a single CY48R1 (101-
            # member) live month can take 20-30 min to decode on its own.
            for name, update, share in (("ERA5 update", era5_update, 0.05), ("S2S update", s2s_update, 0.9)):
                try:
                    update(budget * share - (time.time() - t0))
                except Exception as e:  # noqa: BLE001
                    log.warning("%s failed, continuing with existing state: %r", name, e)
        d = refit_and_forecast()
        (STATE / "last_good.json").write_text(json.dumps(d, indent=1, default=str))
        build(d, ROOT / "site" / "build" / "latest")
        log.info("daily run complete in %.0fs", time.time() - t0)
        return 0
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        return rebuild_stale(repr(e))


if __name__ == "__main__":
    sys.exit(main())
