# Phase 3 hazard model report (protocol v2)

Generated 2026-10-03T16:19:14Z from `data/processed/hazard/model` (trained 2026-10-03T11:32:00Z, frozen 2026-10-03T11:39:44Z). Bootstrap: 2000 resamples, 95% percentile intervals; positives resampled as events, universe rows iid per region. test_2018 was evaluated once with the frozen model, frozen baselines and frozen thresholds (evaluations recorded for this model: 2).

## 0. Protocol history

**v1** (`reports/phase3_hazard_report_v1.md`, kept) chose hyper-parameters among 48 candidates on the 2016-17 validation split, early-stopped on a noisy false-alarm metric, and used that same split for the isotonic calibration AND the 90%-recall threshold. It was evaluated on test_2018, and the result was poor: a model that tied every baseline, a recall shortfall at the validation threshold, an over-confident calibration, and `stat_elev_mean` as the top feature.

- v1 test_2018 recall at its validation-chosen 90% threshold: 78.8% [70.0, 87.5] (target 90%), FA share 18.1% [17.9, 18.3]; overall recall incl. out-of-domain 74.1% [64.7, 83.5].
- v1 test FA@90 (own threshold): hazard model 28.2% [21.0, 45.0]; intensity-duration 31.8% [27.8, 41.2]; LHASA-style 40.1% [28.5, 45.1]; logistic regression 48.8% [31.8, 52.6].
- v1 test calibration: mean predicted 0.809 vs observed 0.596 per 100k cell-days (ECE 0.299 per 100k).
- v1 validation FA@90 (in-sample selection): 18.6% [16.4, 27.3]; top feature `stat_elev_mean`.

**v2** (`docs/phase3-design.md`, Protocol v2) was adopted AFTER the v1 test result had been seen, partly because of it. This is stated plainly: test_2018 has therefore been looked at once under v1, and v2 is not a clean first look at it. What v2 does is remove the specific reuse that made v1 optimistic: every choice (hyper-parameters, number of trees, feature groups, calibration, thresholds) is made by year-blocked cross-validation on 2007-2017 (train + validation), the model and thresholds were frozen (checksummed `FROZEN.json`) before any test scoring, and test_2018 is evaluated once with nothing changed afterwards.

## 1. Gate assessment

**Recall-first target** (at least 90% of in-domain test_2018 events at the stage-1 Watch threshold, raw score 0.02332 = calibrated risk 0.000004134): NOT reached (shortfall 5.0 points; the 95% CI still contains 90%).

- test recall 85.0% [77.5, 92.5]; false-alarm share at that point 21.4% [21.2, 21.6] (universe non-buffer cell-days alerted)
- plain 90% OOF threshold: recall 82.5% [73.8, 90.0], FA share 19.2% [19.0, 19.4]
- per region: himalaya: recall 87.5% [77.1, 95.8], FA 23.9% [23.6, 24.1]; western_ghats: recall 81.2% [65.6, 93.8], FA 12.6% [12.4, 12.8]
- overall recall counting out-of-domain positives as misses: 80.0% [71.8, 88.2] (in-domain 85.0% [76.2, 92.5])

