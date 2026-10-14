# Backtest

**SYNTHETIC DATA.** This run exercises the driver on the synthetic fixture (known bias and skill). No real-world skill is claimed. The real backtest replaces this file once S2S and CDS data are in `state/`.

Open test winters: 2017/18, 2018/19, 2019/20, 2020/21, 2021/22, 2022/23 (DJF weeks). Sealed, never evaluated here: 2023/24, 2024/25, 2025/26. Model thresholds use 0 base dates after the issue date (0 = strict). Lift = RPSS(method) − RPSS(operationally debiased model), winter-block bootstrap 95% intervals; an interval spanning zero reads 'no demonstrated improvement'.

## Lift over the debiased model, per index and lead

| source | index | lead | n weeks | debiased RPSS | raw RPSS | PBC RPSS | **PBC lift** | 95% CI | significant | Debias++ lift | Persistence++ lift | flag |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ecmwf | MOI | 19 | 152 | 0.265 | -0.534 | 0.274 | **+0.009** | -0.011 to +0.035 | no | -0.101 | +0.034 |  |
| ecmwf | SJI | 19 | 152 | 0.203 | -0.459 | 0.219 | **+0.016** | -0.022 to +0.048 | no | -0.046 | +0.014 |  |
| ecmwf | SHI | 19 | 152 | 0.358 | -0.400 | 0.321 | **-0.037** | -0.081 to +0.013 | no | -0.139 | +0.007 | IMPLAUSIBLE: investigate leak |
| ecmwf | EAT | 19 | 152 | 0.208 | -0.421 | 0.183 | **-0.025** | -0.100 to +0.036 | no | -0.069 | -0.023 |  |
| jma | MOI | 19 | 152 | 0.142 | -0.228 | 0.164 | **+0.022** | -0.004 to +0.043 | no | -0.029 | +0.028 |  |
| jma | SJI | 19 | 152 | 0.133 | -0.112 | 0.164 | **+0.031** | +0.010 to +0.057 | yes | +0.027 | +0.002 |  |
| jma | SHI | 19 | 152 | 0.163 | -0.176 | 0.154 | **-0.010** | -0.058 to +0.039 | no | -0.046 | -0.003 |  |
| jma | EAT | 19 | 152 | 0.138 | -0.075 | 0.151 | **+0.013** | -0.077 to +0.090 | no | +0.022 | -0.031 |  |
| ecmwf | MOI | 26 | 152 | 0.210 | -0.536 | 0.238 | **+0.027** | -0.001 to +0.051 | no | -0.050 | +0.012 |  |
| ecmwf | SJI | 26 | 152 | 0.208 | -0.403 | 0.242 | **+0.034** | +0.014 to +0.050 | yes | -0.004 | +0.016 |  |
| ecmwf | SHI | 26 | 152 | 0.288 | -0.437 | 0.275 | **-0.012** | -0.061 to +0.040 | no | -0.089 | +0.014 | IMPLAUSIBLE: investigate leak |
| ecmwf | EAT | 26 | 152 | 0.189 | -0.396 | 0.188 | **-0.001** | -0.073 to +0.067 | no | -0.031 | -0.012 |  |
| jma | MOI | 26 | 152 | 0.126 | -0.171 | 0.181 | **+0.055** | +0.035 to +0.075 | yes | +0.039 | +0.021 |  |
| jma | SJI | 26 | 152 | 0.135 | -0.100 | 0.166 | **+0.031** | -0.003 to +0.068 | no | +0.028 | -0.003 |  |
| jma | SHI | 26 | 152 | 0.231 | -0.120 | 0.204 | **-0.027** | -0.074 to +0.026 | no | -0.069 | -0.015 |  |
| jma | EAT | 26 | 152 | 0.135 | -0.088 | 0.149 | **+0.015** | -0.097 to +0.113 | no | +0.023 | -0.025 |  |
| duet | MOI | 19 | 152 | 0.265 | -0.534 | 0.257 | **-0.009** | -0.067 to +0.034 | no | +nan | +nan |  |
| duet | SJI | 19 | 152 | 0.203 | -0.459 | 0.219 | **+0.016** | -0.022 to +0.048 | no | +nan | +nan |  |
| duet | SHI | 19 | 152 | 0.358 | -0.400 | 0.263 | **-0.095** | -0.143 to -0.048 | yes | +nan | +nan | IMPLAUSIBLE: investigate leak |
| duet | EAT | 19 | 152 | 0.208 | -0.421 | 0.183 | **-0.025** | -0.100 to +0.036 | no | +nan | +nan |  |
| duet | MOI | 26 | 152 | 0.210 | -0.536 | 0.238 | **+0.027** | -0.001 to +0.051 | no | +nan | +nan |  |
| duet | SJI | 26 | 152 | 0.208 | -0.403 | 0.242 | **+0.034** | +0.014 to +0.050 | yes | +nan | +nan |  |
| duet | SHI | 26 | 152 | 0.288 | -0.437 | 0.275 | **-0.012** | -0.061 to +0.040 | no | +nan | +nan |  |
| duet | EAT | 26 | 152 | 0.189 | -0.396 | 0.186 | **-0.003** | -0.086 to +0.083 | no | +nan | +nan |  |

Snow-week (Stage 3) and windows-of-opportunity tables are added once SNOW-W truth exists (needs the CDS key).
