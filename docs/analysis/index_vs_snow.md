# Index vs western-Hokkaido snow proxy, ERA5 era (DJF weekly)

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