**Model versus baselines** (paired bootstrap, each scorer at its own frozen Watch threshold; the equal-recall column re-picks each scorer's threshold on the test labels and is descriptive only):

| baseline | model recall | baseline recall | recall: model minus baseline | model FA | baseline FA | FA: baseline minus model | equal-recall FA@90: baseline minus model | verdict |
|---|---|---|---|---|---|---|---|---|
| intensity-duration | 85.0% [77.5, 92.5] | 87.5% [80.0, 93.8] | -0.0250 [-0.0875, 0.0375] | 21.4% [21.2, 21.6] | 32.4% [32.2, 32.7] | 0.1103 [0.1083, 0.1124] | 0.0393 [-0.1572, 0.1620] | tie |
| LHASA-style | 85.0% [77.5, 92.5] | 88.8% [81.2, 95.0] | -0.0375 [-0.1250, 0.0375] | 21.4% [21.2, 21.6] | 39.8% [39.6, 40.1] | 0.1844 [0.1821, 0.1866] | 0.1147 [-0.0728, 0.2440] | tie |
| logistic regression | 85.0% [77.5, 92.5] | 86.2% [78.8, 93.8] | -0.0125 [-0.0625, 0.0375] | 21.4% [21.2, 21.6] | 40.9% [40.6, 41.1] | 0.1945 [0.1923, 0.1969] | 0.1992 [0.0293, 0.2774] | model better |

Verdict is read from the equal-recall FA@90 interval: `model better` / `<baseline> better` only when the 95% interval excludes 0, otherwise `tie`. Intervals that include 0 mean test_2018 cannot separate the scorers.

**Limits**

- Statistical power is low: test_2018 has 80 in-domain positive cell-days (48 Himalaya, 32 Ghats), so every interval is wide and per-region and per-baseline comparisons are mostly unresolved.
- The landslide inventory is partial and rain-triggered only (NASA catalogs); unlabeled landslides sit among the universe negatives, so false-alarm shares are upper bounds. The inventory's yearly recording rate varies more than 10-fold across 2007-2017 (8 positives in 2007 and 2008 against 100+ in later years).
- Rain is the 0.25 degree IMD gauge grid (CHIRPS 0.05 degree elsewhere) at daily resolution: no hourly intensity, so short intense bursts are not resolved.
- Positives below the slope floor (outside the model domain) are excluded from training and the primary metrics and counted as misses in the overall recall.
- Elevation (`stat_elev_mean`) is the top feature and dropping it worsened cross-validated FA@90 by more than its standard error; it may act as a location or inventory-reporting proxy. Leave-region-out (with and without elevation) is the check, and with few positives it is only indicative.
- Calibrated probabilities use one pooled base rate; the cross-validated per-year observed rate varied by more than 10x, so the probabilities are uncertain by about a factor of two even where the ranking is good.
- Source-disagreement features (`src_`) were not selected; source disagreement is handled by the alert engine. The integ and corr groups were not selected, so how their features were constructed relative to the CV folds does not affect the frozen model.
- Labels are rain-triggered cell-days only; earthquake, construction and unknown triggers are excluded from positives and kept as buffer.

## 2. Stage-1 cross-validation results (summary; full tables in `reports/phase3_hazard_cv_report.md`)

Year-blocked CV over 2007-2017, folds [[2007, 2008], [2009, 2010], [2011, 2012], [2013, 2014], [2015], [2016], [2017]]. Selected feature set `drop_src` (30 inputs), 15 leaves, min_data_in_leaf 40, feature_fraction 0.5, lambda_l2 0, learning_rate 0.05, neg_mix `matched_plus_universe`, 118 trees (median of fold optima). The integ and corr groups were evaluated and not selected.

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

## 3. Frozen thresholds

Derived in stage 1 from each scorer's own pooled out-of-fold scores (Watch = recall-first: highest threshold whose bootstrap 5th-percentile OOF recall is at least 90%; Warning = OOF recall 75%; Emergency = OOF recall 50%). Raw-score units, except the deployed rule which alerts on calibrated risk >= the risk threshold (same ranking, but isotonic plateaus make it alert slightly more).

| scorer | Watch | plain 90% | Warning | Emergency |
|---|---|---|---|---|
| hazard model | 0.02332 | 0.02738 | 0.06997 | 0.16265 |
| hazard model, deployed rule (risk threshold) | 4.13e-06 | 5.87e-06 | 0.00002 | 0.00004 |
| intensity-duration | 2.38202 | 2.61954 | 5.38369 | 11.07515 |
| LHASA-style | 0.43955 | 0.69757 | 2.38913 | 5.22430 |
| logistic regression | -0.77190 | -0.65494 | -0.16185 | 0.41697 |

## 4. test_2018 at the frozen thresholds

80 in-domain positive cell-days (5 more below the slope floor), 199,520 universe negative rows. Realised recall (positives resampled as events) and FA share (weighted share of non-buffer universe cell-days alerted), 95% bootstrap CIs; no threshold was re-picked on test.

| scorer | threshold | recall [95% CI] | FA share [95% CI] |
|---|---|---|---|
| hazard model | Watch (recall-first) | 85.0% [77.5, 92.5] | 21.4% [21.2, 21.6] |
| hazard model | plain 90% recall | 82.5% [73.8, 90.0] | 19.2% [19.0, 19.4] |
| hazard model | Warning (75%) | 65.0% [53.8, 75.0] | 9.0% [8.9, 9.2] |
| hazard model | Emergency (50%) | 38.8% [28.7, 48.8] | 3.4% [3.3, 3.5] |
| hazard model, deployed rule (risk threshold) | Watch (recall-first) | 86.2% [78.8, 92.5] | 21.8% [21.6, 22.0] |
| hazard model, deployed rule (risk threshold) | plain 90% recall | 85.0% [77.5, 92.5] | 19.9% [19.7, 20.1] |
| hazard model, deployed rule (risk threshold) | Warning (75%) | 68.8% [58.8, 78.8] | 9.1% [9.0, 9.3] |
| hazard model, deployed rule (risk threshold) | Emergency (50%) | 38.8% [28.7, 48.8] | 3.5% [3.4, 3.6] |
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
| intensity-duration | Watch (recall-first) | -0.0250 [-0.0875, 0.0375] | 0.1103 [0.1083, 0.1124] |
| intensity-duration | plain 90% recall | -0.0250 [-0.0875, 0.0375] | 0.1153 [0.1133, 0.1174] |
| intensity-duration | Warning (75%) | -0.0250 [-0.1250, 0.0750] | 0.0871 [0.0854, 0.0889] |
| intensity-duration | Emergency (50%) | -0.1125 [-0.2125, -0.0125] | 0.0380 [0.0367, 0.0392] |
| LHASA-style | Watch (recall-first) | -0.0375 [-0.1250, 0.0375] | 0.1844 [0.1821, 0.1866] |
| LHASA-style | plain 90% recall | -0.0250 [-0.0875, 0.0500] | 0.1750 [0.1726, 0.1772] |
| LHASA-style | Warning (75%) | -0.1125 [-0.2000, -0.0250] | 0.1510 [0.1490, 0.1531] |
| LHASA-style | Emergency (50%) | -0.1875 [-0.3000, -0.0750] | 0.1053 [0.1036, 0.1072] |
| logistic regression | Watch (recall-first) | -0.0125 [-0.0625, 0.0375] | 0.1945 [0.1923, 0.1969] |
| logistic regression | plain 90% recall | -0.0250 [-0.1000, 0.0378] | 0.1712 [0.1689, 0.1735] |
| logistic regression | Warning (75%) | -0.0375 [-0.1375, 0.0625] | 0.0998 [0.0980, 0.1017] |
| logistic regression | Emergency (50%) | -0.1625 [-0.2625, -0.0625] | 0.0401 [0.0389, 0.0414] |

### Buffer rows counted as negatives (sensitivity)

| scorer | threshold | recall | FA share, buffer excluded | FA share, buffer included |
|---|---|---|---|---|
| hazard model | Watch (recall-first) | 85.0% [77.5, 92.5] | 21.4% [21.2, 21.6] | 21.5% |
| hazard model | plain 90% recall | 82.5% [73.8, 90.0] | 19.2% [19.0, 19.4] | 19.3% |
| hazard model, deployed rule (risk threshold) | Watch (recall-first) | 86.2% [78.8, 92.5] | 21.8% [21.6, 22.0] | 21.9% |
| hazard model, deployed rule (risk threshold) | plain 90% recall | 85.0% [77.5, 92.5] | 19.9% [19.7, 20.1] | 20.0% |
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
| hazard model | Watch (recall-first) | 87.5% [77.1, 95.8] | 23.9% [23.6, 24.1] |
| hazard model | plain 90% recall | 85.4% [75.0, 93.8] | 21.4% [21.1, 21.6] |
| hazard model, deployed rule (risk threshold) | Watch (recall-first) | 89.6% [81.2, 97.9] | 24.3% [24.0, 24.6] |
| hazard model, deployed rule (risk threshold) | plain 90% recall | 87.5% [77.1, 95.8] | 22.2% [21.9, 22.4] |
| intensity-duration | Watch (recall-first) | 87.5% [77.1, 95.8] | 33.4% [33.1, 33.7] |
| intensity-duration | plain 90% recall | 83.3% [72.9, 93.8] | 31.6% [31.3, 31.9] |
| LHASA-style | Watch (recall-first) | 85.4% [75.0, 93.8] | 41.6% [41.3, 41.9] |
| LHASA-style | plain 90% recall | 83.3% [72.9, 93.8] | 38.6% [38.4, 39.0] |
| logistic regression | Watch (recall-first) | 85.4% [75.0, 93.8] | 47.5% [47.2, 47.8] |
| logistic regression | plain 90% recall | 83.3% [72.9, 91.7] | 42.3% [42.0, 42.6] |

**western_ghats** (32 positives) - WARNING: only 32 positive cell-days (< 100): intervals are wide and unstable

| scorer | threshold | recall [95% CI] | FA share [95% CI] |
|---|---|---|---|
| hazard model | Watch (recall-first) | 81.2% [65.6, 93.8] | 12.6% [12.4, 12.8] |
| hazard model | plain 90% recall | 78.1% [62.5, 90.6] | 11.3% [11.1, 11.5] |
| hazard model, deployed rule (risk threshold) | Watch (recall-first) | 81.2% [65.6, 93.8] | 12.9% [12.7, 13.1] |
| hazard model, deployed rule (risk threshold) | plain 90% recall | 81.2% [65.6, 93.8] | 11.7% [11.5, 11.9] |
| intensity-duration | Watch (recall-first) | 87.5% [75.0, 96.9] | 29.0% [28.7, 29.2] |
| intensity-duration | plain 90% recall | 87.5% [75.0, 96.9] | 27.5% [27.2, 27.8] |
| LHASA-style | Watch (recall-first) | 93.8% [84.4, 100.0] | 33.6% [33.3, 33.9] |
| LHASA-style | plain 90% recall | 87.5% [75.0, 96.9] | 29.6% [29.3, 29.8] |
| logistic regression | Watch (recall-first) | 87.5% [75.0, 96.9] | 17.0% [16.8, 17.3] |
| logistic regression | plain 90% recall | 87.5% [75.0, 96.9] | 14.8% [14.5, 15.0] |

### Overall recall (out-of-domain positives count as misses)

| threshold | scope | scorer | in-domain recall | overall recall |
|---|---|---|---|---|
| Watch (recall-first) | all | hazard model | 85.0% [76.2, 92.5] | 80.0% [71.8, 88.2] |
| Watch (recall-first) | all | hazard model, deployed rule (risk threshold) | 86.2% [78.8, 92.5] | 81.2% [72.9, 89.4] |
| Watch (recall-first) | all | intensity-duration | 87.5% [80.0, 93.8] | 82.4% [74.1, 90.6] |
| Watch (recall-first) | all | LHASA-style | 88.8% [81.2, 95.0] | 83.5% [75.3, 90.6] |
| Watch (recall-first) | all | logistic regression | 86.2% [78.8, 93.8] | 81.2% [72.9, 89.4] |
| Watch (recall-first) | himalaya | hazard model | 87.5% [77.1, 95.8] | 85.7% [75.5, 93.9] |
| Watch (recall-first) | himalaya | hazard model, deployed rule (risk threshold) | 89.6% [79.2, 97.9] | 87.8% [77.6, 95.9] |
| Watch (recall-first) | himalaya | intensity-duration | 87.5% [77.1, 95.8] | 85.7% [75.5, 93.9] |
| Watch (recall-first) | himalaya | LHASA-style | 85.4% [75.0, 93.8] | 83.7% [73.5, 91.8] |
| Watch (recall-first) | himalaya | logistic regression | 85.4% [75.0, 93.8] | 83.7% [73.5, 93.9] |
| Watch (recall-first) | western_ghats | hazard model | 81.2% [65.6, 93.8] | 72.2% [58.3, 86.1] |
| Watch (recall-first) | western_ghats | hazard model, deployed rule (risk threshold) | 81.2% [65.6, 93.8] | 72.2% [58.3, 86.1] |
| Watch (recall-first) | western_ghats | intensity-duration | 87.5% [75.0, 96.9] | 77.8% [63.9, 88.9] |
| Watch (recall-first) | western_ghats | LHASA-style | 93.8% [84.4, 100.0] | 83.3% [69.4, 94.4] |
| Watch (recall-first) | western_ghats | logistic regression | 87.5% [75.0, 96.9] | 77.8% [63.9, 91.7] |
| plain 90% recall | all | hazard model | 82.5% [73.8, 90.0] | 77.6% [68.2, 85.9] |
| plain 90% recall | all | hazard model, deployed rule (risk threshold) | 85.0% [76.2, 92.5] | 80.0% [71.8, 88.2] |
| plain 90% recall | all | intensity-duration | 85.0% [76.2, 91.2] | 80.0% [70.6, 88.2] |
| plain 90% recall | all | LHASA-style | 85.0% [76.2, 92.5] | 80.0% [71.8, 88.2] |
| plain 90% recall | all | logistic regression | 85.0% [77.5, 92.5] | 80.0% [71.8, 88.2] |
| plain 90% recall | himalaya | hazard model | 85.4% [75.0, 93.8] | 83.7% [73.5, 93.9] |
| plain 90% recall | himalaya | hazard model, deployed rule (risk threshold) | 87.5% [77.1, 95.8] | 85.7% [75.5, 93.9] |
| plain 90% recall | himalaya | intensity-duration | 83.3% [72.9, 93.8] | 81.6% [69.4, 91.8] |
| plain 90% recall | himalaya | LHASA-style | 83.3% [72.9, 93.8] | 81.6% [69.4, 91.8] |
| plain 90% recall | himalaya | logistic regression | 83.3% [70.8, 93.8] | 81.6% [69.4, 91.8] |
| plain 90% recall | western_ghats | hazard model | 78.1% [62.5, 90.6] | 69.4% [55.5, 83.3] |
| plain 90% recall | western_ghats | hazard model, deployed rule (risk threshold) | 81.2% [65.6, 93.8] | 72.2% [58.3, 86.1] |
| plain 90% recall | western_ghats | intensity-duration | 87.5% [75.0, 96.9] | 77.8% [63.9, 88.9] |
| plain 90% recall | western_ghats | LHASA-style | 87.5% [75.0, 96.9] | 77.8% [63.9, 91.7] |
| plain 90% recall | western_ghats | logistic regression | 87.5% [75.0, 96.9] | 77.8% [63.9, 91.7] |

### Descriptive: metrics with thresholds re-picked on test (not an operating result)

These choose each scorer's threshold from the test labels themselves; they compare ranking quality at equal recall or equal alert share. Weighted PR-AUC sits near the base rate for every scorer and its interval is very wide: read it with caution.

| scorer | FA @ 80% recall | FA @ 90% recall | FA @ 95% recall | recall @ FA 1% | recall @ FA 5% | PR-AUC |
|---|---|---|---|---|---|---|
| hazard model | 15.2% [10.3, 24.5] | 28.6% [18.8, 48.4] | 48.3% [25.8, 72.6] | 25.0% [15.0, 35.0] | 48.8% [37.5, 60.0] | 0.00009 [0.00006, 0.00020] |
| hazard model, deployed rule (risk threshold) | 18.7% [11.6, 27.7] | 36.4% [19.7, 51.4] | 51.3% [27.6, 78.0] | 18.8% [11.2, 27.5] | 45.0% [33.8, 56.2] | 0.00008 [0.00005, 0.00016] |
| intensity-duration | 24.1% [18.1, 31.8] | 32.5% [28.5, 41.3] | 41.2% [32.3, 65.4] | 26.2% [17.5, 36.2] | 46.2% [36.2, 57.5] | 0.00015 [0.00008, 0.00038] |
| LHASA-style | 28.0% [18.8, 39.2] | 40.0% [28.4, 45.1] | 44.9% [39.5, 100.0] | 8.8% [2.5, 16.2] | 30.0% [21.2, 41.2] | 0.00003 [0.00002, 0.00006] |
| logistic regression | 29.7% [19.3, 43.2] | 48.5% [32.6, 52.7] | 52.6% [46.2, 59.5] | 26.2% [17.5, 36.2] | 47.5% [37.5, 58.8] | 0.00015 [0.00007, 0.00038] |

Paired equal-recall FA@90 (baseline minus model):

| baseline | difference [95% CI] | verdict |
|---|---|---|
| intensity-duration | 0.0393 [-0.1572, 0.1620] | tie |
| LHASA-style | 0.1147 [-0.0728, 0.2440] | tie |
| logistic regression | 0.1992 [0.0293, 0.2774] | model better |

## 5. Calibration on test_2018

Calibrated probability that a cell-day has a landslide, at the test year's operating base rate; per 100k cell-days. Stage-1 cross-fitted calibration over-predicted by 37% and varied by more than 10x across years (the inventory's yearly recording rate), so a factor-of-two uncertainty on the probabilities is expected and a single test year cannot narrow it.

