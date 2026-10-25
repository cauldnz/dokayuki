"""JMA WMC Tokyo CPS4 hindcast fetcher: URL layout, member coding, daily assembly, lattice (no network)."""
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dokayuki.config import Box
from dokayuki.fetch import wmc
from dokayuki.grid import LAT, LON, domain_lattice

DOMAIN = Box(lat=(21.0, 72.0), lon=(75.0, 225.0))


def test_start_dates_are_the_s2s_cps_reforecast_dates():
    assert len(wmc.START_MMDD) == 24
    assert wmc.START_MMDD[:4] == ("0116", "0131", "0210", "0225")
    assert wmc.start_dates((10, 11, 12, 1, 2, 3)) == ["0116", "0131", "0210", "0225", "0312", "0327",
                                                       "1013", "1028", "1112", "1127", "1212", "1227"]
    assert wmc.HYEARS == tuple(range(1991, 2021))


def test_url_matches_the_wmc_directory_layout():
    assert wmc.url("0116", 1991, "z500") == (
        "https://ds.data.jma.go.jp/wmc/data/gpv/model/1mE_Hind_125.CPS4/Daily/0116/1991/"
        "JMACPS_1p25deg_19910116_p500_Phh_hind_mb.grb2")
    assert wmc.file_name("1227", 2020, "tp") == "JMACPS_1p25deg_20201227_surf_Prr_hind_mb.grb2"
    assert wmc.file_name("0116", 1991, "t2m", "geps2503") == "JMAGEPS_1p25deg_19910116_h2_Ptt_hind_mb.grb2"
    with pytest.raises(ValueError):
        wmc.url("0115", 1991, "msl")


def test_estimate_drops_unavailable_fields_and_counts_bytes():
    est = wmc.estimate_pull(["z500", "t850", "u10hpa", "sst"], ["0116", "0131"], [1991, 1992, 1993])
    assert est["fields"] == ["z500", "t850"]
    assert est["files"] == 2 * 3 * 2
    assert est["bytes"] == int((9.7 + 14.0) * 6 * 2**20)
    full = wmc.estimate_pull(["msl", "t2m", "tp", "t850", "z500"], list(wmc.START_MMDD))
    assert 40 < full["gb"] < 60     # the whole five-field set crosses the 20 GB stop-and-ask line
    winter = wmc.estimate_pull(["msl", "t2m", "tp", "t850", "z500"], wmc.start_dates((10, 11, 12, 1, 2, 3)))
    assert 20 < winter["gb"] < 30


def test_member_index_is_a_bijection_onto_0_12():
    coded = [(1, 0)] + [(3, k) for k in range(1, 7)] + [(2, k) for k in range(1, 7)]
    idx = [wmc.member_index(t, n) for t, n in coded]
    assert sorted(idx) == list(range(13))
    assert wmc.member_index(3, 2) == 2 and wmc.member_index(2, 2) == 8
    with pytest.raises(ValueError):
        wmc.member_index(4, 1)


def _records(short, days, nlat=5, nlon=6, scale_member=1.0):
    recs = []
    for m in range(wmc.N_MEMBERS):
        for d in days:
            vals = np.full((nlat, nlon), 100.0 * d + scale_member * m, dtype="float64")
            recs.append((m, 24 * (d - 1), 24 * d, vals))
    return recs


def test_assemble_labels_windows_by_forecast_day_and_scales_precip():
    lat = np.array([90.0, 88.75, 87.5, 86.25, 85.0]); lon = np.arange(6) * 1.25
    init = pd.Timestamp("1991-01-16")
    z = wmc.assemble(_records("z500", range(1, 35)), lat, lon, init, "z500")
    assert z.dims == ("number", "time", "step_day", LAT, LON)
    assert z.shape == (13, 1, 34, 5, 6)
    assert list(z["step_day"].values[:3]) == [1, 2, 3] and int(z["step_day"].values[-1]) == 34
    assert float(z.sel(number=8, step_day=19).isel(time=0)[0, 0]) == 100.0 * 19 + 8
    assert not np.isnan(z.values).any()
    # precipitation: no day-1 window in the files, mm -> m
    tp = wmc.assemble(_records("tp", range(2, 35)), lat, lon, init, "tp")
    assert list(tp["step_day"].values[:2]) == [2, 3]
    assert float(tp.sel(number=0, step_day=2).isel(time=0)[0, 0]) == pytest.approx(0.2)
    # a 6-h window would silently break the daily labelling
    with pytest.raises(ValueError):
        wmc.assemble([(0, 0, 6, np.zeros((5, 6)))], lat, lon, init, "msl")


def test_to_lattice_lands_exactly_on_the_domain_lattice_and_preserves_a_plane():
    lat = 90.0 - 1.25 * np.arange(145); lon = 1.25 * np.arange(288)
    init = pd.Timestamp("1991-01-16")
    # a linear field in lat and lon is reproduced exactly by bilinear interpolation
    plane = lat[:, None] * 2.0 + lon[None, :] * 0.5
    recs = [(m, 24 * (d - 1), 24 * d, plane) for m in range(wmc.N_MEMBERS) for d in (19, 20)]
    da = wmc.assemble(recs, lat, lon, init, "t850")
    out = wmc.to_lattice(da, DOMAIN)
    lat_t, lon_t = domain_lattice(DOMAIN)
    np.testing.assert_array_equal(out[LAT].values, lat_t)
    np.testing.assert_array_equal(out[LON].values, lon_t)
    expect = lat_t[:, None] * 2.0 + lon_t[None, :] * 0.5
    np.testing.assert_allclose(out.sel(number=3, step_day=20).isel(time=0).values, expect, rtol=0, atol=1e-4)


@pytest.mark.skipif(not os.environ.get("DOKAYUKI_WMC_SAMPLE"), reason="set DOKAYUKI_WMC_SAMPLE to a downloaded z500 file")
def test_real_file_decodes_to_13_members_and_34_days():
    pytest.importorskip("eccodes")
    path = Path(os.environ["DOKAYUKI_WMC_SAMPLE"])
    da = wmc.open_wmc_daily(path, "z500", pd.Timestamp("1991-01-16"))
    assert da.shape[:3] == (13, 1, 34)
    assert not np.isnan(da.values).any()
    assert 4500 < float(da.mean()) < 6000
