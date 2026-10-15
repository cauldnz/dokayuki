"""S2S database on the ECMWF Data Store (ECDS): ECMWF (``ecmwf``) and JMA (``jma``) fields.

Request shape (from the ECDS forms, probed 2026-10-14): collection ``s2s-forecasts`` /
``s2s-reforecasts`` with ``origin``, ``year``/``month``/``day`` (init date), ``time``,
``level_type`` (single_level | pressure), ``variable``, ``level_value``, ``forecast_type``
(control_forecast | perturbed_forecast), ``leadtime_hour`` (ranges like ``"432_456"`` for
accumulated/instantaneous 24-h steps or instants like ``"456"``), ``area`` [N, W, S, E],
``data_format`` grib. Reforecasts add ``hyear``/``hmonth``/``hday``.

Only the domain box, the needed variables and the steps for days 18..33 are requested.
Requests are resumable: submit, persist the request id, poll, download.

Credentials: ``ECMWF_API_KEY`` (the same key serves CDS; ``ECDS_KEY`` still honoured) and the
public ``ECDS_URL`` (default https://ecds.ecmwf.int/api); the S2S
licence must be accepted on the ECDS profile page.
"""
from __future__ import annotations

import json
import threading
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
    # short -> (level_type, variable, level_value, kind)
    # kind: "instant" (value at an hour) | "accum" (total from the start) | "daily" (24-h mean, "a_b" ranges)
    "msl":  ("single_level", "mean_sea_level_pressure", None, "instant"),
    "t2m":  ("single_level", "2_m_temperature", None, "daily"),
    "tp":   ("single_level", "total_precipitation", None, "accum"),
    "sf":   ("single_level", "snow_fall_water_equivalent", None, "accum"),
    "sst":  ("single_level", "sea_surface_temperature", None, "daily"),
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

    Instantaneous fields are taken at 00 UTC of each day (hour 24*(d-1)). Accumulated fields on
    ECDS are totals from the start of the forecast at plain hours, so the daily amount for day d
    is acc(24*d) - acc(24*(d-1)): request 24*(first_day-1) .. 24*last_day and difference later.
    """
    if kind == "accum":
        return [f"{24 * d}" for d in range(first_day - 1, last_day + 1)]
    if kind == "daily":
        return [f"{24 * (d - 1)}_{24 * d}" for d in range(first_day, last_day + 1)]
    return [f"{24 * (d - 1)}" for d in range(first_day, last_day + 1)]


def _area(domain: Box) -> list[float]:
    return [domain.lat[1], domain.lon[0], domain.lat[0], domain.lon[1]]


def build_request(origin: str, init: pd.Timestamp, fields: list[str], domain: Box,
                  forecast_type: str | list[str], reforecast: bool = False, hyears: list[int] | None = None,
                  time: str = "00:00", days: list[int] | None = None, area: list[float] | None = None,
                  grid: list[str] | None = None) -> list[dict]:
    """One request per (level_type, kind). ECDS forms take one level_type per request; ``days``
    puts every init day of ``init``'s month into one request (the GRIB then carries a ``time``
    axis). For reforecasts ``hday`` mirrors ``day`` and ``hyear`` lists the hindcast years."""
    fields = [f for f in fields if f in AVAILABLE[origin]]
    days = days or [init.day]
    by_type: dict[tuple, list[str]] = {}
    for f in fields:
        by_type.setdefault((VARIABLES[f][0], VARIABLES[f][2]), []).append(f)
    reqs = []
    for (ltype, _lev), fs in by_type.items():
        kinds = {VARIABLES[f][3] for f in fs}
        for kind in sorted(kinds):
            sub = [f for f in fs if VARIABLES[f][3] == kind]
            req = {
                "origin": origin,
                "year": f"{init.year}", "month": f"{init.month:02d}", "day": [f"{d:02d}" for d in days],
                "time": time,
                "level_type": ltype,
                "variable": list(dict.fromkeys(VARIABLES[f][1] for f in sub)),
                "forecast_type": forecast_type,
                "leadtime_hour": leadtime_hours(kind),
                "area": area or _area(domain),
                "data_format": "grib",
            }
            if grid:
                req["grid"] = grid
            if ltype == "pressure":
                req["level_value"] = sorted({VARIABLES[f][2] for f in sub})
            if reforecast:
                req["hyear"] = [str(y) for y in (hyears or [])]
                req["hmonth"] = [f"{init.month:02d}"]
                req["hday"] = [f"{d:02d}" for d in days]
            reqs.append(req)
    return reqs


# Stage-1 (trigger) targets need fields outside the domain box: a coarse hemispheric MSLP for
# the AO projection, the Ural box for UBI and the 60N band for U10_60N. Each is a small request.
HEMI_PARTS = {
    "ao":   (["msl"],    [90.0, 0.0, 20.0, 360.0], ["3", "3"]),
    "ural": (["z500"],   [70.0, 40.0, 45.0, 80.0], None),
    "u10":  (["u10hpa"], [61.5, 0.0, 58.5, 360.0], None),
}


def hemi_requests(origin: str, init: pd.Timestamp, forecast_type, reforecast: bool = False,
                  hyears: list[int] | None = None, days: list[int] | None = None) -> list[tuple[str, dict]]:
    out = []
    for part, (fields, area, grid) in HEMI_PARTS.items():
        for req in build_request(origin, init, fields, None, forecast_type, reforecast, hyears, days=days, area=area, grid=grid):
            out.append((part, req))
    return out


@dataclass
class RequestLog:
    """Persisted request ids so interrupted runs resume instead of resubmitting. Thread-safe:
    several fetches may run at once (ECDS lets one user hold several requests in flight)."""
    path: Path
    entries: dict = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    @classmethod
    def load(cls, path: Path) -> "RequestLog":
        if path.exists():
            return cls(path=path, entries=json.loads(path.read_text()))
        return cls(path=path)

    def save(self) -> None:
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.entries, indent=1, default=str))
            tmp.replace(self.path)

    def get(self, key: str):
        with self.lock:
            return self.entries.get(key)

    def set(self, key: str, rid) -> None:
        with self.lock:
            self.entries[key] = rid
        self.save()

    def pop(self, key: str) -> None:
        with self.lock:
            self.entries.pop(key, None)
        self.save()

    def key(self, collection: str, req: dict) -> str:
        return collection + ":" + json.dumps(req, sort_keys=True)


def ecds_client():
    from ecmwf.datastores import Client
    url = os.environ.get("ECDS_URL", "https://ecds.ecmwf.int/api")
    key = os.environ.get("ECMWF_API_KEY") or os.environ.get("ECDS_KEY")
    if not key:
        raise RuntimeError("ECMWF_API_KEY not set (and the S2S licence must be accepted on ECDS)")
    logging.getLogger("ecmwf.datastores.processing").setLevel(logging.WARNING)
    logging.getLogger("multiurl.base").setLevel(logging.WARNING)
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
    rid = reqlog.get(key)
    remote = None
    if rid:
        try:
            remote = client.get_remote(rid)
        except Exception as e:  # noqa: BLE001
            log.warning("stale request id %s: %s", rid, e)
    if remote is None:
        remote = client.submit(collection, req)
        reqlog.set(key, remote.request_id)
        log.info("submitted %s -> %s", collection, remote.request_id)
    t0 = time.time()
    while time.time() - t0 < budget_s:
        status = remote.status
        if status in ("successful", "succeeded"):
            target.parent.mkdir(parents=True, exist_ok=True)
            remote.download(str(target))
            return target
        if status in ("failed", "rejected", "dismissed"):
            try:
                detail = remote.json.get("metadata", {}).get("log") or remote.json.get("metadata", {}).get("request", {}).get("ids")
            except Exception:  # noqa: BLE001
                detail = ""
            log.error("request %s %s: %s", remote.request_id, status, detail)
            reqlog.pop(key)
            return None
        time.sleep(poll_s)
    log.warning("budget exhausted waiting for %s (status %s); will resume next run", remote.request_id, remote.status)
    return None


# ----------------------------------------------------------------------------- GRIB -> daily member fields
def open_grib_daily(path: Path, kind_by_short: dict[str, str] | None = None) -> xr.Dataset:
    """Open an S2S GRIB with cfgrib and return daily fields on (number, time, step_day, lat, lon).

    Instantaneous fields: value at 00 UTC of day d is labelled step_day = d (d = hours/24 + 1).
    Accumulated fields (tp, sf): the 24-h accumulation ending at hour h is labelled by the day
    it covers: step_day = h/24. De-accumulation is done on the "from start" totals.
    """
    import cfgrib  # noqa: WPS433
    dss = cfgrib.open_datasets(str(path), backend_kwargs={"indexpath": ""})
    out = {}
    for ds in dss:
        for v in ds.data_vars:
            # split pressure-level variables into our short names (t850, z500, u850, v850, u10hpa)
            if "isobaricInhPa" in ds[v].dims:
                for lev in ds["isobaricInhPa"].values:
                    out.update(_daily(ds[v].sel(isobaricInhPa=lev, drop=True), _short(v, float(lev))))
                continue
            if "isobaricInhPa" in ds[v].coords:
                out.update(_daily(ds[v].drop_vars("isobaricInhPa"), _short(v, float(ds["isobaricInhPa"].values))))
                continue
            out.update(_daily(ds[v], v))
    return xr.Dataset(out)


GRIB_SHORT = {"t": "t", "gh": "z", "u": "u", "v": "v", "z": "z"}


def _short(v: str, level: float) -> str:
    base = GRIB_SHORT.get(v, v)
    return f"{base}10hpa" if level == 10 else f"{base}{int(level)}"


def _daily(da: xr.DataArray, name: str) -> dict:
    if True:
        if True:
            if "number" not in da.dims:
                da = da.expand_dims(number=[int(da.coords.get("number", 0))])
            if "time" not in da.dims:
                da = da.expand_dims(time=[da.coords["time"].values])
            if "step" not in da.dims:
                da = da.expand_dims(step=[da.coords["step"].values])
            hours = (da["step"].values / np.timedelta64(1, "h")).astype(int)
            attrs = da.attrs
            step_type = attrs.get("GRIB_stepType", "instant")
            da = da.transpose("number", "time", "step", ...)
            if step_type in ("avg", "mean") or (step_type != "accum" and hours.size and hours[0] % 24 == 0 and attrs.get("GRIB_stepRange", "").find("-") > 0):
                day = (hours // 24).astype(int)
                da2 = da.rename({"step": "step_day"}).assign_coords(step_day=day)
            elif step_type == "accum":
                # cumulative from init -> daily increments; label by the day ending at that hour
                vals = da.values
                inc = np.diff(vals, axis=2, prepend=np.zeros_like(vals[:, :, :1]))
                day = (hours // 24).astype(int)
                da2 = xr.DataArray(inc, dims=("number", "time", "step_day") + tuple(da.dims[3:]),
                                   coords={"number": da["number"], "time": da["time"], "step_day": day, **{d: da[d] for d in da.dims[3:]}})
            else:
                day = (hours // 24 + 1).astype(int)
                da2 = da.rename({"step": "step_day"}).assign_coords(step_day=day)
            return {name: da2.drop_vars([c for c in da2.coords if c not in da2.dims], errors="ignore")}
