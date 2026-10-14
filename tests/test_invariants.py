"""Invariants and causality of every intermediate step, on synthetic data with known answers."""
import numpy as np
import pandas as pd
import pytest
import xarray as xr

from conftest import GT_DELTA, K, LEAD
from dokayuki.cdf import combine_forecast_reforecast, lagged_ensemble, reforecast_to_time
from dokayuki.debiaspp import tune_debiaspp
from dokayuki.duet import duet
from dokayuki.pbc import run_pbc
from dokayuki.persistpp import persistpp
from dokayuki.project import cdf_to_bins, project_cdf
from dokayuki.thresholds import model_thresholds, observed_thresholds
from dokayuki.validate import check_bins, check_cdf, check_thresholds
from dokayuki.weekly import weekly_from_daily


def test_thresholds_monotone_and_use_only_prior_years(synth):
    thr = synth["thr"]
    assert check_thresholds(thr).ok
    truth = synth["truth"].copy()
    t = pd.Timestamp("2019-01-10")
    # corrupt everything from the target year on: thresholds for t must not move
    truth.values[(truth.time >= pd.Timestamp("2019-01-01")).values] += 1e3
    thr2 = observed_thresholds(truth, K, times=pd.DatetimeIndex([t]))
    np.testing.assert_allclose(thr2.sel(time=t).values, thr.sel(time=t).values)
    # ... but corrupting a prior year does change them
    truth2 = synth["truth"].copy(); truth2.values[(truth2.time.dt.year == 2010).values] += 1e3
    thr3 = observed_thresholds(truth2, K, times=pd.DatetimeIndex([t]))
    assert not np.allclose(thr3.sel(time=t).values, thr.sel(time=t).values)


def test_model_thresholds_strict_mode_uses_only_past_base_dates(synth):
    rf = synth["rf"]
    issue = pd.Timestamp("2019-01-07")
    strict = model_thresholds(rf, K, pd.DatetimeIndex([issue]), n_before=4, n_after=0)
    rf_bad = rf.copy(); rf_bad.values[(rf_bad.issue > issue).values] += 1e3
    strict2 = model_thresholds(rf_bad, K, pd.DatetimeIndex([issue]), n_before=4, n_after=0)
    np.testing.assert_allclose(strict.values, strict2.values)
    ref = model_thresholds(rf, K, pd.DatetimeIndex([issue]), n_before=4, n_after=4)
    ref2 = model_thresholds(rf_bad, K, pd.DatetimeIndex([issue]), n_before=4, n_after=4)
    assert not np.allclose(ref.values, ref2.values)            # the reference recipe does look ahead (documented)
    assert check_thresholds(strict.rename({"issue": "time"})).ok


def test_reforecast_placement_dates_and_feb29():
    issues = pd.DatetimeIndex(["2016-02-29", "2017-03-02"])
    rf = xr.DataArray(np.zeros((2, 2, 1, 1)), dims=("issue", "hyear", "member", "target"),
                      coords={"issue": issues, "hyear": [-2, -1], "member": [0], "target": ["a"]})
    out = reforecast_to_time(rf, 19)
    times = pd.DatetimeIndex(out.time.values)
    assert pd.Timestamp("2014-02-28") + pd.Timedelta(days=18) in times      # 2016-02-29 -> 2014-02-28
    assert pd.Timestamp("2015-02-28") + pd.Timedelta(days=18) in times
    assert pd.Timestamp("2016-03-02") + pd.Timedelta(days=18) in times
    assert (pd.DatetimeIndex(out.issue.values) >= times).all()               # every hindcast row knows its real issuance


