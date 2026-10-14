"""Phase 3 backtest driver: strictly causal, winter-blocked, lift-first.

Inputs come from the state store (weekly truth per target, per-member index values for each
source and lead) or from the synthetic generator (``--synthetic``) so the whole driver can be
exercised without credentials. For every (source, index, lead) it scores climatology, raw,
operationally debiased (model thresholds), Debias++, Persistence++, PBC, then Duet across
sources, on the open test winters only; the sealed winters are never touched.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import xarray as xr

from .cdf import climatology_cdf, combine_forecast_reforecast, forecast_to_time, members_to_cdf, members_to_cdf_by_issue, reforecast_to_time
from .debiaspp import tune_debiaspp
from .experiments import assert_not_locked
from .pbc import pbc_from_components
from .persistpp import persistpp
from .project import project_cdf
from .score import lift, rps, rpss
from .thresholds import indicators, model_thresholds, observed_thresholds
from .validate import implausible_skill
from .weekly import season_of

log = logging.getLogger(__name__)


@dataclass
class SourceData:
    name: str
    fc: xr.DataArray            # (issue, member, target) weekly values for one lead
    rf: xr.DataArray            # (issue, hyear, member, target)


@dataclass
class IndexResult:
    source: str
    target: str
    lead: int
    rpss: dict = field(default_factory=dict)      # method -> RPSS over test weeks
    lifts: dict = field(default_factory=dict)     # method -> lift dict vs debiased
    n_weeks: int = 0
    seasons: list = field(default_factory=list)
    implausible: bool = False


def _winter_mask(times: pd.DatetimeIndex, winters: set[str], months=(12, 1, 2)) -> np.ndarray:
    return np.array([(season_of(t) in winters) and (t.month in months) for t in times])


def run_source(src: SourceData, truth: xr.DataArray, lead: int, K: int, gt_delta: int, test_winters: list[str],
               locked: tuple[str, ...], n_after: int = 0, scope: str = "per_target") -> tuple[dict[str, xr.DataArray], xr.DataArray, pd.DatetimeIndex]:
    """All calibrated CDFs for one source and lead on the test targets. Returns (cdfs, O, targets)."""
    thr = observed_thresholds(truth, K)
    O = indicators(truth, thr)
    fct, rft = forecast_to_time(src.fc, lead), reforecast_to_time(src.rf, lead)
    F_obs = members_to_cdf(combine_forecast_reforecast(fct, rft, reforecast_keep="first"), thr)
    # operationally debiased = model thresholds (the "debiased" model the lift is measured against);
    # reforecast rows get the thresholds of their own issuance so Persistence++ trains on the full history
    issues = src.fc.get_index("issue")
    mthr = model_thresholds(src.rf, K, issues, n_before=4, n_after=n_after)
    F_mod_fc = members_to_cdf_by_issue(fct, mthr)
    F_mod_rf = members_to_cdf_by_issue(rft, mthr)
    F_mod = combine_forecast_reforecast(F_mod_fc, F_mod_rf, reforecast_keep="last")
    all_t = fct.get_index("time")
    targets = all_t[_winter_mask(all_t, set(test_winters))]
    assert_not_locked({season_of(t) for t in targets} & set(locked))
    tuned = tune_debiaspp(F_obs, O, targets, gt_delta, scope=scope, lead=lead)
    pp = persistpp(F_mod, O, targets, gt_delta, lead, K)
    cdfs = {
        "raw": project_cdf(F_obs.reindex(time=targets)),
        "debiased": project_cdf(F_mod.reindex(time=targets)),
        "debiaspp": project_cdf(tuned.pred),
        "persistpp": project_cdf(pp),
    }
    cdfs["pbc"] = pbc_from_components(tuned.pred, pp)
    return cdfs, O, targets


def score_methods(cdfs: dict[str, xr.DataArray], O: xr.DataArray, targets: pd.DatetimeIndex, K: int, source: str, lead: int) -> list[IndexResult]:
    Ot = O.reindex(time=targets)
    clim = climatology_cdf(K, Ot)
    out = []
    for tg in Ot["target"].values:
        r = IndexResult(source=source, target=str(tg), lead=lead, n_weeks=int(Ot.sel(target=tg).notnull().all("k").sum()),
                        seasons=sorted({season_of(t) for t in targets}))
        rc = rps(clim, Ot).sel(target=tg).to_series()
        rd = rps(cdfs["debiased"], Ot).sel(target=tg).to_series()
        for m, P in cdfs.items():
            rm = rps(P, Ot).sel(target=tg).to_series()
            r.rpss[m] = float(rpss(P.sel(target=[tg]), clim.sel(target=[tg]), Ot.sel(target=[tg])).item())
            if m not in ("debiased", "raw"):
                r.lifts[m] = lift(rm, rd, rc, n_boot=1000)
            if implausible_skill(r.rpss[m]):
                r.implausible = True
        out.append(r)
    return out


def write_backtest_md(results: list[IndexResult], duet_results: list[IndexResult], path, synthetic: bool, locked: tuple[str, ...],
                      test_winters: list[str], n_after: int) -> None:
    lines = ["# Backtest", ""]
    if synthetic:
        lines.append("**SYNTHETIC DATA.** This run exercises the driver on the synthetic fixture (known bias and skill). "
                     "No real-world skill is claimed. The real backtest replaces this file once S2S and CDS data are in `state/`.")
        lines.append("")
    lines += [f"Open test winters: {', '.join(test_winters)} (DJF weeks). Sealed, never evaluated here: {', '.join(locked)}. "
              f"Model thresholds use {n_after} base dates after the issue date (0 = strict). Lift = RPSS(method) − RPSS(operationally debiased model), "
              "winter-block bootstrap 95% intervals; an interval spanning zero reads 'no demonstrated improvement'.", ""]
    lines += ["## Lift over the debiased model, per index and lead", "",
              "| source | index | lead | n weeks | debiased RPSS | raw RPSS | PBC RPSS | **PBC lift** | 95% CI | significant | Debias++ lift | Persistence++ lift | flag |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in results + duet_results:
        L = r.lifts.get("pbc", {}); d = r.lifts.get("debiaspp", {}); p = r.lifts.get("persistpp", {})
        lines.append(f"| {r.source} | {r.target} | {r.lead} | {r.n_weeks} | {r.rpss.get('debiased', float('nan')):.3f} | {r.rpss.get('raw', float('nan')):.3f} | "
                     f"{r.rpss.get('pbc', float('nan')):.3f} | **{L.get('lift', float('nan')):+.3f}** | {L.get('ci', (float('nan'), float('nan')))[0]:+.3f} to {L.get('ci', (float('nan'), float('nan')))[1]:+.3f} | "
                     f"{'yes' if L.get('significant') else 'no'} | {d.get('lift', float('nan')):+.3f} | {p.get('lift', float('nan')):+.3f} | {'IMPLAUSIBLE: investigate leak' if r.implausible else ''} |")
    lines += ["", "Snow-week (Stage 3) and windows-of-opportunity tables are added once SNOW-W truth exists (needs the CDS key).", ""]
    path.write_text("\n".join(lines))


def summarise_for_site(results: list[IndexResult], prefer_source: str = "duet") -> dict:
    """{index: {lead: {"rpss":..., "ci":..., "lift": {...}}}} for the forecast JSON."""
    out: dict = {}
    for r in results:
        if r.source != prefer_source:
            continue
        L = r.lifts.get("pbc")
        out.setdefault(r.target, {})[r.lead] = {"rpss": r.rpss.get("pbc"), "ci": list(L["ci"]) if L else None,
                                                "lift": {"lift": L["lift"], "ci": list(L["ci"]), "significant": L["significant"],
                                                         "skill_pbc": L["skill_model"], "skill_debiased": L["skill_ref"],
                                                         "skill_raw": r.rpss.get("raw")} if L else None}
    return out
