# Phase 6 live-capable hazard model report (v3-live)

Generated 2026-10-15T18:20:27Z from `data/processed/hazard/model_v3_live` (trained 2026-10-15T01:05:17Z, frozen 2026-10-15T18:19:57Z; calibration: per region). Bootstrap: 2000 resamples, 95% percentile intervals; positives resampled as events, universe rows iid per region. test_2018 was evaluated once with the frozen model, frozen baselines and frozen thresholds (evaluations recorded for this model: 1).

v3-live is the protocol-v2 model retrained on features that exist every morning (NASA IMERG rain, terrain), with per-region calibration. Its operational behaviour on live-timed inputs is in `reports/phase6_backtest.md`; everything on this page uses the training-style inputs.

## 0. Verdict: v3-live against frozen v2

**v3-live is live-capable and is not shown to be better than v2**: the paired 95% interval of the out-of-fold FA@90 difference (v3-live minus v2) includes zero (spec section 4.4). It is the model the live runner uses because v2 cannot run live; v2 stays as the archive reference.

| pooled OOF FA@90 (share of universe cell-days alerted at 90% recall) | value |
|---|---|
| v3-live (this model) | 0.1955 |
| frozen v2 | 0.1884 |
| difference, v3-live minus v2 (positive = v3-live has more false alarms) | +0.0071 (bootstrap mean +0.0059, SE 0.0149), 95% CI [-0.0203, +0.0384] |
| share of paired resamples in which v3-live is better | 0.374 |

2000 paired bootstrap resamples over the same development rows (year-blocked cross-validation over 2007-2017). This, not the test year, is the model-selection evidence; the test look below does not change the verdict.

### test_2018 at the recall-first Watch threshold: v3-live next to v2's frozen result

80 in-domain positive cell-days (5 more below the slope floor) and the weighted universe. Detection = share of the in-domain positive cell-days whose own cell scored at or above the Watch threshold; share on alert = weighted share of non-buffer universe cell-days at or above it. 95% bootstrap intervals (positives resampled as events).

| scorer / threshold | detection (recall) [95% CI] | share of cell-days on alert [95% CI] |
|---|---|---|
| v3-live (raw score 0.01818) | 83.8% [75.0, 91.2] | 21.2% [21.0, 21.4] |
| frozen v2 (raw score 0.02332) | 85.0% [77.5, 92.5] | 21.4% [21.2, 21.6] |
| v3-live, Himalaya | 83.3% [72.9, 93.8] | 23.4% [23.1, 23.6] |
| frozen v2, Himalaya | 87.5% [77.1, 95.8] | 23.9% [23.6, 24.1] |
| v3-live, Western Ghats | 84.4% [71.8, 96.9] | 13.3% [13.1, 13.5] |
| frozen v2, Western Ghats | 81.2% [65.6, 93.8] | 12.6% [12.4, 12.8] |
| v3-live, overall recall counting out-of-domain positives as misses | 78.8% [70.6, 87.1] | - |
| frozen v2, overall recall counting out-of-domain positives as misses | 80.0% [71.8, 88.2] | - |

**This comparison is descriptive, not a hypothesis test.** The two models are separate fits scored on the same test year, v2's figures are read from its frozen report (`reports/phase3_hazard_report.json`), and no paired test between them is made on test_2018 (80 positives cannot resolve a difference of this size). Each model uses its own frozen Watch threshold, so detection and alert share move together: compare them as a pair.

## 1. Gate assessment

**Recall-first target** (at least 90% of in-domain test_2018 events at the stage-1 Watch threshold, raw score 0.01818 = calibrated risk 0.000003015): NOT reached (shortfall 6.2 points; the 95% CI still contains 90%).

- test recall 83.8% [75.0, 91.2]; false-alarm share at that point 21.2% [21.0, 21.4] (universe non-buffer cell-days alerted)
- plain 90% OOF threshold: recall 83.8% [75.0, 91.2], FA share 17.8% [17.6, 18.0]
- per region: himalaya: recall 83.3% [72.9, 93.8], FA 23.4% [23.1, 23.6]; western_ghats: recall 84.4% [71.8, 96.9], FA 13.3% [13.1, 13.5]
- overall recall counting out-of-domain positives as misses: 78.8% [70.6, 87.1] (in-domain 83.8% [75.0, 91.2])