| scope | observed base rate | mean predicted | ECE (deciles) | ECE / base rate |
|---|---|---|---|---|
| all | 0.596 | 0.522 | 0.075 | 0.125 |
| himalaya | 0.458 | 0.573 | 0.209 | 0.456 |
| western_ghats | 1.089 | 0.341 | 0.760 | 0.698 |

Reliability, risk tail bins (low to high), per 100k cell-days:

| bin | population | positives | mean predicted | observed |
|---|---|---|---|---|
| 0 | 90.86% | 25 | 0.148 | 0.205 |
| 1 | 8.31% | 40 | 3.165 | 3.585 |
| 2 | 0.78% | 13 | 12.509 | 12.379 |
| 3 | 0.05% | 2 | 53.707 | 29.848 |

Reliability by deciles of risk:

| decile | population | positives | mean predicted | observed |
|---|---|---|---|---|
| 0 | 13.96% | 0 | 0.000 | 0.000 |
| 1 | 8.01% | 0 | 0.008 | 0.000 |
| 2 | 16.83% | 2 | 0.026 | 0.088 |
| 3 | 7.03% | 1 | 0.041 | 0.106 |
| 4 | 15.15% | 2 | 0.047 | 0.098 |
| 6 | 11.36% | 4 | 0.115 | 0.262 |
| 7 | 7.78% | 3 | 0.278 | 0.287 |
| 8 | 10.73% | 13 | 0.793 | 0.902 |
| 9 | 9.14% | 55 | 4.241 | 4.481 |

