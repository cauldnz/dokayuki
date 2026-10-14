# ADR 0002: every fit is strictly causal in issuance, beyond the reference implementation

Status: accepted, 2026-10-14. One open parameter.

Context: the reference repo places on-the-fly reforecasts at their hindcast target dates and lets
all of them train every target, including reforecasts issued (in later years) after a target's
init date. The leakage test caught this. The reference's model-threshold recipe also uses four
reforecast base dates after the issuance date.

Decision: training rows must satisfy both `time ≤ t* − gt_delta` and `issue ≤ init(t*)`
(`causal_issuance=True` everywhere; `False` only in the parity test). A target whose only model
run post-dates its init gets no forecast. The number of base dates after the issue date used
for model thresholds (`n_after`) stays a parameter: strict (0) is the headline, the reference
recipe (4) is reported beside it until Chris decides.

Consequences: `test_no_future_leakage`, `test_non_causal_target_is_nan`,
`test_model_thresholds_strict_mode_uses_only_past_base_dates`; `docs/METHOD.md` §1.
