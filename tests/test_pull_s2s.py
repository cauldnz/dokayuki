"""The S2S pull's job layout and piece joining (no network)."""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import xarray as xr
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from pull_s2s import hyear_chunks, join_pieces  # noqa: E402


def test_hyear_chunks_cover_every_year_once_in_tens():
    chunks = hyear_chunks(list(range(2003, 2023)))
    assert [c for c, _ in chunks] == [list(range(2003, 2013)), list(range(2013, 2023))]
    assert [s for _, s in chunks] == ["_h2003-2012", "_h2013-2022"]
    assert hyear_chunks(list(range(1991, 2021)))[-1] == (list(range(2011, 2021)), "_h2011-2020")
    assert hyear_chunks(None) == [(None, "")]


def _piece(numbers, times):
    return xr.DataArray(np.random.rand(len(numbers), len(times)), dims=("number", "time"),
                        coords={"number": numbers, "time": pd.to_datetime(times)})


def test_join_pieces_members_on_number_and_chunks_on_time():
    t1 = ["2003-01-02", "2004-01-02"]; t2 = ["2013-01-02", "2014-01-02"]
    cont1, pert1 = _piece([0], t1), _piece([1, 2], t1)
    both2 = _piece([0, 1, 2], t2)
    out = join_pieces([pert1, both2, cont1])
    assert list(out["number"].values) == [0, 1, 2]
    assert [str(t)[:10] for t in out["time"].values] == t1 + t2
    xr.testing.assert_equal(out.sel(number=0, time=t1[0]), cont1.sel(number=0, time=t1[0]))
    xr.testing.assert_equal(out.sel(number=2, time=t2[1]), both2.sel(number=2, time=t2[1]))
    assert join_pieces([cont1]) is cont1
