# Phase 3d - extreme-rain corrector

Target: gauge daily rain (IMD-day) on clean real days (150-valid-day station-years) not flagged by the out-of-fold integrity engine, on days where aligned CHIRPS exists. Headline predictors exclude IMD; `corrector_with_imd` is the LEAKAGE-RISK variant (the IMD grid probably ingests these gauges). Station splits are the frozen Phase 2 ones; 95% CIs resample TEST stations.

## Data

| split | stations | rows | exceedance rows | exceedances |
|---|---|---|---|---|
| test | 6 | 6143 | 5913 | 33 |
| train | 22 | 20980 | 18444 | 158 |
| val | 8 | 7808 | 6249 | 47 |

Only 6 TEST stations (of 140) have clean, unflagged days with CHIRPS; 33 TEST exceedance days. Share of rows without terrain (station cell not in the terrain store): 0.224. Per-station threshold: 99th percentile of wet days (>= 1 mm) in 2007-2015 (19 stations have >= 30 wet days).

## Pinball loss on TEST stations (mean mm [95% CI]; skill = 1 - loss/raw loss)

| method | alpha 0.5 | alpha 0.9 | alpha 0.99 |
|---|---|---|---|
| raw_chirps | 4.809 [2.94, 6.55] | 4.676 [2.52, 6.63] | 4.646 [2.44, 6.61] |
| linear_scaling | 3.815 [2.38, 5.15]; skill 0.207, diff -0.994 [-1.41, -0.57] | 3.513 [2.79, 4.22]; skill 0.249, diff -1.163 [-2.47, 0.24] | 0.796 [0.73, 0.90]; skill 0.829, diff -3.850 [-5.77, -1.71] |
| corrector | 3.505 [2.32, 4.66]; skill 0.271, diff -1.304 [-1.94, -0.60]; vs linear -0.311 [-0.52, -0.00] | 2.657 [2.01, 3.40]; skill 0.432, diff -2.020 [-3.41, -0.52]; vs linear -0.857 [-0.99, -0.59] | 0.646 [0.52, 0.85]; skill 0.861, diff -4.001 [-5.91, -1.92]; vs linear -0.150 [-0.20, -0.05] |
| corrector_with_imd | 3.441 [2.58, 4.39]; skill 0.284, diff -1.367 [-2.39, -0.29]; vs linear -0.374 [-0.97, 0.30] | 2.921 [2.72, 3.61]; skill 0.375, diff -1.755 [-3.78, 0.42]; vs linear -0.592 [-1.31, 0.17] | 0.770 [0.68, 1.10]; skill 0.834, diff -3.877 [-5.85, -1.75]; vs linear -0.026 [-0.10, 0.22] |

## Coverage of the 0.9 / 0.99 quantiles on TEST (target in header)

| method | 0.9 | 0.99 |
|---|---|---|
| raw_chirps | 0.641 [0.53, 0.77] | 0.641 [0.53, 0.77] |
| linear_scaling | 0.929 [0.89, 0.96] | 0.995 [0.99, 1.00] |
| corrector | 0.902 [0.89, 0.93] | 0.987 [0.98, 0.99] |
| corrector_with_imd | 0.910 [0.85, 0.97] | 0.986 [0.98, 1.00] |

## Bias on the top 1% of TEST gauge days (gauge >= 72.9 mm; 63 rows at 6 stations; mean gauge 100.9 mm)

| method | q50 mean bias mm | q90 | q99 |
|---|---|---|---|
| raw_chirps | -66.6 [-84.14, -59.34] | -66.6 [-84.14, -59.34] | -66.6 [-84.14, -59.34] |
| linear_scaling | -86.2 [-112.92, -76.12] | -44.3 [-61.26, -37.19] | 21.8 [6.78, 27.08] |
| corrector | -78.5 [-111.84, -66.73] | -42.2 [-69.50, -31.35] | 4.8 [-13.99, 12.11] |
| corrector_with_imd | -78.1 [-122.68, -62.62] | -41.0 [-74.42, -28.65] | -3.6 [-28.28, 5.40] |

## Exceedance of the station 99th wet-day percentile (33 positives of 5913 TEST rows at 4 of 4 stations)

| score | PR-AUC [CI] | recall at 1% false-flag [CI] | recall at 5% false-flag [CI] |
|---|---|---|---|
| raw_chirps | 0.047 [0.03, 0.15] | 0.152 [0.06, 0.40] | 0.394 [0.23, 0.65] |
| linear_scaling | 0.047 [0.03, 0.15] | 0.152 [0.06, 0.40] | 0.394 [0.23, 0.65] |
| corrector | 0.071 [0.05, 0.25] | 0.212 [0.00, 0.55] | 0.455 [0.23, 0.70] |
| corrector_with_imd | 0.071 [0.06, 0.14] | 0.212 [0.12, 0.45] | 0.455 [0.29, 0.70] |

## Wayanad check (cell 20305122, 11.51 N 76.13 E; terrain available; elevation 1037 m)

