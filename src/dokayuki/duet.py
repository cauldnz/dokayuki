"""Duet: combine two PBC systems (ECMWF, JMA) per target and lead.

Reference Duet is the equal mean. Here we choose per target among {equal, A only, B only} by
the RPS on a validation year that precedes the test period (strictly causal: the validation
year is held out before the first test date, and the choice is frozen for the test period).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import xarray as xr

from .project import project_cdf
from .score import rps
from .thresholds import K_DIM, TIME

MODES = ("equal", "a", "b")


@dataclass
class DuetResult:
    pred: xr.DataArray
    mode: xr.DataArray          # (target,) chosen mode name
    val_rps: xr.DataArray       # (mode, target)


def combine(a: xr.DataArray, b: xr.DataArray, mode: str) -> xr.DataArray:
    if mode == "a":
        return a
    if mode == "b":
        return b
    aa, bb = xr.align(a, b, join="inner")
    return project_cdf((aa + bb) / 2.0)


def duet(a: xr.DataArray, b: xr.DataArray, O: xr.DataArray, validation: tuple[pd.Timestamp, pd.Timestamp],
         test_start: pd.Timestamp, modes=MODES) -> DuetResult:
    """``validation`` = (start, end) inclusive, must end before ``test_start``."""
    v0, v1 = pd.Timestamp(validation[0]), pd.Timestamp(validation[1])
    if v1 >= pd.Timestamp(test_start):
        raise ValueError("validation period must precede the test period")
    a = a.transpose(TIME, K_DIM, ...)
    b = b.reindex_like(a)
    Ov = O.reindex_like(a)
    scores = []
    for m in modes:
        c = combine(a, b, m)
        sel = (c[TIME] >= v0) & (c[TIME] <= v1)
        r = rps(c.sel({TIME: sel}), Ov.sel({TIME: sel})).mean(TIME, skipna=True)
        scores.append(r)
    S = xr.concat(scores, dim="mode").assign_coords(mode=list(modes))
    best_idx = S.fillna(np.inf).argmin("mode")
    best = S["mode"].values[best_idx.values]
    out = xr.zeros_like(a)
    for m in modes:
        sel = best == m
        if not sel.any():
            continue
        c = combine(a, b, m)
        out = xr.where(xr.DataArray(sel, dims=a.dims[2:], coords={d: a[d] for d in a.dims[2:]}), c, out)
    mode_da = xr.DataArray(best, dims=a.dims[2:], coords={d: a[d] for d in a.dims[2:]})
    return DuetResult(pred=out.rename("duet"), mode=mode_da, val_rps=S)
