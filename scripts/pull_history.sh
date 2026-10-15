#!/usr/bin/env bash
# Approved history pulls (free WB2 store): Oct-Apr 1979-2023 t850 and z500 on the domain, and msl+z500 hemispheric.
set -euo pipefail; cd "$(dirname "$0")/.."
PY=.venv/bin/python
$PY scripts/pull_era5_15.py --fields t850 --start 1979-10-15 --end 2023-01-10 --months 10,11,12,1,2,3,4 --out state/era5_15_daily_t850.zarr --max-gb 100
$PY scripts/pull_era5_15.py --fields z500 --start 1979-10-15 --end 2023-01-10 --months 10,11,12,1,2,3,4 --out state/era5_15_daily_z500.zarr --max-gb 100
$PY scripts/pull_era5_15.py --fields u850,v850 --start 1979-10-15 --end 2023-01-10 --months 10,11,12,1,2,3,4 --out state/era5_15_daily_uv850.zarr --max-gb 100
$PY scripts/pull_era5_15.py --hemispheric --fields msl,z500 --start 1979-10-15 --end 2023-01-10 --months 10,11,12,1,2,3,4 --out state/era5_15_hemi_daily.zarr --max-gb 100
echo "history pulls complete"
