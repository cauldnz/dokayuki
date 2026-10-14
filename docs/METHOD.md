# Method

## 1. Pipeline in one paragraph

Weekly fields from the ECMWF and JMA subseasonal ensembles (via the S2S database on ECDS) are
reduced, member by member, to a handful of circulation indices and to a western-Hokkaido
snow-week measure. Each index (and each 1.5° grid cell) is calibrated with Probabilistic Bias
Correction (Guan, Mouatadid et al., *Nature*, 2026, doi:10.1038/s41586-026-11126-x; reference
code https://github.com/mouatadid/pbc): the ensemble is turned into a quintile CDF against
ERA5 thresholds, Debias++ removes the day-of-year-dependent bias learned from 20 years of
reforecasts, Persistence++ regresses the quintile indicators on two observed lags, the model
CDF and the rolling climatology, both are projected onto valid CDFs and averaged. The
calibrated index outlooks, plus predictors observed at issue time, feed a small regularised
logistic model for the snow-week terciles and the big-snow-week probability (Stage 3).

Implementation notes that go beyond the paper are in `docs/DATA_NOTES.md`; the parity test
(`tests/test_parity.py`) shows our Debias++, tuner, Persistence++ and projector agree with
ports of the reference code to 1e-6 on an identical sea-level-pressure slice.

**Causality additions.** Beyond the reference, every fit excludes model runs issued after the
forecast's init date (the reference lets on-the-fly reforecasts from later years enter the
training set at past hindcast dates). The leakage test corrupts everything after the issue
date and requires identical forecasts. One caveat is left open deliberately: model-threshold
quantiles follow the reference "SUBS-M-climate" recipe (latest reforecast base date ≤ issue,
plus 4 before and **4 after**); `n_after` is a parameter and the backtest should report both
settings.

## 2. Index definitions, with what the literature says

All indices are cos(latitude)-weighted means of **weekly-mean** fields on the 1.5° lattice,
with the sign chosen so that **higher = more Hokkaido snow**. Boxes live in
`config/indices.yaml`. Literature check performed 2026-10-14 (sources in brackets; "via
Wang & Chen 2010" means the definition was confirmed from Table 1 of Wang, L. & Chen, W.,
*Adv. Atmos. Sci.* 27, 855–870, 2010, doi:10.1007/s00376-009-9094-3 because the original
full text was paywalled).

| Key | Definition used | Reported as | Literature |
|---|---|---|---|
| **SHI** Siberian High intensity | MSLP, 40–65°N, 80–120°E | hPa − 1000 | Exactly the box of Panagiotopoulos, Shahgedanova, Hannachi & Stephenson, *J. Climate* 18, 1411 (2005), doi:10.1175/JCLI3352.1, also used by Jeong et al., *JGR* 116, D23102 (2011), doi:10.1029/2011JD015904 and D'Arrigo et al., *GRL* 32, L05705 (2005). The "Gong" box is 40–60°N, 70–120°E (Gong, Wang & Zhu, *GRL* 28, 2073, 2001, doi:10.1029/2000GL012311); Gong & Ho (2002) is *Theor. Appl. Climatol.* 72, 1, not GRL. We keep the Panagiotopoulos box and label it so. |
| **ALI** Aleutian Low intensity | −MSLP, 30–65°N, 160°E–140°W | −(hPa − 1000) | Exactly the North Pacific Index region of Trenberth & Hurrell, *Clim. Dyn.* 9, 303 (1994); NCAR Climate Data Guide gives a DJF mean of 1007.1 hPa and SD 2.9 hPa for 1979–2024 (monthly), consistent with our weekly DJF mean of −7.3 (i.e. 1007.3 hPa). Sign reversed so that a deep low is positive. |
| **MOI** winter monsoon index | MSLP at the lattice cell nearest Irkutsk (52.3°N, 104.3°E → 52.5°N, 105.0°E) minus Nemuro (43.3°N, 145.6°E → 43.5°N, 145.5°E) | hPa | The station-pair index of Hanawa, Watanabe, Iwasaka, Suga & Toba, *J. Meteor. Soc. Japan* 66, 445 (1988), doi:10.2151/jmsj1965.66.3_445, used operationally by JMA (TCC press releases: "sea level pressure difference between Irkutsk and Nemuro"). Takemura, Maeda & Kawamura, *Atmos. Sci. Lett.* (2024), doi:10.1002/asl.1229 use the same grid points and find r = +0.85 with the NW wind over the Sea of Japan. Takahashi & Idenaga, *JMSJ* 91, 639 (2013), doi:10.2151/jmsj.2013-506 warn that MOI is weaker than their Akita−Nagasaki index for *Honshu* cold surges on pentad scales; for Hokkaido the Irkutsk−Nemuro pair is the natural one. |
| **MOI_box** | MSLP (45–60°N, 95–115°E) − (35–50°N, 140–155°E) | hPa | Box variant in the spirit of the JMA TCC operational EAWM index, SLP(50–60°N, 90–110°E) − SLP(35–45°N, 140–160°E) (JMA EASCOF 2013 poster P2-6), and of Chan & Li (2004). Kept only as a sensitivity check: r = 0.98 with MOI. |
| **SJC** Sea-of-Japan cold air | −T850, 38–46°N, 132–141°E | −°C | No published index uses this box; it is the thermodynamic half of the instability measure. JMA's forecasting rule of thumb is T850 ≤ −6 °C for snow on the plains (used in the cold-day precipitation alternative). The literature check suggested shifting the box slightly west/north (38–47°N, 130–141°E) to cover the upstream fetch; kept as a config option, not adopted before the backtest. |
| **SJI** Sea-of-Japan instability | (SST − T850), same box; for forecasts the SST is the latest observed anomaly persisted onto the target week's climatology | °C | The 13 °C sea-to-850 hPa criterion is confirmed for the Sea of Japan by West, Steenburgh & Mace, *JGR Atmos.* (2019), doi:10.1029/2018JD029586 (sea-effect periods defined by SST − T850 ≥ 13 °C carry most SOJ cloud and precipitation), and originates in the Great Lakes work of Holroyd (1971) and Niziol (1987). Our DJF weekly mean is 18.9 °C (20th pct 16.8), so the box is convective most of the winter and the index measures *how* convective. No formal JPCZ-specific threshold was found. |
| **EAT** East Asian trough | −Z500, 30–45°N, 125–145°E | −(m − 5500) | Exactly the Sun & Li (1997) trough index (via Wang & Chen 2010, Table 1, index I_SunBM), sign reversed. Alternatives: Cui & Sun (1999) 35–40°N, 110–130°E; Wang et al., *J. Climate* 22, 600 (2009), doi:10.1175/2008JCLI2295.1 (PC1 over 25–50°N, 100–180°E plus a tilt index). |