## 6. 2023 India window test (Watch threshold)

A window-positive cell is detected if the maximum score over the 46 window days of any of its 3x3 neighbourhood cells reaches the Watch threshold. Control cells are scored on their own cell only, so their any-alert share is an upper bound on false alarms: the inventory is partial and a control cell has one cell's chance where a detection has nine.

| scorer | Watch threshold | detected | detection share [95% CI] | controls alerted | control any-alert share [95% CI] | control cell-days alerted |
|---|---|---|---|---|---|---|
| hazard model | 0.02332 | 24/24 | 100.0% [100.0, 100.0] | 3272/4000 | 81.8% [80.5, 83.0] | 46.7% |
| hazard model, deployed rule (risk threshold) | 4.13e-06 | 24/24 | 100.0% [100.0, 100.0] | 3285/4000 | 82.1% [80.9, 83.4] | 47.2% |
| intensity-duration | 2.38202 | 24/24 | 100.0% [100.0, 100.0] | 4000/4000 | 100.0% [100.0, 100.0] | 71.7% |
| LHASA-style | 0.43955 | 24/24 | 100.0% [100.0, 100.0] | 4000/4000 | 100.0% [100.0, 100.0] | 71.6% |
| logistic regression | -0.77190 | 24/24 | 100.0% [100.0, 100.0] | 3962/4000 | 99.1% [98.8, 99.3] | 68.4% |

