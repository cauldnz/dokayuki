# Data notes

Every source, licence and latency used by PBC-Hokkaido, plus the status of each
**(verify)** item from the build brief. Keep this file current: if a fact here
is wrong, the pipeline is wrong.

## Phase 0 — environment probe (2026-10-14, cloud build container)

Reachability from the build container, via its HTTPS egress proxy
(`curl -sS -o /dev/null -w "%{http_code}"`):

| Host | Result | Note |
|---|---|---|
| `ecds.ecmwf.int` | 200 (`/api/catalogue/v1/collections/s2s-forecasts` → 200) | ECDS reachable; needs `ECDS_URL`/`ECDS_KEY` for retrievals (not present in the container) |
| `storage.googleapis.com/gcp-public-data-arco-era5/ar/…/.zmetadata` | 200 | ARCO-ERA5 anonymous read works (directory listing itself is 404, expected) |
| `cds.climate.copernicus.eu` | 200 | fallback only; needs `CDSAPI_KEY` |
| `iridl.ldeo.columbia.edu` | 200 (`/SOURCES/.BoM/.MJO/.RMM/` → 302 redirect) | IRI Data Library reachable; the ECMWF S2S collection needs a free login |
| `cpc.ncep.noaa.gov` (AO page and `ftp.cpc.ncep.noaa.gov/cwlinks/…ao…csv`) | 200 | AO daily index reachable |
| `www.bom.gov.au/climate/mjo/graphics/rmm.74toRealtime.txt` | 403 with curl's default UA, **200 with a browser User-Agent** | BoM blocks non-browser UAs; fetcher sets a UA. IRI mirror is the fallback |
| `www.data.jma.go.jp/risk/obsdl/` | 200 | AMeDAS download portal reachable (manual/semi-manual pull only) |
| `github.com` (HTML, API) | 403 | web/API blocked, but `git clone https://github.com/mouatadid/pbc.git` and `raw.githubusercontent.com` work |
| `hokkaidowilds.org` | 200 | design study possible |
| `fonts.googleapis.com` | 404 on `/` | host reachable (a 404 on the bare root is normal) |
| `pypi.org` | 200 | package installs work |

Conclusion: no data host is blocked outright, but **no credentials** are present
in the container, so ECDS/CDS retrievals and the IRI ECMWF collection cannot be
exercised here. Phase 1 therefore builds and tests on synthetic fixtures with
realistic shapes and an injected, known bias and signal; real data runs through
`scripts/bootstrap.sh` on a machine with credentials (or in Actions with
secrets).

Container: 4 vCPU, 15 GB RAM, Python 3.13.16, `uv` 0.11.

## Time conventions (locked)

- All dates are UTC. `init` is the model initialisation date (00 UTC).
- Lead `L` (19 or 26) denotes the week **starting on `init + (L − 1)` days**,
  i.e. days 19–25 or 26–32 counting `init` as day 1. This matches the
  reference repo (`issuance_to_target = issuance + lead − 1 day`) and the AI
  Weather Quest definition.
- Weekly truth and forecasts are labelled by the week's **start date**.
- `forecast_delta(L) = L − 1` days between init and target start.
- `gt_delta(L) = forecast_delta(L) + measurement_lag`, where
  `measurement_lag = aggregation (7) + truth latency − issue delay`. The
  reference uses 7 + 2 = 9 for ERA5 (4-day latency offset by publishing 2
  days late). We publish ~2 days after init (the S2S 48 h embargo) and ERA5T
  lands ~5 days behind real time, so the operational default is
  `measurement_lag = 7 + 5 − 2 = 10`. The parity test uses 9 to match the
  reference exactly. Set in `config/region.yaml: time.measurement_lag_days`.

## Reference-repo facts recorded while reading `mouatadid/pbc` (2026-10-14)

- Grid `global1_5`: latitude −90…90 step 1.5, longitude 0…358.5 step 1.5
  (`src/data/helpers/data_utils.py::get_grid`). Our domain is the sub-lattice
  21.0…72.0°N, 75.0…225.0°E of that grid (all multiples of 1.5).
- ERA5 is pulled from CDS already on 1.5° (`grid: [1.5, 1.5]`), i.e. CDS
  bilinear interpolation; a `coarsen_data(scale_factor=6)` helper exists for
  0.25° sources. We coarsen ARCO 0.25° by a factor-6 block mean.
