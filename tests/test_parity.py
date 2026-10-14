"""Parity with the reference repo's Debias++, tuner, Persistence++, projector and thresholds.

Slice: a 1.5-degree box of synthetic "mslp" (9 x 13 cells), lead 19 (ecmwf_delta = 18,
start_delta = 27 as for ERA5 in the reference), real-time targets in one year.
"""
import numpy as np
import pandas as pd
import pytest
import xarray as xr

from pbch.cdf import combine_forecast_reforecast, forecast_to_time, members_to_cdf, reforecast_to_time
from pbch.debiaspp import CANDIDATES, debiaspp, tune_debiaspp
from pbch.grid import cos_weights, domain_lattice, stack_targets, unstack_targets
from pbch.config import Box
from pbch.persistpp import persistpp
from pbch.project import project_cdf
from pbch.synth import SynthSpec, make_forecasts, make_truth_weekly
from pbch.thresholds import indicators, observed_thresholds
from reference_port import (ref_debiaspp, ref_percentile_for_date, ref_persistpp, ref_project, ref_tuner_select)

LEAD, ECMWF_DELTA, START_DELTA = 19, 18, 27
K = 5
TOL = 1e-6


@pytest.fixture(scope="module")
def grid_case():
    lats, lons = domain_lattice(Box(lat=(36.0, 48.0), lon=(129.0, 147.0)))
    n = len(lats) * len(lons)
    spec = SynthSpec(start="1980-01-01", end="2017-12-31", n_targets=n, first_forecast_year=2015, seed=5,
                     bias=0.6, seasonal_bias=0.4, skill=0.5)
    truth = make_truth_weekly(spec)
    fc, rf = make_forecasts(truth, spec, LEAD)
    # the reference's pd.to_datetime({year, month, day}) cannot place a Feb 29 issuance in a
    # non-leap hindcast year (ours maps it to Feb 28), so the parity slice excludes those issuances
    keep = ~((fc.issue.dt.month == 2) & (fc.issue.dt.day == 29))
    fc, rf = fc.sel(issue=keep), rf.sel(issue=keep)
    # relabel the target axis as (latitude, longitude)
    mi = xr.Coordinates.from_pandas_multiindex(
        pd.MultiIndex.from_product([lats, lons], names=["latitude", "longitude"]), "target")
    truth = truth.drop_vars("target").assign_coords(mi)
    fc = fc.drop_vars("target").assign_coords(mi)
    rf = rf.drop_vars("target").assign_coords(mi)
    thr = observed_thresholds(truth, K)
    O = indicators(truth, thr)
    fct, rft = forecast_to_time(fc, LEAD), reforecast_to_time(rf, LEAD)
    # per-issuance CDFs in the reference's own layout (it does its own placement and dedup)
    fc_cdf = members_to_cdf(fct, thr).drop_vars(["origin", "issue"])
    fc_cdf = fc_cdf.assign_coords(time=fc["issue"].values).rename({"time": "issuance_date"})
    n_iss, n_hy = rf.sizes["issue"], rf.sizes["hyear"]
    rf_full = rf.stack(time=("issue", "hyear"))
    from pbch.weekly import forecast_delta
    yrs = np.array([iss.year + int(hy) for iss, hy in rf_full.get_index("time")])
    mons = np.array([iss.month for iss, _ in rf_full.get_index("time")])
    days = np.array([iss.day for iss, _ in rf_full.get_index("time")])
    leap = (yrs % 4 == 0) & ((yrs % 100 != 0) | (yrs % 400 == 0))
    days = np.where((mons == 2) & (days == 29) & ~leap, 28, days)
    tt = pd.to_datetime(pd.DataFrame({"year": yrs, "month": mons, "day": days})) + pd.Timedelta(days=forecast_delta(LEAD))
    thr_rf = thr.reindex(time=pd.DatetimeIndex(tt.values).unique()).sel(time=tt.values).values  # (T, k, target)
    rfv = rf_full.transpose("time", "member", "target").values                                # (T, member, target)
    below = (rfv[:, :, None, :] < thr_rf[:, None, :, :]).astype(float)
    below[np.isnan(rfv)[:, :, None, :].repeat(K - 1, axis=2)] = np.nan
    with np.errstate(invalid="ignore"):
        rf_cdf_flat = np.nanmean(below, axis=1)                                                # (T, k, target)
    rf_cdf = xr.DataArray(rf_cdf_flat.reshape(n_iss, n_hy, K - 1, n),
                          dims=("issuance_date", "year_delta", "k", "target"),
                          coords={"issuance_date": rf["issue"].values, "year_delta": rf["hyear"].values,
                                  "k": np.arange(1, K)}).assign_coords(mi)
    targets = pd.DatetimeIndex([t for t in fct.time.values if pd.Timestamp(t).year == 2017])
    return dict(truth=truth, thr=thr, O=O, fct=fct, rft=rft, fc_cdf=fc_cdf, rf_cdf=rf_cdf, targets=targets,
                lats=lats, lons=lons, mi=mi, lat_of_target=np.repeat(lats, len(lons)))


