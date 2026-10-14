"""PBC = mean of the projected tuned Debias++ and projected Persistence++ CDFs, re-projected."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import xarray as xr

from .debiaspp import CANDIDATES, tune_debiaspp
from .persistpp import persistpp
from .project import project_cdf
from .thresholds import K_DIM, TIME


@dataclass
class PBCResult:
    pbc: xr.DataArray
    debiaspp: xr.DataArray
    persistpp: xr.DataArray
    choice: xr.DataArray


def pbc_from_components(debias: xr.DataArray, persist: xr.DataArray) -> xr.DataArray:
    d, p = xr.align(project_cdf(debias), project_cdf(persist), join="inner")
    return project_cdf(((d + p) / 2.0).rename("pbc"))


def run_pbc(F_obs: xr.DataArray, F_pp: xr.DataArray, O: xr.DataArray, targets: pd.DatetimeIndex,
            gt_delta: int, lead: int, K: int, candidates=CANDIDATES, years: int = 20,
            tune_years: int = 3, scope: str = "pooled", weights: xr.DataArray | None = None,
            causal_issuance: bool = True) -> PBCResult:
    """Full PBC for one (source, lead).

    ``F_obs``: model CDF against observed thresholds (Debias++ always uses this).
    ``F_pp``:  model CDF used by Persistence++ (observed thresholds for precipitation-like
               targets, model thresholds otherwise — pass the same array if you want one).
    """
    tuned = tune_debiaspp(F_obs, O, targets, gt_delta, candidates=candidates, years=years,
                          tune_years=tune_years, scope=scope, weights=weights,
                          causal_issuance=causal_issuance, lead=lead)
    pp = persistpp(F_pp, O, targets, gt_delta, lead, K, causal_issuance=causal_issuance)
    return PBCResult(pbc=pbc_from_components(tuned.pred, pp), debiaspp=tuned.pred, persistpp=pp,
                     choice=tuned.choice)