Predictability context (from the same literature check): ECMWF skill for East Asian cold
events is about 7 days for typical events and >10 days for persistent ones (Dai et al., *JGR*
2021, doi:10.1029/2020JD033860); week-3 cold-surge skill exists in windows tied to Ural
blocking, the Siberian High and SST precursors (Liu et al., *AOSL* 2025,
doi:10.1016/j.aosl.2025.100610; Liu, Su & Wang, *Sci. China Earth Sci.* 2026,
doi:10.1007/s11430-026-2013-2); GloSea5 week-3 EAWM skill is limited by the Siberian High
(Ham & Jeong, *Atmosphere* 2021, doi:10.3390/atmos12101311). No paper scores SHI or NPI at
weeks 3–4 directly. **Expect small RPSS.**

## 3. Which indices relate to western-Hokkaido snow in the ERA5 era?

Computed from the WeatherBench2 1.5° ERA5 store (DJF 1979/80–2022/23) with
`scripts/analyze_indices.py`. **Caveat:** the 0.25° ERA5 snowfall needed for SNOW-W requires a
CDS key, so the snow measure here is the 1.5° **cold-day precipitation** over the SNOW-W box
(precipitation on days with box-mean T850 ≤ −6 °C), with plain box precipitation as a
second column. The analysis is to be re-run on SNOW-W and on AMeDAS snowfall once those are
in `state/`.

Sample: 1979-12-02 to 2022-12-30, 521 non-overlapping DJF weeks (44 winters). Snow proxy = 1.5-degree cold-day precipitation over the SNOW-W box (precipitation on days with box-mean T850 <= -6 C), until 0.25-degree ERA5 snowfall is pulled from CDS.

## Climatology of the weekly indices (DJF)

| index | mean | sd | 20th pct | 80th pct |
|---|---|---|---|---|
| SHI | 28.51 | 5.30 | 23.60 | 32.72 |
| ALI | -7.34 | 6.04 | -13.00 | -2.00 |
| MOI | 18.69 | 8.79 | 11.23 | 26.07 |
| MOI_box | 18.26 | 8.05 | 11.40 | 25.00 |
| SJC | 12.15 | 3.02 | 9.73 | 14.66 |
| SJI | 18.89 | 2.70 | 16.78 | 21.28 |
| EAT | 48.59 | 64.14 | -8.06 | 102.74 |

## Correlation with the snow proxy (Pearson r, Spearman rho; weekly, DJF)

