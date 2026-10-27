"""Spec update 1: new ingredient indices, lift metric, experiment log guard."""
import numpy as np
import pandas as pd
import pytest
import xarray as xr

import dokayuki.experiments as experiments
from dokayuki.config import Box, load_indices, load_stage_names
from dokayuki.experiments import assert_not_locked
from dokayuki.indices import ao_projection, nw_flow, sji_days, ural_blocking, zonal_mean_at
from dokayuki.score import effective_n, lift
from test_indices import _field


def test_nw_flow_sign():
    box = Box(lat=(38.0, 46.0), lon=(132.0, 141.0))
    u = _field(lambda la, lo: np.full_like(la, 5.0)); v = _field(lambda la, lo: np.full_like(la, -5.0))   # from the NW
    assert abs(nw_flow(u, v, box).isel(time=0).item() - 5 * np.sqrt(2)) < 1e-9
    assert nw_flow(-u, -v, box).isel(time=0).item() < 0                                                  # from the SE


def test_zonal_mean_at_60n():
    f = _field(lambda la, lo: la * 0 + lo)
    assert abs(zonal_mean_at(f, 60.0).isel(time=0).item() - np.mean(f.longitude.values)) < 1e-9


def test_sji_days_counts_threshold_days():
    t = pd.date_range("2020-01-01", periods=10)
    sst = xr.DataArray(np.full(10, 283.15), dims=["time"], coords={"time": t})
    t850 = xr.DataArray(283.15 - np.array([14, 10, 15, 13, 12, 20, 1, 13, 14, 15.0]), dims=["time"], coords={"time": t})
    d = sji_days(sst, t850, Box(lat=(38, 46), lon=(132, 141)), 13.0)
    assert d.sel(time="2020-01-01").item() == 4          # days 1,3,4,6 within the first 7
    assert d.time.values[-1] == np.datetime64("2020-01-04")


def test_ural_blocking_anomaly_and_ao_projection():
    z = _field(lambda la, lo: np.full_like(la, 5600.0), times=3)
    clim = z.isel(time=0).drop_vars("time").expand_dims(dayofyear=[1, 2, 3]).assign_coords(dayofyear=[1, 2, 3]) - 50.0
    ub = ural_blocking(z, clim, Box(lat=(45, 70), lon=(40, 80)))
    assert np.allclose(ub.values, 50.0)
    pattern = _field(lambda la, lo: np.cos(np.deg2rad(lo)), times=1).isel(time=0)
    anom = 2.0 * pattern.expand_dims(time=[pd.Timestamp("2020-01-01")])
    assert abs(ao_projection(anom, pattern).item() - 2.0) < 1e-9


def test_lift_detects_known_improvement():
    rng = np.random.default_rng(0)
    t = pd.date_range("2010-12-01", "2022-02-28", freq="7D"); t = t[t.month.isin([12, 1, 2])]
    clim = pd.Series(0.667, index=t)
    ref = pd.Series(clim * (1 - 0.02) + rng.normal(0, 0.05, len(t)), index=t)
    model = pd.Series(clim * (1 - 0.10) + rng.normal(0, 0.05, len(t)), index=t)
    r = lift(model, ref, clim, n_boot=400)
    assert r["lift"] > 0.04 and r["ci"][0] > 0 and r["significant"]
    r0 = lift(ref, ref, clim, n_boot=200)
    assert abs(r0["lift"]) < 1e-12 and not r0["significant"]


def test_effective_n_shrinks_with_autocorrelation():
    rng = np.random.default_rng(1)
    white = pd.Series(rng.standard_normal(500))
    ar = pd.Series(np.cumsum(rng.standard_normal(500)) * 0.1 + rng.standard_normal(500) * 0.2)
    assert effective_n(white) > 350 and effective_n(ar) < effective_n(white)


def test_locked_winters_guard_and_stages(monkeypatch):
    # the mechanism, not today's project config: v1-frozen (2026-10-27) unsealed the real
    # locked_final_exam_winters, so this locks its own fake set rather than depending on that.
    monkeypatch.setattr(experiments, "locked_winters", lambda: ("2022/23", "2024/25"))
    with pytest.raises(RuntimeError):
        assert_not_locked(["2022/23", "2024/25"])
    assert_not_locked(["2017/18"])
    defs = load_indices()
    assert {k: v.stage for k, v in defs.items() if k in ("U10_60N", "SHI", "NWF", "SJI13")} == {"U10_60N": 1, "SHI": 2, "NWF": 3, "SJI13": 4}
    assert load_stage_names()[4]["name"] == "Fuel"
