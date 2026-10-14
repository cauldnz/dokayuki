"""Observed conditioning predictors: AO (NOAA CPC) and MJO RMM (BoM, IRI mirror fallback).

Sources, licences, lags (also in docs/DATA_NOTES.md):
- AO: https://ftp.cpc.ncep.noaa.gov/cwlinks/norm.daily.ao.cdas.z1000.19500101_current.csv
  (NOAA CPC, US public domain, ~1 day lag). Columns year,month,day,ao_index_cdas.
- MJO RMM: https://www.bom.gov.au/clim_data/IDCKGEM000/rmm.74toRealtime.txt
  (the old /climate/mjo/graphics/ path stopped updating in Feb 2024). Needs a browser User-Agent.
  Fallback: IRI Data Library mirror SOURCES/.BoM/.MJO/.RMM. Columns year month day RMM1 RMM2 phase amplitude.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import requests

log = logging.getLogger(__name__)

AO_URL = "https://ftp.cpc.ncep.noaa.gov/cwlinks/norm.daily.ao.cdas.z1000.19500101_current.csv"
RMM_URL = "https://www.bom.gov.au/clim_data/IDCKGEM000/rmm.74toRealtime.txt"
RMM_URL_LEGACY = "http://www.bom.gov.au/climate/mjo/graphics/rmm.74toRealtime.txt"
RMM_IRI_URL = ("https://iridl.ldeo.columbia.edu/SOURCES/.BoM/.MJO/.RMM/"
               ".RMM1/.RMM2/.phase/.amplitude/T/(1%20Jun%201974)/last/RANGE/"
               "%5BRMM1%20RMM2%20phase%20amplitude%5D%5BT%5Dtable:/T/toS/data.tsv")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36 dokayuki"
MISSING = 1.0e35


def _get(url: str, timeout: int = 60) -> str:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
    r.raise_for_status()
    return r.text


def parse_ao(text: str) -> pd.Series:
    df = pd.read_csv(io.StringIO(text))
    t = pd.to_datetime(df[["year", "month", "day"]])
    s = pd.Series(df["ao_index_cdas"].astype(float).values, index=t, name="ao")
    return s[~s.index.duplicated()].sort_index()


def parse_rmm(text: str) -> pd.DataFrame:
    rows = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 7:
            continue
        try:
            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
            r1, r2, ph, amp = float(parts[3]), float(parts[4]), int(float(parts[5])), float(parts[6])
        except ValueError:
            continue
        rows.append((pd.Timestamp(y, m, d), r1, r2, ph, amp))
    df = pd.DataFrame(rows, columns=["time", "rmm1", "rmm2", "phase", "amplitude"]).set_index("time")
    bad = (df[["rmm1", "rmm2", "amplitude"]].abs() >= MISSING).any(axis=1) | (df["phase"] == 999)
    df.loc[bad, ["rmm1", "rmm2", "amplitude"]] = np.nan
    df.loc[bad, "phase"] = 0
    return df[~df.index.duplicated()].sort_index()


def fetch_ao(cache: Path | None = None) -> pd.Series:
    text = _get(AO_URL)
    s = parse_ao(text)
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        s.to_frame().to_parquet(cache)
    log.info("AO: %d days, last %s", len(s), s.index[-1].date())
    return s


def fetch_rmm(cache: Path | None = None) -> pd.DataFrame:
    last_err = None
    for url in (RMM_URL, RMM_URL_LEGACY):
        try:
            df = parse_rmm(_get(url))
            if len(df) and df.index[-1] >= pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(days=60):
                break
            log.warning("RMM from %s is stale (last %s)", url, df.index[-1].date() if len(df) else None)
        except Exception as e:  # noqa: BLE001
            last_err = e
            log.warning("RMM fetch failed from %s: %s", url, e)
    else:
        raise RuntimeError(f"no fresh RMM source reachable: {last_err}")
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(cache)
    log.info("RMM: %d days, last %s", len(df), df.index[-1].date())
    return df


def mjo_features(rmm: pd.DataFrame) -> pd.DataFrame:
    """Amplitude and the (cos, sin) of the phase angle, so the model sees a smooth phase."""
    ang = np.arctan2(rmm["rmm2"], rmm["rmm1"])
    return pd.DataFrame({"mjo_amp": rmm["amplitude"], "mjo_cos": np.cos(ang), "mjo_sin": np.sin(ang),
                         "mjo_phase": rmm["phase"]}, index=rmm.index)
