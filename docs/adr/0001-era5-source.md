# ADR 0001: ERA5 comes from CDS operationally, with the WeatherBench2 1.5° store for free history

Status: accepted, 2026-10-14.

Context: the brief named ARCO-ERA5 as the primary source. Every ARCO/WeatherBench2 Zarr is
chunked one global field per time step (4 MB per hour for surface fields, 150 MB for the
37-level fields), so a 1979-to-present pull would be terabytes; snowfall and 10 hPa wind exist
only in the hourly 0.25° store.

Decision: the Copernicus CDS (keyed, area-subset daily-statistics requests) is the operational
ERA5 path and the only source of snowfall and 10 hPa wind; the WeatherBench2 1.5° 6-hourly store
(same lattice as the reference repo, 8-step chunks) supplies bulk history to 2023-01-10 without a
key.

Consequences: `scripts/pull_era5_15.py` and `scripts/pull_cds.py`; a CDS key is required before
any real backtest; see `docs/DATA_NOTES.md`.
