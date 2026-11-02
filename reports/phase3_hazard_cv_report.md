# Phase 3 hazard model: protocol v2 stage-1 cross-validation report

Generated 2026-10-03T11:32:00Z. v2: year-blocked CV over 2007-2017; v1 (validation-split selection) is disclosed history. No test_2018, window or case rows were read. Folds: [[2007, 2008], [2009, 2010], [2011, 2012], [2013, 2014], [2015], [2016], [2017]]. Development: 789 in-domain positive cell-days (+35 outside the slope domain, excluded), 8240 matched negatives, 399,272 universe negative rows (146,726,496 cell-days; base rate 0.538 per 100k). Runtime 11.0 min.

**Selected**: feature set `drop_src` (30 inputs), 15 leaves, min_data_in_leaf 40, feature_fraction 0.5, lambda_l2 0, learning_rate 0.05, neg_mix `matched_plus_universe`, 118 trees.

## Hyper-parameter grid (top 10 of 17, pooled OOF)

| candidate | leaves | min leaf | feat frac | L2 | neg_mix | trees | OOF FA @ 90% recall | OOF log-loss | selected |
|---|---|---|---|---|---|---|---|---|---|
| grid_08_matched_plus_universe | 15 | 40 | 0.5 | 0 | matched_plus_universe | 122 | 19.8% | 0.2241 | yes |
| grid_08 | 15 | 40 | 0.5 | 0 | matched_only | 180 | 21.8% | 0.2129 |  |
| grid_10 | 15 | 40 | 0.8 | 0 | matched_only | 126 | 21.9% | 0.2149 |  |
| grid_07 | 7 | 80 | 0.8 | 5 | matched_only | 410 | 22.1% | 0.2131 |  |
| grid_13 | 15 | 80 | 0.5 | 5 | matched_only | 204 | 22.1% | 0.2119 |  |
| grid_14 | 15 | 80 | 0.8 | 0 | matched_only | 156 | 22.1% | 0.2136 |  |
| grid_12 | 15 | 80 | 0.5 | 0 | matched_only | 195 | 22.1% | 0.2123 |  |
| grid_09 | 15 | 40 | 0.5 | 5 | matched_only | 226 | 22.3% | 0.2114 |  |
| grid_01 | 7 | 40 | 0.5 | 5 | matched_only | 292 | 22.4% | 0.2134 |  |
| grid_03 | 7 | 40 | 0.8 | 5 | matched_only | 327 | 22.6% | 0.2137 |  |

## Feature-group selection (selected hyper-parameters)

A more complex candidate replaces a simpler one only if its pooled OOF FA@90 is lower by more than its own bootstrap SE. Stage 2 extends the stage-1 winner.

| stage | candidate | inputs | OOF FA@90 | bootstrap SE | 95% CI | OOF PR-AUC | trees | decision |
|---|---|---|---|---|---|---|---|---|
| 1 | full | 43 | 0.1982 | 0.0138 | [0.1680, 0.2196] | 0.00014 | 122 |  |
| 1 | stat_no_elevation | 41 | 0.2448 | 0.0174 | [0.2135, 0.2850] | 0.00010 | 106 |  |
| 1 | drop_src | 30 | 0.1884 | 0.0109 | [0.1726, 0.2128] | 0.00020 | 118 | selected |
| 1 | drop_wet | 37 | 0.2017 | 0.0141 | [0.1712, 0.2290] | 0.00013 | 129 |  |
| 2 | drop_src | 30 | 0.1884 | 0.0109 | [0.1726, 0.2128] | 0.00020 | 118 | selected |
| 2 | drop_src+integ | 35 | 0.2092 | 0.0169 | [0.1724, 0.2412] | 0.00019 | 175 |  |
| 2 | drop_src+corr | 34 | 0.1974 | 0.0168 | [0.1654, 0.2333] | 0.00016 | 147 |  |
| 2 | drop_src+integ+corr | 39 | 0.1931 | 0.0144 | [0.1670, 0.2282] | 0.00016 | 118 |  |

## OOF thresholds and alert levels (model)

recall_first = highest threshold whose bootstrap 5th-percentile OOF recall is at least 90%; Watch = recall_first, Warning = OOF recall 75%, Emergency = OOF recall 50%.

| threshold | raw score | calibrated risk | OOF recall | OOF FA share |
|---|---|---|---|---|
| plain_recall_90 | 0.02738 | 0.000005865 | 90.1% | 18.84% |
| recall_first | 0.02332 | 0.000004134 | 91.8% | 20.95% |
| watch | 0.02332 | 0.000004134 | 91.8% | 20.95% |
| warning | 0.06997 | 0.000015831 | 75.0% | 9.05% |
| emergency | 0.16265 | 0.000036972 | 50.1% | 3.44% |

