import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dokayuki.cdf import combine_forecast_reforecast, forecast_to_time, members_to_cdf, reforecast_to_time  # noqa: E402
from dokayuki.synth import SynthSpec, make_forecasts, make_truth_weekly  # noqa: E402
from dokayuki.thresholds import indicators, observed_thresholds  # noqa: E402

LEAD = 19
GT_DELTA = 18 + 9   # reference measurement lag (parity); operational default is 10
K = 5


@pytest.fixture(scope="session")
def synth():
    spec = SynthSpec(start="1980-01-01", end="2021-12-31", n_targets=3, first_forecast_year=2015, seed=1)
    truth = make_truth_weekly(spec)
    fc, rf = make_forecasts(truth, spec, LEAD)
    thr = observed_thresholds(truth, K)
    O = indicators(truth, thr)
    fct = forecast_to_time(fc, LEAD)
    rft = reforecast_to_time(rf, LEAD)
    allm = combine_forecast_reforecast(fct, rft, reforecast_keep="first")
    F = members_to_cdf(allm, thr)
    targets = pd.DatetimeIndex([t for t in fct.time.values if pd.Timestamp(t).year >= 2019])
    return dict(spec=spec, truth=truth, fc=fc, rf=rf, thr=thr, O=O, F=F, targets=targets, fct=fct, rft=rft)