def _ours_F(case, keep):
    allm = combine_forecast_reforecast(case["fct"], case["rft"], reforecast_keep=keep)
    return members_to_cdf(allm, case["thr"])


def _ref_inputs(case, k):
    fc = unstack_targets(case["fc_cdf"].sel(k=k, drop=True))
    rf = unstack_targets(case["rf_cdf"].sel(k=k, drop=True))
    gt = unstack_targets(case["O"].sel(k=k, drop=True))
    return fc, rf, gt


def test_thresholds_match_reference(grid_case):
    truth = unstack_targets(grid_case["truth"])
    for d in ["2017-01-10", "2017-07-04", "2016-02-29"]:
        d = pd.Timestamp(d)
        for k in range(1, K):
            ref = ref_percentile_for_date(truth, d, k / K).squeeze("quantile", drop=True)
            ours = unstack_targets(grid_case["thr"].sel(time=d, k=k, drop=True))
            np.testing.assert_allclose(ours.values, ref.values, atol=TOL)


def test_debiaspp_matches_reference(grid_case):
    F = _ours_F(grid_case, keep="first")
    targets = grid_case["targets"]
    ours = debiaspp(F, grid_case["O"], targets, START_DELTA, 35, 20, causal_issuance=False)
    for k in range(1, K):
        fc, rf, gt = _ref_inputs(grid_case, k)
        ref = ref_debiaspp(fc, rf, gt, targets, ECMWF_DELTA, START_DELTA, 35, 20)
        assert set(ref) == set(targets)
        for t in targets:
            o = unstack_targets(ours.sel(time=t, k=k, drop=True))
            np.testing.assert_allclose(o.values, ref[t].transpose("latitude", "longitude").values, atol=TOL)


def test_tuner_matches_reference(grid_case):
    F = _ours_F(grid_case, keep="first")
    O, targets = grid_case["O"], grid_case["targets"]
    weights = xr.DataArray(np.cos(np.deg2rad(np.abs(grid_case["lat_of_target"]))), dims=["target"]).assign_coords(grid_case["mi"])
    tuned = tune_debiaspp(F, O, targets, START_DELTA, candidates=CANDIDATES, years=20, tune_years=3,
                          scope="pooled", weights=weights, causal_issuance=False)
    # reference: wtd_mse per submodel per date over std_tune-like dates, then select
    ftimes = F.get_index("time")
    tune_dates = ftimes[ftimes >= pd.Timestamp("2013-01-01")]
    for k in [1, 4]:
        cols = {}
        for (s, d) in CANDIDATES:
            P = debiaspp(F, O, tune_dates, START_DELTA, s, 20, days=d, causal_issuance=False).sel(k=k)
            err = ((P - O.reindex(time=tune_dates).sel(k=k)) ** 2)
            cols[f"m{s}_d{d}"] = err.weighted(weights).mean("target").to_series()
        metric_df = pd.DataFrame(cols).dropna(how="all")
        for t in targets[::7]:
            chosen = ref_tuner_select(metric_df, t, START_DELTA, 3, None)
            ours = tuned.choice.sel(time=t, k=k).item()
            assert chosen == f"m{CANDIDATES[ours][0]}_d{CANDIDATES[ours][1]}", (t, k, chosen, ours)


def test_persistpp_matches_reference(grid_case):
    F = _ours_F(grid_case, keep="last")
    targets = grid_case["targets"]
    ours = persistpp(F, grid_case["O"], targets, START_DELTA, LEAD, K, causal_issuance=False)
    for k in [1, 3]:
        fc, rf, gt = _ref_inputs(grid_case, k)
        ref = ref_persistpp(fc, rf, gt, targets, ECMWF_DELTA, START_DELTA, LEAD, fill_value=k * 0.2)
        ref_da = ref.iloc[:, 0].to_xarray()  # (latitude, longitude, time)
        o = unstack_targets(ours.sel(k=k, drop=True)).transpose("latitude", "longitude", "time")
        ref_da = ref_da.reindex_like(o)
        ok = ref_da.notnull()
        assert int(ok.sum()) > 0.9 * ok.size, "reference produced too few predictions"
        np.testing.assert_allclose(o.where(ok).values, ref_da.values, atol=TOL, equal_nan=True)


def test_projector_matches_reference(grid_case):
    rng = np.random.default_rng(0)
    lats, lons = grid_case["lats"], grid_case["lons"]
    raw = rng.uniform(0, 1, (3, K - 1, len(lats), len(lons)))
    raw[0, :, 0, 0] = np.nan
    P = xr.DataArray(raw, dims=("time", "k", "latitude", "longitude"),
                     coords={"time": pd.date_range("2017-01-01", periods=3), "k": np.arange(1, K),
                             "latitude": lats, "longitude": lons})
    ours = unstack_targets(project_cdf(stack_targets(P)))
    for i in range(3):
        ref = ref_project([raw[i, q] for q in range(K - 1)])
        np.testing.assert_allclose(ours.isel(time=i).transpose("k", "latitude", "longitude").values, ref, atol=TOL, equal_nan=True)