## 7. Case studies (scored only; deployed rule: calibrated risk against the card's alert levels)

Thresholds (calibrated risk): Watch 0.000004134, Warning 0.000015831, Emergency 0.000036972.

### Kerala 2018 (2018-08-01 to 08-20)

- 23 positive cell-days: detected on the event day (cell or a neighbour at Watch+) 23/23; own cell at Watch+ 22; detected within 7 days before or on the event day 23.
- median first-alert lead 7.0 days; median consecutive Watch+ days before the event 7.0.
- alerted area: mean Watch+ share 31.9% of 8,048 cells (max 54.7%), mean Warning+ share 15.7%.

| cell | date | own level | detected | alert days before | first-alert lead (days) |
|---|---|---|---|---|---|
| 20405115 | 2018-08-05 | 1 | True | 4 | 4 |
| 19945134 | 2018-08-08 | 2 | True | 7 | 7 |
| 20035135 | 2018-08-08 | 2 | True | 7 | 7 |
| 20115127 | 2018-08-08 | 2 | True | 7 | 7 |
| 20345115 | 2018-08-08 | 3 | True | 7 | 7 |
| 20565111 | 2018-08-08 | 2 | True | 7 | 7 |
| 20305120 | 2018-08-09 | 3 | True | 7 | 7 |
| 20375119 | 2018-08-09 | 0 | True | 1 | 7 |
| 20385120 | 2018-08-09 | 1 | True | 1 | 7 |
| 19945137 | 2018-08-15 | 3 | True | 7 | 7 |
| 19965134 | 2018-08-15 | 3 | True | 7 | 7 |
| 20235117 | 2018-08-15 | 3 | True | 7 | 7 |
| 20495114 | 2018-08-15 | 2 | True | 7 | 7 |
| 19965138 | 2018-08-16 | 3 | True | 7 | 7 |
| 20065129 | 2018-08-16 | 3 | True | 7 | 7 |
| 20065137 | 2018-08-16 | 3 | True | 7 | 7 |
| 20375118 | 2018-08-16 | 2 | True | 7 | 7 |
| 20485114 | 2018-08-16 | 3 | True | 7 | 7 |
| 20025142 | 2018-08-17 | 2 | True | 7 | 7 |
| 20485114 | 2018-08-17 | 3 | True | 7 | 7 |
| 19955142 | 2018-08-18 | 2 | True | 7 | 7 |
| 20565112 | 2018-08-18 | 3 | True | 7 | 7 |
| 19925142 | 2018-08-19 | 2 | True | 7 | 7 |