**Model versus baselines** (paired bootstrap, each scorer at its own frozen Watch threshold; the equal-recall column re-picks each scorer's threshold on the test labels and is descriptive only):

| baseline | model recall | baseline recall | recall: model minus baseline | model FA | baseline FA | FA: baseline minus model | equal-recall FA@90: baseline minus model | verdict |
|---|---|---|---|---|---|---|---|---|
| intensity-duration | 83.8% [75.0, 91.2] | 87.5% [80.0, 93.8] | -0.0375 [-0.1250, 0.0500] | 21.2% [21.0, 21.4] | 32.4% [32.2, 32.7] | 0.1126 [0.1104, 0.1150] | 0.0186 [-0.0930, 0.1770] | tie |
| LHASA-style | 83.8% [75.0, 91.2] | 88.8% [81.2, 95.0] | -0.0500 [-0.1250, 0.0250] | 21.2% [21.0, 21.4] | 39.8% [39.6, 40.1] | 0.1867 [0.1842, 0.1893] | 0.0940 [-0.0343, 0.2346] | tie |
| logistic regression | 83.8% [75.0, 91.2] | 86.2% [78.8, 93.8] | -0.0250 [-0.1000, 0.0500] | 21.2% [21.0, 21.4] | 40.9% [40.6, 41.1] | 0.1968 [0.1944, 0.1994] | 0.1784 [0.0308, 0.2994] | model better |

Verdict is read from the equal-recall FA@90 interval: `model better` / `<baseline> better` only when the 95% interval excludes 0, otherwise `tie`. Intervals that include 0 mean test_2018 cannot separate the scorers.

## 2. Stage-1 cross-validation results (summary; full tables in `reports/phase6_v3_cv_report.md`)

Year-blocked CV over 2007-2017, folds [[2007, 2008], [2009, 2010], [2011, 2012], [2013, 2014], [2015], [2016], [2017]]. Selected feature set `imerg_core` (26 inputs), 7 leaves, min_data_in_leaf 40, feature_fraction 0.5, lambda_l2 0, learning_rate 0.05, neg_mix `matched_plus_universe`, 315 trees (median of fold optima).

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

## 3. Frozen thresholds

Derived in stage 1 from each scorer's own pooled out-of-fold scores (Watch = recall-first: highest threshold whose bootstrap 5th-percentile OOF recall is at least 90%; Warning = OOF recall 75%; Emergency = OOF recall 50%). Raw-score units, except the deployed rule which alerts on calibrated risk >= the risk threshold (same ranking, but isotonic plateaus make it alert slightly more).

| scorer | Watch | plain 90% | Warning | Emergency |
|---|---|---|---|---|
| hazard model | 0.01818 | 0.02354 | 0.07457 | 0.20203 |
| intensity-duration | 2.38202 | 2.61954 | 5.38369 | 11.07515 |
| LHASA-style | 0.43955 | 0.69757 | 2.38913 | 5.22430 |
| logistic regression | -0.77190 | -0.65494 | -0.16185 | 0.41697 |

Calibrated-risk thresholds by region (per-region calibration: the same raw score maps to a different risk in each region, so the deployed rule alerts on `risk >= that region's threshold`, which is the raw threshold seen through the region's calibrator):

| level | raw score | Himalaya | Western Ghats |
|---|---|---|---|
| Watch | 0.01818 | 0.000002782 | 0.000003808 |
| Warning | 0.07457 | 0.000013766 | 0.000013681 |
| Emergency | 0.20203 | 0.000049227 | 0.000025643 |

## 4. test_2018 at the frozen thresholds

80 in-domain positive cell-days (5 more below the slope floor), 199,520 universe negative rows. Realised recall (positives resampled as events) and FA share (weighted share of non-buffer universe cell-days alerted), 95% bootstrap CIs; no threshold was re-picked on test.

| scorer | threshold | recall [95% CI] | FA share [95% CI] |
|---|---|---|---|
| hazard model | Watch (recall-first) | 83.8% [75.0, 91.2] | 21.2% [21.0, 21.4] |
| hazard model | plain 90% recall | 83.8% [75.0, 91.2] | 17.8% [17.6, 18.0] |
| hazard model | Warning (75%) | 62.5% [52.5, 72.5] | 7.1% [7.0, 7.2] |
| hazard model | Emergency (50%) | 41.2% [31.2, 52.5] | 2.0% [2.0, 2.1] |
| hazard model, deployed rule (risk threshold) | Watch (recall-first) | 86.2% [78.8, 93.8] | 26.2% [26.0, 26.4] |
| intensity-duration | Watch (recall-first) | 87.5% [80.0, 93.8] | 32.4% [32.2, 32.7] |
| intensity-duration | plain 90% recall | 85.0% [77.5, 92.5] | 30.7% [30.5, 30.9] |
| intensity-duration | Warning (75%) | 67.5% [57.5, 77.5] | 17.7% [17.5, 17.9] |
| intensity-duration | Emergency (50%) | 50.0% [40.0, 61.3] | 7.2% [7.1, 7.3] |
| LHASA-style | Watch (recall-first) | 88.8% [81.2, 95.0] | 39.8% [39.6, 40.1] |
| LHASA-style | plain 90% recall | 85.0% [77.5, 92.5] | 36.7% [36.4, 36.9] |
| LHASA-style | Warning (75%) | 76.2% [67.5, 85.0] | 24.1% [23.9, 24.3] |
| LHASA-style | Emergency (50%) | 57.5% [46.2, 67.5] | 13.9% [13.7, 14.1] |
| logistic regression | Watch (recall-first) | 86.2% [78.8, 93.8] | 40.9% [40.6, 41.1] |
| logistic regression | plain 90% recall | 85.0% [77.5, 92.5] | 36.3% [36.0, 36.5] |
| logistic regression | Warning (75%) | 68.8% [58.8, 78.8] | 19.0% [18.8, 19.2] |
| logistic regression | Emergency (50%) | 55.0% [45.0, 66.2] | 7.4% [7.3, 7.5] |

Paired differences at the Watch thresholds (model minus / minus model, positive favours the model):

| baseline | threshold | recall: model minus baseline | FA: baseline minus model |
|---|---|---|---|
| intensity-duration | Watch (recall-first) | -0.0375 [-0.1250, 0.0500] | 0.1126 [0.1104, 0.1150] |
| intensity-duration | plain 90% recall | -0.0125 [-0.1000, 0.0750] | 0.1290 [0.1268, 0.1312] |
| intensity-duration | Warning (75%) | -0.0500 [-0.1750, 0.0750] | 0.1064 [0.1045, 0.1084] |
| intensity-duration | Emergency (50%) | -0.0875 [-0.2250, 0.0375] | 0.0515 [0.0502, 0.0527] |
| LHASA-style | Watch (recall-first) | -0.0500 [-0.1250, 0.0250] | 0.1867 [0.1842, 0.1893] |
| LHASA-style | plain 90% recall | -0.0125 [-0.0875, 0.0625] | 0.1887 [0.1862, 0.1912] |
| LHASA-style | Warning (75%) | -0.1375 [-0.2500, -0.0250] | 0.1703 [0.1682, 0.1725] |
| LHASA-style | Emergency (50%) | -0.1625 [-0.2750, -0.0375] | 0.1188 [0.1170, 0.1207] |
| logistic regression | Watch (recall-first) | -0.0250 [-0.1000, 0.0500] | 0.1968 [0.1944, 0.1994] |
| logistic regression | plain 90% recall | -0.0125 [-0.0875, 0.0628] | 0.1848 [0.1824, 0.1873] |
| logistic regression | Warning (75%) | -0.0625 [-0.1875, 0.0625] | 0.1191 [0.1171, 0.1212] |
| logistic regression | Emergency (50%) | -0.1375 [-0.2625, -0.0125] | 0.0536 [0.0523, 0.0550] |

### Buffer rows counted as negatives (sensitivity)

| scorer | threshold | recall | FA share, buffer excluded | FA share, buffer included |
|---|---|---|---|---|
| hazard model | Watch (recall-first) | 83.8% [75.0, 91.2] | 21.2% [21.0, 21.4] | 21.3% |
| hazard model | plain 90% recall | 83.8% [75.0, 91.2] | 17.8% [17.6, 18.0] | 17.9% |
| hazard model, deployed rule (risk threshold) | Watch (recall-first) | 86.2% [78.8, 93.8] | 26.2% [26.0, 26.4] | 26.3% |
| intensity-duration | Watch (recall-first) | 87.5% [80.0, 93.8] | 32.4% [32.2, 32.7] | 32.5% |
| intensity-duration | plain 90% recall | 85.0% [77.5, 92.5] | 30.7% [30.5, 30.9] | 30.8% |
| LHASA-style | Watch (recall-first) | 88.8% [81.2, 95.0] | 39.8% [39.6, 40.1] | 39.9% |
| LHASA-style | plain 90% recall | 85.0% [77.5, 92.5] | 36.7% [36.4, 36.9] | 36.7% |
| logistic regression | Watch (recall-first) | 86.2% [78.8, 93.8] | 40.9% [40.6, 41.1] | 40.9% |
| logistic regression | plain 90% recall | 85.0% [77.5, 92.5] | 36.3% [36.0, 36.5] | 36.4% |

### Per region

**himalaya** (48 positives) - WARNING: only 48 positive cell-days (< 100): intervals are wide and unstable

| scorer | threshold | recall [95% CI] | FA share [95% CI] |
|---|---|---|---|
| hazard model | Watch (recall-first) | 83.3% [72.9, 93.8] | 23.4% [23.1, 23.6] |
| hazard model | plain 90% recall | 83.3% [72.9, 93.8] | 19.6% [19.4, 19.9] |
| hazard model, deployed rule (risk threshold) | Watch (recall-first) | 87.5% [77.1, 95.8] | 29.3% [29.1, 29.6] |
| intensity-duration | Watch (recall-first) | 87.5% [77.1, 95.8] | 33.4% [33.1, 33.7] |
| intensity-duration | plain 90% recall | 83.3% [72.9, 93.8] | 31.6% [31.3, 31.9] |
| LHASA-style | Watch (recall-first) | 85.4% [75.0, 93.8] | 41.6% [41.3, 41.9] |
| LHASA-style | plain 90% recall | 83.3% [72.9, 93.8] | 38.6% [38.4, 39.0] |
| logistic regression | Watch (recall-first) | 85.4% [75.0, 93.8] | 47.5% [47.2, 47.8] |
| logistic regression | plain 90% recall | 83.3% [72.9, 91.7] | 42.3% [42.0, 42.6] |

**western_ghats** (32 positives) - WARNING: only 32 positive cell-days (< 100): intervals are wide and unstable

| scorer | threshold | recall [95% CI] | FA share [95% CI] |
|---|---|---|---|
| hazard model | Watch (recall-first) | 84.4% [71.8, 96.9] | 13.3% [13.1, 13.5] |
| hazard model | plain 90% recall | 84.4% [71.8, 96.9] | 11.2% [11.0, 11.4] |
| hazard model, deployed rule (risk threshold) | Watch (recall-first) | 84.4% [71.8, 96.9] | 15.2% [14.9, 15.4] |
| intensity-duration | Watch (recall-first) | 87.5% [75.0, 96.9] | 29.0% [28.7, 29.2] |
| intensity-duration | plain 90% recall | 87.5% [75.0, 96.9] | 27.5% [27.2, 27.8] |
| LHASA-style | Watch (recall-first) | 93.8% [84.4, 100.0] | 33.6% [33.3, 33.9] |
| LHASA-style | plain 90% recall | 87.5% [75.0, 96.9] | 29.6% [29.3, 29.8] |
| logistic regression | Watch (recall-first) | 87.5% [75.0, 96.9] | 17.0% [16.8, 17.3] |
| logistic regression | plain 90% recall | 87.5% [75.0, 96.9] | 14.8% [14.5, 15.0] |

### Overall recall (out-of-domain positives count as misses)

| threshold | scope | scorer | in-domain recall | overall recall |
|---|---|---|---|---|
| Watch (recall-first) | all | hazard model | 83.8% [75.0, 91.2] | 78.8% [70.6, 87.1] |
| Watch (recall-first) | all | hazard model, deployed rule (risk threshold) | 86.2% [78.8, 93.8] | 81.2% [72.9, 89.4] |
| Watch (recall-first) | all | intensity-duration | 87.5% [80.0, 93.8] | 82.4% [74.1, 90.6] |
| Watch (recall-first) | all | LHASA-style | 88.8% [81.2, 95.0] | 83.5% [75.3, 90.6] |
| Watch (recall-first) | all | logistic regression | 86.2% [78.8, 93.8] | 81.2% [72.9, 89.4] |
| Watch (recall-first) | himalaya | hazard model | 83.3% [72.9, 93.8] | 81.6% [69.4, 91.8] |
| Watch (recall-first) | himalaya | hazard model, deployed rule (risk threshold) | 87.5% [77.1, 95.8] | 85.7% [75.5, 95.9] |
| Watch (recall-first) | himalaya | intensity-duration | 87.5% [77.1, 95.8] | 85.7% [75.5, 93.9] |
| Watch (recall-first) | himalaya | LHASA-style | 85.4% [75.0, 93.8] | 83.7% [73.5, 91.8] |
| Watch (recall-first) | himalaya | logistic regression | 85.4% [75.0, 93.8] | 83.7% [73.5, 93.9] |
| Watch (recall-first) | western_ghats | hazard model | 84.4% [71.9, 96.9] | 75.0% [61.1, 88.9] |
| Watch (recall-first) | western_ghats | hazard model, deployed rule (risk threshold) | 84.4% [71.9, 96.9] | 75.0% [61.1, 88.9] |
| Watch (recall-first) | western_ghats | intensity-duration | 87.5% [75.0, 96.9] | 77.8% [63.9, 88.9] |
| Watch (recall-first) | western_ghats | LHASA-style | 93.8% [84.4, 100.0] | 83.3% [69.4, 94.4] |
| Watch (recall-first) | western_ghats | logistic regression | 87.5% [75.0, 96.9] | 77.8% [63.9, 91.7] |
| plain 90% recall | all | hazard model | 83.8% [75.0, 91.2] | 78.8% [70.6, 87.1] |
| plain 90% recall | all | intensity-duration | 85.0% [76.2, 91.2] | 80.0% [70.6, 88.2] |
| plain 90% recall | all | LHASA-style | 85.0% [76.2, 92.5] | 80.0% [71.8, 88.2] |
| plain 90% recall | all | logistic regression | 85.0% [77.5, 92.5] | 80.0% [71.8, 88.2] |
| plain 90% recall | himalaya | hazard model | 83.3% [72.9, 93.8] | 81.6% [69.4, 91.8] |
| plain 90% recall | himalaya | intensity-duration | 83.3% [72.9, 93.8] | 81.6% [69.4, 91.8] |
| plain 90% recall | himalaya | LHASA-style | 83.3% [72.9, 93.8] | 81.6% [69.4, 91.8] |
| plain 90% recall | himalaya | logistic regression | 83.3% [70.8, 93.8] | 81.6% [69.4, 91.8] |
| plain 90% recall | western_ghats | hazard model | 84.4% [71.9, 96.9] | 75.0% [61.1, 88.9] |
| plain 90% recall | western_ghats | intensity-duration | 87.5% [75.0, 96.9] | 77.8% [63.9, 88.9] |
| plain 90% recall | western_ghats | LHASA-style | 87.5% [75.0, 96.9] | 77.8% [63.9, 91.7] |
| plain 90% recall | western_ghats | logistic regression | 87.5% [75.0, 96.9] | 77.8% [63.9, 91.7] |

### Descriptive: metrics with thresholds re-picked on test (not an operating result)

These choose each scorer's threshold from the test labels themselves; they compare ranking quality at equal recall or equal alert share. Weighted PR-AUC sits near the base rate for every scorer and its interval is very wide: read it with caution.

| scorer | FA @ 80% recall | FA @ 90% recall | FA @ 95% recall | recall @ FA 1% | recall @ FA 5% | PR-AUC |
|---|---|---|---|---|---|---|
| hazard model | 16.2% [11.9, 26.9] | 30.6% [16.8, 43.5] | 43.4% [29.1, 66.5] | 30.0% [20.0, 40.0] | 56.2% [45.0, 67.5] | 0.00046 [0.00013, 0.01292] |
| hazard model, deployed rule (risk threshold) | 17.9% [12.9, 31.5] | 31.5% [18.4, 45.0] | 44.9% [31.4, 99.9] | 26.2% [17.5, 35.0] | 47.5% [37.5, 57.5] | 0.00058 [0.00010, 0.02588] |
| intensity-duration | 24.1% [18.1, 31.8] | 32.5% [28.5, 41.3] | 41.2% [32.3, 65.4] | 26.2% [17.5, 36.2] | 46.2% [36.2, 57.5] | 0.00015 [0.00008, 0.00038] |
| LHASA-style | 28.0% [18.8, 39.2] | 40.0% [28.4, 45.1] | 44.9% [39.5, 100.0] | 8.8% [2.5, 16.2] | 30.0% [21.2, 41.2] | 0.00003 [0.00002, 0.00006] |
| logistic regression | 29.7% [19.3, 43.2] | 48.5% [32.6, 52.7] | 52.6% [46.2, 59.5] | 26.2% [17.5, 36.2] | 47.5% [37.5, 58.8] | 0.00015 [0.00007, 0.00038] |

Paired equal-recall FA@90 (baseline minus model):

| baseline | difference [95% CI] | verdict |
|---|---|---|
| intensity-duration | 0.0186 [-0.0930, 0.1770] | tie |
| LHASA-style | 0.0940 [-0.0343, 0.2346] | tie |
| logistic regression | 0.1784 [0.0308, 0.2994] | model better |

## 5. Calibration on test_2018

Calibrated probability that a cell-day has a landslide, at the test year's operating base rate; per 100k cell-days. Stage-1 cross-fitted calibration over-predicted by 38% and varied by more than 10x across years (the inventory's yearly recording rate), so a factor-of-two uncertainty on the probabilities is expected and a single test year cannot narrow it.

| scope | observed base rate | mean predicted | ECE (deciles) | ECE / base rate |
|---|---|---|---|---|
| all | 0.596 | 0.653 | 0.276 | 0.463 |
| himalaya | 0.458 | 0.466 | 0.188 | 0.411 |
| western_ghats | 1.089 | 1.322 | 0.594 | 0.546 |

Reliability, risk tail bins (low to high), per 100k cell-days:

| bin | population | positives | mean predicted | observed |
|---|---|---|---|---|
| 0 | 92.24% | 30 | 0.128 | 0.242 |
| 1 | 6.88% | 29 | 2.774 | 3.137 |
| 2 | 0.79% | 17 | 12.633 | 15.969 |
| 3 | 0.08% | 4 | 302.304 | 36.978 |

Reliability by deciles of risk:

| decile | population | positives | mean predicted | observed |
|---|---|---|---|---|
| 0 | 10.20% | 0 | 0.000 | 0.000 |
| 1 | 14.50% | 3 | 0.011 | 0.154 |
| 2 | 6.04% | 0 | 0.012 | 0.000 |
| 3 | 14.81% | 0 | 0.014 | 0.000 |
| 4 | 6.40% | 0 | 0.022 | 0.000 |
| 5 | 13.34% | 3 | 0.067 | 0.167 |
| 6 | 7.64% | 4 | 0.123 | 0.390 |
| 7 | 7.47% | 3 | 0.270 | 0.299 |
| 8 | 11.84% | 17 | 0.627 | 1.069 |
| 9 | 7.76% | 50 | 6.891 | 4.799 |

## 6. 2023 India window test (Watch threshold)

A window-positive cell is detected if the maximum score over the 46 window days of any of its 3x3 neighbourhood cells reaches the Watch threshold. Control cells are scored on their own cell only, so their any-alert share is an upper bound on false alarms: the inventory is partial and a control cell has one cell's chance where a detection has nine.

| scorer | Watch threshold | detected | detection share [95% CI] | controls alerted | control any-alert share [95% CI] | control cell-days alerted |
|---|---|---|---|---|---|---|
| hazard model | 0.01818 | 24/24 | 100.0% [100.0, 100.0] | 3113/4000 | 77.8% [76.6, 79.2] | 46.8% |
| hazard model, deployed rule (risk threshold) | n/a | 24/24 | 100.0% [100.0, 100.0] | 3322/4000 | 83.0% [81.9, 84.2] | 53.3% |
| intensity-duration | 2.38202 | 24/24 | 100.0% [100.0, 100.0] | 4000/4000 | 100.0% [100.0, 100.0] | 71.7% |
| LHASA-style | 0.43955 | 24/24 | 100.0% [100.0, 100.0] | 4000/4000 | 100.0% [100.0, 100.0] | 71.6% |
| logistic regression | -0.77190 | 24/24 | 100.0% [100.0, 100.0] | 3962/4000 | 99.1% [98.8, 99.3] | 68.4% |

The deployed rule has no single threshold in the table above: it alerts where the calibrated risk reaches the Watch risk threshold of the cell's own region (section 3).

## 7. Case studies (scored only; deployed rule: calibrated risk against the card's alert levels)

Thresholds (calibrated risk): Watch 0.000003808, Warning 0.000013681, Emergency 0.000025643.

### Kerala 2018 (2018-08-01 to 08-20)

- 23 positive cell-days: detected on the event day (cell or a neighbour at Watch+) 23/23; own cell at Watch+ 23; detected within 7 days before or on the event day 23.
- median first-alert lead 7.0 days; median consecutive Watch+ days before the event 7.0.
- alerted area: mean Watch+ share 32.1% of 8,048 cells (max 57.7%), mean Warning+ share 17.1%.

| cell | date | own level | detected | alert days before | first-alert lead (days) |
|---|---|---|---|---|---|
| 20405115 | 2018-08-05 | 1 | True | 4 | 4 |
| 19945134 | 2018-08-08 | 2 | True | 7 | 7 |
| 20035135 | 2018-08-08 | 2 | True | 7 | 7 |
| 20115127 | 2018-08-08 | 2 | True | 7 | 7 |
| 20345115 | 2018-08-08 | 3 | True | 7 | 7 |
| 20565111 | 2018-08-08 | 1 | True | 7 | 7 |
| 20305120 | 2018-08-09 | 3 | True | 7 | 7 |
| 20375119 | 2018-08-09 | 3 | True | 7 | 7 |
| 20385120 | 2018-08-09 | 3 | True | 7 | 7 |
| 19945137 | 2018-08-15 | 3 | True | 7 | 7 |
| 19965134 | 2018-08-15 | 3 | True | 7 | 7 |
| 20235117 | 2018-08-15 | 3 | True | 7 | 7 |
| 20495114 | 2018-08-15 | 3 | True | 7 | 7 |
| 19965138 | 2018-08-16 | 3 | True | 7 | 7 |
| 20065129 | 2018-08-16 | 3 | True | 7 | 7 |
| 20065137 | 2018-08-16 | 3 | True | 7 | 7 |
| 20375118 | 2018-08-16 | 3 | True | 7 | 7 |
| 20485114 | 2018-08-16 | 3 | True | 7 | 7 |
| 20025142 | 2018-08-17 | 3 | True | 7 | 7 |
| 20485114 | 2018-08-17 | 3 | True | 7 | 7 |
| 19955142 | 2018-08-18 | 3 | True | 7 | 7 |
| 20565112 | 2018-08-18 | 2 | True | 7 | 7 |
| 19925142 | 2018-08-19 | 3 | True | 7 | 7 |

Alerted area per day:

| date | cells | Watch+ cells | Watch+ share | Warning+ share | Emergency cells |
|---|---|---|---|---|---|
| 2018-08-01 | 8048 | 2168 | 26.9% | 14.4% | 679 |
| 2018-08-02 | 8048 | 2078 | 25.8% | 9.0% | 212 |
| 2018-08-03 | 8048 | 1946 | 24.2% | 8.0% | 128 |
| 2018-08-04 | 8048 | 2199 | 27.3% | 8.5% | 143 |
| 2018-08-05 | 8048 | 2137 | 26.6% | 7.1% | 84 |
| 2018-08-06 | 8048 | 1522 | 18.9% | 3.0% | 23 |
| 2018-08-07 | 8048 | 1692 | 21.0% | 5.8% | 78 |
| 2018-08-08 | 8048 | 2232 | 27.7% | 14.3% | 537 |
| 2018-08-09 | 8048 | 2587 | 32.1% | 19.1% | 927 |
| 2018-08-10 | 8048 | 2172 | 27.0% | 16.0% | 783 |
| 2018-08-11 | 8048 | 2181 | 27.1% | 18.2% | 938 |
| 2018-08-12 | 8048 | 2517 | 31.3% | 19.2% | 791 |
| 2018-08-13 | 8048 | 3199 | 39.7% | 24.1% | 1209 |
| 2018-08-14 | 8048 | 2916 | 36.2% | 23.5% | 1223 |
| 2018-08-15 | 8048 | 2845 | 35.4% | 26.1% | 1662 |
| 2018-08-16 | 8048 | 3314 | 41.2% | 27.2% | 1616 |
| 2018-08-17 | 8048 | 4641 | 57.7% | 40.3% | 2166 |
| 2018-08-18 | 8048 | 3247 | 40.3% | 22.5% | 1135 |
| 2018-08-19 | 8048 | 3062 | 38.0% | 21.5% | 1005 |
| 2018-08-20 | 8048 | 2952 | 36.7% | 14.6% | 383 |

### Wayanad 2024 (no NASA label: qualitative replay)

Focus cell 20295122 (0.8 km from the focus point), 9 cells within 10 km, 140 cells in the box. First Watch+ day: focus 2024-07-15, within 10 km 2024-07-15, box 2024-07-15. First Warning+ day: focus 2024-07-15, within 10 km 2024-07-15, box 2024-07-15. Peak risk within 10 km 41.82 per 100k on 2024-07-30.

| date | focus risk /100k | focus level | max within 10 km /100k | level | box max /100k | box level | box cells at Watch+ |
|---|---|---|---|---|---|---|---|
| 2024-07-15 | 19.72 | 3 | 19.72 | 3 | 28.49 | 3 | 140/140 |
| 2024-07-16 | 19.72 | 3 | 19.72 | 3 | 28.49 | 3 | 140/140 |
| 2024-07-17 | 19.72 | 3 | 19.72 | 3 | 19.72 | 3 | 140/140 |
| 2024-07-18 | 19.72 | 3 | 19.72 | 3 | 19.72 | 3 | 139/140 |
| 2024-07-19 | 19.72 | 3 | 28.49 | 3 | 41.82 | 3 | 140/140 |
| 2024-07-20 | 19.72 | 3 | 19.72 | 3 | 41.82 | 3 | 140/140 |
| 2024-07-21 | 6.51 | 3 | 14.59 | 3 | 19.72 | 3 | 133/140 |
| 2024-07-22 | 19.72 | 3 | 19.72 | 3 | 28.49 | 3 | 125/140 |
| 2024-07-23 | 19.72 | 3 | 19.72 | 3 | 19.72 | 3 | 128/140 |
| 2024-07-24 | 19.72 | 3 | 19.72 | 3 | 19.72 | 3 | 126/140 |
| 2024-07-25 | 19.72 | 3 | 19.72 | 3 | 19.72 | 3 | 128/140 |
| 2024-07-26 | 19.72 | 3 | 19.72 | 3 | 19.72 | 3 | 130/140 |
| 2024-07-27 | 19.72 | 3 | 19.72 | 3 | 19.72 | 3 | 129/140 |
| 2024-07-28 | 19.72 | 3 | 19.72 | 3 | 19.72 | 3 | 131/140 |
| 2024-07-29 | 19.72 | 3 | 19.72 | 3 | 19.72 | 3 | 117/140 |
| 2024-07-30 | 28.49 | 3 | 41.82 | 3 | 41.82 | 3 | 137/140 |
| 2024-07-31 | 19.72 | 3 | 19.72 | 3 | 19.72 | 3 | 129/140 |
| 2024-08-01 | 28.49 | 3 | 28.49 | 3 | 52.54 | 3 | 133/140 |
| 2024-08-02 | 19.72 | 3 | 19.72 | 3 | 19.72 | 3 | 126/140 |
| 2024-08-03 | 19.72 | 3 | 19.72 | 3 | 19.72 | 3 | 106/140 |
| 2024-08-04 | 2.56 | 3 | 4.75 | 3 | 11.18 | 3 | 70/140 |
| 2024-08-05 | 4.81 | 3 | 4.81 | 3 | 7.08 | 3 | 75/140 |

## 8. Leave-region-out (elevation-as-proxy check)

Frozen hyper-parameters, neg_mix and tree count, refitted on ONE region's development rows (no early stopping) and scored on the other region's test_2018 rows; the full model (trained on both regions) is the reference. Thresholds are re-picked on the test labels per scorer, so this compares ranking only. `no_elevation` drops the elevation-like columns (stat_elev_mean, stat_elev_std). Warnings flag fewer than 100 positives.

**himalaya development rows -> western_ghats test_2018** (32 positives) - WARNING: only 32 positive cell-days (< 100): intervals are wide and unstable

| scorer | FA @ 90% recall | recall @ FA 5% | PR-AUC | FA@90: scorer minus full model |
|---|---|---|---|---|
| full model | 19.5% [4.8, 55.7] | 78.1% [62.5, 90.6] | 0.00104 [0.00040, 0.00344] | - |
| region_only | 29.2% [5.2, 30.7] | 71.9% [56.2, 87.5] | 0.00062 [0.00031, 0.00151] | 0.0972 [-0.2635, 0.0988] (tie) |
| region_only_no_elevation | 23.0% [5.6, 35.2] | 71.9% [56.2, 87.5] | 0.00116 [0.00041, 0.03228] | 0.0350 [-0.2055, 0.1534] (tie) |

**western_ghats development rows -> himalaya test_2018** (48 positives) - WARNING: only 48 positive cell-days (< 100): intervals are wide and unstable

| scorer | FA @ 90% recall | recall @ FA 5% | PR-AUC | FA@90: scorer minus full model |
|---|---|---|---|---|
| full model | 34.5% [19.3, 47.4] | 45.8% [31.2, 60.4] | 0.02089 [0.00003, 0.06260] | - |
| region_only | 62.0% [33.8, 78.5] | 25.0% [12.5, 37.5] | 0.00002 [0.00001, 0.00003] | 0.2750 [0.0055, 0.4570] (full model better) |
| region_only_no_elevation | 72.0% [34.7, 81.5] | 25.0% [12.5, 37.5] | 0.00002 [0.00001, 0.00004] | 0.3754 [0.0972, 0.5434] (full model better) |

## 9. Ablations on test_2018 (reporting only; nothing selected)

Each stage-1 group candidate is refitted on all development rows with the frozen hyper-parameters and its own cross-validated tree count, and evaluated at ITS OWN out-of-fold recall-first threshold; the last column is the paired FA difference to the frozen model (`imerg_core`, positive = variant has more false alarms).

| variant | inputs | trees | threshold | OOF recall / FA | test recall | test FA share | FA: variant minus frozen model |
|---|---|---|---|---|---|---|---|
| imerg_core (frozen model) | 26 | 315 | 0.01818 | 91.8% / 22.8% | 83.8% [75.0, 91.2] | 21.2% [21.0, 21.4] | - |
| imerg_core_noelev | 24 | 190 | 0.02031 | 91.8% / 25.1% | 80.0% [71.2, 88.8] | 23.0% [22.7, 23.2] | 0.0179 [0.0164, 0.0193] |
| imerg_core+iapi | 29 | 289 | 0.01778 | 91.8% / 23.2% | 85.0% [76.2, 92.5] | 21.2% [21.0, 21.4] | -8.16e-05 [-0.0009, 0.0007] |
| imerg_core+inbr | 30 | 310 | 0.01769 | 91.8% / 22.9% | 83.8% [75.0, 91.2] | 21.2% [21.0, 21.4] | 0.0003 [-0.0005, 0.0012] |
| imerg_core+iapi+inbr | 33 | 253 | 0.01818 | 91.8% / 23.1% | 85.0% [76.2, 92.5] | 21.3% [21.1, 21.5] | 0.0016 [0.0007, 0.0026] |

## 10. Monotonicity and feature importance (frozen model)

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

## 11. Per-region calibration (cross-validation)

Per-region isotonic calibrators (a region with fewer than 25 OOF positives uses the pooled calibrator). Cross-fitted: each fold is calibrated by maps fitted on the other folds. Values per 100k cell-days at the region's own base rate; the pooled columns are the pooled calibrator on the same rows.

| region | OOF positives | calibrator | observed | predicted (per region) | ECE (per region) | predicted (pooled) | ECE (pooled) |
|---|---|---|---|---|---|---|---|
| himalaya | 682 | own | 0.595 | 1.013 | 0.437 | 0.613 | 0.055 |
| western_ghats | 107 | own | 0.333 | 0.724 | 0.415 | 1.206 | 0.902 |

## 12. Limits

- Statistical power is low: test_2018 has 80 in-domain positive cell-days (48 Himalaya, 32 Ghats), so every interval is wide; v3-live and v2 differ by less than those intervals, and the test year cannot separate them.
- test_2018 is a second look at the same year: v2 was evaluated on it (twice, the repeat disclosed in its record) and v1 before that. The v3-live model, its thresholds and its configuration were frozen before this look and nothing was tuned afterwards, but the year is not untouched. The model-selection evidence is the year-blocked cross-validation, not this test.
- The comparison with v2 on test_2018 is descriptive. The two models are scored on the same rows, but v2's numbers are read from its frozen report and no paired test between v2 and v3-live is made on the test year.
- Rain is IMERG V07 (Late run, 0.1 degree, mapped to the 0.05 degree cells), not the gauge-based IMD grid used by v2; IMERG daily totals are satellite estimates and can miss or smear short intense bursts on steep terrain.
- The landslide inventory is partial and rain-triggered only (NASA catalogs); unlabeled landslides sit among the universe negatives, so false-alarm shares are upper bounds. Its yearly recording rate varies more than 10-fold.
- Elevation (`stat_elev_mean`) is a leading feature and may act as a location or inventory-reporting proxy; leave-region-out (with and without elevation) is the check and, with few positives, only indicative.
- Per-region calibration changes the probabilities, not the ranking: the Watch, Warning and Emergency decisions are made on the raw score, and each region's risk thresholds are the same raw thresholds seen through its calibrator. Cross-fitted OOF calibration error is larger than the in-sample figure (see the calibration section).
- Operational (live) inputs differ from the training inputs (Early run for the newest day, a GFS or persisted tail for the 00-03 UTC hours); the train/live gap that causes is measured in `reports/phase6_backtest.md`, not here: every number on this page uses the training-style inputs.