| IMD day | IMD mm | CHIRPS aligned mm | CHIRPS 3-day mm | q50 | q90 | q99 | P(exceed) | with IMD: q50 | q90 | q99 |
|---|---|---|---|---|---|---|---|---|---|---|
| 2024-07-23 | 35.3 | n/a | n/a | 6.5 | 21.6 | 51.1 | 0.011 | 26.7 | 60.7 | 79.3 |
| 2024-07-24 | 16.7 | 28.7 | n/a | 7.5 | 38.4 | 107.9 | 0.019 | 15.7 | 42.7 | 85.3 |
| 2024-07-25 | 25.6 | 19.1 | n/a | 6.2 | 31.7 | 87.9 | 0.011 | 24.7 | 47.8 | 72.8 |
| 2024-07-26 | 53.3 | 43.9 | 91.8 | 12.1 | 46.8 | 92.8 | 0.019 | 51.7 | 83.6 | 120.6 |
| 2024-07-27 | 37.8 | 29.5 | 92.5 | 9.3 | 42.2 | 88.2 | 0.011 | 37.4 | 61.3 | 97.3 |
| 2024-07-28 | 5.0 | 25.8 | 99.1 | 9.6 | 36.5 | 89.0 | 0.019 | 8.1 | 14.4 | 54.7 |
| 2024-07-29 | 6.6 | 7.4 | 62.6 | 2.5 | 22.4 | 50.3 | 0.003 | 5.4 | 14.5 | 34.4 |
| 2024-07-30 | 179.2 | 51.6 | 84.7 | 31.2 | 71.1 | 127.1 | 0.127 | 73.3 | 160.4 | 214.8 |
| 2024-07-31 | 16.7 | 7.4 | 66.3 | 6.2 | 24.4 | 56.0 | 0.003 | 14.9 | 29.6 | 61.2 |
| 2024-08-01 | 31.6 | 51.6 | 110.5 | 21.0 | 57.4 | 118.5 | 0.020 | 37.3 | 61.9 | 112.8 |
| 2024-08-02 | 42.5 | 0.0 | 58.9 | 6.0 | 23.5 | 49.2 | 0.003 | 36.0 | 66.8 | 98.3 |

On 2024-07-30 the IMD value is 179.2 mm; aligned CHIRPS gives 0.29 of it. The CHIRPS-only corrector predicts q50 0.17, q90 0.40, q99 0.71 of the IMD value. Verdict (the gap counts as closed when q90 >= 50% of IMD): the corrector does NOT close the gap.

## Verdicts (from the CIs above)

- pinball alpha 0.5: corrector beats raw CHIRPS (skill 0.271, paired diff -1.304 [-1.94, -0.60])
- pinball alpha 0.5: corrector_with_imd beats raw CHIRPS (skill 0.284, paired diff -1.367 [-2.39, -0.29])
- pinball alpha 0.5: linear_scaling beats raw CHIRPS (skill 0.207, paired diff -0.994 [-1.41, -0.57])
- pinball alpha 0.9: corrector beats raw CHIRPS (skill 0.432, paired diff -2.020 [-3.41, -0.52])
- pinball alpha 0.9: corrector_with_imd ties (CI of the paired loss difference contains 0) raw CHIRPS (skill 0.375, paired diff -1.755 [-3.78, 0.42])
- pinball alpha 0.9: linear_scaling ties (CI of the paired loss difference contains 0) raw CHIRPS (skill 0.249, paired diff -1.163 [-2.47, 0.24])
- pinball alpha 0.99: corrector beats raw CHIRPS (skill 0.861, paired diff -4.001 [-5.91, -1.92])
- pinball alpha 0.99: corrector_with_imd beats raw CHIRPS (skill 0.834, paired diff -3.877 [-5.85, -1.75])
- pinball alpha 0.99: linear_scaling beats raw CHIRPS (skill 0.829, paired diff -3.850 [-5.77, -1.71])
- pinball alpha 0.5: corrector beats the linear quantile scaling (paired diff -0.311 [-0.52, -0.00])
- pinball alpha 0.5: corrector_with_imd ties (CI of the paired loss difference contains 0) the linear quantile scaling (paired diff -0.374 [-0.97, 0.30])
- pinball alpha 0.9: corrector beats the linear quantile scaling (paired diff -0.857 [-0.99, -0.59])
- pinball alpha 0.9: corrector_with_imd ties (CI of the paired loss difference contains 0) the linear quantile scaling (paired diff -0.592 [-1.31, 0.17])
- pinball alpha 0.99: corrector beats the linear quantile scaling (paired diff -0.150 [-0.20, -0.05])
- pinball alpha 0.99: corrector_with_imd ties (CI of the paired loss difference contains 0) the linear quantile scaling (paired diff -0.026 [-0.10, 0.22])
- exceedance PR-AUC: corrector 0.071 [0.05, 0.25] is not separable from raw CHIRPS 0.047 [0.03, 0.15]
- exceedance PR-AUC: corrector_with_imd 0.071 [0.06, 0.14] is above raw CHIRPS 0.047 [0.03, 0.15]
- exceedance PR-AUC: linear_scaling 0.047 [0.03, 0.15] is not separable from raw CHIRPS 0.047 [0.03, 0.15]

## Notes and limits

- Headline predictors exclude IMD; `corrector_with_imd` is a leakage-risk variant, not for use.
- The exceedance threshold is the station's own 99th wet-day percentile in 2007-2015; on cells the classifier is applied with the same absolute predictors, so corr_p_exceed99 means 'exceeds a typical station p99', not a per-cell percentile.
- elev_point is the station elevation for stations and the cell's mean elevation for cells.
- Terrain is missing for stations whose cell is not in the terrain store (NaN, handled natively by LightGBM).
- Few usable stations: TEST has very few stations with clean, unflagged, CHIRPS-covered days, so every CI is wide.
- Gauge rain is the target; the corrector can only learn the gauge-vs-satellite relation at the 36 station sites, mostly lowland: it cannot be assumed to transfer to windward slopes.

Runtime 26.1 s.