Alerted area per day:

| date | cells | Watch+ cells | Watch+ share | Warning+ share | Emergency cells |
|---|---|---|---|---|---|
| 2018-08-01 | 8048 | 1519 | 18.9% | 7.3% | 185 |
| 2018-08-02 | 8048 | 1716 | 21.3% | 6.0% | 57 |
| 2018-08-03 | 8048 | 1498 | 18.6% | 4.0% | 25 |
| 2018-08-04 | 8048 | 1865 | 23.2% | 5.8% | 83 |
| 2018-08-05 | 8048 | 2101 | 26.1% | 7.5% | 115 |
| 2018-08-06 | 8048 | 1558 | 19.4% | 3.4% | 17 |
| 2018-08-07 | 8048 | 1666 | 20.7% | 4.9% | 60 |
| 2018-08-08 | 8048 | 2106 | 26.2% | 13.9% | 458 |
| 2018-08-09 | 8048 | 2686 | 33.4% | 19.7% | 931 |
| 2018-08-10 | 8048 | 2395 | 29.8% | 16.6% | 722 |
| 2018-08-11 | 8048 | 2436 | 30.3% | 14.5% | 489 |
| 2018-08-12 | 8048 | 2806 | 34.9% | 17.0% | 506 |
| 2018-08-13 | 8048 | 3153 | 39.2% | 24.8% | 991 |
| 2018-08-14 | 8048 | 3280 | 40.8% | 26.1% | 1165 |
| 2018-08-15 | 8048 | 3170 | 39.4% | 25.2% | 1248 |
| 2018-08-16 | 8048 | 3317 | 41.2% | 26.4% | 1283 |
| 2018-08-17 | 8048 | 4405 | 54.7% | 36.5% | 1438 |
| 2018-08-18 | 8048 | 3536 | 43.9% | 23.3% | 726 |
| 2018-08-19 | 8048 | 3368 | 41.8% | 19.7% | 444 |
| 2018-08-20 | 8048 | 2708 | 33.6% | 11.4% | 293 |

