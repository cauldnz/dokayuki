"""Pull daily 1.5-degree ERA5 domain fields from the WeatherBench2 store into state/.

Usage: python scripts/pull_era5_15.py --fields msl,t2m,tp,sst --start 1979-10-15 --end 2023-01-10 --months 10,11,12,1,2,3,4
"""
import argparse, logging, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from dokayuki.config import RegionConfig
from dokayuki.fetch.era5 import estimate_pull, pull_daily_domain, pull_land_sea_mask

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
p = argparse.ArgumentParser()
p.add_argument("--fields", default="msl,t2m,tp,sst")
p.add_argument("--start", default="1979-10-15")
p.add_argument("--end", default="2023-01-10")
p.add_argument("--months", default="10,11,12,1,2,3,4")
p.add_argument("--out", default="state/era5_15_daily.zarr")
p.add_argument("--max-gb", type=float, default=20.0)
p.add_argument("--dry-run", action="store_true")
a = p.parse_args()
cfg = RegionConfig.load()
fields = a.fields.split(",")
months = tuple(int(m) for m in a.months.split(",")) if a.months else None
est = estimate_pull(fields, a.start, a.end, months)
logging.info("estimate: %s", est)
if est["gb_total"] > a.max_gb:
    logging.error("estimated %.1f GB exceeds --max-gb %.1f; refusing (ask first)", est["gb_total"], a.max_gb)
    sys.exit(2)
if a.dry_run:
    sys.exit(0)
t0 = time.time()
pull_land_sea_mask(cfg.domain, Path("state/lsm_15.nc"))
pull_daily_domain(fields, cfg.domain, a.start, a.end, Path(a.out), months=months)
logging.info("done in %.0fs", time.time() - t0)