- Observed thresholds (`era5-percentiles.py`): for each target date, the
  quantile of weekly values from the previous 20 years (−20…−1) at day offsets
  {−4, −2, 0, +2, +4}. Feb 29 → Feb 28 via `relativedelta`.
- Model thresholds (`ecmwf-quintiles.py`, "SUBS-M-climate recipe"): quantiles
  of pooled reforecasts over 9 base dates (the latest reforecast date ≤ the
  issuance date, plus 4 before and 4 after) × 20 hindcast years × 11 members.
- `F(k)` (`ecmwf.py`, `ecmwf-F.py`): fraction of members with weekly value
  `< q(k)`; perturbed + control, 11 members for reforecasts, 51/101 for
  real-time forecasts.
- Debias++ (`ecmwfpp/batch_predict.py`): training set = times `≤ t* − gt_delta`
  with `remainder = floor(delta mod 365.242199) ≤ margin or ≥ 365 − margin` and
  `dividend = floor(delta / 365.242199) < years`; prediction =
  `clip(F[t*] + mean(O − F), 0, 1)`. Reforecast-based CDFs are placed at their
  hindcast target dates, duplicates resolved in favour of real forecasts.
- Tuner (`tuner/batch_predict.py`): for each target date and quintile k, picks
  the submodel with the lowest mean latitude-weighted Brier score over the
  previous 3 years (same `dividend < 3`, `time ≤ t* − gt_delta` rule). The
  selection is **global** (one config for the whole map per date and k).
- Persistence++ (`perpp_ecmwf/batch_predict.py`): per grid cell, features
  `[O.shift(gt_delta), O.shift(gt_delta + horizon − 1), F, C, 1]`, where `C` is
  the 20-year rolling climatology of `O` (padded with k/K, Feb 29 dropped,
  shifted +1 year, then a centred 9-day mean). Rolling least squares via
  XᵀX / Xᵀy sufficient statistics, `np.linalg.solve` with `lstsq` fallback,
  clipped to [0, 1]. `train_years = all`, `margin = None`.
- Projector: `sklearn.isotonic.isotonic_regression(y_min=0, y_max=1)` across
  k, applied only where the CDF is not already non-decreasing.
- PBC (`pbc_ecmwf`, `equal=True`): mean of projected tuned Debias++ and
  projected Persistence++, then projected again.
- Duet (`duet/batch_predict.py`): equal mean of PBC-ECMWF and PBC-MSN. Our
  Duet adds the {equal, A, B} selection on a held-out validation year.
- Climatology baseline (`climatology/batch_predict.py`): the constant k/K.
- RPSS (`rpss.py`): RPS per date = Σ_k latitude-weighted MSE of the k-th
  cumulative probability; RPSS = 1 − mean(RPS_model)/mean(RPS_clim).
- `std_test` = Mondays and Fridays 2016–2024; `std_tune` daily 2013–2026.

## Sources, licences, latencies

(To be completed through Phase 2; each row must have a URL, licence and lag.)

| Source | Use | URL | Licence | Lag |
|---|---|---|---|---|
| ECMWF extended-range, S2S database on ECDS (`ecmf`) | model fields + on-the-fly reforecasts | https://ecds.ecmwf.int/datasets/s2s-forecasts | CC BY 4.0 (attribution: "Contains modified ECMWF data") | 48 h embargo |
| JMA (`rjtd`) via S2S database on ECDS | model fields + fixed 1991–2020 hindcasts | same | CC BY-NC 4.0 | 48 h |
| WeatherBench2 / ARCO ERA5 1.5° 6-hourly (Google Cloud) | bulk truth history to 2023-01-10 | `https://storage.googleapis.com/weatherbench2/datasets/era5/1959-2023_01_10-6h-240x121_equiangular_with_poles_conservative.zarr` | Copernicus C3S licence (free, attribution) | static (ends 2023-01-10) |
| CDS ERA5 (daily statistics, pressure levels) | truth after 2023-01-10, snowfall at 0.25°, 10 hPa wind | https://cds.climate.copernicus.eu | C3S licence | ERA5T ~5 days |
| CDS ERA5 | fallback truth | https://cds.climate.copernicus.eu | C3S licence | ~5 days |
| NOAA CPC AO daily index | observed predictor | https://ftp.cpc.ncep.noaa.gov/cwlinks/norm.daily.ao.cdas.z1000.19500101_current.csv | US public domain | ~1 day |
| BoM RMM MJO index | observed predictor | https://www.bom.gov.au/clim_data/IDCKGEM000/rmm.74toRealtime.txt (needs browser UA; to 2026-10-12 when probed); IRI mirror `SOURCES/.BoM/.MJO/.RMM/` | BoM: CC BY 4.0 (copyright page, verified 2026-10-15) | ~1–2 days |
| JMA AMeDAS | station snow validation | https://www.data.jma.go.jp/risk/obsdl/ | JMA Public Data License; credit 出典：気象庁ホームページ | manual pull |

