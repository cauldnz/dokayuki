# Validation: why the numbers can be trusted

"I built something" is not a result. This page maps every claim the project makes to the test
that proves it, and says what each kind of test can and cannot show. `make validate` prints the
same matrix with the live pass/fail status; CI runs it on every push.

## Layers

| Layer | What it proves | Where |
|---|---|---|
| **Parity** | Our Debias++, tuner, Persistence++ and projector agree with line-faithful ports of the reference repo to 1e-6 on an identical 1.5° slice | `tests/reference_port.py`, `tests/test_parity.py` |
| **Unit and invariant** | Each step does what its definition says: thresholds non-decreasing in k and built from prior years only; CDFs within [0, 1] and monotone; bins sum to one; hindcast placement and Feb 29; dedup policy; lagged-ensemble pooling; weekly windows; index geometry and signs | `tests/test_core.py`, `tests/test_invariants.py`, `tests/test_indices.py`, `tests/test_ingredients.py` |
| **Causality / leakage** | Corrupting everything after the issue date (truth after the last observable week, model runs after init) leaves the forecast bit-identical; a target whose only run post-dates init is NaN; the tuner ignores future scores; Duet validation must precede the test period; strict model thresholds use only past base dates. The test also shows it has teeth: corrupting the observed past does change the forecast | `test_no_future_leakage`, `test_non_causal_target_is_nan`, `test_tuner_choice_ignores_future_scores`, `test_duet_refuses_validation_overlapping_test`, `test_model_thresholds_strict_mode_uses_only_past_base_dates` |
| **Statistical** | On synthetic data with a known answer: a known bias is removed; the calibrated output is reliable where the raw ensemble is not; zero-skill input gives zero-skill output (no fabricated skill, lift interval covers zero); real skill sits far outside a season-permutation null (which is at or below climatology for a sharp forecast); lift intervals detect a known improvement; effective sample size shrinks with autocorrelation | `tests/test_statistical.py`, `tests/test_ingredients.py` |
| **Runtime validation** | Daily data in physical ranges, no constant or NaN-ridden fields, monotone time; every published CDF valid; the forecast JSON passes a schema and semantic rules (terciles sum to one, valid window = init + lead − 1 and after the issue date, no graded signal without a skilful model, P(big week) ≤ P(above), implausibly high skill flagged as a probable leak). The site is never built from an invalid forecast; the daily run keeps the last good outlook and raises the stale banner instead | `src/pbch/validate.py`, `tests/test_validate.py` |
| **Guardrails** | The sealed winters cannot be evaluated by accident; every trial is logged with a running count; a deflated best-of-N skill is available | `src/pbch/experiments.py`, `test_locked_winters_guard_and_stages` |
| **End to end** | Synthetic members → thresholds → PBC → forecast JSON → validation → built site | `tests/test_pipeline_e2e.py` |
| **Site** | No third-party runtime requests or cookies; alt text and ARIA on charts; weight budget; the Normie/Nerd toggle sets the mode, persists it and yields to the URL parameter; no horizontal overflow; three fixture states rendered at three widths in light and dark (`docs/screenshots/`) | `tests/test_pipeline_e2e.py`, `scripts/design_qa.py` |
| **References** | Only entries verified in `docs/REFERENCES_CHECK.md` render | `src/pbch/site/references.py`, `test_unverified_references_never_render` |

## What these tests do not show

- They do not show real-world skill. That is the backtest's job (Phase 3), under the guardrails
  in `docs/METHOD.md` §0, and it is reported with intervals and a permutation null.
- Parity is on sea-level pressure at lead 19 over a cropped box; it establishes the algorithms,
  not the data pipeline. Data-pipeline checks are the runtime validators and the ECDS/CDS pulls'
  own range checks.
- The synthetic fixture has a seasonal cycle, AR(1) persistence, a seasonal bias and a tunable
  skill; it does not have regime behaviour, so the statistical tests are necessary, not
  sufficient.

## Running

```bash
make test        # ~2 min
make qa          # screenshots
make validate    # the matrix with live status; non-zero exit if anything fails
```
