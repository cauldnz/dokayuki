"""S2S database on the ECMWF Data Store (ECDS): ECMWF (``ecmwf``) and JMA (``jma``) fields.

Request shape (from the ECDS forms, probed 2026-10-14): collection ``s2s-forecasts`` /
``s2s-reforecasts`` with ``origin``, ``year``/``month``/``day`` (init date), ``time``,
``level_type`` (single_level | pressure), ``variable``, ``level_value``, ``forecast_type``
(control_forecast | perturbed_forecast), ``leadtime_hour`` (ranges like ``"432_456"`` for
accumulated/instantaneous 24-h steps or instants like ``"456"``), ``area`` [N, W, S, E],
``data_format`` grib. Reforecasts add ``hyear``/``hmonth``/``hday``.

Only the domain box, the needed variables and the steps for days 18..33 are requested.
Requests are resumable: submit, persist the request id, poll, download.

Credentials: ``ECDS_URL`` (default https://ecds.ecmwf.int/api) and ``ECDS_KEY``; the S2S
licence must be accepted on the ECDS profile page.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from ..config import Box

log = logging.getLogger(__name__)

VARIABLES = {
    # short -> (level_type, variable, level_value, kind)   kind: "instant" | "accum"
    "msl":  ("single_level", "mean_sea_level_pressure", None, "instant"),
    "t2m":  ("single_level", "2_m_temperature", None, "instant"),
    "tp":   ("single_level", "total_precipitation", None, "accum"),
    "sf":   ("single_level", "snow_fall_water_equivalent", None, "accum"),
    "sst":  ("single_level", "sea_surface_temperature", None, "instant"),
    "t850": ("pressure", "temperature", "850_hpa", "instant"),
    "z500": ("pressure", "geopotential_height", "500_hpa", "instant"),
    "u10hpa": ("pressure", "u_component_of_wind", "10_hpa", "instant"),
    "u850": ("pressure", "u_component_of_wind", "850_hpa", "instant"),
    "v850": ("pressure", "v_component_of_wind", "850_hpa", "instant"),
}
# fields each origin carries (from the ECDS constraints, 2026-10-14)
AVAILABLE = {
    "ecmwf": {"msl", "t2m", "tp", "sf", "sst", "t850", "z500", "u10hpa", "u850", "v850"},
    "jma":   {"msl", "t2m", "tp", "sst", "t850", "z500", "u10hpa", "u850", "v850"},   # no snowfall
}
LEAD_DAYS = (18, 33)   # covers week-3 (days 19-25) and week-4 (26-32) for leads 19 and 26


def leadtime_hours(kind: str, first_day: int = LEAD_DAYS[0], last_day: int = LEAD_DAYS[1]) -> list[str]:
    """Hour strings for daily values of forecast days first_day..last_day (day d = init + d-1).

    Instantaneous fields are taken at 00 UTC of each day (hour 24*(d-1)); accumulated fields as
    the 24-h window "a_b" ending at 00 UTC of the next day.
    """
    out = []
    for d in range(first_day, last_day + 1):
        h0 = 24 * (d - 1)
        out.append(f"{h0}_{h0 + 24}" if kind == "accum" else f"{h0}")
    return out


def _area(domain: Box) -> list[float]:
    return [domain.lat[1], domain.lon[0], domain.lat[0], domain.lon[1]]


def build_request(origin: str, init: pd.Timestamp, fields: list[str], domain: Box,
                  forecast_type: str, reforecast: bool = False, hyears: list[int] | None = None,
                  time: str = "00:00") -> list[dict]:
    """One request per level_type (ECDS forms require a single level_type per request)."""
    fields = [f for f in fields if f in AVAILABLE[origin]]
    by_type: dict[str, list[str]] = {}
    for f in fields:
        by_type.setdefault(VARIABLES[f][0], []).append(f)
    reqs = []
    for ltype, fs in by_type.items():
        kinds = {VARIABLES[f][3] for f in fs}
        for kind in sorted(kinds):
            sub = [f for f in fs if VARIABLES[f][3] == kind]
            req = {
                "origin": origin,
                "year": f"{init.year}", "month": f"{init.month:02d}", "day": f"{init.day:02d}",
                "time": time,
                "level_type": ltype,
                "variable": [VARIABLES[f][1] for f in sub],
                "forecast_type": forecast_type,
                "leadtime_hour": leadtime_hours(kind),
                "area": _area(domain),
                "data_format": "grib",
            }
            if ltype == "pressure":
                req["level_value"] = sorted({VARIABLES[f][2] for f in sub})
            if reforecast:
                req["hyear"] = [str(y) for y in (hyears or [])]
                req["hmonth"] = [f"{init.month:02d}"]
                req["hday"] = [f"{init.day:02d}"]
            reqs.append(req)
    return reqs


@dataclass
class RequestLog:
    """Persisted request ids so interrupted runs resume instead of resubmitting."""
    path: Path
    entries: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "RequestLog":
        if path.exists():
            return cls(path=path, entries=json.loads(path.read_text()))
        return cls(path=path)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.entries, indent=1, default=str))

    def key(self, collection: str, req: dict) -> str:
        return collection + ":" + json.dumps(req, sort_keys=True)


def ecds_client():
    from ecmwf.datastores import Client
    url = os.environ.get("ECDS_URL", "https://ecds.ecmwf.int/api")
    key = os.environ.get("ECDS_KEY")
    if not key:
        raise RuntimeError("ECDS_KEY not set (and the S2S licence must be accepted on ECDS)")
    return Client(url=url, key=key, progress=False)


def fetch(collection: str, req: dict, target: Path, reqlog: RequestLog, client=None,
          budget_s: float = 1800.0, poll_s: float = 20.0) -> Path | None:
    """Submit (or resume) a request, poll within ``budget_s``, download to ``target``.

    Returns the path when the file is ready, else None (request stays logged for next time).
    """
    if target.exists() and target.stat().st_size > 0:
        return target
    client = client or ecds_client()
    key = reqlog.key(collection, req)
    rid = reqlog.entries.get(key)
    remote = None
    if rid:
        try:
            remote = client.get_remote(rid)
        except Exception as e:  # noqa: BLE001
            log.warning("stale request id %s: %s", rid, e)
    if remote is None:
        remote = client.submit(collection, req)
        reqlog.entries[key] = remote.request_id
        reqlog.save()
        log.info("submitted %s -> %s", collection, remote.request_id)
    t0 = time.time()
    while time.time() - t0 < budget_s:
        status = remote.status
        if status in ("successful", "succeeded"):
            target.parent.mkdir(parents=True, exist_ok=True)
            remote.download(str(target))
            return target
        if status in ("failed", "rejected", "dismissed"):
            log.error("request %s %s: %s", remote.request_id, status, getattr(remote, "error", ""))
            reqlog.entries.pop(key, None)
            reqlog.save()
            return None
        time.sleep(poll_s)
    log.warning("budget exhausted waiting for %s (status %s); will resume next run", remote.request_id, remote.status)
    return None


# ----------------------------------------------------------------------------- GRIB -> daily member fields
def open_grib_daily(path: Path, kind_by_short: dict[str, str] | None = None) -> xr.Dataset:
    """Open an S2S GRIB with cfgrib and return daily fields on (number, step_day, lat, lon).

    Instantaneous fields: value at 00 UTC of day d is labelled step_day = d (d = hours/24 + 1).
    Accumulated fields (tp, sf): the 24-h accumulation ending at hour h is labelled by the day
    it covers: step_day = h/24. De-accumulation is done on the "from start" totals.
    """
    import cfgrib  # noqa: WPS433
    dss = cfgrib.open_datasets(str(path), backend_kwargs={"indexpath": ""})
    out = {}
    for ds in dss:
        for v in ds.data_vars:
            da = ds[v]
            if "number" not in da.dims:
                da = da.expand_dims(number=[int(da.coords.get("number", 0))])
            hours = (da["step"].values / np.timedelta64(1, "h")).astype(int)
            attrs = da.attrs
            step_type = attrs.get("GRIB_stepType", "instant")
            if step_type == "accum":
                # cumulative from init -> daily increments; label by the day ending at that hour
                vals = da.transpose("number", "step", ...).values
                inc = np.diff(vals, axis=1, prepend=np.zeros_like(vals[:, :1]))
                day = (hours // 24).astype(int)
                da2 = xr.DataArray(inc, dims=("number", "step_day") + tuple(da.dims[2:]),
                                   coords={"number": da["number"], "step_day": day, **{d: da[d] for d in da.dims[2:]}})
            else:
                day = (hours // 24 + 1).astype(int)
                da2 = da.transpose("number", "step", ...).rename({"step": "step_day"}).assign_coords(step_day=day)
            out[v] = da2
    return xr.Dataset(out)
