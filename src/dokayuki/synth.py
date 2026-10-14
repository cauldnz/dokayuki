"""Synthetic fixtures with realistic shapes, an injected known bias and a known signal.

Truth: seasonal cycle + AR(1) weekly anomalies. Forecast members: truth anomaly scaled by a
skill factor + bias (constant plus seasonal) + member noise. Both scalar indices and a small
1.5-degree grid are produced on the ``target`` dimension.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import xarray as xr

from .thresholds import TIME
from .weekly import forecast_delta, weekly_from_daily


@dataclass
class SynthSpec:
    start: str = "1996-01-01"
    end: str = "2025-12-31"
    n_targets: int = 3
    bias: float = 1.0                 # units of anomaly std
    seasonal_bias: float = 0.5
    skill: float = 0.4                # correlation-ish between member mean and truth anomaly
    member_noise: float = 1.0
    n_members_fc: int = 11
    n_members_rf: int = 11
    issue_weekdays: tuple = (0, 3)    # Mon/Thu
    first_forecast_year: int = 2015
    hindcast_years: int = 20
    seed: int = 0


def make_truth_daily(spec: SynthSpec) -> xr.DataArray:
    rng = np.random.default_rng(spec.seed)
    t = pd.date_range(spec.start, spec.end, freq="D")
    doy = t.dayofyear.values
    n = len(t)
    anom = np.zeros((n, spec.n_targets))
    e = rng.standard_normal((n, spec.n_targets))
    phi = 0.8
    for i in range(1, n):
        anom[i] = phi * anom[i - 1] + np.sqrt(1 - phi**2) * e[i]
    cycle = 10 * np.cos(2 * np.pi * (doy - 15) / 365.25)[:, None] * np.linspace(0.5, 1.5, spec.n_targets)[None, :]
    y = cycle + 3.0 * anom
    return xr.DataArray(y, dims=(TIME, "target"), coords={TIME: t, "target": [f"idx{i}" for i in range(spec.n_targets)]}, name="y")


def make_truth_weekly(spec: SynthSpec) -> xr.DataArray:
    return weekly_from_daily(make_truth_daily(spec), "mean")


def _members_for(truth_weekly: xr.DataArray, times: pd.DatetimeIndex, spec: SynthSpec, n_members: int,
                 rng: np.random.Generator, bias_scale: float = 1.0) -> np.ndarray:
    """Member weekly values for target starts ``times``: (time, member, target)."""
    y = truth_weekly.reindex({TIME: times}).values   # (time, target)
    clim = 10 * np.cos(2 * np.pi * (times.dayofyear.values - 15) / 365.25)[:, None] * np.linspace(0.5, 1.5, spec.n_targets)[None, :]
    anom = (y - clim) / 3.0
    seasonal = spec.seasonal_bias * np.sin(2 * np.pi * times.dayofyear.values / 365.25)[:, None]
    mean = clim + 3.0 * (spec.skill * anom + bias_scale * (spec.bias + seasonal))
    noise = rng.standard_normal((len(times), n_members, spec.n_targets)) * 3.0 * spec.member_noise
    return mean[:, None, :] + noise


def make_forecasts(truth_weekly: xr.DataArray, spec: SynthSpec, lead: int) -> tuple[xr.DataArray, xr.DataArray]:
    """Real-time forecasts (issue, member, target) and on-the-fly reforecasts (issue, hyear, member, target)."""
    rng = np.random.default_rng(spec.seed + lead)
    all_days = pd.date_range(f"{spec.first_forecast_year}-01-01", spec.end, freq="D")
    issues = all_days[all_days.weekday.isin(spec.issue_weekdays)]
    tgt = issues + pd.Timedelta(days=forecast_delta(lead))
    last_truth = truth_weekly.get_index(TIME)[-1]
    issues, tgt = issues[tgt <= last_truth], tgt[tgt <= last_truth]
    fc = _members_for(truth_weekly, tgt, spec, spec.n_members_fc, rng)
    fc_da = xr.DataArray(fc, dims=("issue", "member", "target"),
                         coords={"issue": issues, "member": np.arange(spec.n_members_fc), "target": truth_weekly["target"]})
    hy = np.arange(-spec.hindcast_years, 0)
    rf = np.full((len(issues), len(hy), spec.n_members_rf, spec.n_targets), np.nan)
    for j, d in enumerate(hy):
        hind_tgt = pd.DatetimeIndex([t.replace(year=t.year + int(d)) if not (t.month == 2 and t.day == 29) else t.replace(year=t.year + int(d), day=28) for t in tgt])
        ok = hind_tgt >= truth_weekly.get_index(TIME)[0]
        if ok.any():
            rf[ok, j] = _members_for(truth_weekly, hind_tgt[ok], spec, spec.n_members_rf, rng)
    rf_da = xr.DataArray(rf, dims=("issue", "hyear", "member", "target"),
                         coords={"issue": issues, "hyear": hy, "member": np.arange(spec.n_members_rf), "target": truth_weekly["target"]})
    return fc_da, rf_da
