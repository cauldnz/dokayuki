#!/usr/bin/env bash
# One-off bootstrap of state/ (restartable). Estimates size and time before pulling.
#
# Usage: scripts/bootstrap.sh [--yes] [--with-3d] [--with-cds] [--with-s2s]
#   --yes       do not ask before pulls over the 20 GB threshold
#   --with-3d   pull t850/z500 for Oct-Apr (not only DJF) from the 1.5-degree store (~55 GB download)
#   --with-cds  pull snowfall (0.25 deg, SNOW-W box), 10 hPa wind and post-2023 fields via CDS (needs CDSAPI_KEY)
#   --with-s2s  pull ECMWF/JMA S2S members via ECDS (needs ECDS_KEY, licence accepted)
#
# Credentials (env vars, never committed): CDSAPI_URL/CDSAPI_KEY, ECDS_URL/ECDS_KEY.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-.venv/bin/python}
YES=0; WITH3D=0; WITHCDS=0; WITHS2S=0
for a in "$@"; do case "$a" in --yes) YES=1;; --with-3d) WITH3D=1;; --with-cds) WITHCDS=1;; --with-s2s) WITHS2S=1;; esac; done
mkdir -p state logs
echo "== 1/5 observed indices (AO, MJO)"
$PY scripts/fetch_obs_indices.py
echo "== 2/5 ERA5 1.5-degree bulk history (free, WeatherBench2 store, to 2023-01-10)"
$PY scripts/pull_era5_15.py --fields msl,t2m,tp,sst --start 1979-10-15 --end 2023-01-10 --months 10,11,12,1,2,3,4 --out state/era5_15_daily.zarr
if [ "$WITH3D" = 1 ]; then
  EXTRA=""; [ "$YES" = 1 ] && EXTRA="--max-gb 1000"
  $PY scripts/pull_era5_15.py --fields t850 --start 1979-10-15 --end 2023-01-10 --months 10,11,12,1,2,3,4 --out state/era5_15_daily_t850.zarr $EXTRA
  $PY scripts/pull_era5_15.py --fields z500 --start 1979-10-15 --end 2023-01-10 --months 10,11,12,1,2,3,4 --out state/era5_15_daily_z500.zarr $EXTRA
else
  $PY scripts/pull_era5_15.py --fields t850 --start 1979-12-01 --end 2023-01-10 --months 12,1,2 --out state/era5_15_daily_t850.zarr
  $PY scripts/pull_era5_15.py --fields z500 --start 1979-12-01 --end 2023-01-10 --months 12,1,2 --out state/era5_15_daily_z500.zarr
fi
if [ "$WITHCDS" = 1 ]; then
  echo "== 3/5 CDS: snowfall over the SNOW-W box (0.25 deg), 10 hPa wind, fields after 2023-01-10"
  : "${CDSAPI_KEY:?CDSAPI_KEY not set}"
  $PY scripts/pull_cds.py
else
  echo "== 3/5 CDS skipped (no --with-cds): SNOW-W and post-2023 truth not available"
fi
if [ "$WITHS2S" = 1 ]; then
  echo "== 4/5 ECDS S2S members (ECMWF + JMA); resumable, request ids in state/requests.json"
  : "${ECDS_KEY:?ECDS_KEY not set}"
  $PY scripts/pull_s2s.py --origins ecmwf,jma --start 2015-01-01
else
  echo "== 4/5 S2S skipped (no --with-s2s)"
fi
echo "== 5/5 weekly truth, indices and analysis"
$PY scripts/analyze_indices.py
echo "bootstrap complete; state/ size:"; du -sh state
