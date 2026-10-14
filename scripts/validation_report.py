"""Print the claim -> evidence matrix with the live status of each backing test (runs pytest on them)."""
import json, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
CLAIMS = [
    ("Debias++, the tuner, Persistence++ and the projector reproduce the reference implementation to 1e-6", ["tests/test_parity.py"]),
    ("A known model bias is removed and climatology scores exactly RPSS 0", ["tests/test_core.py::test_known_bias_is_removed", "tests/test_core.py::test_climatology_rpss_is_zero"]),
    ("Projection never worsens RPS and yields valid distributions", ["tests/test_core.py::test_projection_never_worsens_rps", "tests/test_invariants.py::test_pbc_outputs_are_valid_distributions"]),
    ("No future data reaches any fit (truth after issue, model runs after init); a target with no causal run is NaN", ["tests/test_core.py::test_no_future_leakage", "tests/test_core.py::test_non_causal_target_is_nan"]),
    ("Thresholds use only prior years; strict model thresholds use only past base dates", ["tests/test_invariants.py::test_thresholds_monotone_and_use_only_prior_years", "tests/test_invariants.py::test_model_thresholds_strict_mode_uses_only_past_base_dates"]),
    ("Tuning looks only at the past; Duet validation must precede the test period", ["tests/test_invariants.py::test_tuner_choice_ignores_future_scores", "tests/test_invariants.py::test_duet_refuses_validation_overlapping_test"]),
    ("Date bookkeeping: leads, hindcast placement (Feb 29), dedup policy, lagged ensembles, weekly windows", ["tests/test_core.py::test_lead_bookkeeping", "tests/test_invariants.py::test_reforecast_placement_dates_and_feb29", "tests/test_invariants.py::test_combine_prefers_forecast_and_keeps_requested_reforecast", "tests/test_invariants.py::test_lagged_ensemble_pools_older_runs_at_longer_leads", "tests/test_invariants.py::test_weekly_aggregation_has_no_partial_weeks"]),
    ("Calibrated output is reliable where the raw ensemble is not", ["tests/test_statistical.py::test_pbc_is_reliable_where_raw_is_not"]),
    ("No skill in, no skill out: PBC does not fabricate skill", ["tests/test_statistical.py::test_no_skill_input_yields_no_fabricated_skill"]),
    ("Real skill sits far outside the season-permutation null", ["tests/test_statistical.py::test_permutation_null_separates_real_skill_from_chance"]),
    ("Lift has a correct block-bootstrap interval and detects a known improvement; effective N shrinks with autocorrelation", ["tests/test_ingredients.py::test_lift_detects_known_improvement", "tests/test_ingredients.py::test_effective_n_shrinks_with_autocorrelation"]),
    ("Index geometry and signs match their definitions (boxes, point pairs, NW flow, 13 C days, vortex, blocking, AO projection)", ["tests/test_indices.py", "tests/test_ingredients.py::test_nw_flow_sign", "tests/test_ingredients.py::test_zonal_mean_at_60n", "tests/test_ingredients.py::test_sji_days_counts_threshold_days", "tests/test_ingredients.py::test_ural_blocking_anomaly_and_ao_projection"]),
    ("The sealed final-exam winters cannot be evaluated by accident", ["tests/test_ingredients.py::test_locked_winters_guard_and_stages"]),
    ("Runtime validators catch corrupt data, invalid CDFs, leaky or implausible forecasts", ["tests/test_validate.py"]),
    ("Numerical safety: singular designs fall back to least squares with finite odds", ["tests/test_invariants.py::test_persistpp_survives_singular_design"]),
    ("End to end: synthetic members become a schema-valid, causal forecast and a built site", ["tests/test_pipeline_e2e.py::test_forecast_json_round_trips_and_is_causal"]),
    ("Site: no third-party runtime requests or cookies; text alternatives; under the weight budget; toggle works and persists", ["tests/test_pipeline_e2e.py::test_site_has_no_third_party_runtime_requests", "tests/test_pipeline_e2e.py::test_site_accessibility_basics", "tests/test_pipeline_e2e.py::test_page_weight_budget", "tests/test_pipeline_e2e.py::test_mode_toggle_in_browser"]),
    ("Unverified references never render", ["tests/test_pipeline_e2e.py::test_unverified_references_never_render"]),
]
res = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:warnings", "-rA"], cwd=ROOT, capture_output=True, text=True)
passed = set(); failed = set()
for line in res.stdout.splitlines():
    if line.startswith("PASSED "):
        passed.add(line.split()[1])
    elif line.startswith(("FAILED ", "ERROR ")):
        failed.add(line.split()[1])
def status(ids):
    st = []
    for i in ids:
        def hit(p):
            return p == i or p.startswith(i + "::") or p.startswith(i + "[") or (i.endswith(".py") and p.startswith(i))
        ok = [p for p in passed if hit(p)]
        bad = [f for f in failed if hit(f)]
        st.append("FAIL" if bad else ("pass" if ok else "missing"))
    return st
print("# Validation report\n\n| Claim | Evidence (tests) | Status |\n|---|---|---|")
for claim, ids in CLAIMS:
    st = status(ids)
    print(f"| {claim} | {'<br>'.join(f'`{i}`' for i in ids)} | {', '.join(st)} |")
print(f"\n{len(passed)} passed, {len(failed)} failed.")
sys.exit(1 if failed else 0)
