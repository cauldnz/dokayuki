"""Unit tests for the PBC core: bias removal, projection, climatology RPSS, leakage."""
import numpy as np
import pandas as pd
import pytest
import xarray as xr

from conftest import GT_DELTA, K, LEAD
from pbch.cdf import climatology_cdf, combine_forecast_reforecast, forecast_to_time, members_to_cdf, reforecast_to_time
from pbch.debiaspp import debiaspp, tune_debiaspp
from pbch.persistpp import persistpp, rolling_climatology
from pbch.pbc import run_pbc
from pbch.project import cdf_to_bins, project_cdf
from pbch.score import rps, rpss
from pbch.thresholds import indicators, observed_thresholds
from pbch.weekly import forecast_delta, init_for_target


def test_known_bias_is_removed(synth):
    """Raw members carry +1 sd bias; Debias++ must pull the mean CDF back to ~k/K."""
    F, O, targets = synth["F"], synth["O"], synth["targets"]
    raw_mean = F.sel(time=targets).mean(("time", "target")).values
    P = debiaspp(F, O, targets, GT_DELTA, 35, 20, lead=LEAD)
    deb_mean = P.mean(("time", "target")).values
    nominal = np.arange(1, K) / K
    assert np.abs(raw_mean - nominal).mean() > 0.15, "fixture should be visibly biased"
    assert np.abs(deb_mean - nominal).mean() < 0.03, f"bias not removed: {deb_mean}"
    clim = climatology_cdf(K, P)
    Ot = O.reindex(time=targets)
    assert float(rpss(P, clim, Ot).mean()) > 0.05
    assert float(rpss(F.sel(time=targets), clim, Ot).mean()) < 0.0


def test_projection_never_worsens_rps(synth):
    """Isotonic projection is the L2 projection onto the convex set that contains the truth CDF."""
    O, targets = synth["O"], synth["targets"]
    rng = np.random.default_rng(0)
    P = xr.DataArray(rng.uniform(0, 1, (len(targets), K - 1, O.sizes["target"])), dims=("time", "k", "target"),
                     coords={"time": targets, "k": np.arange(1, K), "target": O["target"]})
    Q = project_cdf(P)
    Ot = O.reindex(time=targets)
    assert np.all(np.diff(Q.values, axis=1) >= -1e-12)
    r_before, r_after = rps(P, Ot), rps(Q, Ot)
    ok = r_before.notnull() & r_after.notnull()
    assert float((r_after - r_before).where(ok).max()) <= 1e-10
    # projection is idempotent and leaves monotone CDFs untouched
    xr.testing.assert_allclose(project_cdf(Q), Q)
    bins = cdf_to_bins(Q)
    assert np.allclose(bins.sum("bin").values, 1.0)
    assert float(bins.min()) >= -1e-12


def test_climatology_rpss_is_zero(synth):
    O, targets = synth["O"], synth["targets"]
    Ot = O.reindex(time=targets)
    clim = climatology_cdf(K, Ot)
    assert np.allclose(rpss(clim, clim, Ot).values, 0.0)


def test_persistpp_and_pbc_beat_climatology(synth):
    F, O, targets = synth["F"], synth["O"], synth["targets"]
    Ot = O.reindex(time=targets)
    clim = climatology_cdf(K, Ot)
    pp = persistpp(F, O, targets, GT_DELTA, LEAD, K)
    assert float(rpss(pp, clim, Ot).mean()) > 0.03
    res = run_pbc(F, F, O, targets, GT_DELTA, LEAD, K, scope="per_target")
    assert float(rpss(res.pbc, clim, Ot).mean()) > 0.05
    assert np.all(np.diff(res.pbc.values, axis=1) >= -1e-12)


def test_rolling_climatology_semantics():
    """Padded years use k/K; after 20 real years the climatology equals the 20-year mean."""
    t = pd.date_range("1990-01-01", "2012-12-31", freq="D")
    rng = np.random.default_rng(3)
    O = xr.DataArray(rng.integers(0, 2, (len(t), 1, 1)).astype(float), dims=("time", "k", "target"),
                     coords={"time": t, "k": [1], "target": ["a"]})
    C = rolling_climatology(O, K=5, years=20, margin=4)
    # early entry: mostly padding (k/K = 0.2) -> close to 0.2 but not exactly (one real year)
    first = C.sel(time="1991-06-15").item()
    assert abs(first - 0.2) < 0.06
    # a fully-covered date: compare with explicit construction
    d = pd.Timestamp("2011-06-15")
    vals = []
    for y in range(1, 21):
        for off in range(-4, 5):
            vals.append(O.sel(time=(d - pd.DateOffset(years=y)) + pd.Timedelta(days=off)).item())
    assert abs(C.sel(time=d).item() - np.mean(vals)) < 1e-12
    assert "2000-02-29" not in C.time.dt.strftime("%Y-%m-%d").values


