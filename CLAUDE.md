# dokayuki (ドカ雪)

Week 3–4 probabilistic outlooks of Sea-of-Japan-side Hokkaido snow, from circulation indices
calibrated with Probabilistic Bias Correction, published daily to GitHub Pages as a
HokkaidoWilds.org-family page. Personal, non-commercial research project by Chris Auld.

## Read first

- `docs/METHOD.md` — thesis (we claim no new physics; the headline metric is the lift over the
  debiased and raw models), overfitting guardrails, the five-stage ingredient chain, index
  definitions with citations.
- `docs/VALIDATION.md` — every claim mapped to the test that proves it. `make validate`.
- `docs/DATA_NOTES.md` — sources, licences, latencies, every (verify) item and its status.
- `docs/DESIGN.md` — the dashboard's tokens (from hokkaidowilds.org), Normie/Nerd modes, copy
  and citation rules.
- `experiments/log.csv` — every configuration ever evaluated. Winters 2023/24–2025/26 are sealed.

## Rules that are not negotiable

- Causality: no fit may see truth after the issue date or model runs issued after init. The
  leakage tests enforce it; keep them green.
- Honest uncertainty: every skill number carries a block-bootstrap interval; a non-significant
  lift is "no demonstrated improvement".
- Physics before fitting: no predictor without a cited rationale; no citation without a row in
  `docs/REFERENCES_CHECK.md`.
- Never commit credentials or raw GRIB. The one key comes from the `ECMWF_API_KEY` env var only.
- Never publish from an invalid forecast: `dokayuki.validate.check_forecast_json` gates the build.
- Stop and ask before: credentialed or paid actions, the first Pages publish, pulls over ~20 GB.

## Working here

```bash
make setup && make test     # ~2 min, 51 tests incl. parity, leakage, statistical, e2e
make qa                     # screenshots of three fixture states, both modes, light/dark
make validate               # claim -> evidence matrix with live status
make site                   # build the fixture site to site/build/latest
```

Python 3.13, `uv`, xarray/zarr/numpy/pandas/scikit-learn/jinja2. Package `src/dokayuki`.
All dates UTC; a lead L week starts at init + (L − 1) days. Probabilities on the site are
rounded to 5 %. Commit messages: small, logical, no model identifiers.

## Agent skills

### Issue tracker

Issues live in this repo's GitHub Issues (`gh` CLI). See `docs/agents/issue-tracker.md`.

### Triage labels

The five default labels (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`,
`wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` at the root and `docs/adr/`. See `docs/agents/domain.md`.
