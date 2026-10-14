"""Forecast JSON (latest.json) helpers: signal grades, plain-English lines, headline guarded by skill."""
from __future__ import annotations


INDEX_PLAIN = {
    "SHI": ("Siberian High", "stronger than normal", "weaker than normal"),
    "ALI": ("Aleutian Low", "deeper than normal", "weaker than normal"),
    "MOI": ("Monsoon gradient", "stronger than normal", "weaker than normal"),
    "SJC": ("Sea-of-Japan cold air", "colder than normal", "milder than normal"),
    "SJI": ("Instability over the sea", "more convective than normal", "more stable than normal"),
    "EAT": ("East Asian trough", "deeper than normal", "weaker than normal"),
}


def expected_quintile(q: list[float]) -> float:
    return float(sum((i + 1) * p for i, p in enumerate(q)))


def signal_grade(terciles: dict, skilful: bool, rpss: float | None) -> str:
    """How far the probabilities move from 1/3 each, gated by backtest skill."""
    if not skilful:
        return "No signal"
    shift = max(abs(terciles["above"] - 1 / 3), abs(terciles["below"] - 1 / 3))
    strength = shift * (1.0 if (rpss or 0) >= 0.05 else 0.6)
    if strength >= 0.20:
        return "Strong"
    if strength >= 0.11:
        return "Moderate"
    if strength >= 0.05:
        return "Weak"
    return "No signal"


def week_line(terciles: dict, big: float, grade: str, skilful: bool) -> str:
    if not skilful:
        return "The snow model isn't skilful enough yet to call this week; read the circulation indices instead."
    a, b = terciles["above"], terciles["below"]
    if grade == "No signal":
        return "No real lean either way: about the usual odds of snow for this time of year."
    if a > b:
        if grade == "Strong":
            return "Looks like a decent chance of a big week on the Sea of Japan side."
        if grade == "Moderate":
            return "Leaning snowier than normal on the Sea of Japan side."
        return "A slight lean towards a snowier week than normal."
    if grade == "Strong":
        return "Looks like a lean week: odds favour below-normal snow."
    if grade == "Moderate":
        return "Leaning drier than normal for the Sea of Japan side."
    return "A slight lean towards a quieter week than normal."


def index_line(key: str, q: list[float], skilful: bool) -> str:
    name, up, down = INDEX_PLAIN.get(key, (key, "higher than normal", "lower than normal"))
    if not skilful:
        return f"{name}: not skilful yet at this lead."
    top2, bot2 = q[3] + q[4], q[0] + q[1]
    if top2 >= 0.5:
        return f"{name} {up} likely."
    if bot2 >= 0.5:
        return f"{name} {down} likely."
    return f"{name} near normal."


def headline(d: dict) -> str:
    sm = d["snow_model"]
    if d.get("stale"):
        return f"Outlook is stale (data behind since {d.get('stale_since')}); showing the last good run."
    if not sm["skilful"]:
        return "The snow mapping isn't proven skilful yet, so no snow call: here's what the circulation indices say."
    w3, w4 = d["weeks"][0], d["weeks"][1]
    g3, g4 = w3["grade"], w4["grade"]
    if g3 in ("Strong", "Moderate") and w3["terciles"]["above"] > w3["terciles"]["below"]:
        tail = " and the following week looks similar" if g4 in ("Strong", "Moderate") and w4["terciles"]["above"] > w4["terciles"]["below"] else ""
        return f"Week 3 is leaning snowier than normal on the Sea of Japan side{tail}."
    if g3 in ("Strong", "Moderate") and w3["terciles"]["above"] < w3["terciles"]["below"]:
        return "Week 3 is leaning quieter than normal; no big-week signal yet."
    if g4 in ("Strong", "Moderate") and w4["terciles"]["above"] > w4["terciles"]["below"]:
        return "Nothing clear for week 3, but week 4 is leaning snowier than normal."
    return "No strong signal either way: expect roughly normal odds of snow for the season."


STAGES = {1: "Trigger", 2: "Outbreak", 3: "Steering", 4: "Fuel", 5: "Delivery"}


def stage_state(score: float) -> str:
    """Three-way state of an ingredient-chain stage from a signed score (sum of standardised
    contributions of its indices): lining up / neutral / against."""
    if score >= 0.25:
        return "lining up"
    if score <= -0.25:
        return "against"
    return "neutral"


def lift_badge(lift: dict | None) -> str:
    """Spec update 1: badges lead with the lift over the operationally debiased model."""
    if not lift or lift.get("lift") is None:
        return "No proven skill yet"
    if not lift.get("significant"):
        return "No demonstrated improvement over the raw model"
    sign = "+" if lift["lift"] >= 0 else ""
    return f"Lift over debiased model: {sign}{lift['lift']:.2f} RPSS ({lift['ci'][0]:+.2f} to {lift['ci'][1]:+.2f})"
