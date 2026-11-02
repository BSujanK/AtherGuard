# Phase 2b - day-basis experiment

128 IMD-covered stations (11 with enough clean pairs; clean = station-year >= 200 valid days), clean real days 2007-01-01..2018-12-31; both valid and either > 0; clean real days only. station day t is paired with reference day t + lag. Medians over stations (>= 100 pairs per station and lag), 95% bootstrap CI over stations.

## station vs imd

| lag | median Pearson [CI] | median Spearman [CI] | stations | pooled pairs |
|---|---|---|---|---|
| -2 | 0.068 [-0.017, 0.124] | 0.020 [-0.065, 0.039] | 11 | 6632 |
| -1 | 0.202 [0.078, 0.243] | 0.134 [0.033, 0.257] | 11 | 6811 |
| +0 | 0.688 [0.530, 0.882] | 0.618 [0.509, 0.767] | 11 | 6225 |
| +1 | 0.236 [0.186, 0.291] | 0.192 [0.136, 0.250] | 11 | 6385 |
| +2 | 0.087 [0.054, 0.111] | 0.034 [-0.008, 0.050] | 11 | 6416 |

## station vs chirps_utc

| lag | median Pearson [CI] | median Spearman [CI] | stations | pooled pairs |
|---|---|---|---|---|
| -2 | 0.132 [0.053, 0.156] | -0.049 [-0.125, 0.012] | 11 | 5987 |
| -1 | 0.378 [0.295, 0.426] | 0.199 [0.102, 0.236] | 11 | 5742 |
| +0 | 0.156 [0.124, 0.207] | 0.015 [-0.093, 0.112] | 11 | 5826 |
| +1 | -0.002 [-0.051, 0.048] | -0.126 [-0.191, -0.073] | 11 | 5909 |
| +2 | -0.034 [-0.094, 0.015] | -0.158 [-0.255, -0.124] | 11 | 5933 |

## station vs chirps_aligned

| lag | median Pearson [CI] | median Spearman [CI] | stations | pooled pairs |
|---|---|---|---|---|
| -2 | 0.058 [-0.033, 0.088] | -0.039 [-0.105, 0.011] | 11 | 6264 |
| -1 | 0.177 [0.098, 0.229] | 0.058 [-0.007, 0.105] | 11 | 6162 |
| +0 | 0.378 [0.318, 0.458] | 0.233 [0.116, 0.274] | 11 | 6027 |
| +1 | 0.170 [0.137, 0.232] | 0.065 [-0.070, 0.118] | 11 | 6121 |
| +2 | 0.016 [-0.022, 0.057] | -0.117 [-0.170, -0.038] | 11 | 6167 |

## Exceedance agreement, days >= 50 mm (station vs IMD)

| lag | station days >= 50 | IMD also >= 50 [CI] | IMD days >= 50 | station also >= 50 [CI] |
|---|---|---|---|---|
| -2 | 402 | 0.082 [0.023, 0.131] | 260 | 0.127 [0.050, 0.185] |
| -1 | 402 | 0.117 [0.058, 0.162] | 271 | 0.173 [0.120, 0.225] |
| +0 | 402 | 0.376 [0.217, 0.494] | 272 | 0.555 [0.439, 0.742] |
| +1 | 402 | 0.159 [0.082, 0.222] | 254 | 0.252 [0.178, 0.321] |
| +2 | 402 | 0.082 [0.033, 0.136] | 245 | 0.135 [0.078, 0.222] |

Caveat: the IMD grid is interpolated from IMD gauges that probably include some of these stations, so agreement with IMD at lag 0 shows the day labels are consistent, not that the two are independent; CHIRPS (satellite plus gauges, UTC day) is the independent check on the timing.

## Verdict (generated from the numbers above)

- imd: median Pearson peaks at lag +0 (0.688, 95% CI [0.530, 0.882]; 11 stations); Spearman peaks at lag +0; per-station peak lags: {'0': 11}.
- chirps_utc: median Pearson peaks at lag -1 (0.378, 95% CI [0.295, 0.426]; 11 stations); Spearman peaks at lag -1; lag 0 is NOT the maximum (median Pearson 0.156, CI [0.124, 0.207]); per-station peak lags: {'-2': 1, '-1': 10}.
- chirps_aligned: median Pearson peaks at lag +0 (0.378, 95% CI [0.318, 0.458]; 11 stations); Spearman peaks at lag +0; per-station peak lags: {'-1': 1, '0': 10}.
- Implication for D5: station vs IMD agrees best at lag 0 (same day label); CHIRPS on the UTC day is best matched by the previous UTC day (lag -1), as an IMD-day label (03:00 UTC D-1 to 03:00 UTC D) predicts; the D5-aligned CHIRPS agrees best at lag 0, which supports the alignment.

## Sensitivity: clean = station-year >= 150 valid days (24 stations with enough pairs)

- imd: median Pearson peaks at lag +0 (0.712, 95% CI [0.657, 0.776]; 24 stations); Spearman peaks at lag +0; per-station peak lags: {'0': 24}.
- chirps_utc: median Pearson peaks at lag -1 (0.360, 95% CI [0.305, 0.412]; 23 stations); Spearman peaks at lag -1; lag 0 is NOT the maximum (median Pearson 0.192, CI [0.156, 0.239]); per-station peak lags: {'-1': 23}.
- chirps_aligned: median Pearson peaks at lag +0 (0.388, 95% CI [0.337, 0.444]; 23 stations); Spearman peaks at lag +0; per-station peak lags: {'0': 23}.
- Implication for D5: station vs IMD agrees best at lag 0 (same day label); CHIRPS on the UTC day is best matched by the previous UTC day (lag -1), as an IMD-day label (03:00 UTC D-1 to 03:00 UTC D) predicts; the D5-aligned CHIRPS agrees best at lag 0, which supports the alignment.
