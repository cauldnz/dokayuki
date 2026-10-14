"""ERA5 via CDS (keyed): daily snowfall over the SNOW-W box at 0.25 deg, 1.5-degree daily domain fields
after 2023-01-10, and 10 hPa zonal wind at 60N. Resumable: one NetCDF per (field, year) in state/cds/.

Usage: pull_cds.py [--start 1979] [--end 2026] [--recent] [--budget-s N] [--dry-run]
"""
import argparse
import logging
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pandas as pd
from dokayuki.config import RegionConfig, SnowConfig
from dokayuki.fetch.era5 import cds_client, cds_daily_request, cds_daily_snowfall_request

ROOT = Path(__file__).resolve().parents[1]; OUT = ROOT / "state" / "cds"
MONTHS = [f"{m:02d}" for m in (10, 11, 12, 1, 2, 3, 4)]
FIELDS_15 = {"msl": ("mean_sea_level_pressure", None), "t2m": ("2m_temperature", None), "tp": ("total_precipitation", None),
             "sst": ("sea_surface_temperature", None), "t850": ("temperature", 850), "z500": ("geopotential", 500),
             "u850": ("u_component_of_wind", 850), "v850": ("v_component_of_wind", 850)}
log = logging.getLogger("cds")


def jobs(cfg, snow, years, recent):
    out = []
    for y in years:
        out.append(("sf", y, "derived-era5-single-levels-daily-statistics", cds_daily_snowfall_request(y, snow.mask, MONTHS)))
        if y >= 2023:
            for f, (var, lvl) in FIELDS_15.items():
                ds = "derived-era5-pressure-levels-daily-statistics" if lvl else "derived-era5-single-levels-daily-statistics"
                stat = "daily_sum" if f == "tp" else "daily_mean"
                out.append((f, y, ds, cds_daily_request(var, y, cfg.domain, MONTHS, lvl, stat)))
            hemi = cds_daily_request("u_component_of_wind", y, cfg.domain, MONTHS, 10)
            hemi["area"] = [61.5, 0, 58.5, 360]
            out.append(("u10hpa", y, "derived-era5-pressure-levels-daily-statistics", hemi))
        # 10 hPa u at 60N for all years (small)
        if y < 2023:
            hemi = cds_daily_request("u_component_of_wind", y, cfg.domain, MONTHS, 10); hemi["area"] = [61.5, 0, 58.5, 360]
            out.append(("u10hpa", y, "derived-era5-pressure-levels-daily-statistics", hemi))
    return out


def main():
    p = argparse.ArgumentParser(); p.add_argument("--start", type=int, default=1979); p.add_argument("--end", type=int, default=pd.Timestamp.utcnow().year)
    p.add_argument("--recent", action="store_true", help="only the current and previous year"); p.add_argument("--budget-s", type=float, default=3600); p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(); logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    cfg, snow = RegionConfig.load(), SnowConfig.load()
    years = [a.end - 1, a.end] if a.recent else list(range(a.start, a.end + 1))
    todo = [j for j in jobs(cfg, snow, years, a.recent) if not (OUT / f"{j[0]}_{j[1]}.nc").exists() or a.recent and j[1] >= a.end]
    log.info("%d CDS requests to run (%d already stored)", len(todo), len(jobs(cfg, snow, years, a.recent)) - len(todo))
    if a.dry_run:
        for f, y, ds, req in todo[:5]: log.info("%s %s %s %s", f, y, ds, {k: v for k, v in req.items() if k != "day"})
        return 0
    client = cds_client(); OUT.mkdir(parents=True, exist_ok=True); t0 = time.time()
    for f, y, ds, req in todo:
        if time.time() - t0 > a.budget_s:
            log.warning("budget exhausted; resume next run"); return 0
        target = OUT / f"{f}_{y}.nc"
        log.info("retrieving %s %s", f, y)
        client.retrieve(ds, req, str(target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
