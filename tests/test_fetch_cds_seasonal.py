"""JMA CDS seasonal fetcher: request shape, dataset routing, decode (no network)."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from dokayuki.config import Box
from dokayuki.fetch import cds_seasonal as cs
from dokayuki.grid import LAT, LON, domain_lattice

DOMAIN = Box(lat=(21.0, 72.0), lon=(75.0, 225.0))


def test_request_routes_pressure_level_fields_correctly():
    r = cs.request("t850", [1993, 1994], "0116", domain=DOMAIN)
    assert r["originating_centre"] == "jma" and r["system"] == "3"
    assert r["variable"] == ["temperature"] and r["pressure_level"] == "850"
    assert r["year"] == ["1993", "1994"] and r["month"] == "01" and r["day"] == "16"
    assert r["area"] == [72.0, 75.0, 21.0, 225.0]

    r2 = cs.request("msl", [1993], "0131", system="cps4", domain=DOMAIN)
    assert "pressure_level" not in r2
    assert r2["system"] == "4"


def test_request_rejects_a_non_s2s_start_date():
    with pytest.raises(ValueError):
        cs.request("msl", [1993], "0115", domain=DOMAIN)


def test_request_needs_area_or_domain():
    with pytest.raises(ValueError):
        cs.request("msl", [1993], "0116")


def test_requests_for_splits_single_and_pressure_datasets():
    reqs = cs.requests_for(["msl", "t850", "z500", "sst"], [1993], ["0116", "0615"], domain=DOMAIN)
    assert len(reqs) == 2 * 4
    datasets = {f: d for (d, r) in reqs for f in r["variable"]}
    assert datasets["mean_sea_level_pressure"] == cs.DATASET_SINGLE
    assert datasets["temperature"] == cs.DATASET_PRESSURE
    assert datasets["geopotential"] == cs.DATASET_PRESSURE
    assert datasets["sea_surface_temperature"] == cs.DATASET_SINGLE


def test_requests_for_skips_unknown_fields():
    reqs = cs.requests_for(["msl", "snowfall"], [1993], ["0116"], domain=DOMAIN)
    assert len(reqs) == 1


def test_hindcast_years_stops_before_the_real_time_period():
    years = cs.hindcast_years("cps3")
    assert years[0] == 1992 and years[-1] == 2022
    assert len(years) == 31


def _synthetic_netcdf(tmp_path: Path, start_years: list[int], nlat=5, nlon=6) -> Path:
    """A minimal CDS-seasonal-shaped Dataset: (forecast_reference_time, realization,
    leadtime_hour, latitude, longitude), values = 100*year + lead_day, so decode can be checked
    against a known number."""
    lat = np.linspace(72.0, 21.0, nlat)
    lon = np.linspace(75.0, 225.0, nlon)
    hours = np.arange(0, 43, 6)  # 0,6,...,42h, 6-hourly -> days 1, 2 (0-18h, 24-42h)
    frt = pd.DatetimeIndex([pd.Timestamp(f"{y}-01-16") for y in start_years])
    data = np.zeros((len(start_years), 24, len(hours), nlat, nlon), dtype="float64")
    for i, y in enumerate(start_years):
        for j, h in enumerate(hours):
            data[i, :, j] = 100.0 * y + (h // 24 + 1)
    ds = xr.Dataset(
        {"z": (("forecast_reference_time", "realization", "leadtime_hour", LAT, LON), data)},
        coords={"forecast_reference_time": frt, "realization": np.arange(24), "leadtime_hour": hours,
                LAT: lat, LON: lon},
    )
    path = tmp_path / "sample.nc"
    ds.to_netcdf(path)
    return path


def test_open_seasonal_decodes_to_the_wmc_layout_and_reduces_to_daily(tmp_path):
    path = _synthetic_netcdf(tmp_path, [1993, 1994])
    da = cs.open_seasonal(path, "msl")  # scale 1.0, so the daily-mean reduction is checked exactly
    assert set(da.dims) >= {"number", "time", "step_day", LAT, LON}
    assert da.sizes["time"] == 2 and da.sizes["number"] == 24
    assert list(da["step_day"].values) == [1, 2]
    # every 6-hourly value within a day was the same constant, so the daily mean reproduces it
    got = float(da.sel(time=da["time"].values[0], step_day=1, number=0, **{LAT: da[LAT].values[0], LON: da[LON].values[0]}))
    assert got == pytest.approx(100.0 * 1993 + 1)


def test_open_seasonal_applies_the_geopotential_to_height_scale(tmp_path):
    path = _synthetic_netcdf(tmp_path, [1993])
    da = cs.open_seasonal(path, "z500")
    got = float(da.sel(time=da["time"].values[0], step_day=1, number=0, **{LAT: da[LAT].values[0], LON: da[LON].values[0]}))
    assert got == pytest.approx((100.0 * 1993 + 1) / 9.80665)


def test_to_lattice_lands_on_the_domain_lattice(tmp_path):
    path = _synthetic_netcdf(tmp_path, [1993])
    da = cs.open_seasonal(path, "z500")
    out = cs.to_lattice(da, DOMAIN)
    lat_t, lon_t = domain_lattice(DOMAIN)
    np.testing.assert_allclose(out[LAT].values, lat_t)
    np.testing.assert_allclose(out[LON].values, lon_t)
