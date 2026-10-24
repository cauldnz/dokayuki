# Backtest

Open test winters: 2017/18, 2018/19, 2019/20, 2020/21, 2021/22, 2022/23 (DJF weeks). Sealed, never evaluated here: 2023/24, 2024/25, 2025/26. Model thresholds use 0 base dates after the issue date (0 = strict). Lift = RPSS(method) − RPSS(operationally debiased model), winter-block bootstrap 95% intervals; an interval spanning zero reads 'no demonstrated improvement'.

## Lift over the debiased model, per index and lead

| source | index | lead | n weeks | debiased RPSS | raw RPSS | PBC RPSS | **PBC lift** | 95% CI | significant | Debias++ lift | Persistence++ lift | flag |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ecmwf | SHI | 19 | 138 | 0.019 | 0.066 | 0.075 | **+0.056** | -0.006 to +0.148 | no | +0.053 | +0.015 |  |
| ecmwf | ALI | 19 | 138 | -0.088 | -0.030 | 0.008 | **+0.096** | +0.003 to +0.182 | yes | +0.057 | +0.100 |  |
| ecmwf | MOI | 19 | 138 | 0.063 | 0.075 | 0.089 | **+0.026** | -0.045 to +0.106 | no | +0.030 | -0.026 |  |
| ecmwf | MOI_box | 19 | 138 | 0.015 | 0.027 | 0.051 | **+0.036** | -0.046 to +0.125 | no | +0.030 | -0.006 |  |
| ecmwf | SJC | 19 | 130 | 0.019 | 0.060 | 0.019 | **+0.053** | -0.026 to +0.147 | no | +0.067 | -0.010 |  |
| ecmwf | EAT | 19 | 130 | 0.024 | 0.109 | 0.121 | **+0.015** | -0.062 to +0.118 | no | +0.096 | -0.094 |  |
| ecmwf | SHI | 26 | 138 | -0.009 | 0.019 | 0.041 | **+0.056** | -0.015 to +0.159 | no | +0.045 | +0.010 |  |
| ecmwf | ALI | 26 | 138 | -0.194 | -0.141 | -0.061 | **+0.134** | +0.018 to +0.258 | yes | +0.067 | +0.160 |  |
| ecmwf | MOI | 26 | 138 | -0.001 | -0.016 | 0.020 | **+0.023** | -0.027 to +0.079 | no | +0.013 | -0.036 |  |
| ecmwf | MOI_box | 26 | 138 | -0.031 | -0.067 | -0.001 | **+0.026** | -0.044 to +0.106 | no | +0.000 | -0.010 |  |
| ecmwf | SJC | 26 | 130 | 0.023 | 0.013 | -0.024 | **+0.082** | -0.116 to +0.312 | no | +0.032 | +0.008 |  |
| ecmwf | EAT | 26 | 130 | 0.010 | 0.077 | 0.083 | **+0.109** | -0.057 to +0.256 | no | +0.085 | +0.067 |  |

Snow-week (Stage 3) and windows-of-opportunity tables are added once SNOW-W truth exists (needs the CDS key).
