"""The validators must catch broken inputs (a validator that never fails proves nothing)."""
import copy

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from pbch.site.fixtures import make_state
from pbch.validate import (FIELD_RANGES, ValidationError, check_bins, check_cdf, check_daily_fields,
                           check_forecast_json, check_thresholds, implausible_skill)


def _daily(v, var="msl"):
    t = pd.date_range("2020-01-01", periods=5)
    return xr.Dataset({var: (("time", "latitude", "longitude"), v)}, coords={"time": t, "latitude": [40.0, 41.5], "longitude": [140.0, 141.5]})


def test_daily_field_checks_catch_corruption():
    good = _daily(np.full((5, 2, 2), 101000.0) + np.random.default_rng(0).normal(0, 100, (5, 2, 2)))
    assert check_daily_fields(good).ok
    assert not check_daily_fields(_daily(np.full((5, 2, 2), 101000.0))).ok                 # constant
    assert not check_daily_fields(_daily(np.full((5, 2, 2), 50.0) + np.arange(20).reshape(5, 2, 2))).ok   # out of range
    bad = good.copy(); bad["msl"].values[2] = np.nan
    assert not check_daily_fields(bad, max_nan_frac=0.1).ok
    rev = good.isel(time=slice(None, None, -1))
    assert not check_daily_fields(rev).ok                                                   # time not increasing


def test_cdf_bins_threshold_checks():
    t = pd.date_range("2020-01-01", periods=2)
    good = xr.DataArray([[[0.1], [0.4], [0.6], [0.9]], [[0.0], [0.0], [0.5], [1.0]]], dims=("time", "k", "target"),
                        coords={"time": t, "k": [1, 2, 3, 4], "target": ["a"]})
    assert check_cdf(good).ok
    bad = good.copy(); bad.values[0, 2, 0] = 0.3
    assert not check_cdf(bad).ok                                                            # non-monotone
    bad2 = good.copy(); bad2.values[1, 1, 0] = np.nan
    assert not check_cdf(bad2).ok                                                           # partial NaN
    bad3 = good.copy(); bad3.values[0, 3, 0] = 1.2
    assert not check_cdf(bad3).ok
    bins = xr.DataArray([[[0.2], [0.2], [0.2], [0.2], [0.2]]], dims=("time", "bin", "target"), coords={"time": t[:1], "bin": [1, 2, 3, 4, 5], "target": ["a"]})
    assert check_bins(bins).ok
    assert not check_bins(bins * 1.1).ok
    thr = good.copy(); assert check_thresholds(thr).ok
    thr.values[0, 1, 0] = -5; assert not check_thresholds(thr).ok


def test_forecast_json_semantic_rules():
    base = make_state("strong")
    assert check_forecast_json(base).ok
    d = copy.deepcopy(base); d["weeks"][0]["terciles"]["above"] += 0.2
    assert any("sum to 1" in p for p in check_forecast_json(d).problems)
    d = copy.deepcopy(base); d["weeks"][0]["valid"] = [d["issued"], d["issued"]]
    r = check_forecast_json(d); assert not r.ok
    d = copy.deepcopy(base); d["snow_model"]["skilful"] = False
    assert any("not skilful" in p for p in check_forecast_json(d).problems)
    d = copy.deepcopy(base); d["indices"][0]["skill"]["19"]["rpss"] = 0.6
    assert any("probable leak" in p for p in check_forecast_json(d).problems)
    d = copy.deepcopy(base); d["weeks"][1]["big_week"] = 0.95
    assert any("exceeds" in p for p in check_forecast_json(d).problems)
    d = copy.deepcopy(base); d["weeks"][0]["grade"] = "Huge"
    assert any("schema" in p for p in check_forecast_json(d).problems)
    d = copy.deepcopy(base); del d["weeks"][0]["stages"]
    assert not check_forecast_json(d).ok
    with pytest.raises(ValidationError):
        check_forecast_json(d).raise_if_failed()


def test_implausible_skill_guard():
    assert implausible_skill(0.45) and not implausible_skill(0.08)
    assert implausible_skill(0.22, "snow")
