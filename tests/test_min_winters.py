"""A lift over too few winters is never significant; empty inputs do not crash."""
import numpy as np
import pandas as pd
from dokayuki.score import MIN_BLOCKS, block_bootstrap_ci, lift
from dokayuki.site.schema import lift_badge


def _series(winters, val, seed):
    rng = np.random.default_rng(seed)
    idx = pd.DatetimeIndex([pd.Timestamp(f"{y}-12-01") + pd.Timedelta(days=7 * i) for y in winters for i in range(13)])
    return pd.Series(val + 0.01 * rng.standard_normal(len(idx)), index=idx)


def test_two_winters_is_insufficient_even_with_a_clear_gap():
    m, r, c = _series([2017, 2018], 0.5, 1), _series([2017, 2018], 0.8, 2), _series([2017, 2018], 1.0, 3)
    out = lift(m, r, c, n_boot=200)
    assert out["n_blocks"] == 2 and out["insufficient_blocks"] and not out["significant"]
    assert out["ci"][0] > 0   # the interval alone would have called it
    assert "Too few winters" in lift_badge(out) and str(MIN_BLOCKS) in lift_badge(out)


def test_enough_winters_can_be_significant():
    ys = list(range(2010, 2010 + MIN_BLOCKS))
    out = lift(_series(ys, 0.5, 1), _series(ys, 0.8, 2), _series(ys, 1.0, 3), n_boot=200)
    assert out["n_blocks"] == MIN_BLOCKS and not out["insufficient_blocks"] and out["significant"]
    assert lift_badge(out).startswith("Lift over debiased model")


def test_empty_inputs_do_not_crash():
    nan = pd.Series(np.nan, index=_series([2017], 0.0, 0).index)
    out = lift(nan, nan, nan, n_boot=10)
    assert out["n_blocks"] == 0 and not out["significant"] and np.isnan(out["lift"])
    assert all(np.isnan(v) for v in block_bootstrap_ci(nan, nan, n_boot=10))