### Wayanad 2024 (no NASA label: qualitative replay)

Focus cell 20295122 (0.8 km from the focus point), 9 cells within 10 km, 140 cells in the box. First Watch+ day: focus 2024-07-15, within 10 km 2024-07-15, box 2024-07-15. First Warning+ day: focus 2024-07-15, within 10 km 2024-07-15, box 2024-07-15. Peak risk within 10 km 45.20 per 100k on 2024-07-17.

| date | focus risk /100k | focus level | max within 10 km /100k | level | box max /100k | box level | box cells at Watch+ |
|---|---|---|---|---|---|---|---|
| 2024-07-15 | 22.70 | 3 | 22.70 | 3 | 22.70 | 3 | 99/140 |
| 2024-07-16 | 22.70 | 3 | 22.70 | 3 | 34.39 | 3 | 115/140 |
| 2024-07-17 | 45.20 | 3 | 45.20 | 3 | 45.20 | 3 | 115/140 |
| 2024-07-18 | 22.70 | 3 | 34.39 | 3 | 45.20 | 3 | 118/140 |
| 2024-07-19 | 22.70 | 3 | 22.70 | 3 | 34.39 | 3 | 114/140 |
| 2024-07-20 | 22.70 | 3 | 22.70 | 3 | 34.39 | 3 | 98/140 |
| 2024-07-21 | 8.14 | 3 | 12.31 | 3 | 22.70 | 3 | 70/140 |
| 2024-07-22 | 10.60 | 3 | 10.60 | 3 | 22.70 | 3 | 61/140 |
| 2024-07-23 | 12.31 | 3 | 12.31 | 3 | 12.31 | 3 | 66/140 |
| 2024-07-24 | 8.14 | 3 | 8.14 | 3 | 18.27 | 3 | 65/140 |
| 2024-07-25 | 12.31 | 3 | 12.31 | 3 | 22.70 | 3 | 71/140 |
| 2024-07-26 | 22.70 | 3 | 22.70 | 3 | 34.39 | 3 | 82/140 |
| 2024-07-27 | 22.70 | 3 | 22.70 | 3 | 22.70 | 3 | 85/140 |
| 2024-07-28 | 7.47 | 3 | 7.47 | 3 | 8.14 | 3 | 67/140 |
| 2024-07-29 | 4.26 | 3 | 8.14 | 3 | 8.14 | 3 | 66/140 |
| 2024-07-30 | 45.20 | 3 | 45.20 | 3 | 45.20 | 3 | 121/140 |
| 2024-07-31 | 18.27 | 3 | 18.27 | 3 | 34.39 | 3 | 74/140 |
| 2024-08-01 | 22.70 | 3 | 22.70 | 3 | 45.20 | 3 | 115/140 |
| 2024-08-02 | 12.31 | 3 | 12.31 | 3 | 22.70 | 3 | 74/140 |
| 2024-08-03 | 7.47 | 3 | 8.14 | 3 | 10.60 | 3 | 69/140 |
| 2024-08-04 | 6.43 | 3 | 6.43 | 3 | 8.14 | 3 | 65/140 |
| 2024-08-05 | 3.74 | 3 | 3.74 | 3 | 4.26 | 3 | 56/140 |

