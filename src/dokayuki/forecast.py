"""Assemble the forecast JSON from calibrated index CDFs, Stage-3 outputs and observed predictors.

This is the one place where numbers become the page. Everything it emits is validated by
``dokayuki.validate.check_forecast_json`` before the site is built; on failure the daily run keeps
the last good outlook and raises the stale banner.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import xarray as xr

from .config import IndexDef, load_stage_names
from .project import cdf_to_bins
from .site.schema import STAGES, expected_quintile, headline, index_line, lift_badge, signal_grade, stage_state, week_line
from .weekly import forecast_delta


def quintiles_from_cdf(P: xr.DataArray, t: pd.Timestamp, target: str) -> list[float]:
    b = cdf_to_bins(P.sel(time=[t], target=[target]))
    q = [round(float(x), 3) for x in b.values.ravel()]
    q[-1] = round(1.0 - sum(q[:-1]), 3)      # rounding never breaks the sum-to-one invariant
    return q


def assemble_forecast(issued: dt.date, init: dt.date, index_cdfs: dict[int, xr.DataArray], index_defs: dict[str, IndexDef],
                      index_skill: dict, snow: dict | None, drivers: dict, stale_since: str | None = None,
                      names: dict | None = None, generated_at: str | None = None) -> dict:
    """index_cdfs: {lead: DataArray(time, k, target)} of projected PBC CDFs for the issue's targets.
    index_skill: {key: {lead: {"rpss": float, "lift": {...}}}} from the backtest.
    snow: None (not skilful / absent) or {lead: {"terciles": {...}, "big_week": p, "factors": [...], "skill": {...}, "lift": {...}}}.
    """
    names = names or {}
    stage_names = load_stage_names()
    skilful = snow is not None and all(snow[l].get("skill", {}).get("rpss") is not None for l in (19, 26))
    weeks = []
    for lead in (19, 26):
        start = init + dt.timedelta(days=forecast_delta(lead))
        if snow and lead in snow:
            s = snow[lead]
            t = s["terciles"]; big = s["big_week"]; factors = s.get("factors", [])
            lift = s.get("lift"); sk = s.get("skill", {})
        else:
            t = {"below": 1 / 3, "near": 1 / 3, "above": 1 / 3}; big = 0.2; factors = []; lift = None; sk = {}
        grade = signal_grade(t, skilful, sk.get("rpss"))
        stages = []
        for sid in STAGES:
            sc = float(sum(f["contribution"] for f in factors if f.get("stage") == sid))
            stages.append({"id": sid, "name": STAGES[sid], "score": round(sc, 2), "state": "neutral" if sid == 5 else stage_state(sc)})
        weeks.append({"lead": lead, "label": "Week 3" if lead == 19 else "Week 4",
                      "valid": [start.isoformat(), (start + dt.timedelta(days=6)).isoformat()],
                      "terciles": {k: round(float(v), 3) for k, v in t.items()}, "big_week": round(float(big), 3),
                      "grade": grade, "line": week_line(t, big, grade, skilful), "factors": factors, "stages": stages,
                      "lift": lift, "lift_badge": lift_badge(lift),
                      "skill": {"rpss": sk.get("rpss"), "bss_big": sk.get("bss_big"), "roc_big": sk.get("roc_big"),
                                "period": sk.get("period", ""), "ci": sk.get("ci")}})
    indices = []
    for key, idx in index_defs.items():
        if key not in names and key not in ("SHI", "ALI", "MOI", "SJC", "SJI", "EAT", "U10_60N", "UBI", "AO", "NWF", "SJI13"):
            continue
        q, line, sk, skf, lb = {}, {}, {}, {}, {}
        for lead in (19, 26):
            P = index_cdfs.get(lead)
            t = pd.Timestamp(init + dt.timedelta(days=forecast_delta(lead)))
            if P is None or key not in P["target"].values or t not in P.get_index("time"):
                continue
            qq = quintiles_from_cdf(P, t, key)
            if any(np.isnan(qq)):
                continue
            q[str(lead)] = qq
            s = index_skill.get(key, {}).get(lead, {})
            sk[str(lead)] = {"rpss": s.get("rpss"), "ci": s.get("ci"), "lift": s.get("lift")}
            skf[str(lead)] = bool(s.get("lift", {}).get("significant")) and (s.get("rpss") or 0) > 0
            line[str(lead)] = index_line(key, qq, skf[str(lead)])
            lb[str(lead)] = lift_badge(s.get("lift"))
        if not q:
            continue
        for lead in ("19", "26"):   # the schema needs both leads; fill a missing one with climatology, unskilful
            if lead not in q:
                q[lead] = [0.2] * 5; sk[lead] = {"rpss": None, "ci": None, "lift": None}; skf[lead] = False
                line[lead] = index_line(key, q[lead], False); lb[lead] = lift_badge(None)
        indices.append({"key": key, "name": names.get(key, idx.plain), "stage": idx.stage, "quintiles": q,
                        "expected": {l: round(expected_quintile(q[l]), 2) for l in q}, "line": line, "skill": sk,
                        "skilful": skf, "lift_badge": lb})
    d = {"issued": issued.isoformat(), "generated_at": generated_at or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
         "init_dates": {"ecmwf": init.isoformat(), "jma": init.isoformat()}, "stale": stale_since is not None,
         "stale_since": stale_since,
         "snow_model": {"skilful": skilful, "skill": (snow[19].get("skill", {}) if snow else {"rpss": None, "period": "", "ci": None})},
         "weeks": weeks, "indices": indices, "drivers": drivers, "maps": [], "season": [],
         "backtest": {"snow": [], "lift": [], "final_exam": None, "windows": [], "experiments": {"n_trials": 0, "best": None, "deflated": None},
                      "effective_n": {"weeks": 0, "effective": 0}, "note": ""}, "repro": {"commit": "", "state_version": "", "command": ""}}
    d["headline"] = headline(d)
    return d