def _poison(synth, t_star: pd.Timestamp, seed=7, window: tuple | None = None):
    """Replace everything not observable at issue time with garbage; rebuild thresholds and CDFs.

    With ``window=(a, b)`` instead corrupt truth weeks starting in [a, b] (a *past* window), to
    show the test has teeth.
    """
    rng = np.random.default_rng(seed)
    truth, fc, rf = synth["truth"].copy(), synth["fc"].copy(), synth["rf"].copy()
    init = init_for_target(t_star, LEAD)
    last_obs_week_start = t_star - pd.Timedelta(days=GT_DELTA)
    if window is None:
        bad = truth.time > last_obs_week_start
        truth.values[bad.values] = rng.normal(50, 30, size=truth.values[bad.values].shape)
        badf = fc.issue > init
        fc.values[badf.values] = rng.normal(50, 30, size=fc.values[badf.values].shape)
        badr = rf.issue > init
        rf.values[badr.values] = rng.normal(50, 30, size=rf.values[badr.values].shape)
    else:
        bad = (truth.time >= pd.Timestamp(window[0])) & (truth.time <= pd.Timestamp(window[1]))
        truth.values[bad.values] = rng.normal(50, 30, size=truth.values[bad.values].shape)
    thr = observed_thresholds(truth, K)
    O = indicators(truth, thr)
    allm = combine_forecast_reforecast(forecast_to_time(fc, LEAD), reforecast_to_time(rf, LEAD))
    F = members_to_cdf(allm, thr)
    return F, O


@pytest.mark.parametrize("t_star", ["2020-01-13", "2020-12-11"])
def test_no_future_leakage(synth, t_star):
    """Predictions for t* must not change when all data after the issue date is corrupted."""
    t_star = pd.Timestamp(t_star)
    F, O = synth["F"], synth["O"]
    Fp, Op = _poison(synth, t_star)
    tg = pd.DatetimeIndex([t_star])
    clean = run_pbc(F, F, O, tg, GT_DELTA, LEAD, K, scope="per_target")
    dirty = run_pbc(Fp, Fp, Op, tg, GT_DELTA, LEAD, K, scope="per_target")
    for name in ("debiaspp", "persistpp", "pbc"):
        a, b = getattr(clean, name), getattr(dirty, name)
        assert np.isfinite(a.values).all(), f"{name}: NaN prediction"
        np.testing.assert_allclose(a.values, b.values, atol=1e-12, err_msg=f"{name} leaks future data")
    # and the test must have teeth: corrupting *observable* data does change the forecast
    Fq, Oq = _poison(synth, t_star, seed=11, window=("2017-11-01", "2018-03-31"))   # observed past
    other = run_pbc(Fq, Fq, Oq, tg, GT_DELTA, LEAD, K, scope="per_target")
    assert not np.allclose(other.pbc.values, clean.pbc.values)


def test_non_causal_target_is_nan(synth):
    """A target whose only model run was issued after its init date gets no forecast."""
    F, O = synth["F"], synth["O"]
    t = pd.Timestamp("2020-12-10")   # Sunday init: no real forecast, only a later reforecast covers it
    assert str(F.sel(time=t).origin.values) == "reforecast"
    P = debiaspp(F, O, pd.DatetimeIndex([t]), GT_DELTA, 35, 20, lead=LEAD)
    assert np.isnan(P.values).all()
    P2 = debiaspp(F, O, pd.DatetimeIndex([t]), GT_DELTA, 35, 20, causal_issuance=False)
    assert np.isfinite(P2.values).all()


def test_lead_bookkeeping():
    assert forecast_delta(19) == 18 and forecast_delta(26) == 25
    assert init_for_target(pd.Timestamp("2020-01-19"), 19) == pd.Timestamp("2020-01-01")
