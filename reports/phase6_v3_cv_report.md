# Phase 3 hazard model: protocol v2 stage-1 cross-validation report

Generated 2026-10-15T01:05:17Z. v2: year-blocked CV over 2007-2017; v1 (validation-split selection) is disclosed history. No test_2018, window or case rows were read. Folds: [[2007, 2008], [2009, 2010], [2011, 2012], [2013, 2014], [2015], [2016], [2017]]. Development: 789 in-domain positive cell-days (+35 outside the slope domain, excluded), 8240 matched negatives, 399,272 universe negative rows (146,726,496 cell-days; base rate 0.538 per 100k). Runtime 8.4 min.

**Selected**: feature set `imerg_core` (26 inputs), 7 leaves, min_data_in_leaf 40, feature_fraction 0.5, lambda_l2 0, learning_rate 0.05, neg_mix `matched_plus_universe`, 315 trees.

## Hyper-parameter grid (top 10 of 17, pooled OOF)

| candidate | leaves | min leaf | feat frac | L2 | neg_mix | trees | OOF FA @ 90% recall | OOF log-loss | selected |
|---|---|---|---|---|---|---|---|---|---|
| grid_00_matched_plus_universe | 7 | 40 | 0.5 | 0 | matched_plus_universe | 315 | 19.6% | 0.2146 | yes |
| grid_00 | 7 | 40 | 0.5 | 0 | matched_only | 352 | 22.6% | 0.2072 |  |
| grid_10 | 15 | 40 | 0.8 | 0 | matched_only | 213 | 22.7% | 0.2071 |  |
| grid_08 | 15 | 40 | 0.5 | 0 | matched_only | 252 | 22.7% | 0.2047 |  |
| grid_12 | 15 | 80 | 0.5 | 0 | matched_only | 246 | 23.1% | 0.2066 |  |
| grid_13 | 15 | 80 | 0.5 | 5 | matched_only | 263 | 23.2% | 0.2062 |  |
| grid_06 | 7 | 80 | 0.8 | 0 | matched_only | 257 | 23.4% | 0.2098 |  |
| grid_09 | 15 | 40 | 0.5 | 5 | matched_only | 302 | 23.8% | 0.2050 |  |
| grid_07 | 7 | 80 | 0.8 | 5 | matched_only | 473 | 23.8% | 0.2090 |  |
| grid_04 | 7 | 80 | 0.5 | 0 | matched_only | 366 | 23.8% | 0.2077 |  |

## Feature-group selection (selected hyper-parameters)

A more complex candidate replaces a simpler one only if its pooled OOF FA@90 is lower by more than its own bootstrap SE. Stage 2 extends the stage-1 winner.

| stage | candidate | inputs | OOF FA@90 | bootstrap SE | 95% CI | OOF PR-AUC | trees | decision |
|---|---|---|---|---|---|---|---|---|
| 1 | imerg_core | 26 | 0.1955 | 0.0178 | [0.1679, 0.2348] | 0.00533 | 315 | selected |
| 1 | imerg_core_noelev | 24 | 0.2331 | 0.0124 | [0.2096, 0.2597] | 0.00394 | 190 |  |
| 2 | imerg_core | 26 | 0.1955 | 0.0178 | [0.1679, 0.2348] | 0.00533 | 315 | selected |
| 2 | imerg_core+iapi | 29 | 0.1988 | 0.0192 | [0.1665, 0.2358] | 0.00273 | 289 |  |
| 2 | imerg_core+inbr | 30 | 0.2043 | 0.0143 | [0.1797, 0.2338] | 0.00155 | 310 |  |
| 2 | imerg_core+iapi+inbr | 33 | 0.2012 | 0.0180 | [0.1703, 0.2356] | 0.00532 | 253 |  |

## OOF thresholds and alert levels (model)

recall_first = highest threshold whose bootstrap 5th-percentile OOF recall is at least 90%; Watch = recall_first, Warning = OOF recall 75%, Emergency = OOF recall 50%.

| threshold | raw score | calibrated risk | OOF recall | OOF FA share |
|---|---|---|---|---|
| plain_recall_90 | 0.02354 | 0.000003518 | 90.1% | 19.55% |
| recall_first | 0.01818 | 0.000003015 | 91.8% | 22.78% |
| watch | 0.01818 | 0.000003015 | 91.8% | 22.78% |
| warning | 0.07457 | 0.000011842 | 75.0% | 8.30% |
| emergency | 0.20203 | 0.000048147 | 50.1% | 2.60% |

