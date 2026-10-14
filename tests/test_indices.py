"""Index geometry and weekly aggregation on a synthetic lattice."""
import numpy as np
import pandas as pd
import xarray as xr

from dokayuki.config import Box, IndexDef, load_indices
from dokayuki.grid import area_mean, domain_lattice, coarsen_block_mean
from dokayuki.indices import all_indices, cold_day_precip, index_value
from dokayuki.weekly import weekly_from_daily


def _field(value_fn, times=3):
    lats, lons = domain_lattice(Box(lat=(21.0, 72.0), lon=(75.0, 225.0)))
    LAT, LON = np.meshgrid(lats, lons, indexing="ij")
    v = value_fn(LAT, LON)
    data = np.repeat(v[None], times, axis=0)
    return xr.DataArray(data, dims=("time", "latitude", "longitude"),
                        coords={"time": pd.date_range("2020-01-01", periods=times), "latitude": lats, "longitude": lons})


def test_box_mean_is_cos_weighted():
    f = _field(lambda la, lo: la)  # value = latitude
    box = Box(lat=(40.0, 65.0), lon=(80.0, 120.0))
    m = area_mean(f, box).isel(time=0).item()
    lats = f.latitude.values; sel = (lats >= 40) & (lats <= 65)
    w = np.cos(np.deg2rad(lats[sel]))
    assert abs(m - (lats[sel] * w).sum() / w.sum()) < 1e-9


def test_config_indices_evaluate_with_expected_signs():
    defs = load_indices()
    msl = _field(lambda la, lo: 101000.0 + 1000.0 * (lo < 125))      # high in the west, low in the east
    t850 = _field(lambda la, lo: np.full_like(la, 273.15 - 10.0))     # -10 C everywhere
    z500 = _field(lambda la, lo: np.full_like(la, 5400.0))
    sst = _field(lambda la, lo: np.full_like(la, 283.15))
    out = all_indices(defs, {"msl": msl, "t850": t850, "z500": z500}, sst=sst)
    v = out.isel(time=0).to_pandas()
    assert v["SHI"] > 15 and v["SHI"] < 25             # (1020 hPa - 1000)
    assert v["ALI"] > -15 and v["ALI"] < -5            # -(1010 - 1000)
    assert v["MOI"] > 5                                # Irkutsk (104E) high minus Nemuro (145E) low = +10 hPa
    assert abs(v["SJC"] - 10.0) < 1e-6                 # -(T850 C) = +10
    assert abs(v["SJI"] - 20.0) < 1e-6                 # SST - T850 = 10 - (-10)
    assert abs(v["EAT"] - 100.0) < 1e-6                # -(5400 - 5500)


def test_point_difference_uses_nearest_cells():
    idx = IndexDef(key="d", name="d", field="msl", sign=1, scale=1.0, plain="d",
                   point_difference={"a": {"lat": 52.3, "lon": 104.3}, "b": {"lat": 43.3, "lon": 145.6}})
    f = _field(lambda la, lo: lo)
    v = index_value(idx, {"msl": f}).isel(time=0).item()
    assert abs(v - (105.0 - 145.5)) < 1e-9   # 104.3E -> nearest lattice 105.0E; 145.6E -> 145.5E


def test_weekly_from_daily_labels_week_start():
    t = pd.date_range("2020-01-01", periods=20)
    da = xr.DataArray(np.arange(20.0), dims=["time"], coords={"time": t})
    w = weekly_from_daily(da, "sum")
    assert w.sel(time="2020-01-01").item() == sum(range(7))
    assert w.time.values[-1] == np.datetime64("2020-01-14")   # last complete week starts day 14


def test_cold_day_precip():
    t = pd.date_range("2020-01-01", periods=4)
    tp = xr.DataArray([1.0, 2.0, 3.0, 4.0], dims=["time"], coords={"time": t})
    t850 = xr.DataArray([270.0, 260.0, 268.0, 265.0], dims=["time"], coords={"time": t})
    out = cold_day_precip(tp, t850, 273.15 - 6.0)
    assert list(out.values) == [0.0, 2.0, 0.0, 4.0]


def test_coarsen_block_mean_centres_on_lattice():
    lats = np.arange(-90, 90.001, 0.25); lons = np.arange(0, 360, 0.25)
    LAT, LON = np.meshgrid(lats, lons, indexing="ij")
    da = xr.DataArray(LAT, dims=("latitude", "longitude"), coords={"latitude": lats, "longitude": lons})
    c = coarsen_block_mean(da, 6)
    assert 43.5 in c.latitude.values and 141.0 in c.longitude.values
    # six 0.25-degree cells cannot be centred exactly on a 1.5-degree point: the block for 43.5
    # spans cell centres 42.75..44.0 (mean 43.375), a documented half-cell offset
    assert abs(c.sel(latitude=43.5, longitude=141.0).item() - 43.5) < 0.15
