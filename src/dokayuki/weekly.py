"""Weekly aggregation and issuance / lead / target bookkeeping (UTC, leads from init)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr

DAYS_PER_YEAR = 365.242199  # the reference repo's year length for the day-of-year arithmetic


def forecast_delta(lead: int) -> int:
    """Days from init to the start of the target week (lead 19 -> 18, lead 26 -> 25)."""
    return int(lead) - 1


def target_start(init: pd.Timestamp | np.ndarray, lead: int):
    return init + pd.Timedelta(days=forecast_delta(lead))


def init_for_target(target: pd.Timestamp, lead: int) -> pd.Timestamp:
    return target - pd.Timedelta(days=forecast_delta(lead))


def weekly_from_daily(daily: xr.DataArray, how: str = "mean", days: int = 7) -> xr.DataArray:
    """Weekly value labelled by the week's **start** date, for every daily start.

    ``how`` is "mean" (temperature, pressure, height) or "sum" (precipitation, snowfall).
    The last ``days-1`` labels are NaN (incomplete weeks) and dropped.
    """
    if how == "mean":
        r = daily.rolling(time=days, center=False).mean()
    elif how == "sum":
        r = daily.rolling(time=days, center=False).sum()
    else:
        raise ValueError(how)
    out = r.shift(time=-(days - 1))
    return out.isel(time=slice(0, out.sizes["time"] - (days - 1)))


def weekly_from_member_steps(da: xr.DataArray, lead: int, how: str = "mean", step_dim: str = "step") -> xr.DataArray:
    """Weekly value for ``lead`` from daily forecast steps.

    ``da`` has a ``step`` dimension of integer day offsets from init (day 1 = init + 0 days,
    i.e. step d is the day starting at init + (d-1) days, so that lead 19 covers steps 19..25).
    For accumulated fields (precip) ``da`` must already be de-accumulated to daily amounts.
    """
    steps = list(range(lead, lead + 7))
    sel = da.sel({step_dim: steps})
    return sel.mean(step_dim) if how == "mean" else sel.sum(step_dim)


def delta_features(target: pd.Timestamp, times: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(delta, dividend, remainder) as in the reference repo: delta in days from ``times`` to ``target``."""
    delta = (target - times).days.values.astype("float64")
    dividend = np.floor(delta / DAYS_PER_YEAR)
    remainder = np.floor(delta % DAYS_PER_YEAR)
    return delta, dividend, remainder


def training_mask(target: pd.Timestamp, times: pd.DatetimeIndex, gt_delta: int,
                  margin_in_days: int | None, years: int | None,
                  issue: np.ndarray | None = None, forecast_delta_days: int | None = None) -> np.ndarray:
    """Boolean mask of ``times`` usable to train for ``target`` under the reference rules.

    If ``issue`` (the model issuance date of each row) and ``forecast_delta_days`` are given,
    rows whose model run was issued after the target's init date are excluded as well
    (causal issuance; the reference repo does not apply this).
    """
    delta, dividend, remainder = delta_features(target, times)
    indic = np.asarray(times <= target - pd.Timedelta(days=gt_delta))
    if issue is not None and forecast_delta_days is not None:
        init = np.datetime64(target - pd.Timedelta(days=forecast_delta_days))
        indic &= np.asarray(issue) <= init
    if margin_in_days is not None:
        indic &= (remainder <= margin_in_days) | (remainder >= 365 - margin_in_days)
    if years is not None:
        indic &= dividend < years
    return indic


def shift_years(dates: pd.DatetimeIndex, years: int) -> pd.DatetimeIndex:
    """Shift dates by whole years, Feb 29 -> Feb 28 (relativedelta semantics)."""
    out = []
    for d in dates:
        try:
            out.append(d.replace(year=d.year + years))
        except ValueError:
            out.append(d.replace(year=d.year + years, day=28))
    return pd.DatetimeIndex(out)


def season_of(t: pd.Timestamp) -> str:
    """Winter label like '2016/17' for any date in Jul(2016)..Jun(2017)."""
    y = t.year if t.month >= 7 else t.year - 1
    return f"{y}/{str(y + 1)[-2:]}"