def test_combine_prefers_forecast_and_keeps_requested_reforecast():
    t = pd.Timestamp("2018-01-19")
    fc = xr.DataArray([[[1.0]]], dims=("time", "member", "target"), coords={"time": [t], "member": [0], "target": ["a"]})
    fc = fc.assign_coords(origin=("time", ["forecast"]), issue=("time", [np.datetime64("2018-01-01")]))
    rf = xr.DataArray([[[2.0]], [[3.0]]], dims=("time", "member", "target"), coords={"time": [t, t], "member": [0], "target": ["a"]})
    rf = rf.assign_coords(origin=("time", ["reforecast"] * 2), issue=("time", [np.datetime64("2019-01-01"), np.datetime64("2020-01-01")]))
    assert combine_forecast_reforecast(fc, rf).values.item() == 1.0
    assert combine_forecast_reforecast(None, rf, reforecast_keep="first").values.item() == 2.0
    assert combine_forecast_reforecast(None, rf, reforecast_keep="last").values.item() == 3.0


def test_lagged_ensemble_pools_older_runs_at_longer_leads():
    issues = pd.date_range("2024-01-01", periods=4)
    da = xr.DataArray(np.arange(4 * 3 * 2 * 1, dtype=float).reshape(4, 3, 2, 1), dims=("issue", "lead", "member", "target"),
                      coords={"issue": issues, "lead": [19, 20, 21], "member": [0, 1], "target": ["a"]})
    pooled = lagged_ensemble(da, n_runs=3, lead=19)
    assert pooled.sizes["member"] == 6 and pooled.sel(issue=issues[-1]).notnull().all()
    assert pooled.sel(issue=issues[0]).sizes["member"] == 6 and int(pooled.sel(issue=issues[0]).notnull().sum()) == 2  # only one run available yet


def test_pbc_outputs_are_valid_distributions(synth):
    F, O, targets = synth["F"], synth["O"], synth["targets"]
    res = run_pbc(F, F, O, targets[:40], GT_DELTA, LEAD, K, scope="per_target")
    for name in ("debiaspp", "persistpp", "pbc"):
        da = getattr(res, name)
        assert check_cdf(project_cdf(da), name=name).ok
    assert check_bins(cdf_to_bins(res.pbc)).ok


def test_persistpp_survives_singular_design(synth):
    """A constant model feature makes X'X singular; the lstsq fallback must still give finite odds."""
    F, O, targets = synth["F"], synth["O"], synth["targets"][:10]
    Fc = xr.zeros_like(F) + 0.5
    Fc = Fc.assign_coords(issue=F["issue"], origin=F["origin"])
    P = persistpp(Fc, O, targets, GT_DELTA, LEAD, K)
    assert np.isfinite(P.values).all() and (P.values >= 0).all() and (P.values <= 1).all()


def test_tuner_choice_ignores_future_scores(synth):
    F, O, targets = synth["F"], synth["O"], synth["targets"][:6]
    a = tune_debiaspp(F, O, targets, GT_DELTA, scope="per_target", lead=LEAD)
    Op = O.copy(); Op.values[(Op.time > targets.max()).values] = np.nan      # remove all later truth
    b = tune_debiaspp(F, Op, targets, GT_DELTA, scope="per_target", lead=LEAD)
    np.testing.assert_array_equal(a.choice.values, b.choice.values)
    np.testing.assert_allclose(a.pred.values, b.pred.values)


def test_duet_refuses_validation_overlapping_test(synth):
    F, O, targets = synth["F"], synth["O"], synth["targets"][:4]
    res = run_pbc(F, F, O, targets, GT_DELTA, LEAD, K, scope="per_target")
    with pytest.raises(ValueError):
        duet(res.pbc, res.pbc, O, validation=("2019-01-01", "2019-12-31"), test_start=pd.Timestamp("2019-06-01"))


def test_weekly_aggregation_has_no_partial_weeks():
    t = pd.date_range("2020-01-01", periods=9)
    w = weekly_from_daily(xr.DataArray(np.ones(9), dims=["time"], coords={"time": t}), "sum")
    assert w.sizes["time"] == 3 and (w.values == 7).all()
