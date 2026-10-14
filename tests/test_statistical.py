"""Statistical validation on synthetic data with known answers: calibration, no fabricated skill,
permutation null. These are the tests that say 'the numbers mean what we claim'."""
import numpy as np
import pandas as pd
import pytest
import xarray as xr

from conftest import GT_DELTA, K, LEAD
from dokayuki.cdf import climatology_cdf, combine_forecast_reforecast, forecast_to_time, members_to_cdf, reforecast_to_time
from dokayuki.pbc import run_pbc
from dokayuki.project import cdf_to_bins
from dokayuki.score import lift, reliability, rps, rpss
from dokayuki.synth import SynthSpec, make_forecasts, make_truth_weekly
from dokayuki.thresholds import indicators, observed_thresholds
from dokayuki.validate import implausible_skill, permutation_null


def _build(spec):
    truth = make_truth_weekly(spec)
    fc, rf = make_forecasts(truth, spec, LEAD)
    thr = observed_thresholds(truth, K)
    O = indicators(truth, thr)
    F = members_to_cdf(combine_forecast_reforecast(forecast_to_time(fc, LEAD), reforecast_to_time(rf, LEAD)), thr)
    fct = forecast_to_time(fc, LEAD)
    targets = pd.DatetimeIndex([t for t in fct.time.values if pd.Timestamp(t).year >= 2019])
    return truth, thr, O, F, targets


def test_pbc_is_reliable_where_raw_is_not(synth):
    """Reliability: among weeks where PBC says P(y < q2) is in a bin, the observed frequency matches."""
    F, O, targets = synth["F"], synth["O"], synth["targets"]
    res = run_pbc(F, F, O, targets, GT_DELTA, LEAD, K, scope="per_target")
    Ot = O.reindex(time=targets)
    def slope(P):
        p = P.sel(k=2).values.ravel(); o = Ot.sel(k=2).values.ravel()
        tab = reliability(p, o, bins=5).dropna()
        tab = tab[tab.n >= 15]
        b = np.polyfit(tab.mean_forecast, tab.obs_freq, 1)[0]
        return b
    assert abs(slope(res.pbc) - 1) < 0.35, "PBC should be close to reliable"
    assert abs(slope(F.sel(time=targets)) - 1) > 0.35 or float(rpss(F.sel(time=targets), climatology_cdf(K, Ot), Ot).mean()) < 0, "raw should be visibly miscalibrated"


def test_no_skill_input_yields_no_fabricated_skill():
    """Members with zero skill (pure noise + bias): PBC must land near climatology, not above it."""
    spec = SynthSpec(start="1980-01-01", end="2021-12-31", n_targets=2, first_forecast_year=2015, seed=9, skill=0.0, bias=1.0)
    truth, thr, O, F, targets = _build(spec)
    res = run_pbc(F, F, O, targets, GT_DELTA, LEAD, K, scope="per_target")
    Ot = O.reindex(time=targets); clim = climatology_cdf(K, Ot)
    r = rpss(res.pbc, clim, Ot).values
    assert np.all(r < 0.03), f"fabricated skill: {r}"
    # and the lift over the raw (debiased-by-climatology) model has an interval covering zero
    m = rps(res.pbc, Ot).isel(target=0).to_series(); c = rps(clim, Ot).isel(target=0).to_series()
    L = lift(m, c, c, n_boot=300)
    assert L["ci"][0] <= 0.0 <= L["ci"][1] + 0.02


def test_permutation_null_separates_real_skill_from_chance(synth):
    """Shuffle which winter's truth goes with which winter's forecasts: skill must collapse."""
    F, O = synth["F"], synth["O"]
    targets = pd.DatetimeIndex([t for t in synth["fct"].time.values if pd.Timestamp(t).year >= 2017])   # 5 seasons
    res = run_pbc(F, F, O, targets, GT_DELTA, LEAD, K, scope="per_target")
    Ot = O.reindex(time=targets); clim = climatology_cdf(K, Ot)
    real = float(rpss(res.pbc, clim, Ot).mean())
    seasons = sorted({t.year for t in targets})
    truth_by_season = {y: Ot.sel(time=Ot.time.dt.year == y) for y in seasons}
    def skill_with(shuffled):
        parts = []
        for y, src in shuffled.items():
            dst = Ot.sel(time=Ot.time.dt.year == y)
            n = min(dst.sizes["time"], src.sizes["time"])
            parts.append(src.isel(time=slice(0, n)).assign_coords(time=dst.time.values[:n]))
        Os = xr.concat(parts, dim="time").sortby("time")
        return float(rpss(res.pbc.sel(time=Os.time), clim.sel(time=Os.time), Os).mean())
    null = permutation_null(skill_with, truth_by_season, n_perm=24, seed=1)
    assert real > null.mean() + 3 * null.std(), f"real {real:.3f} vs null {null.mean():.3f} +/- {null.std():.3f}"
    assert real > null.max()
    # a sharp forecast paired with the wrong winters scores at or below climatology: the null is <= 0
    assert null.mean() <= 0.01


def test_skill_guard_thresholds_match_paper_scale():
    assert not implausible_skill(0.12) and implausible_skill(0.35)
