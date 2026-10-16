# Plan: where to get S2S data from, and a downloader worth publishing

Probed 2026-10-17 from the cloud session. Numbers below are measured unless marked.

## Finding that changes the project

WeatherBench2 (Google, public GCS bucket `weatherbench2`, anonymous reads) carries the ECMWF
extended-range ensemble, the same IFS runs the S2S database serves, as consolidated Zarr:

| Store (`datasets/ifs_extended_range/`) | Dims | Content |
|---|---|---|
| `raw/ifs-ext-pressure-levels-inst-24h.zarr` | time 730 × number 50 × step 0..46 d × level 10 × 121 × 240 | z, q, t, u, v at 10, 50, 100, 200, 300, 500, 700, 850, 925, 1000 hPa, 00 UTC each day |
| `raw/ifs-ext-reforecast-pressure-levels-inst-24h.zarr` | forecast_time 730 × number 10 × hindcast_year −20..−1 × step 0..46 × level 10 × grid | same, reforecasts |
| `daily/ifs-ext-full-single-level-avg.zarr` | time 730 × number 50 × step 0..45 × grid | daily means: 2t, 2d, sst, skt, snow depth, tcc, tcw, tp 24 h, 2t max/min, … |
| `daily/ifs-ext-reforecast-full-single-level-avg.zarr` | + hindcast_year 20, number 10 | same, reforecasts |
| `weekly/…` | week-averaged versions of both | |

- Inits: every Monday and Thursday, 2016-01-04 to 2022-12-29 (730). That covers the Duet
  validation winter and all seven open test winters. Grid 1.5°, the lattice we already use.
- Members: perturbed only (50 forecast, 10 reforecast); no control member.
- Missing for us: mean sea level pressure (use z1000: Δp ≈ Δz/8 m per hPa, or the hypsometric
  conversion; the CPC AO is defined on Z1000 anyway) and snowfall (same as JMA; cold-day
  precipitation proxy). Everything else the index chain needs is there: t850, z500, u850, v850,
  u at 10 hPa, sst, 2t, tp.
- Read speed from the cloud container: one init, one variable, domain box, 16 steps: forecasts
  11 MB in 7 s, reforecasts 45 MB in 5 s. Chunks are global per (init, member block, level, step
  block), so a hemispheric read costs the same as a box read. Nine variables × 730 inits ≈ 2 min
  per init serial, about 24 h single-threaded for all of 2016–2022, a few hours with 8 threads,
  and nothing kept on disk beyond the decoded members.

Against ECDS for the same span: 1152 requests, one at a time on their side, two to three days,
130 GB of GRIB. ECDS stays the source for 2023 onward and for daily operations; WB2 is the
source for the backtest.

## Other sources probed

- IRI Data Library: holds ECMWF (and other centres') S2S forecasts and reforecasts with OPeNDAP
  and box or point subsetting; everything sits behind a free login plus the S2S licence
  (`dlauth`), so unprobed beyond the tree. Candidate for JMA and for point pulls.
- Polytope (ECMWF feature extraction): needs ECMWF-account credentials, not the ECDS key; the
  ECDS key is refused. Coverage of the S2S archive unverified. Low priority.
- ECMWF open data on AWS (`ecmwf-forecasts`): real-time only (rolling window), 0.25°/0.4°,
  ENS streams. Useful for a live page later, not for history.
- CMA S2S mirror (s2s.cma.cn): DNS failed from here twice. Unverified.
- ERA5: WB2 `era5_weekly` and `era5_daily` exist alongside the 1.5° store we already use.

## Plan A (do first): backtest off WeatherBench2, this week

1. `dokayuki.fetch.wb2_ext`: open the four stores lazily; for each init in the window, read the
   nine fields over the domain plus the AO hemispheric z1000, reduce to weekly values per lead
   and to the per-member indices, write `state/members/ecmwf/{lead}/{forecast,reforecast}_idx.nc`
   in the layout the pull already produces (issue, member, target / issue, hyear, member, target)
   with `source="wb2"` recorded. Reuse `decode()`'s index code; only the reader differs.
2. msl from z1000 with the conversion written down in METHOD; a parity check against the ECDS
   months already decoded on the laptop (Oct 2016 onward): same inits, same members, the
   indices should agree to rounding. That is the test that lets us trust the switch.
3. Run with a thread pool over inits, Oct–Apr 2016/17 to 2022/23, from the laptop or a cloud
   session (no disk, no credentials, no queue). Then the real backtest.
4. Stop the ECDS history pull once the parity check passes; keep ECDS for 2023+ and daily runs.

## Plan B: the downloader library (`ecmwf-haul`, own repo)

Scope, in priority order:
1. Source registry and router: a dataset spec (origin, stream, variables, levels, area, dates,
   members) is matched against sources with declared capabilities (random access or job queue,
   date coverage, grid, member sets, licence, credentials needed, cost model). The router
   picks the cheapest source that satisfies the spec and explains the choice. First entries:
   WB2 GCS Zarr, ECDS, CDS, IRI DL, AWS open data, ARCO/WB2 ERA5.
2. ECDS/CDS job-queue backend: planner that probes the cost limit once and splits on 403
   (years, days, variables), submit-ahead pipeline that keeps the server's serial worker fed
   while downloads run, SQLite ledger (spec hash, request id, state, bytes, checksum),
   resumable range downloads, GRIB message-count check, idempotent reruns.
3. Zarr backend: region/period/member selection with chunk-aware batching and bounded threads.
4. CLI: `haul plan` (sources considered, cost and time per source), `haul run`, `haul status`.
5. Output adapters: GRIB as delivered, or long-format Parquet partitioned by month for DuckDB
   over httpfs (origin, init, hindcast_year, member, lead, lat, lon, value), plus a tiny
   per-member index table for products like dokayuki.

Not in scope for v1: Polytope, CMA mirror, any JMA-specific handling beyond the ECDS backend.

## Decisions (Chris, 2026-10-17)

- Backtest on WeatherBench2's 50-member forecasts and 10-member reforecasts, no control member.
  Record `members: perturbed only (WB2)` in METHOD and BACKTEST; the reference PBC code is
  indifferent to the member count.
- Library: `ecmwf-haul`, MIT, under cauldnz, after Plan A.
