"""Line-faithful ports of the reference repo's core steps (mouatadid/pbc, MIT), used only by
the parity test. Variable names and operations follow the originals:

- Debias++:   src/models/ecmwfpp/batch_predict.py
- Tuner:      src/models/tuner/batch_predict.py + tuner/util.py::get_tuning_dates
- Persist++:  src/models/perpp_ecmwf/batch_predict.py (lld_data, rolling clim, fit_and_predict)
- Projector:  src/models/projector/batch_predict.py
- ERA5 thresholds: src/data/datasets/era5-percentiles.py::compute_20yr_avg

The reference pipeline itself cannot run here (it needs its IRI/CDS data layout and the
``aiwqd`` conda environment), so these ports take the same in-memory arrays.
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd
import xarray as xr
from dateutil.relativedelta import relativedelta
from sklearn.isotonic import isotonic_regression

DAYS_PER_YEAR = 365.242199


# ----------------------------------------------------------------------------- reforecast placement
def ref_reforecast_to_time(rf_cdf: xr.DataArray, ecmwf_delta: int, keep: str) -> xr.DataArray:
    """rf_cdf dims (issuance_date, year_delta, latitude, longitude) -> time axis (reference)."""
    reforecast_data = rf_cdf.stack(time=("issuance_date", "year_delta"))
    index = reforecast_data.get_index("time")
    model_issuance_dates = index.get_level_values(0)
    start_years = index.get_level_values(1)
    start_dates = pd.to_datetime({
        "year": model_issuance_dates.year + start_years,
        "month": model_issuance_dates.month,
        "day": model_issuance_dates.day,
    }) + timedelta(days=ecmwf_delta)
    reforecast_data = reforecast_data.drop_vars(["time", "issuance_date", "year_delta"])
    reforecast_data = reforecast_data.assign_coords(time=start_dates.values)
    reforecast_data = reforecast_data.dropna(dim="time", how="all")
    reforecast_data = reforecast_data.drop_duplicates("time", keep=keep)
    return reforecast_data.sortby("time")


def ref_forecast_to_time(fc_cdf: xr.DataArray, ecmwf_delta: int) -> xr.DataArray:
    forecast_data = fc_cdf.rename({"issuance_date": "time"})
    forecast_data = forecast_data.dropna(dim="time", how="all")
    return forecast_data.assign_coords(time=forecast_data.time + pd.Timedelta(days=ecmwf_delta))


# ----------------------------------------------------------------------------- Debias++ (ecmwfpp)
def ref_debiaspp(fc_cdf: xr.DataArray, rf_cdf: xr.DataArray, gt: xr.DataArray, target_dates,
                 ecmwf_delta: int, start_delta_days: int, margin_in_days, years, fit_intercept=True):
    """Returns dict target_date -> DataArray(latitude, longitude) of clipped predictions."""
    reforecast_data = ref_reforecast_to_time(rf_cdf, ecmwf_delta, keep="first")
    forecast_data = ref_forecast_to_time(fc_cdf, ecmwf_delta)
    target_date_objs = pd.DatetimeIndex(target_dates)
    forecast_targets = forecast_data.get_index("time").intersection(target_date_objs)
    preds = forecast_data.sel(time=forecast_targets).sortby("time")
    first_forecast_target = forecast_targets.min()
    reforecast_targets = reforecast_data.get_index("time").intersection(target_date_objs)
    if not forecast_targets.empty:
        reforecast_targets = reforecast_targets[reforecast_targets < first_forecast_target]
    preds = xr.concat([reforecast_data.sel(time=reforecast_targets), preds], dim="time").sortby("time")
    all_data = xr.concat([reforecast_data, forecast_data], dim="time")
    all_data = all_data.drop_duplicates(dim="time", keep="last")
    all_data = all_data.sortby("time")
    gt_times = all_data.get_index("time").intersection(gt.get_index("time"))
    gt_ds = gt.sel(time=gt_times).load()
    debias_data = gt_ds - all_data
    start_delta = timedelta(days=start_delta_days)
    valid_targets = forecast_targets.union(reforecast_targets)
    X = pd.DataFrame(index=debias_data.time.values, columns=["delta", "dividend", "remainder"], dtype=np.float64)
    out = {}
    for target_date_obj in sorted(valid_targets):
        X["delta"] = (target_date_obj - pd.to_datetime(debias_data.time.values)).days
        X["dividend"] = np.floor(X.delta / DAYS_PER_YEAR)
        X["remainder"] = np.floor(X.delta % DAYS_PER_YEAR)
        last_train_date = target_date_obj - start_delta
        indic = (X.index <= last_train_date)
        if margin_in_days is not None:
            indic &= ((X.remainder <= margin_in_days) | (X.remainder >= 365 - margin_in_days))
        if years != "all":
            indic = indic & (X.dividend < years)
        pred = preds.sel(time=[target_date_obj])
        if fit_intercept:
            if not indic.any():
                continue
            pred = pred + debias_data.isel(time=indic).mean(dim="time")
        pred = pred.clip(min=0, max=1)
        out[target_date_obj] = pred.squeeze("time", drop=True)
    return out


# ----------------------------------------------------------------------------- tuner
def ref_tuner_select(metric_df: pd.DataFrame, target_date_obj, start_delta_days: int, num_years, margin_in_days):
    """metric_df: index = dates, columns = submodel names, values = wtd_mse. Returns chosen column."""
    X = pd.DataFrame(index=metric_df.index, columns=["delta", "dividend", "remainder"], dtype=np.float64)
    start_delta = timedelta(days=start_delta_days)
    last_train_date = target_date_obj - start_delta
    X["delta"] = (target_date_obj - X.index).days
    X["remainder"] = np.floor(X.delta % DAYS_PER_YEAR)
    indic = (X.index <= last_train_date)
    if margin_in_days is not None:
        indic &= ((X.remainder <= margin_in_days) | (X.remainder >= 365 - margin_in_days))
    if num_years != "all":
        X["dividend"] = np.floor(X.delta / DAYS_PER_YEAR)
        indic &= (X.dividend < num_years)
    if not indic.any():
        return None
    return metric_df[indic].mean().idxmin()


# ----------------------------------------------------------------------------- Persistence++
def ref_rolling_clim(gt_ds: xr.Dataset, measurement_variable: str, clim_col: str, fill_value: float,
                     clim_years=20, clim_margin=4) -> xr.Dataset:
    time_index = gt_ds.time.get_index("time")
    first_time = time_index[0]
    first_time = first_time.replace(year=first_time.year - (clim_years - 1), day=1, month=1)
    last_time = time_index[-1]
    new_time_index = pd.date_range(start=first_time, end=last_time, freq="D")
    rolling_clim = gt_ds.reindex(time=new_time_index, fill_value=fill_value)
    rolling_clim = rolling_clim.sel(time=~((rolling_clim.time.dt.month == 2) & (rolling_clim.time.dt.day == 29)))

    def groupby_rolling(sub_ds, periods=clim_years, min_periods=clim_years):
        return sub_ds.rolling(time=periods, min_periods=min_periods, center=False).mean()

    month_day_str = rolling_clim.time.dt.strftime("%m-%d")
    rolling_clim = rolling_clim.groupby(month_day_str).map(groupby_rolling).dropna("time", how="all")
    rolling_clim["time"] = rolling_clim.time.get_index("time").shift(freq=pd.DateOffset(years=1))
    rolling_clim = rolling_clim.rolling(time=2 * clim_margin + 1, center=True).mean().dropna("time", how="all")
    return rolling_clim.rename({measurement_variable: clim_col})


def ref_fit_and_predict(df, gt_col, x_cols, target_dates, gt_delta):
    last_stored_date = target_dates[0] - gt_delta
    t = df.index.get_level_values("time")
    date_block = (t <= last_stored_date)
    train_data = df[date_block]
    n_train = len(train_data)
    if n_train > 0:
        X_train = train_data[x_cols].values
        y_val = train_data[gt_col].values
        XtX = X_train.T @ X_train
        Xty = X_train.T @ y_val
    else:
        n_features = len(x_cols)
        XtX = np.zeros((n_features, n_features))
        Xty = np.zeros(n_features)
    all_predictions = []
    for target_date in target_dates:
        last_train_date = target_date - gt_delta
        date_block = ((t <= last_train_date) & (t > last_stored_date))
        new_data = df[date_block]
        last_stored_date = last_train_date
        n_train += len(new_data)
        if len(new_data) > 0:
            X_train = new_data[x_cols].values
            y_val = new_data[gt_col].values
            XtX += X_train.T @ X_train
            Xty += X_train.T @ y_val
        if n_train > 0:
            try:
                coef = np.linalg.solve(XtX, Xty)
            except np.linalg.LinAlgError:
                coef = np.linalg.lstsq(XtX, Xty)[0]
            X_test = df.loc[t == target_date, x_cols]
            if len(X_test) == 0:
                continue
            pred_df = pd.DataFrame({gt_col: [np.dot(X_test.values[0], coef)]}, index=X_test.index)
            all_predictions.append(pred_df)
    return pd.concat(all_predictions, ignore_index=False)


def ref_persistpp(fc_cdf: xr.DataArray, rf_cdf: xr.DataArray, gt: xr.DataArray, target_dates,
                  ecmwf_delta: int, gt_delta_days: int, horizon: int, fill_value: float,
                  clim_years=20, clim_margin=4):
    """Returns DataFrame indexed by (latitude, longitude, time) with clipped predictions."""
    measurement_variable = "fk_mslp"
    gt_col = measurement_variable
    clim_col = measurement_variable + "_clim"
    ecmwf_col = f"iri_ecmwf_{measurement_variable}"
    gt_delta = timedelta(days=gt_delta_days)
    first_shift = int(gt_delta.days)
    x_cols = [f"{measurement_variable}_shift{first_shift}",
              f"{measurement_variable}_shift{first_shift + int(horizon) - 1}",
              ecmwf_col, clim_col, "ones"]
    exclude_cols = set([clim_col, ecmwf_col])
    gt_ds = gt.to_dataset(name=measurement_variable).load()
    gt_times = gt_ds.time.get_index("time")
    lld_data = gt_ds
    for shift in [first_shift, first_shift + int(horizon) - 1]:
        gt_shift = gt_ds.rename({measurement_variable: f"{measurement_variable}_shift{shift}"})
        gt_shift["time"] = gt_times.shift(freq=f"{shift}D")
        lld_data = xr.merge([lld_data, gt_shift], join="right")
    rolling_clim = ref_rolling_clim(gt_ds, measurement_variable, clim_col, fill_value, clim_years, clim_margin)
    lld_data = xr.merge([lld_data, rolling_clim], join="right")
    lld_data.update({"ones": xr.ones_like(lld_data[measurement_variable])})
    lld_data = lld_data.sortby("time").to_dataframe()
    lld_data = lld_data.dropna(subset=set(x_cols) - exclude_cols)
    lld_data = lld_data.reorder_levels(["latitude", "longitude", "time"])
    # ECMWF features (single lead)
    reforecast_data = ref_reforecast_to_time(rf_cdf, ecmwf_delta, keep="last")
    reforecast_coords = list(reforecast_data.coords)
    reforecast_series = reforecast_data.rename(ecmwf_col).to_series().dropna()
    forecast_data = fc_cdf.rename({"issuance_date": "time"})
    forecast_data = forecast_data.assign_coords(time=forecast_data.get_index("time").shift(freq=f"{ecmwf_delta}D"))
    forecast_data = forecast_data.transpose(*[c for c in reforecast_coords if c in forecast_data.dims])
    forecast_series = forecast_data.rename(ecmwf_col).to_series().dropna()
    forecast_series = forecast_series.reorder_levels(reforecast_series.index.names)
    ecmwf = pd.concat([forecast_series, reforecast_series])
    ecmwf = ecmwf.loc[~ecmwf.index.duplicated(keep="first")]
    ecmwf.sort_index(inplace=True)
    lld_data = lld_data.join(ecmwf, how="inner").sort_index()
    relevant_cols = list(set([gt_col] + x_cols).intersection(lld_data.columns))
    lld_data = lld_data[relevant_cols].dropna(subset=x_cols)
    sorted_targets = sorted(pd.DatetimeIndex(target_dates))
    dates_with_features = lld_data[x_cols].index.unique(level="time")
    targets_to_process = [t for t in sorted_targets if t in dates_with_features]
    preds = []
    for name, group in lld_data.groupby(["latitude", "longitude"]):
        preds.append(ref_fit_and_predict(group, gt_col, x_cols, targets_to_process, gt_delta))
    all_preds = pd.concat(preds).clip(0, 1)
    return all_preds


# ----------------------------------------------------------------------------- projector
def ref_project(f_preds: list[np.ndarray]) -> np.ndarray:
    f_projs = np.clip(np.stack(f_preds, axis=0), 0, 1)
    for i in range(f_projs.shape[1]):
        for j in range(f_projs.shape[2]):
            preds = f_projs[:, i, j]
            if np.any(np.isnan(preds)):
                continue
            if np.any(preds[:-1] > preds[1:]):
                f_projs[:, i, j] = isotonic_regression(preds, y_min=0, y_max=1, increasing=True)
    return f_projs


# ----------------------------------------------------------------------------- ERA5 thresholds
def ref_percentile_for_date(weekly_means: xr.DataArray, date, q: float, date_window=(-4, -2, 0, 2, 4)):
    clim_data = []
    for year_change in np.arange(-20, 0):
        for day_change in date_window:
            new_date = date + relativedelta(years=int(year_change)) + relativedelta(days=float(day_change))
            clim_data.append(weekly_means.sel(time=new_date))
    full_clim_set = xr.concat(clim_data, dim="time")
    return full_clim_set.quantile(q=[q], dim="time")
