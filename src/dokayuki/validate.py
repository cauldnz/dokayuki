"""Runtime validation: data invariants, probability invariants, forecast JSON schema, statistical
sanity guards. Everything here is used both by tests and by the daily run (which refuses to publish
and shows the stale banner when a check fails).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import xarray as xr

from .thresholds import K_DIM, TIME

# physical ranges (SI) for the gridded fields; anything outside is a corrupt pull, not weather
FIELD_RANGES = {
    "msl": (87000.0, 109000.0), "t2m": (180.0, 335.0), "tp": (0.0, 1.0), "sf": (0.0, 1.0), "sst": (265.0, 310.0),
    "t850": (210.0, 320.0), "z500": (4500.0, 6100.0), "u850": (-120.0, 120.0), "v850": (-120.0, 120.0), "u10hpa": (-200.0, 200.0),
}


class ValidationError(AssertionError):
    pass


@dataclass
class Report:
    ok: bool = True
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def fail(self, msg: str) -> None:
        self.ok = False
        self.problems.append(msg)

    def raise_if_failed(self) -> None:
        if not self.ok:
            raise ValidationError("; ".join(self.problems))


# ----------------------------------------------------------------------------- data invariants
def check_daily_fields(ds: xr.Dataset, max_nan_frac: float = 0.02, report: Report | None = None) -> Report:
    """Time axis strictly increasing and daily, values inside physical ranges, limited NaN."""
    r = report or Report()
    t = pd.DatetimeIndex(ds[TIME].values)
    if not t.is_monotonic_increasing or t.has_duplicates:
        r.fail("time axis not strictly increasing")
    for v in ds.data_vars:
        da = ds[v]
        lo, hi = FIELD_RANGES.get(v, (-np.inf, np.inf))
        vals = da.values
        finite = np.isfinite(vals)
        nan_frac = 1 - finite.mean() if vals.size else 0.0
        if v != "sst" and nan_frac > max_nan_frac:   # sst is NaN over land by construction
            r.fail(f"{v}: {nan_frac:.1%} NaN")
        if finite.any() and (np.nanmin(vals) < lo or np.nanmax(vals) > hi):
            r.fail(f"{v}: values outside [{lo}, {hi}] (min {np.nanmin(vals):.3g}, max {np.nanmax(vals):.3g})")
        if finite.any() and np.nanstd(vals) == 0:
            r.fail(f"{v}: constant field")
    return r


def check_weekly_targets(da: xr.DataArray, report: Report | None = None) -> Report:
    r = report or Report()
    if TIME not in da.dims or "target" not in da.dims:
        r.fail("weekly targets need (time, target) dims")
        return r
    if np.isnan(da.values).all():
        r.fail("all-NaN weekly targets")
    return r


# ----------------------------------------------------------------------------- probability invariants
def check_cdf(P: xr.DataArray, tol: float = 1e-9, report: Report | None = None, name: str = "cdf") -> Report:
    """Every CDF: within [0, 1], non-decreasing in k, no NaN mixed inside a single CDF."""
    r = report or Report()
    v = P.transpose(TIME, K_DIM, ...).values
    nan = np.isnan(v)
    mixed = nan.any(axis=1) & ~nan.all(axis=1)
    if mixed.any():
        r.fail(f"{name}: {int(mixed.sum())} CDFs with partial NaN")
    ok = ~nan.all(axis=1)
    vv = v[:, :, ...]
    if ok.any():
        if np.nanmin(vv) < -tol or np.nanmax(vv) > 1 + tol:
            r.fail(f"{name}: values outside [0, 1]")
        d = np.diff(vv, axis=1)
        if np.nanmin(d) < -tol:
            r.fail(f"{name}: non-monotone CDF (min step {np.nanmin(d):.2e})")
    return r


def check_bins(B: xr.DataArray, tol: float = 1e-6, report: Report | None = None) -> Report:
    r = report or Report()
    s = B.sum("bin", skipna=False)
    if float(np.nanmax(np.abs(s.values - 1))) > tol:
        r.fail("bin probabilities do not sum to 1")
    if float(np.nanmin(B.values)) < -tol:
        r.fail("negative bin probability")
    return r


def check_thresholds(q: xr.DataArray, report: Report | None = None) -> Report:
    r = report or Report()
    d = np.diff(q.transpose(TIME, K_DIM, ...).values, axis=1)
    if np.nanmin(d) < 0:
        r.fail("thresholds not non-decreasing in k")
    return r


# ----------------------------------------------------------------------------- statistical sanity
def implausible_skill(rpss: float, kind: str = "index") -> bool:
    """Guan et al. report global PBC-ECMWF RPSS of about 0.1 or less for SLP and T2m and 0.02-0.07 for
    precipitation at weeks 3-4. Anything far above is a probable leak."""
    limit = {"index": 0.30, "grid": 0.25, "snow": 0.20}[kind]
    return rpss > limit


def permutation_null(fit_predict, truth_by_season: dict, n_perm: int = 20, seed: int = 0) -> np.ndarray:
    """Skill under a season-permutation null: shuffle which season's truth goes with which season's
    forecasts and re-run ``fit_predict`` (a callable mapping a truth dict -> skill). Any real skill
    must sit well outside this distribution; a pipeline that leaks future truth will show skill
    even here."""
    rng = np.random.default_rng(seed)
    keys = list(truth_by_season)
    if len(keys) < 4:
        raise ValueError("permutation null needs at least 4 seasons")
    out = []
    tries = 0
    while len(out) < n_perm and tries < 50 * n_perm:
        tries += 1
        perm = rng.permutation(len(keys))
        if (perm == np.arange(len(keys))).all():
            continue   # the identity permutation is the real pairing, not a null draw
        shuffled = {keys[i]: truth_by_season[keys[j]] for i, j in enumerate(perm)}
        out.append(fit_predict(shuffled))
    return np.asarray(out)


# ----------------------------------------------------------------------------- forecast JSON schema
FORECAST_SCHEMA = {
    "type": "object",
    "required": ["issued", "generated_at", "init_dates", "stale", "snow_model", "headline", "weeks", "indices", "drivers"],
    "properties": {
        "issued": {"type": "string", "format": "date"},
        "generated_at": {"type": "string"},
        "init_dates": {"type": "object", "required": ["ecmwf"], "additionalProperties": {"type": ["string", "null"]}},
        "stale": {"type": "boolean"},
        "stale_since": {"type": ["string", "null"]},
        "headline": {"type": "string", "minLength": 10, "maxLength": 160},
        "snow_model": {"type": "object", "required": ["skilful", "skill"], "properties": {"skilful": {"type": "boolean"}}},
        "weeks": {"type": "array", "minItems": 2, "maxItems": 2, "items": {
            "type": "object", "required": ["lead", "label", "valid", "terciles", "big_week", "grade", "line", "factors", "stages"],
            "properties": {
                "lead": {"enum": [19, 26]},
                "valid": {"type": "array", "minItems": 2, "maxItems": 2, "items": {"type": "string", "format": "date"}},
                "terciles": {"type": "object", "required": ["below", "near", "above"],
                             "properties": {k: {"type": "number", "minimum": 0, "maximum": 1} for k in ("below", "near", "above")}},
                "big_week": {"type": "number", "minimum": 0, "maximum": 1},
                "grade": {"enum": ["Strong", "Moderate", "Weak", "No signal"]},
                "stages": {"type": "array", "minItems": 5, "maxItems": 5, "items": {"type": "object", "required": ["id", "name", "state"],
                           "properties": {"state": {"enum": ["lining up", "neutral", "against"]}}}},
            }}},
        "indices": {"type": "array", "items": {"type": "object", "required": ["key", "name", "quintiles", "skill", "skilful", "stage"],
                    "properties": {"quintiles": {"type": "object", "required": ["19", "26"],
                                   "additionalProperties": {"type": "array", "minItems": 5, "maxItems": 5, "items": {"type": "number", "minimum": 0, "maximum": 1}}}}}},
    },
}


def check_forecast_json(d: dict, report: Report | None = None) -> Report:
    """Schema plus the semantic rules a schema cannot express."""
    import jsonschema
    r = report or Report()
    v = jsonschema.Draft202012Validator(FORECAST_SCHEMA, format_checker=jsonschema.FormatChecker())
    for e in sorted(v.iter_errors(d), key=lambda e: list(e.path)):
        r.fail(f"schema: {'/'.join(str(p) for p in e.path)}: {e.message}")
    if r.problems:
        return r
    issued = dt.date.fromisoformat(d["issued"])
    for w in d["weeks"]:
        t = w["terciles"]
        if abs(t["below"] + t["near"] + t["above"] - 1) > 2e-3:   # values are rounded to 3 decimals
            r.fail(f"{w['label']}: terciles do not sum to 1")
        v0, v1 = (dt.date.fromisoformat(x) for x in w["valid"])
        if (v1 - v0).days != 6:
            r.fail(f"{w['label']}: valid window is not 7 days")
        init = dt.date.fromisoformat(d["init_dates"]["ecmwf"])
        if (v0 - init).days != w["lead"] - 1:
            r.fail(f"{w['label']}: valid start is not init + lead - 1")
        if v0 <= issued:
            r.fail(f"{w['label']}: valid window starts before issue date (leak of the present)")
        if w["grade"] != "No signal" and not d["snow_model"]["skilful"]:
            r.fail(f"{w['label']}: a graded signal is shown although the snow model is not skilful")
        if w["big_week"] > t["above"] + 1e-6:
            r.fail(f"{w['label']}: P(big week) exceeds P(above normal)")
    for ix in d["indices"]:
        for lead, q in ix["quintiles"].items():
            if abs(sum(q) - 1) > 3e-3:
                r.fail(f"{ix['key']} {lead}: quintiles do not sum to 1")
            if ix["skill"][lead].get("rpss") is not None and implausible_skill(ix["skill"][lead]["rpss"]):
                r.fail(f"{ix['key']} {lead}: implausibly high RPSS {ix['skill'][lead]['rpss']}: probable leak")
    return r