## OOF metrics, model versus baselines (same protocol)

| scorer | FA @ 0.8 recall | FA @ 0.9 recall | FA @ 0.95 recall | recall @ FA 0.1% | recall @ FA 1.0% | recall @ FA 5.0% | recall @ FA 10.0% | PR-AUC |
|---|---|---|---|---|---|---|---|---|
| hazard model | 11.2% [9.8, 12.9] | 18.8% [17.3, 21.3] | 28.8% [24.1, 35.1] | 8.0% [6.1, 10.0] | 27.6% [24.5, 30.8] | 58.8% [55.3, 62.2] | 77.4% [74.5, 80.4] | 0.00020 [0.00014, 0.00793] |
| intensity-duration | 22.8% [20.5, 25.1] | 32.1% [30.8, 34.8] | 40.0% [37.4, 45.6] | 1.5% [0.8, 2.5] | 13.4% [11.2, 15.7] | 39.5% [36.1, 42.8] | 56.1% [52.5, 59.4] | 0.00004 [0.00004, 0.00005] |
| LHASA-style | 27.8% [25.7, 30.6] | 37.7% [35.1, 41.4] | 100.0% [43.6, 100.0] | 0.0% [0.0, 0.0] | 2.9% [1.8, 4.1] | 17.0% [14.2, 19.6] | 35.5% [32.1, 39.0] | 0.00002 [0.00002, 0.00002] |
| logistic regression | 23.4% [20.6, 26.0] | 36.1% [31.5, 41.2] | 49.1% [43.6, 55.5] | 1.6% [0.8, 2.7] | 14.6% [12.2, 16.9] | 39.9% [36.2, 43.3] | 60.2% [56.7, 63.4] | 0.00004 [0.00004, 0.00005] |

