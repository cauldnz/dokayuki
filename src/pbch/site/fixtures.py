"""Three realistic fixture states for design QA: strong snow signal, no signal, stale / not skilful."""
from __future__ import annotations

import datetime as dt

import numpy as np

from .schema import STAGES, expected_quintile, headline, index_line, lift_badge, signal_grade, stage_state, week_line

INDICES = ["U10_60N", "UBI", "AO", "SHI", "MOI", "ALI", "EAT", "NWF", "SJI", "SJI13"]
NAMES = {"U10_60N": "Polar vortex", "UBI": "Ural blocking", "AO": "Arctic Oscillation", "SHI": "Siberian High",
         "MOI": "Monsoon gradient", "ALI": "Aleutian Low", "EAT": "East Asian trough", "NWF": "Northwesterly flow",
         "SJI": "Sea-effect instability", "SJI13": "Snow-factory days", "SJC": "Sea-of-Japan cold air"}
STAGE_OF = {"U10_60N": 1, "UBI": 1, "AO": 1, "SHI": 2, "MOI": 2, "ALI": 2, "EAT": 3, "NWF": 3, "SJI": 4, "SJI13": 4}
# fixture skill: absolute RPSS of PBC, of the debiased model, of the raw model, per lead
SKILL = {"U10_60N": {19: (0.12, 0.10, 0.08), 26: (0.07, 0.06, 0.04)}, "UBI": {19: (0.05, 0.03, 0.01), 26: (0.02, 0.01, 0.0)},
         "AO": {19: (0.08, 0.06, 0.04), 26: (0.04, 0.03, 0.02)}, "SHI": {19: (0.07, 0.05, 0.02), 26: (0.03, 0.02, 0.01)},
         "MOI": {19: (0.09, 0.06, 0.03), 26: (0.04, 0.03, 0.01)}, "ALI": {19: (0.02, 0.02, 0.01), 26: (-0.01, 0.0, -0.01)},
         "EAT": {19: (0.06, 0.04, 0.02), 26: (0.02, 0.02, 0.0)}, "NWF": {19: (0.06, 0.04, 0.01), 26: (0.03, 0.02, 0.0)},
         "SJI": {19: (0.08, 0.05, 0.02), 26: (0.04, 0.03, 0.01)}, "SJI13": {19: (0.05, 0.03, 0.01), 26: (0.02, 0.02, 0.0)}}


def _lift(pbc, deb, raw, width=0.04):
    d = pbc - deb
    return {"lift": round(d, 3), "ci": [round(d - width, 3), round(d + width, 3)], "significant": abs(d) > width,
            "lift_vs_raw": round(pbc - raw, 3), "skill_pbc": pbc, "skill_debiased": deb, "skill_raw": raw}


def _quint(lean: float, sharp: float = 1.0) -> list[float]:
    base = np.array([0.2] * 5)
    tilt = np.array([-2, -1, 0, 1, 2]) * lean * 0.08 * sharp
    q = np.clip(base + tilt, 0.02, None)
    q = [round(float(x), 3) for x in q / q.sum()]
    q[2] = round(1 - sum(q[:2]) - sum(q[3:]), 3)
    return q


def _grid(rng, lean, lats, lons):
    LAT, LON = np.meshgrid(lats, lons, indexing="ij")
    field = lean * np.cos(np.deg2rad(LON - 140)) * np.sin(np.deg2rad(LAT * 2)) + 0.3 * rng.standard_normal(LAT.shape)
    b = np.clip(np.round(3 + field * 1.5), 1, 5).astype(int)
    p = np.clip(0.22 + 0.25 * np.abs(field), 0.2, 0.7)
    return {"lats": lats.tolist(), "lons": lons.tolist(), "bin": b.tolist(), "prob": np.round(p, 2).tolist()}