| index | r (cold-day precip) | rho | r (box precip) | rho | r with anomalies* |
|---|---|---|---|---|---|
| SHI | +0.16 | +0.17 | +0.08 | +0.11 | +0.16 |
| ALI | -0.01 | -0.01 | -0.10 | -0.11 | -0.04 |
| MOI | +0.38 | +0.37 | +0.27 | +0.28 | +0.39 |
| MOI_box | +0.32 | +0.32 | +0.19 | +0.20 | +0.33 |
| SJC | +0.31 | +0.34 | +0.05 | +0.11 | +0.36 |
| SJI | +0.41 | +0.43 | +0.21 | +0.29 | +0.40 |
| EAT | +0.27 | +0.26 | +0.08 | +0.09 | +0.34 |

*anomalies: day-of-year mean removed, all overlapping DJF weeks (n larger, autocorrelated).

## Tercile agreement: P(snow proxy in top tercile | index in top tercile) vs 0.33 base rate

| index | P(top|top) | P(bottom|bottom) | n |
|---|---|---|---|
| SHI | 0.40 | 0.44 | 174 |
| ALI | 0.32 | 0.37 | 174 |
| MOI | 0.51 | 0.52 | 174 |
| MOI_box | 0.49 | 0.49 | 174 |
| SJC | 0.42 | 0.53 | 174 |
| SJI | 0.50 | 0.55 | 174 |
| EAT | 0.41 | 0.48 | 174 |

## Correlation among indices (DJF weekly)

| | SHI | ALI | MOI | MOI_box | SJC | SJI | EAT |
|---|---|---|---|---|---|---|---|
| SHI | +1.00 | +0.12 | +0.76 | +0.78 | +0.44 | +0.51 | +0.27 |
| ALI | +0.12 | +1.00 | +0.21 | +0.25 | +0.18 | +0.10 | +0.28 |
| MOI | +0.76 | +0.21 | +1.00 | +0.98 | +0.51 | +0.51 | +0.60 |
| MOI_box | +0.78 | +0.25 | +0.98 | +1.00 | +0.53 | +0.54 | +0.60 |
| SJC | +0.44 | +0.18 | +0.51 | +0.53 | +1.00 | +0.83 | +0.73 |
| SJI | +0.51 | +0.10 | +0.51 | +0.54 | +0.83 | +1.00 | +0.51 |
| EAT | +0.27 | +0.28 | +0.60 | +0.60 | +0.73 | +0.51 | +1.00 |

## Joint linear fit (standardised indices -> snow proxy, DJF weekly)

R^2 = 0.34 (in-sample, 521 weeks). Standardised coefficients (mm per 1 sd):

| index | beta |
|---|---|
| SHI | -3.55 |
| ALI | -0.25 |
| MOI | +17.00 |
| MOI_box | -12.26 |
| SJC | -0.68 |
| SJI | +4.95 |
| EAT | -1.22 |

### Reading of the analysis

- **The monsoon gradient (MOI), Sea-of-Japan instability (SJI) and cold air (SJC) carry the
  signal**: r ≈ 0.3–0.4 with weekly cold-day precipitation, and P(top-tercile snow | top-tercile
  index) ≈ 0.5 against a 0.33 base rate. MOI and SJI are the two to lead with.
- **The East Asian trough (EAT)** is a weaker, correlated proxy of the same thing (r = 0.73
  with SJC).
- **The Siberian High on its own is weak** (r ≈ 0.16): a strong high matters for Hokkaido only
  through the gradient to the east, which MOI captures (SHI–MOI r = 0.76).
- **The Aleutian Low is uncorrelated** with the proxy at weekly scale (r ≈ 0). It stays in the
  index set for the maps and as a Stage-3 feature, but should not be expected to carry skill.
- The joint linear fit explains about a third of the weekly variance in-sample; MOI and
  MOI_box fight each other (collinear, r = 0.98), so Stage 3 uses MOI only.
- All indices are strongly inter-correlated (SJC–SJI 0.83, MOI–EAT 0.60): the Stage-3
  regularisation and the "observed predictors only" baseline are there to keep the model honest.

## 4. Snow truth

SNOW-W is the weekly sum of ERA5 snowfall (water equivalent) averaged over western-Hokkaido
land, 42.5–44.5°N, 140.0–141.8°E, at native 0.25°. AMeDAS: Kutchan (倶知安, 16917), Sapporo
(札幌, 14913), Otaru (小樽, 16903) and Asahikawa (旭川, 12927) report hourly snow depth from
which JMA derives daily snowfall (sum of positive hourly depth increments). **Niseko (ニセコ,
16272) is a precipitation-only AMeDAS station since 2010 and reports no snowfall or snow
depth**; the nearest snow-depth stations are Rankoshi (蘭越, 16915) and Kutchan.
