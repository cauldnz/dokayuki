"""Phase 2: which indices actually relate to western-Hokkaido snow in the ERA5 era (DJF weekly)?

Writes docs/analysis/index_vs_snow.md (tables) and docs/analysis/*.png, from state/.
Snow proxy: until CDS snowfall is available, uses the 1.5-degree cold-day precipitation over the
SNOW-W box (precip on days with box-mean T850 <= -6 C) and plain box precipitation.
"""
import logging, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import numpy as np, pandas as pd, xarray as xr
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pbch.config import RegionConfig, SnowConfig, load_indices
from pbch.build_truth import open_daily, weekly_truth
from pbch.masks import load_lsm
from pbch.state import State
from pbch.weekly import season_of

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
cfg, snow, defs = RegionConfig.load(), SnowConfig.load(), load_indices()
st = State(Path("state"))
ds = open_daily([Path("state/era5_15_daily.zarr"), Path("state/era5_15_daily_t850.zarr"), Path("state/era5_15_daily_z500.zarr")])
lsm = load_lsm(Path("state/lsm_15.nc"))
logging.info("daily store: %s", {v: int(ds[v].notnull().any(("latitude", "longitude")).sum()) for v in ds.data_vars})
wk, table = weekly_truth(ds, lsm, cfg, defs, snow)
st.write_weekly("truth_weekly_grid", wk)
st.write_table("truth_weekly_indices", table)
logging.info("weekly table columns: %s", list(table.columns))

out = Path("docs/analysis"); out.mkdir(parents=True, exist_ok=True)
t = table.copy()
t["season"] = [season_of(x) for x in t.index]
idx_cols = [c for c in ["SHI", "ALI", "MOI", "MOI_box", "SJC", "SJI", "EAT"] if c in t.columns]
djf = t[t.index.month.isin([12, 1, 2])].dropna(subset=["cold_day_precip_weekly_mm"] + idx_cols)
# non-overlapping weeks (every 7th day) to keep the sample honest for correlations
djf7 = djf[(djf.index.dayofyear % 7) == 0]
targets = ["cold_day_precip_weekly_mm", "tp_box_weekly_mm"]
lines = ["# Index vs western-Hokkaido snow proxy, ERA5 era (DJF weekly)\n",
         f"Sample: {djf7.index[0].date()} to {djf7.index[-1].date()}, {len(djf7)} non-overlapping DJF weeks "
         f"({djf7.season.nunique()} winters). Snow proxy = 1.5-degree cold-day precipitation over the SNOW-W box "
         "(precipitation on days with box-mean T850 <= -6 C), until 0.25-degree ERA5 snowfall is pulled from CDS.\n",
         "## Climatology of the weekly indices (DJF)\n", "| index | mean | sd | 20th pct | 80th pct |", "|---|---|---|---|---|"]
for c in idx_cols:
    s = djf7[c]
    lines.append(f"| {c} | {s.mean():.2f} | {s.std():.2f} | {s.quantile(.2):.2f} | {s.quantile(.8):.2f} |")
lines += ["\n## Correlation with the snow proxy (Pearson r, Spearman rho; weekly, DJF)\n",
          "| index | r (cold-day precip) | rho | r (box precip) | rho | r with anomalies* |", "|---|---|---|---|---|---|"]
# anomalies: remove the DJF day-of-year mean (linear seasonal cycle) with a 31-day window climatology
def anomalies(s: pd.Series) -> pd.Series:
    clim = s.groupby(s.index.dayofyear).transform("mean")
    return s - clim
res = {}
for c in idx_cols:
    r1 = djf7[c].corr(djf7[targets[0]]); rho1 = djf7[c].corr(djf7[targets[0]], method="spearman")
    r2 = djf7[c].corr(djf7[targets[1]]); rho2 = djf7[c].corr(djf7[targets[1]], method="spearman")
    ra = anomalies(djf[c]).corr(anomalies(djf[targets[0]]))
    res[c] = (r1, rho1, r2, rho2, ra)
    lines.append(f"| {c} | {r1:+.2f} | {rho1:+.2f} | {r2:+.2f} | {rho2:+.2f} | {ra:+.2f} |")
lines.append("\n*anomalies: day-of-year mean removed, all overlapping DJF weeks (n larger, autocorrelated).\n")
# tercile agreement: P(top tercile snow | top tercile index)
lines += ["## Tercile agreement: P(snow proxy in top tercile | index in top tercile) vs 0.33 base rate\n",
          "| index | P(top|top) | P(bottom|bottom) | n |", "|---|---|---|---|"]
y = djf7[targets[0]]; yt = y > y.quantile(2/3); yb = y < y.quantile(1/3)
for c in idx_cols:
    x = djf7[c]; xt = x > x.quantile(2/3); xb = x < x.quantile(1/3)
    lines.append(f"| {c} | {yt[xt].mean():.2f} | {yb[xb].mean():.2f} | {int(xt.sum())} |")
# inter-index correlations
lines += ["\n## Correlation among indices (DJF weekly)\n", "| | " + " | ".join(idx_cols) + " |", "|---|" + "---|" * len(idx_cols)]
C = djf7[idx_cols].corr()
for a in idx_cols:
    lines.append(f"| {a} | " + " | ".join(f"{C.loc[a, b]:+.2f}" for b in idx_cols) + " |")
# multiple regression (standardised) of snow proxy on indices
X = (djf7[idx_cols] - djf7[idx_cols].mean()) / djf7[idx_cols].std()
X = X.assign(ones=1.0)
beta, *_ = np.linalg.lstsq(X.values, y.values, rcond=None)
pred = X.values @ beta
r2 = 1 - ((y.values - pred) ** 2).sum() / ((y.values - y.mean()) ** 2).sum()
lines += ["\n## Joint linear fit (standardised indices -> snow proxy, DJF weekly)\n",
          f"R^2 = {r2:.2f} (in-sample, {len(y)} weeks). Standardised coefficients (mm per 1 sd):", "",
          "| index | beta |", "|---|---|"] + [f"| {c} | {b:+.2f} |" for c, b in zip(idx_cols, beta[:-1])]
(out / "index_vs_snow.md").write_text("\n".join(lines) + "\n")
print("\n".join(lines))
# figure: scatter grid
fig, axes = plt.subplots(2, 4, figsize=(14, 6.5)); axes = axes.ravel()
for ax, c in zip(axes, idx_cols):
    ax.scatter(djf7[c], y, s=8, alpha=.5); ax.set_xlabel(c); ax.set_ylabel("cold-day precip (mm/wk)"); ax.set_title(f"r={res[c][0]:+.2f}")
for ax in axes[len(idx_cols):]: ax.axis("off")
fig.tight_layout(); fig.savefig(out / "index_vs_snow_scatter.png", dpi=110)