## 8. Leave-region-out (elevation-as-proxy check)

Frozen hyper-parameters, neg_mix and tree count, refitted on ONE region's development rows (no early stopping) and scored on the other region's test_2018 rows; the full model (trained on both regions) is the reference. Thresholds are re-picked on the test labels per scorer, so this compares ranking only. `no_elevation` drops the elevation-like columns (stat_elev_mean, stat_elev_std). Warnings flag fewer than 100 positives.

**himalaya development rows -> western_ghats test_2018** (32 positives) - WARNING: only 32 positive cell-days (< 100): intervals are wide and unstable

| scorer | FA @ 90% recall | recall @ FA 5% | PR-AUC | FA@90: scorer minus full model |
|---|---|---|---|---|
| full model | 29.5% [8.6, 38.5] | 65.6% [50.0, 81.2] | 0.00026 [0.00014, 0.00081] | - |
| region_only | 23.1% [9.6, 26.6] | 71.9% [56.2, 87.5] | 0.00026 [0.00013, 0.00080] | -0.0643 [-0.1376, 0.0355] (tie) |
| region_only_no_elevation | 20.9% [7.4, 45.4] | 68.8% [53.1, 84.4] | 0.00042 [0.00015, 0.00259] | -0.0864 [-0.1409, 0.0939] (tie) |

**western_ghats development rows -> himalaya test_2018** (48 positives) - WARNING: only 48 positive cell-days (< 100): intervals are wide and unstable

| scorer | FA @ 90% recall | recall @ FA 5% | PR-AUC | FA@90: scorer minus full model |
|---|---|---|---|---|
| full model | 28.8% [16.7, 43.0] | 43.8% [31.2, 58.3] | 0.00007 [0.00003, 0.00017] | - |
| region_only | 53.7% [32.3, 70.9] | 33.3% [20.8, 45.8] | 0.00002 [0.00002, 0.00004] | 0.2493 [0.1185, 0.3201] (full model better) |
| region_only_no_elevation | 52.1% [35.9, 66.5] | 33.3% [20.8, 45.8] | 0.00002 [0.00002, 0.00006] | 0.2337 [0.1339, 0.3701] (full model better) |

## 9. Ablations on test_2018 (reporting only; nothing selected)

Each stage-1 group candidate is refitted on all development rows with the frozen hyper-parameters and its own cross-validated tree count, and evaluated at ITS OWN out-of-fold recall-first threshold; the last column is the paired FA difference to the frozen model (`drop_src`, positive = variant has more false alarms).

| variant | inputs | trees | threshold | OOF recall / FA | test recall | test FA share | FA: variant minus frozen model |
|---|---|---|---|---|---|---|---|
| full | 43 | 122 | 0.02211 | 91.8% / 21.4% | 83.8% [75.0, 91.2] | 21.6% [21.4, 21.8] | 0.0017 [0.0007, 0.0029] |
| stat_no_elevation | 41 | 106 | 0.01780 | 91.8% / 27.6% | 86.2% [78.8, 93.8] | 27.3% [27.0, 27.5] | 0.0588 [0.0572, 0.0604] |
| drop_src (frozen model) | 30 | 118 | 0.02332 | 91.8% / 20.9% | 85.0% [77.5, 92.5] | 21.4% [21.2, 21.6] | - |
| drop_wet | 37 | 129 | 0.02094 | 91.8% / 22.6% | 83.8% [75.0, 91.2] | 22.9% [22.7, 23.1] | 0.0146 [0.0135, 0.0158] |
| drop_src+integ | 35 | 175 | 0.01746 | 91.8% / 22.9% | 85.0% [76.2, 92.5] | 23.4% [23.2, 23.6] | 0.0199 [0.0189, 0.0210] |
| drop_src+corr | 34 | 147 | 0.01830 | 91.8% / 22.5% | 83.8% [75.0, 91.2] | 23.0% [22.8, 23.2] | 0.0162 [0.0151, 0.0173] |
| drop_src+integ+corr | 39 | 118 | 0.01990 | 91.8% / 22.0% | 82.5% [73.8, 91.2] | 22.4% [22.2, 22.6] | 0.0098 [0.0086, 0.0109] |

## 10. Monotonicity and feature importance (frozen model)

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
