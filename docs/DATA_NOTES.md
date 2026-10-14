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
| ARCO-ERA5 (Google Cloud) | truth, SST, 10 hPa wind | `gs://gcp-public-data-arco-era5/ar/` | Copernicus C3S licence (free, attribution) | ERA5T ~5 days |
| CDS ERA5 | fallback truth | https://cds.climate.copernicus.eu | C3S licence | ~5 days |
| NOAA CPC AO daily index | observed predictor | https://ftp.cpc.ncep.noaa.gov/cwlinks/norm.daily.ao.cdas.z1000.19500101_current.csv | US public domain | ~1 day |
| BoM RMM MJO index | observed predictor | http://www.bom.gov.au/climate/mjo/graphics/rmm.74toRealtime.txt (needs browser UA); IRI mirror `SOURCES/.BoM/.MJO/.RMM/` | BoM: CC BY 4.0 (verify on page) | ~1–2 days |
| JMA AMeDAS | station snow validation | https://www.data.jma.go.jp/risk/obsdl/ | JMA Public Data License; credit 出典：気象庁ホームページ | manual pull |

## (verify) items

| Item | Status | Finding |
|---|---|---|
| Index boxes vs literature | open | Phase 2 |
| Niseko AMeDAS station | open | Phase 2 |
| S2S fields per origin (`ecmf`, `rjtd`): t850, z500, snowfall | open | Phase 2 |
| ECMWF reforecast cadence since CY49R1 (odd days?) | open | Phase 2 |
| JMA CPS4 25-member Tue/Wed runs in S2S? | open | Phase 2 |
| Hokkaido/Japan avalanche bulletin publishers | open | Phase 4 |
| ARCO-ERA5 anonymous read | **resolved** | 200 on `.zmetadata` from the container, no key |
| BoM MJO reachability | **resolved** | 403 for curl UA, 200 with browser UA |