## OOF metrics, model versus baselines (same protocol)

| scorer | FA @ 0.8 recall | FA @ 0.9 recall | FA @ 0.95 recall | recall @ FA 0.1% | recall @ FA 1.0% | recall @ FA 5.0% | recall @ FA 10.0% | PR-AUC |
|---|---|---|---|---|---|---|---|---|
| hazard model | 11.2% [9.6, 12.6] | 19.6% [16.8, 23.5] | 27.9% [25.3, 32.6] | 7.7% [5.8, 9.9] | 30.0% [27.0, 33.6] | 62.6% [59.2, 66.2] | 77.8% [74.9, 80.6] | 0.00533 [0.00146, 0.01420] |
| intensity-duration | 22.8% [20.5, 25.1] | 32.1% [30.8, 34.8] | 40.0% [37.4, 45.6] | 1.5% [0.8, 2.5] | 13.4% [11.2, 15.7] | 39.5% [36.1, 42.8] | 56.1% [52.5, 59.4] | 0.00004 [0.00004, 0.00005] |
| LHASA-style | 27.8% [25.7, 30.6] | 37.7% [35.1, 41.4] | 100.0% [43.6, 100.0] | 0.0% [0.0, 0.0] | 2.9% [1.8, 4.1] | 17.0% [14.2, 19.6] | 35.5% [32.1, 39.0] | 0.00002 [0.00002, 0.00002] |
| logistic regression | 23.4% [20.6, 26.0] | 36.1% [31.5, 41.2] | 49.1% [43.6, 55.5] | 1.6% [0.8, 2.7] | 14.6% [12.2, 16.9] | 39.9% [36.2, 43.3] | 60.2% [56.7, 63.4] | 0.00004 [0.00004, 0.00005] |