## ERA5 source decision (deviation from the brief)

The brief named ARCO-ERA5 as the primary ERA5 source. Probing the stores (2026-10-14) showed
that every ARCO/WeatherBench2 Zarr is chunked as **one global field per time step** (or 8 steps
for the 1.5° stores). Consequences:

| Store | Grid | Chunk | Bytes per chunk (measured) | Verdict |
|---|---|---|---|---|
| `ar/full_37-1h-0p25deg-chunk-1.zarr-v3` (ARCO, hourly, to present) | 0.25° | (1 h, globe) | ~4 MB surface, ~150 MB for 37-level fields | far too heavy for bulk; only source of hourly snowfall and 10 hPa wind without a key |
| `ar/1959-2022-6h-1440x721.zarr` | 0.25° 6-h | (1 step, globe) | 4 MB / 53 MB (13 levels) | no snowfall; too heavy for history |
| WB2 `1959-2023_01_10-6h-240x121_…conservative.zarr` | **1.5°** (exactly the reference lattice) | (8 steps, globe) | msl 0.55, t2m 0.62, tp 0.83, sst 0.14, **t850/z500 7.8 MB** (all 13 levels) | **used for bulk history to 2023-01-10**: 2-D fields Oct–Apr 1979–2023 ≈ 9.6 GB; t850 DJF ≈ 15 GB; t850+z500 NDJFM ≈ 50 GB (needs go-ahead) |

Measured throughput from the build container: ≈ 50–170 MB/s.

So: **CDS is the primary operational ERA5 path** (keyed, area-subset requests are tiny: the
daily-statistics datasets give daily snowfall over the SNOW-W box at 0.25°, and daily 1.5°
fields plus 10 hPa wind by area), and the WB2 1.5° store is the free bulk-history path for the
ERA5-era analysis and backtest truth up to 2023-01-10. Everything after 2023-01-10 (and all
snowfall / 10 hPa wind) requires `CDSAPI_KEY`.

## ECDS S2S request schema (probed 2026-10-14)

Forms at `…/collections/s2s-forecasts/form.json` and `s2s-reforecasts/form.json`:
`origin` ∈ {bom, cma, cnr_isac, cptec, cnrm, eccc, **ecmwf**, hmcr, iap_cas, **jma**, kma, ncep,
ukmo}; `year`/`month`/`day`/`time` (00:00, 12:00); `level_type` ∈ {pressure, single_level,
isentropic, oceanic}; `variable`; `level_value`; `forecast_type` ∈ {control_forecast,
perturbed_forecast}; `leadtime_hour` (instants "456" and 24-h windows "432_456"); `area`
[N, W, S, E]; `data_format` = grib. Reforecasts add `hyear`, `hmonth`, `hday`. Retrieve endpoint
`/api/retrieve/v1/processes/s2s-forecasts`; client `ecmwf-datastores-client` (submit → request
id → poll → download), which is what `src/dokayuki/fetch/s2s.py` wraps.

Real-time coverage on ECDS (init dates per year): ECMWF 104–105/yr 2015–2022 (Mon/Thu), 238 in
2023 (daily from late June), daily since 2024. JMA 104/yr 2015–16 (Tue+Wed), 52–63/yr 2017–2022
(weekly), 323 in 2023, daily since 2024, with 00 and 12 UTC runs.

Reforecasts on ECDS: ECMWF on-the-fly, 20 hindcast years ending the year before the issue
year; 104/yr to 2023, 116 in 2024 and **186 in 2025, 155 so far in 2026 (odd days of the
month)**. JMA fixed sets keyed by system date: 2014-03-04 (hyears 1981–2010), 2017-01-31
(1981–2012), 2020-03-31 (1981–2010), 2021-03-31 (1981–2020), 2022-03-31 and 2022-09-30
(1991–2020). **No CPS4 (2026) reforecast set was listed.**