Own-OOF thresholds (each scorer's thresholds from its own pooled OOF scores):

| scorer | threshold | raw score | OOF recall [95% CI] | OOF FA share [95% CI] |
|---|---|---|---|---|
| hazard model | plain | 0.02738 | 90.1% [88.0, 92.3] | 18.8% [18.7, 19.0] |
| hazard model | recall_first | 0.02332 | 91.8% [89.7, 93.7] | 20.9% [20.8, 21.1] |
| intensity-duration | plain | 2.61954 | 90.1% [88.0, 92.1] | 32.1% [31.9, 32.3] |
| intensity-duration | recall_first | 2.38202 | 91.8% [89.7, 93.7] | 33.9% [33.7, 34.1] |
| LHASA-style | plain | 0.69757 | 90.1% [88.0, 92.0] | 37.7% [37.5, 37.9] |
| LHASA-style | recall_first | 0.43955 | 91.8% [89.7, 93.7] | 41.0% [40.8, 41.2] |
| logistic regression | plain | -0.65494 | 90.1% [88.0, 92.1] | 36.1% [35.9, 36.3] |
| logistic regression | recall_first | -0.77190 | 91.8% [89.7, 93.7] | 40.7% [40.5, 40.9] |

Paired OOF difference in FA share at 90% recall (comparator minus model; positive favours the model):

| comparator | difference [95% CI] | share of resamples model better | verdict |
|---|---|---|---|
| intensity-duration | 0.1328 [0.1115, 0.1526] | 1.00 | model better |
| LHASA-style | 0.1882 [0.1584, 0.2189] | 1.00 | model better |
| logistic regression | 0.1731 [0.1271, 0.2160] | 1.00 | model better |

## Per-fold variability (selected model)

Final tree count = median of fold optima [990, 118, 92, 107, 139, 95, 167] = 118.

| fold | years | positives | early-stop best iteration | FA@90 (fold only) | recall @ FA 5% | design log-loss |
|---|---|---|---|---|---|---|
| 0 | 2007-2008 | 16 | 990 | 0.1959 | 0.6875 | 0.0831 |
| 1 | 2009-2010 | 143 | 118 | 0.2225 | 0.5944 | 0.2415 |
| 2 | 2011-2012 | 126 | 92 | 0.1799 | 0.5873 | 0.2220 |
| 3 | 2013-2014 | 148 | 107 | 0.1500 | 0.6824 | 0.2332 |
| 4 | 2015 | 127 | 139 | 0.1927 | 0.6378 | 0.3821 |
| 5 | 2016 | 106 | 95 | 0.2035 | 0.5566 | 0.2253 |
| 6 | 2017 | 123 | 167 | 0.1932 | 0.5610 | 0.2384 |

## OOF calibration

Base rate 0.538 per 100k cell-days. The saved calibrator is isotonic on the pooled OOF scores (in-sample); the cross-fitted variant calibrates each fold with a map fitted on the other folds and is the honest check.

| calibrator | mean predicted per 100k | ECE (deciles) per 100k | ECE / base rate |
|---|---|---|---|
| insample | 0.538 | 8.55e-16 | 1.59e-15 |
| crossfit | 0.739 | 0.215 | 0.400 |

Per-year mean predicted versus observed risk, per 100k cell-days:

| year | positives | predicted (cross-fitted) | predicted (saved calibrator) | observed |
|---|---|---|---|---|
| 2007 | 8 | 0.838 | 0.671 | 0.065 |
| 2008 | 8 | 2.729 | 0.635 | 0.059 |
| 2009 | 32 | 0.468 | 0.467 | 0.238 |
| 2010 | 111 | 0.579 | 0.577 | 0.827 |
| 2011 | 79 | 0.495 | 0.485 | 0.588 |
| 2012 | 47 | 0.465 | 0.455 | 0.349 |
| 2013 | 97 | 0.508 | 0.512 | 0.722 |
| 2014 | 51 | 0.524 | 0.521 | 0.380 |
| 2015 | 127 | 0.457 | 0.476 | 0.946 |
| 2016 | 106 | 0.509 | 0.532 | 0.787 |
| 2017 | 123 | 0.559 | 0.595 | 0.916 |

## integ candidates with and without a nearby station

FA@90 within each subset uses that subset's own 90%-recall threshold; recall @ FA 5% likewise; the key metric is fa_at_recall_0.9

**with station** (341 positives, 17.5% of the universe cell-days)

| candidate | FA@90 (subset threshold) | recall @ FA 5% | PR-AUC |
|---|---|---|---|
| drop_src | 31.6% [27.4, 37.8] | 43.4% [37.8, 49.0] | 0.00027 [0.00018, 0.00914] |
| drop_src+integ | 32.7% [25.9, 38.7] | 46.9% [41.1, 52.2] | 0.00031 [0.00021, 0.00073] |
| drop_src+integ+corr | 33.2% [28.1, 38.9] | 44.6% [39.0, 49.9] | 0.00022 [0.00015, 0.00045] |

**without station** (448 positives, 82.5% of the universe cell-days)

| candidate | FA@90 (subset threshold) | recall @ FA 5% | PR-AUC |
|---|---|---|---|
| drop_src | 17.6% [14.2, 21.7] | 67.4% [62.9, 71.7] | 0.00680 [0.00010, 0.01795] |
| drop_src+integ | 19.6% [15.7, 24.7] | 69.2% [64.5, 73.2] | 0.00235 [0.00009, 0.00917] |
| drop_src+integ+corr | 19.4% [14.6, 25.8] | 67.4% [62.9, 72.1] | 0.00235 [0.00008, 0.01354] |

## Monotonicity (final model)

| feature | constraint | held | max violation |
|---|---|---|---|
| rain_acc_1 | +1 | yes | 0.00000000 |
| rain_acc_3 | +1 | yes | 0.00000000 |
| rain_acc_5 | +1 | yes | 0.00000000 |
| rain_acc_7 | +1 | yes | 0.00000000 |
| rain_acc_14 | +1 | yes | 0.00000000 |
| rain_acc_30 | +1 | yes | 0.00000000 |
| rain_max1d_7 | +1 | yes | 0.00000000 |
| rain_max1d_30 | +1 | yes | 0.00000000 |
| rain_wetdays_30 | +1 | yes | 0.00000000 |
| rain_days_since_10mm | -1 | yes | 0.00000000 |
| rain_acc3_vs_clim | +1 | yes | 0.00000000 |
| rain_acc7_vs_clim | +1 | yes | 0.00000000 |
| rain_acc30_vs_clim | +1 | yes | 0.00000000 |
| stat_relief | +1 | yes | 0.00000000 |
| stat_slope_mean | +1 | yes | 0.00000000 |
| stat_slope_p90 | +1 | yes | 0.00000000 |
| stat_slope_max | +1 | yes | 0.00000000 |

## Feature importance (gain, top 15)

| feature | share of gain |
|---|---|
| stat_elev_mean | 15.0% |
| rain_acc_1 | 11.1% |
| rain_acc_3 | 9.2% |
| stat_twi_proxy | 5.3% |
| rain_days_since_10mm | 4.9% |
| rain_acc_30 | 4.2% |
| rain_acc_14 | 4.1% |
| stat_curvature_mean | 4.0% |
| stat_elev_std | 3.8% |
| stat_slope_p90 | 3.8% |
| stat_relief | 3.7% |
| stat_slope_mean | 3.4% |
| stat_slope_max | 3.3% |
| rain_share1_3 | 3.2% |
| stat_aspect_cos | 3.1% |