def make_state(kind: str, issued: str = "2026-01-14") -> dict:
    rng = np.random.default_rng({"strong": 1, "none": 2, "stale": 3}[kind])
    issued_d = dt.date.fromisoformat(issued)
    init = issued_d - dt.timedelta(days=2)
    skilful = kind != "stale"
    lean3, lean4 = {"strong": (1.6, 1.0), "none": (0.1, -0.1), "stale": (0.8, 0.3)}[kind]
    weeks = []
    for lead, lean in ((19, lean3), (26, lean4)):
        start = init + dt.timedelta(days=lead - 1)
        above = round(1 / 3 + 0.16 * lean, 3); below = round(1 / 3 - 0.12 * lean, 3)
        t = {"below": below, "near": round(1 - above - below, 3), "above": above}
        big = round(max(0.03, 0.2 + 0.12 * lean), 3)
        rp = {19: 0.06, 26: 0.03}[lead] if skilful else None
        grade = signal_grade(t, skilful, rp)
        factors = [{"key": k, "name": NAMES[k], "stage": STAGE_OF[k], "contribution": round(float(c * lean), 2)} for k, c in
                   (("U10_60N", 0.3), ("UBI", 0.1), ("AO", 0.2), ("SHI", -0.05), ("MOI", 0.55), ("ALI", 0.02),
                    ("EAT", 0.2), ("NWF", 0.35), ("SJI", 0.45), ("SJI13", 0.25))]
        stages = []
        for sid, sname in STAGES.items():
            sc = sum(f["contribution"] for f in factors if f["stage"] == sid)
            stages.append({"id": sid, "name": sname, "score": round(sc, 2), "state": "neutral" if sid == 5 else stage_state(sc)})
        w_lift = _lift(*({19: (0.06, 0.03, 0.02), 26: (0.03, 0.02, 0.0)}[lead])) if skilful else None
        weeks.append({"lead": lead, "label": "Week 3" if lead == 19 else "Week 4",
                      "valid": [start.isoformat(), (start + dt.timedelta(days=6)).isoformat()],
                      "terciles": t, "big_week": big, "grade": grade, "line": week_line(t, big, grade, skilful),
                      "factors": factors, "stages": stages, "lift": w_lift, "lift_badge": lift_badge(w_lift),
                      "skill": {"rpss": rp, "bss_big": (0.04 if lead == 19 else 0.01) if skilful else None,
                                "roc_big": (0.62 if lead == 19 else 0.56) if skilful else None,
                                "period": "DJF 2016/17–2025/26", "ci": ([0.01, 0.11] if lead == 19 else [-0.02, 0.08]) if skilful else None}})
    indices = []
    for k in INDICES:
        q = {}
        for lead, lean in ((19, lean3), (26, lean4)):
            sgn = -1 if k == "ALI" else 1
            q[str(lead)] = _quint(lean * sgn * (0.5 if k in ("SHI", "ALI") else 1.0), 1.0 if lead == 19 else 0.6)
        sk = {str(l): {"rpss": SKILL[k][l][0], "ci": [SKILL[k][l][0] - 0.04, SKILL[k][l][0] + 0.04], "lift": _lift(*SKILL[k][l])} for l in (19, 26)}
        skf = {str(l): sk[str(l)]["lift"]["significant"] and SKILL[k][l][0] > 0 for l in (19, 26)}
        indices.append({"key": k, "name": NAMES[k], "stage": STAGE_OF[k], "quintiles": q, "expected": {l: round(expected_quintile(q[l]), 2) for l in q},
                        "line": {l: index_line(k, q[l], skf[l]) for l in q}, "skill": sk, "skilful": skf,
                        "lift_badge": {str(l): lift_badge(sk[str(l)]["lift"]) for l in (19, 26)}})
    lats = np.arange(21.0, 72.1, 1.5); lons = np.arange(75.0, 225.1, 1.5)
    maps = [{"field": f, "title": t, "lead": 19, "grid": _grid(rng, lean3 * s, lats, lons)} for f, t, s in
            (("msl", "Sea-level pressure", 1.0), ("t850", "850 hPa temperature", -1.0), ("z500", "500 hPa height", -0.8))]
    season = []
    d = dt.date(issued_d.year - (1 if issued_d.month < 7 else 0), 11, 24)
    while d < issued_d - dt.timedelta(days=6):
        doy = (d - dt.date(d.year, 1, 1)).days
        clim = 12 + 10 * np.sin(np.pi * (doy + 30) / 120) if d.month in (12, 1, 2) else 8
        obs = max(0.0, clim * (1 + 0.6 * rng.standard_normal()))
        season.append({"start": d.isoformat(), "obs": round(float(obs), 1), "clim_lo": round(float(clim * 0.5), 1), "clim_hi": round(float(clim * 1.5), 1),
                       "fc19": rng.choice(["below", "near", "above"], p=[0.3, 0.4, 0.3]), "fc26": rng.choice(["below", "near", "above"], p=[0.3, 0.4, 0.3])})
        d += dt.timedelta(days=7)
    state = {
        "issued": issued, "generated_at": f"{issued}T06:40:00Z",
        "init_dates": {"ecmwf": init.isoformat(), "jma": init.isoformat()},
        "stale": kind == "stale", "stale_since": "2026-01-09" if kind == "stale" else None,
        "snow_model": {"skilful": skilful, "skill": {"rpss": 0.06, "period": "DJF 2016/17–2025/26", "ci": [0.01, 0.11]} if skilful else
                       {"rpss": -0.01, "period": "DJF 2016/17–2025/26", "ci": [-0.06, 0.04]}},
        "weeks": weeks, "indices": indices,
        "drivers": {"ao": {"value": -1.4 if kind == "strong" else 0.3, "date": (issued_d - dt.timedelta(days=1)).isoformat()},
                    "mjo": {"phase": 6 if kind == "strong" else 3, "amp": 1.6 if kind == "strong" else 0.7, "rmm1": None, "rmm2": None,
                            "date": (issued_d - dt.timedelta(days=2)).isoformat()},
                    "vortex": {"u10": 8.0 if kind == "strong" else 28.0, "state": "weak / disturbed" if kind == "strong" else "strong",
                               "date": (issued_d - dt.timedelta(days=6)).isoformat()},
                    "sst_anom": 0.9 if kind != "none" else -0.2,
                    "recent_snow": {"Kutchan": {"obs_cm": 118, "normal_cm": 92, "ja": "倶知安"}, "Sapporo": {"obs_cm": 61, "normal_cm": 70, "ja": "札幌"}}},
        "maps": maps, "season": season,
        "backtest": {"snow": [{"model": "Climatology", "rpss19": 0.0, "rpss26": 0.0}, {"model": "Raw ECMWF snowfall", "rpss19": 0.02, "rpss26": 0.0},
                              {"model": "Direct PBC on SNOW-W", "rpss19": 0.04, "rpss26": 0.02}, {"model": "Observed predictors only", "rpss19": 0.03, "rpss26": 0.02},
                              {"model": "Stage-3 snow model", "rpss19": 0.06, "rpss26": 0.03}],
                     "lift": [{"what": "Snow-week terciles, week 3", "model_skill": 0.02, "pbc_lift": 0.02, "pbc_ci": [-0.01, 0.05], "stage3_lift": 0.02, "stage3_ci": [-0.01, 0.05]},
                              {"what": "Snow-week terciles, week 4", "model_skill": 0.0, "pbc_lift": 0.02, "pbc_ci": [-0.02, 0.05], "stage3_lift": 0.01, "stage3_ci": [-0.02, 0.04]}],
                     "final_exam": None,
                     "windows": [{"condition": "weak vortex (U10 60N < 10 m/s at issue)", "n": 31, "rpss": 0.11, "ci": [0.02, 0.19]},
                                 {"condition": "AO < -1 at issue", "n": 44, "rpss": 0.08, "ci": [0.01, 0.15]},
                                 {"condition": "MJO amplitude > 1", "n": 90, "rpss": 0.05, "ci": [0.0, 0.10]},
                                 {"condition": "unconditioned", "n": 156, "rpss": 0.04, "ci": [0.0, 0.08]}],
                     "experiments": {"n_trials": 0, "best": None, "deflated": None},
                     "effective_n": {"weeks": 156, "effective": 71},
                     "note": "FIXTURE numbers for design QA only; the real backtest replaces every number here."},
        "repro": {"commit": "fixture", "state_version": "none", "command": "scripts/bootstrap.sh --with-cds --with-s2s && make backtest && make site"},
    }
    from .references import render as render_refs
    state["references"] = render_refs()
    state["headline"] = headline(state)
    return state