## (verify) items

| Item | Status | Finding |
|---|---|---|
| Index boxes vs literature | **resolved** | SHI = Panagiotopoulos et al. 2005 box (not Gong); ALI = Trenberth & Hurrell NPI region; MOI = Hanawa et al. 1988 (JMA operational); EAT = Sun & Li 1997; SJI 13 °C rule = West et al. 2019; SJC has no precedent. Details and DOIs in docs/METHOD.md |
| Niseko AMeDAS station | **resolved** | ニセコ 16272 is precipitation-only (since 2010): no snowfall, no snow depth. Use Kutchan 16917 (closest) and Rankoshi 16915 |
| S2S fields per origin: t850, z500, snowfall | **resolved** | ECMWF: temperature 850 hPa, geopotential_height 500 hPa, snow_fall_water_equivalent, u 10 hPa all present. JMA: temperature and geopotential_height on the same 10 pressure levels, **no snowfall** (cold-day precipitation used for its snow baseline). Both carry mean_sea_level_pressure, 2 m temperature, total precipitation, SST |
| ECMWF reforecast cadence since CY49R1 | **resolved** | 186 reforecast init dates in 2025 = odd days of each month (also confirmed in the constraints: 01, 03, 05, …) |
| JMA CPS4 25-member Tue/Wed runs in S2S? | **resolved** | First GRIB pulled 2026-10-15 (perturbed_forecast, 2026-01-07 00 UTC, a Wednesday): **4 perturbed members** (+ control = 5), centre `rjtd`. The S2S archive carries the daily 5-member slice, not a 25-member CPS4 run, so JMA is used as a lagged ensemble across issue days as in the reference code. No CPS4 reforecast set is listed |
| Hokkaido/Japan avalanche bulletin publishers | **resolved** | 日本雪崩ネットワーク JAN (https://nadare.jp, bulletins https://data.nadare.jp/avalanche_informations: Niseko/Yotei/Yoichi and Daisetsu/Tokachi regions); ニセコ雪崩情報 Niseko Avalanche Information (http://niseko.nadare.info/, basis of the Niseko Rules); JMA なだれ注意報 advisories; aggregator https://hokkaidowilds.org/avalanche-bulletins-for-central-hokkaido |
| ARCO-ERA5 anonymous read | **resolved** | works, but see the chunking verdict above |
| BoM MJO reachability | **resolved** | current file: https://www.bom.gov.au/clim_data/IDCKGEM000/rmm.74toRealtime.txt (browser UA); the old /climate/mjo/graphics/ file stopped on 2024-02-24 |
| Measurement lag for ERA5T | **resolved** | CDS catalogue constraints for `reanalysis-era5-single-levels` listed data through 2026-10-09 when probed at 01:50 UTC on 2026-10-15 (6 days behind). Operational `measurement_lag_days: 10` keeps 4 days of margin |
| JMA 10 hPa wind in S2S | **resolved** | Both origins list `10_hpa` with u, v, T, Z, w for all years, so `U10_60N` can be computed per member for JMA as well as ECMWF |
| BoM RMM licence | **resolved** | bom.gov.au/other/copyright.shtml: "Licensed from the Commonwealth of Australia under a Creative Commons Attribution 4.0 International Licence" unless marked otherwise; the RMM text file carries no contrary notice. Attribution line on the site: "MJO RMM index: Australian Bureau of Meteorology (CC BY 4.0)" |
| ECDS request shape | **resolved** | One request per (origin, collection, month, forecast type, level type and level): ECDS takes a list of init days (and matching `hday`s), so the GRIB carries a `time` axis. Instantaneous fields at plain hours; `total_precipitation` and `snow_fall_water_equivalent` are totals from the start at plain hours (differenced to daily); `2_m_temperature` and `sea_surface_temperature` are 24-h means on `a_b` ranges. Asking for several pressure levels in one request returns every variable at every level, so levels are requested separately. Measured 2026-10-15: ECMWF control, January 2023 (9 inits), all parts: 10 MB, about 1.1 MB per member-init; decode 10 s |
| ECDS key and S2S licence | **resolved** | Key accepted 2026-10-15; a JMA msl request (one lead, domain box) ran accepted → running → successful in under a minute. The ECDS cost-estimate endpoint returned HTTP 500 repeatedly, so request counts are planned without it |
