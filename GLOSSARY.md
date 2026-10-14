# Glossary

Terms as this repo uses them. Keep entries short; add one when a term gets resolved.

- **Lead (L)**: 19 or 26. The target week starts at `init + (L − 1)` days, i.e. days 19–25 (week 3) or 26–32 (week 4) with init as day 1.
- **Issue date**: when we publish, two days after init (the S2S 48 h embargo).
- **gt_delta**: days from the target week's start back to the start of the last truth week that is fully observed at issue time: `(L − 1) + measurement_lag`, with measurement lag 10 operationally (9 in the reference parity test).
- **Target**: a thing we forecast the weekly value of: a 1.5° grid cell or a scalar index. Both live on the `target` dimension and are treated identically.
- **Weekly value**: the 7-day mean (or sum, for precipitation and snowfall) labelled by the week's start date.
- **Threshold q(k)**: the k/K quantile of truth weekly values from the previous 20 years at day offsets {−4, −2, 0, +2, +4}; K = 5 quintiles, K = 20 extremes. Model thresholds use the model's own hindcasts instead.
- **F(k)**: the ensemble's cumulative probability that the weekly value is below q(k).
- **Debias++**: F plus the mean of (indicator − F) over a day-of-year window in the past 20 years; the window (s) is tuned over 3 years of past scores.
- **Persistence++**: per (target, k, lead) rolling least squares of the indicator on two observed lags, F and the rolling climatology.
- **Projection**: isotonic regression across k so a CDF is non-decreasing in [0, 1].
- **PBC**: the mean of projected Debias++ and projected Persistence++, projected again.
- **Duet**: the ECMWF/JMA combination chosen per target among equal, ECMWF-only, JMA-only on a validation winter that precedes the test period.
- **Lift**: skill of the PBC product minus skill of the operationally debiased (or raw) model, both relative to climatology, with a winter-block bootstrap interval. The headline metric.
- **SNOW-W**: weekly ERA5 snowfall (water equivalent) summed over the week and averaged over western-Hokkaido land (42.5–44.5°N, 140.0–141.8°E) at native 0.25°.
- **Big snow week**: SNOW-W in the top quintile.
- **Ingredient chain**: Trigger → Outbreak → Steering → Fuel → Delivery; the Stage-3 feature groups and the dashboard cards.
- **Final-exam block**: winters 2023/24, 2024/25, 2025/26, sealed until v1 is frozen, evaluated once.
- **Normie / Nerd mode**: the two depths of the same dashboard page; Normie is the default.
- **Stale**: the daily run could not produce a valid new forecast; the last good one is shown with a banner.
