# PBC-Hokkaido

Week-3 and week-4 probabilistic outlooks of Hokkaido winter snowfall (Sea of Japan side:
Niseko, Kutchan, Otaru, Sapporo) from circulation indices calibrated with Probabilistic Bias
Correction (PBC; Guan, Mouatadid et al. 2026, arXiv:2604.16238),
published daily to GitHub Pages.

**Thesis.** The ingredients of Hokkaido snow are known and the models already simulate them;
we claim no new physics. The project tests whether probabilistic bias correction finds
correctable model error at weeks 3–4 and turns it into useful skill for Hokkaido snow. The
headline metric is therefore the **lift** of the calibrated product over the operationally
debiased and raw models, with block-bootstrap confidence intervals; the model's own skill, the
PBC lift and the Stage-3 lift are always reported apart. The last three winters are sealed as
a final exam and evaluated once. Every experiment is logged in `experiments/log.csv`.

Status: Phase 0–2 complete, dashboard built on fixtures (core + parity + leakage tests, data fetchers, ERA5-era index
analysis). Backtest, daily run and site follow. See `docs/`:

- `docs/DATA_NOTES.md` sources, licences, latencies, every (verify) item
- `docs/METHOD.md` index definitions with citations and the index-vs-snow analysis
- `docs/BACKTEST.md` (Phase 3) honest skill against all baselines
- `docs/DESIGN.md` design tokens, Normie/Nerd modes, copy and citation rules, screenshots
- `docs/REFERENCES_CHECK.md` every reference verified before it may appear on the site
- `experiments/log.csv` every configuration evaluated

## Quick start

```bash
uv venv .venv --python 3.13 && uv pip install --python .venv/bin/python -e ".[dev,fetch]"
.venv/bin/python -m pytest                      # unit, leakage and parity tests (synthetic fixtures)
scripts/bootstrap.sh                            # free history (WeatherBench2 ERA5 1.5°, AO, MJO)
scripts/bootstrap.sh --with-cds --with-s2s      # needs CDSAPI_KEY and ECDS_KEY (S2S licence accepted)
```

Credentials are read from environment variables only (`ECDS_URL`/`ECDS_KEY`,
`CDSAPI_URL`/`CDSAPI_KEY`) and are never committed.

## Licensing

- Code: MIT.
- Forecast products on the site: **CC BY-NC 4.0** (non-commercial), because the JMA input is
  CC BY-NC 4.0 via the S2S database.
- Attributions: "Contains modified ECMWF data (CC BY 4.0)"; "JMA data via the S2S database,
  CC BY-NC 4.0"; "ERA5: Copernicus Climate Change Service"; AMeDAS 出典：気象庁ホームページ;
  AO: NOAA CPC; MJO RMM: Australian Bureau of Meteorology; PBC paper and reference code
  (MIT) by Guan, Mouatadid et al.

This is a personal, non-commercial research project. It is **not** an avalanche or mountain
weather forecast.

## Validation

`docs/VALIDATION.md` maps every claim to the test that proves it (parity, invariants, leakage,
statistical checks on data with known answers, runtime validators, end-to-end, site checks).
`make validate` prints the matrix with live status; CI runs it on every push.
