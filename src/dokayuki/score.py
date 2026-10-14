"""Scores: RPS/RPSS, Brier/BSS, reliability, ROC area, block bootstrap confidence intervals."""
from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr

from .thresholds import K_DIM, TIME
from .weekly import season_of


def rps(P: xr.DataArray, O: xr.DataArray) -> xr.DataArray:
    """Ranked probability score per (time, target): sum over k of (P_k - O_k)^2."""
    p, o = xr.align(P.transpose(TIME, K_DIM, ...), O.transpose(TIME, K_DIM, ...), join="inner")
    return ((p - o) ** 2).sum(K_DIM, skipna=False)


def brier(P: xr.DataArray, O: xr.DataArray) -> xr.DataArray:
    p, o = xr.align(P, O, join="inner")
    return (p - o) ** 2


def skill_score(score_model: xr.DataArray, score_ref: xr.DataArray, dims=(TIME,),
                weights: xr.DataArray | None = None) -> xr.DataArray:
    """1 - mean(score_model)/mean(score_ref) over ``dims`` (optionally cos-lat weighted)."""
    m, r = xr.align(score_model, score_ref, join="inner")
    ok = m.notnull() & r.notnull()
    m, r = m.where(ok), r.where(ok)
    if weights is not None:
        mm = m.weighted(weights.fillna(0)).mean(dims)
        rr = r.weighted(weights.fillna(0)).mean(dims)
    else:
        mm, rr = m.mean(dims, skipna=True), r.mean(dims, skipna=True)
    return 1.0 - mm / rr


def rpss(P: xr.DataArray, P_clim: xr.DataArray, O: xr.DataArray, dims=(TIME,),
         weights: xr.DataArray | None = None) -> xr.DataArray:
    return skill_score(rps(P, O), rps(P_clim, O), dims=dims, weights=weights)


def reliability(p: np.ndarray, o: np.ndarray, bins: int = 10):
    """Reliability-diagram table: bin centre, mean forecast, observed frequency, count."""
    p, o = np.asarray(p, float), np.asarray(o, float)
    ok = ~np.isnan(p) & ~np.isnan(o)
    p, o = p[ok], o[ok]
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    rows = []
    for b in range(bins):
        sel = idx == b
        rows.append({"bin": (edges[b] + edges[b + 1]) / 2, "mean_forecast": p[sel].mean() if sel.any() else np.nan,
                     "obs_freq": o[sel].mean() if sel.any() else np.nan, "n": int(sel.sum())})
    return pd.DataFrame(rows)


def roc_area(p: np.ndarray, o: np.ndarray) -> float:
    """Area under the ROC curve (Mann-Whitney form)."""
    p, o = np.asarray(p, float), np.asarray(o, float)
    ok = ~np.isnan(p) & ~np.isnan(o)
    p, o = p[ok], o[ok]
    pos, neg = p[o > 0.5], p[o <= 0.5]
    if len(pos) == 0 or len(neg) == 0:
        return np.nan
    order = np.argsort(np.concatenate([pos, neg]), kind="mergesort")
    ranks = np.empty(len(order)); ranks[order] = np.arange(1, len(order) + 1)
    # average ranks for ties
    vals = np.concatenate([pos, neg])
    s = pd.Series(vals).rank(method="average").values
    return float((s[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def block_bootstrap_ci(score_model: pd.Series, score_ref: pd.Series, n_boot: int = 1000,
                       alpha: float = 0.05, seed: int = 0, block: str = "season") -> tuple[float, float, float]:
    """CI of the skill score 1 - mean(model)/mean(ref), resampling whole winters (blocks)."""
    df = pd.DataFrame({"m": score_model, "r": score_ref}).dropna()
    if block == "season":
        df["blk"] = [season_of(t) for t in df.index]
    else:
        df["blk"] = df.index.year
    groups = {k: g for k, g in df.groupby("blk")}
    keys = list(groups)
    rng = np.random.default_rng(seed)
    est = 1 - df.m.mean() / df.r.mean()
    boots = []
    for _ in range(n_boot):
        pick = rng.choice(keys, size=len(keys), replace=True)
        sub = pd.concat([groups[k] for k in pick])
        boots.append(1 - sub.m.mean() / sub.r.mean())
    lo, hi = np.nanquantile(boots, [alpha / 2, 1 - alpha / 2])
    return float(est), float(lo), float(hi)


# ----------------------------------------------------------------------------- spec update 1: lift and effective N
def lift(score_model: pd.Series, score_ref: pd.Series, score_clim: pd.Series, n_boot: int = 2000,
         alpha: float = 0.05, seed: int = 0, block: str = "season") -> dict:
    """Lift = skill(model) - skill(ref), both relative to climatology, with a block-bootstrap CI.

    Skill = 1 - mean(score)/mean(score_clim). Resamples whole winters jointly for model, ref and
    climatology so the paired difference is honest. Returns point estimate, CI, p (two-sided,
    bootstrap), and the two absolute skills.
    """
    df = pd.DataFrame({"m": score_model, "r": score_ref, "c": score_clim}).dropna()
    df["blk"] = [season_of(t) for t in df.index] if block == "season" else df.index.year
    groups = {k: g for k, g in df.groupby("blk")}
    keys = list(groups)
    def skills(d):
        sm, sr = 1 - d.m.mean() / d.c.mean(), 1 - d.r.mean() / d.c.mean()
        return sm, sr, sm - sr
    sm, sr, est = skills(df)
    rng = np.random.default_rng(seed)
    boots = []
    for _ in range(n_boot):
        pick = rng.choice(keys, size=len(keys), replace=True)
        boots.append(skills(pd.concat([groups[k] for k in pick]))[2])
    boots = np.asarray(boots)
    lo, hi = np.nanquantile(boots, [alpha / 2, 1 - alpha / 2])
    p = 2 * min((boots <= 0).mean(), (boots >= 0).mean())
    return {"skill_model": float(sm), "skill_ref": float(sr), "lift": float(est), "ci": (float(lo), float(hi)),
            "p_boot": float(p), "n_weeks": int(len(df)), "n_blocks": int(len(keys)),
            "significant": bool(lo > 0 or hi < 0)}


def effective_n(x: pd.Series, max_lag: int = 10) -> float:
    """Effective sample size n / (1 + 2 sum_k rho_k) using autocorrelations up to max_lag (Bretherton 1999 form)."""
    v = pd.Series(x).dropna().values
    n = len(v)
    if n < 3:
        return float(n)
    v = v - v.mean()
    denom = (v ** 2).sum()
    rhos = []
    for k in range(1, min(max_lag, n - 1) + 1):
        r = (v[:-k] * v[k:]).sum() / denom
        if r <= 0:
            break
        rhos.append(r)
    return float(n / (1 + 2 * sum(rhos)))


def deflated_skill(best: float, trials: int, null_sd: float) -> float:
    """Simple deflation of the best-of-N skill: subtract the expected maximum of N iid normal nulls
    with standard deviation ``null_sd`` (a conservative stand-in for a reality-check adjustment)."""
    if trials <= 1:
        return best
    from scipy.stats import norm
    # expected max of N standard normals (Blom approximation)
    emax = norm.ppf((trials - 0.375) / (trials + 0.25))
    return float(best - emax * null_sd)