Own-OOF thresholds (each scorer's thresholds from its own pooled OOF scores):

| scorer | threshold | raw score | OOF recall [95% CI] | OOF FA share [95% CI] |
|---|---|---|---|---|
| hazard model | plain | 0.02354 | 90.1% [88.0, 92.1] | 19.6% [19.4, 19.7] |
| hazard model | recall_first | 0.01818 | 91.8% [89.9, 93.7] | 22.8% [22.6, 23.0] |
| intensity-duration | plain | 2.61954 | 90.1% [88.0, 92.1] | 32.1% [31.9, 32.3] |
| intensity-duration | recall_first | 2.38202 | 91.8% [89.7, 93.7] | 33.9% [33.7, 34.1] |
| LHASA-style | plain | 0.69757 | 90.1% [88.0, 92.0] | 37.7% [37.5, 37.9] |
| LHASA-style | recall_first | 0.43955 | 91.8% [89.7, 93.7] | 41.0% [40.8, 41.2] |
| logistic regression | plain | -0.65494 | 90.1% [88.0, 92.1] | 36.1% [35.9, 36.3] |
| logistic regression | recall_first | -0.77190 | 91.8% [89.7, 93.7] | 40.7% [40.5, 40.9] |

Paired OOF difference in FA share at 90% recall (comparator minus model; positive favours the model):

| comparator | difference [95% CI] | share of resamples model better | verdict |
|---|---|---|---|
| intensity-duration | 0.1257 [0.0913, 0.1582] | 1.00 | model better |
| LHASA-style | 0.1811 [0.1424, 0.2193] | 1.00 | model better |
| logistic regression | 0.1659 [0.1174, 0.2189] | 1.00 | model better |

## Per-fold variability (selected model)

Final tree count = median of fold optima [999, 352, 142, 316, 257, 315, 151] = 315.

| fold | years | positives | early-stop best iteration | FA@90 (fold only) | recall @ FA 5% | design log-loss |
|---|---|---|---|---|---|---|
| 0 | 2007-2008 | 16 | 999 | 0.1884 | 0.6875 | 0.0748 |
| 1 | 2009-2010 | 143 | 352 | 0.1642 | 0.6993 | 0.2187 |
| 2 | 2011-2012 | 126 | 142 | 0.1586 | 0.5635 | 0.2200 |
| 3 | 2013-2014 | 148 | 316 | 0.1572 | 0.7297 | 0.2165 |
| 4 | 2015 | 127 | 257 | 0.2071 | 0.5906 | 0.3819 |
| 5 | 2016 | 106 | 315 | 0.2086 | 0.6321 | 0.2250 |
| 6 | 2017 | 123 | 151 | 0.2634 | 0.5854 | 0.2391 |

## OOF calibration

Base rate 0.538 per 100k cell-days. The saved calibrator is isotonic on the pooled OOF scores (in-sample); the cross-fitted variant calibrates each fold with a map fitted on the other folds and is the honest check.

| calibrator | mean predicted per 100k | ECE (deciles) per 100k | ECE / base rate |
|---|---|---|---|
| insample | 0.538 | 6.94e-16 | 1.29e-15 |
| crossfit | 0.743 | 0.240 | 0.446 |

Per-year mean predicted versus observed risk, per 100k cell-days:

| year | positives | predicted (cross-fitted) | predicted (saved calibrator) | observed |
|---|---|---|---|---|
| 2007 | 8 | 0.850 | 0.686 | 0.065 |
| 2008 | 8 | 2.659 | 0.575 | 0.059 |
| 2009 | 32 | 0.463 | 0.452 | 0.238 |
| 2010 | 111 | 0.634 | 0.629 | 0.827 |
| 2011 | 79 | 0.568 | 0.544 | 0.588 |
| 2012 | 47 | 0.551 | 0.520 | 0.349 |
| 2013 | 97 | 0.580 | 0.564 | 0.722 |
| 2014 | 51 | 0.508 | 0.488 | 0.380 |
| 2015 | 127 | 0.402 | 0.443 | 0.946 |
| 2016 | 106 | 0.427 | 0.456 | 0.787 |
| 2017 | 123 | 0.537 | 0.570 | 0.916 |

## OOF calibration per region

Per-region isotonic calibrators (a region with fewer than 25 OOF positives uses the pooled calibrator). Cross-fitted: each fold is calibrated by maps fitted on the other folds. Values per 100k cell-days at the region's own base rate; the pooled columns are the pooled calibrator on the same rows.

| region | OOF positives | calibrator | observed | predicted (per region) | ECE (per region) | predicted (pooled) | ECE (pooled) |
|---|---|---|---|---|---|---|---|
| himalaya | 682 | own | 0.595 | 1.013 | 0.437 | 0.613 | 0.055 |
| western_ghats | 107 | own | 0.333 | 0.724 | 0.415 | 1.206 | 0.902 |

## Monotonicity (final model)

| feature | constraint | held | max violation |
|---|---|---|---|
| stat_relief | +1 | yes | 0.00000000 |
| stat_slope_mean | +1 | yes | 0.00000000 |
| stat_slope_p90 | +1 | yes | 0.00000000 |
| stat_slope_max | +1 | yes | 0.00000000 |
| irain_acc_1 | +1 | yes | 0.00000000 |
| irain_acc_3 | +1 | yes | 0.00000000 |
| irain_acc_5 | +1 | yes | 0.00000000 |
| irain_acc_7 | +1 | yes | 0.00000000 |
| irain_acc_14 | +1 | yes | 0.00000000 |
| irain_acc_30 | +1 | yes | 0.00000000 |
| irain_acc_60 | +1 | yes | 0.00000000 |
| irain_acc_90 | +1 | yes | 0.00000000 |
| irain_max1d_7 | +1 | yes | 0.00000000 |
| irain_max1d_30 | +1 | yes | 0.00000000 |
| irain_wetdays_30 | +1 | yes | 0.00000000 |
| irain_days_since_10mm | -1 | yes | 0.00000000 |
| irain_acc3_vs_clim | +1 | yes | 0.00000000 |
| irain_acc7_vs_clim | +1 | yes | 0.00000000 |
| irain_acc30_vs_clim | +1 | yes | 0.00000000 |

## Feature importance (gain, top 15)

| feature | share of gain |
|---|---|
| irain_acc_1 | 19.5% |
| stat_elev_mean | 14.7% |
| irain_acc_3 | 8.5% |
| stat_slope_max | 4.9% |
| stat_twi_proxy | 4.8% |
| irain_days_since_10mm | 4.6% |
| stat_slope_mean | 4.6% |
| irain_acc_14 | 4.2% |
| irain_share1_3 | 3.8% |
| stat_curvature_mean | 3.7% |
| irain_acc_7 | 3.6% |
| stat_relief | 3.4% |
| stat_aspect_cos | 3.2% |
| stat_aspect_sin | 2.8% |
| stat_elev_std | 2.5% |
