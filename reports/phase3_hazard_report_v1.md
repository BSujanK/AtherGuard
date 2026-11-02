# Phase 3 hazard model report

Generated 2026-10-01T19:23:46Z from `data/processed/hazard/model` (model trained 2026-10-01T19:16:33Z). Bootstrap: 2000 resamples, 95% percentile intervals; positives resampled as events, universe rows iid per region. Thresholds are chosen on validation and applied unchanged to test; no model, baseline or refit was tuned on test, the 2023 window or the case studies.

## Gate assessment

**Validation (own 90%-recall threshold per set)** - false-alarm share at 90% recall, model versus each baseline (paired bootstrap; positive difference favours the model):

| baseline | model FA | baseline FA | baseline minus model [95% CI] | verdict |
|---|---|---|---|---|
| intensity-duration | 0.1861 | 0.3199 | 0.1338 [0.0646, 0.1911] | model better |
| LHASA-style | 0.1861 | 0.3847 | 0.1986 [0.1237, 0.2566] | model better |
| logistic regression | 0.1861 | 0.3933 | 0.2072 [0.1184, 0.2463] | model better |

**test_2018 (own 90%-recall threshold per set)** - false-alarm share at 90% recall, model versus each baseline (paired bootstrap; positive difference favours the model):

| baseline | model FA | baseline FA | baseline minus model [95% CI] | verdict |
|---|---|---|---|---|
| intensity-duration | 0.2817 | 0.3175 | 0.0358 [-0.1308, 0.1337] | tie |
| LHASA-style | 0.2817 | 0.4006 | 0.1189 [-0.0504, 0.1855] | tie |
| logistic regression | 0.2817 | 0.4885 | 0.2067 [-0.0009, 0.2432] | tie |

**Recall-first target** (at least 90% of in-domain test_2018 events at the validation-chosen threshold, raw score 0.0472, calibrated risk 0.00001397): NOT reached (shortfall 11.3 points).

- test recall 78.8% [70.0, 87.5]; false-alarm share at that point 18.1% [17.9, 18.3]
- per region: himalaya: recall 77.1% [64.6, 87.5], FA 19.7% [19.5, 20.0]; western_ghats: recall 81.2% [65.6, 93.8], FA 12.1% [11.9, 12.3]
- overall recall counting out-of-domain positives as misses: 74.1% [64.7, 83.5] (in-domain only: 78.8% [70.0, 87.5])

**Limits**

- Statistical power is low: test_2018 has 80 in-domain positive cell-days (48 Himalaya, 32 Ghats); every interval is a bootstrap over events and universe rows and is wide.
- The landslide inventory is partial (NASA catalogs, rain-triggered, accuracy <= 5 km); unlabeled landslides sit among the negatives, so false-alarm shares are upper bounds.
- Rain comes from the 0.25 degree IMD gauge grid (CHIRPS 0.05 degree elsewhere) at daily resolution: no hourly intensity, so short intense bursts are not resolved.
- Labels are rain-triggered cell-days only; earthquake, construction and unknown triggers are excluded from positives and kept as buffer.
- Positives below the slope floor (outside the model domain) are excluded from training and the primary metrics and counted as misses in the overall recall.
- Calibrated probabilities refer to the all-year operating base rate of the evaluation split (of order 1e-6 per cell-day); isotonic calibration is fitted on validation, so validation ECE is in-sample.

Note: validation figures favour the hazard model by construction (hyper-parameters, early stopping and the calibrator were chosen on validation; the baselines have no tuned parameters). test_2018 is the out-of-sample comparison.

## Data

| split | in-domain positives | by region | out-of-domain positives | universe negative rows | universe cell-days | base rate per 100k cell-days |
|---|---|---|---|---|---|---|
| validation | 229 | himalaya 199, western_ghats 30 | 4 | 199,553 | 26,894,952 | 0.851 |
| test_2018 | 80 | himalaya 48, western_ghats 32 | 5 | 199,520 | 13,429,080 | 0.596 |

Universe negatives are non-buffer, non-positive rows with weights renormalised to the universe size per region; the false-alarm share is the weighted share of those cell-days alerted. PR-AUC is computed on positives plus that weighted population, so a no-skill scorer scores about the base rate (1e-5 or below). Weighted PR-AUC is dominated by the very top of the ranking (a top-ranked positive with no universe negative above it alone contributes 1/n_positives), so it is unstable: read it only with its interval.

## Model selection (validation only)

Metric: validation false-alarm share at 90% recall (lower is better), tie-break weighted PR-AUC. Selected: 16 leaves, min_data_in_leaf 20, feature_fraction 0.5, learning_rate 0.1, neg_mix `matched_only`, 65 trees. Training + selection + calibration + ensemble took 372 s. rain_days_since_10mm is constrained decreasing by assumption: more days since a 10 mm day never raises risk.

| rank | leaves | min leaf | feat frac | lr | neg_mix | trees | val FA @ 90% recall | val PR-AUC |
|---|---|---|---|---|---|---|---|---|
| 1 | 16 | 20 | 0.5 | 0.1 | matched_only | 65 | 0.1861 | 0.00458 |
| 2 | 8 | 20 | 0.5 | 0.1 | matched_plus_universe | 84 | 0.1883 | 0.00026 |
| 3 | 16 | 20 | 0.5 | 0.03 | matched_plus_universe | 278 | 0.1917 | 0.00456 |
| 4 | 16 | 20 | 0.5 | 0.1 | matched_plus_universe | 98 | 0.1948 | 0.00024 |
| 5 | 16 | 20 | 0.9 | 0.1 | matched_plus_universe | 143 | 0.1953 | 0.00020 |
| 6 | 16 | 60 | 0.5 | 0.1 | matched_only | 49 | 0.1955 | 0.00018 |
| 7 | 16 | 60 | 0.9 | 0.1 | matched_plus_universe | 92 | 0.1982 | 0.00025 |
| 8 | 8 | 60 | 0.9 | 0.03 | matched_plus_universe | 140 | 0.1997 | 0.00014 |
| 9 | 8 | 20 | 0.5 | 0.1 | matched_only | 26 | 0.2008 | 0.00017 |
| 10 | 16 | 60 | 0.5 | 0.03 | matched_plus_universe | 165 | 0.2010 | 0.00890 |
| 11 | 16 | 20 | 0.9 | 0.03 | matched_plus_universe | 204 | 0.2028 | 0.00020 |
| 12 | 8 | 60 | 0.5 | 0.1 | matched_plus_universe | 59 | 0.2048 | 0.00018 |
| 13 | 8 | 60 | 0.5 | 0.1 | matched_only | 61 | 0.2061 | 0.00018 |
| 14 | 8 | 20 | 0.9 | 0.03 | matched_plus_universe | 208 | 0.2062 | 0.00015 |
| 15 | 8 | 60 | 0.9 | 0.1 | matched_plus_universe | 72 | 0.2065 | 0.00889 |
| 16 | 16 | 20 | 0.9 | 0.1 | matched_only | 52 | 0.2097 | 0.00024 |
| 17 | 8 | 20 | 0.9 | 0.1 | matched_plus_universe | 68 | 0.2100 | 0.00452 |
| 18 | 4 | 20 | 0.5 | 0.1 | matched_plus_universe | 101 | 0.2107 | 0.00018 |
| 19 | 16 | 60 | 0.9 | 0.1 | matched_only | 60 | 0.2108 | 0.00457 |
| 20 | 16 | 60 | 0.5 | 0.1 | matched_plus_universe | 69 | 0.2145 | 0.00021 |
| 21 | 16 | 60 | 0.9 | 0.03 | matched_only | 86 | 0.2152 | 0.00018 |
| 22 | 4 | 60 | 0.5 | 0.1 | matched_plus_universe | 104 | 0.2157 | 0.00453 |
| 23 | 4 | 20 | 0.5 | 0.1 | matched_only | 75 | 0.2167 | 0.00016 |
| 24 | 8 | 60 | 0.9 | 0.1 | matched_only | 97 | 0.2170 | 0.00456 |
| 25 | 16 | 60 | 0.9 | 0.03 | matched_plus_universe | 112 | 0.2175 | 0.00015 |
| 26 | 8 | 20 | 0.9 | 0.03 | matched_only | 92 | 0.2187 | 0.00016 |
| 27 | 4 | 60 | 0.9 | 0.1 | matched_plus_universe | 83 | 0.2194 | 0.00015 |
| 28 | 4 | 60 | 0.9 | 0.1 | matched_only | 95 | 0.2195 | 0.00456 |
| 29 | 8 | 20 | 0.9 | 0.1 | matched_only | 49 | 0.2201 | 0.00454 |
| 30 | 4 | 20 | 0.9 | 0.1 | matched_plus_universe | 102 | 0.2207 | 0.00015 |
| 31 | 4 | 60 | 0.5 | 0.1 | matched_only | 67 | 0.2210 | 0.00016 |
| 32 | 4 | 20 | 0.9 | 0.1 | matched_only | 69 | 0.2236 | 0.00453 |
| 33 | 16 | 20 | 0.5 | 0.03 | matched_only | 30 | 0.2274 | 0.00013 |
| 34 | 16 | 60 | 0.5 | 0.03 | matched_only | 59 | 0.2290 | 0.00014 |
| 35 | 8 | 60 | 0.5 | 0.03 | matched_only | 28 | 0.2302 | 0.00013 |
| 36 | 8 | 20 | 0.5 | 0.03 | matched_only | 33 | 0.2317 | 0.00014 |
| 37 | 4 | 20 | 0.5 | 0.03 | matched_only | 48 | 0.2352 | 0.00011 |
| 38 | 4 | 60 | 0.5 | 0.03 | matched_only | 48 | 0.2352 | 0.00011 |
| 39 | 16 | 20 | 0.9 | 0.03 | matched_only | 18 | 0.2395 | 0.00012 |
| 40 | 4 | 20 | 0.9 | 0.03 | matched_only | 43 | 0.2433 | 0.00011 |
| 41 | 4 | 60 | 0.9 | 0.03 | matched_only | 43 | 0.2433 | 0.00011 |
| 42 | 8 | 60 | 0.9 | 0.03 | matched_only | 18 | 0.2454 | 0.00011 |
| 43 | 8 | 20 | 0.5 | 0.03 | matched_plus_universe | 40 | 0.2493 | 0.00012 |
| 44 | 8 | 60 | 0.5 | 0.03 | matched_plus_universe | 39 | 0.2519 | 0.00012 |
| 45 | 4 | 20 | 0.9 | 0.03 | matched_plus_universe | 53 | 0.2624 | 0.00010 |
| 46 | 4 | 60 | 0.9 | 0.03 | matched_plus_universe | 53 | 0.2624 | 0.00010 |
| 47 | 4 | 20 | 0.5 | 0.03 | matched_plus_universe | 43 | 0.2717 | 0.00010 |
| 48 | 4 | 60 | 0.5 | 0.03 | matched_plus_universe | 43 | 0.2717 | 0.00010 |

## Validation (thresholds chosen on the set itself)

229 in-domain positives, 199,553 universe negative rows.

| scorer | FA share @ 80% recall | FA share @ 90% recall | FA share @ 95% recall | recall @ FA 0.1% | recall @ FA 1.0% | recall @ FA 5.0% | recall @ FA 10.0% | weighted PR-AUC |
|---|---|---|---|---|---|---|---|---|
| hazard model | 13.0% [11.7, 15.6] | 18.6% [16.4, 27.3] | 30.6% [22.8, 43.4] | 7.9% [4.4, 11.8] | 23.6% [18.3, 29.7] | 52.0% [45.9, 58.5] | 72.1% [66.4, 77.7] | 0.00458 [0.00014, 0.01771] |
| intensity-duration | 24.4% [21.0, 27.9] | 32.0% [28.2, 39.4] | 45.3% [34.3, 54.8] | 1.3% [0.0, 3.1] | 11.4% [7.4, 15.3] | 36.2% [30.1, 42.8] | 55.5% [48.9, 62.0] | 0.00006 [0.00005, 0.00008] |
| LHASA-style | 27.0% [22.7, 32.0] | 38.5% [32.8, 44.7] | 100.0% [40.8, 100.0] | 0.0% [0.0, 0.0] | 3.5% [1.3, 6.6] | 20.1% [14.8, 25.8] | 37.6% [31.4, 44.1] | 0.00003 [0.00002, 0.00003] |
| logistic regression | 23.7% [17.9, 29.8] | 39.3% [30.9, 44.4] | 46.6% [41.5, 60.8] | 0.0% [0.0, 0.0] | 12.2% [8.3, 17.0] | 35.8% [29.7, 42.4] | 57.2% [50.7, 63.8] | 0.00006 [0.00005, 0.00008] |

Paired comparison (FA share at 90% recall):

| comparator | FA share: comparator minus model (95% CI) | share of resamples model better | verdict |
|---|---|---|---|
| intensity-duration | 0.1338 [0.0646, 0.1911] | 1.00 | model better |
| LHASA-style | 0.1986 [0.1237, 0.2566] | 1.00 | model better |
| logistic regression | 0.2072 [0.1184, 0.2463] | 1.00 | model better |

## test_2018 (thresholds chosen on the set itself)

80 in-domain positives, 199,520 universe negative rows.

| scorer | FA share @ 80% recall | FA share @ 90% recall | FA share @ 95% recall | recall @ FA 0.1% | recall @ FA 1.0% | recall @ FA 5.0% | recall @ FA 10.0% | weighted PR-AUC |
|---|---|---|---|---|---|---|---|---|
| hazard model | 19.0% [12.1, 27.4] | 28.2% [21.0, 45.0] | 44.8% [27.6, 70.6] | 6.2% [1.2, 11.2] | 23.8% [15.0, 33.8] | 52.5% [41.2, 63.7] | 67.5% [56.2, 77.5] | 0.00011 [0.00006, 0.00030] |
| intensity-duration | 24.3% [18.1, 30.9] | 31.8% [27.8, 41.2] | 41.1% [31.6, 65.9] | 10.0% [3.8, 16.2] | 26.2% [17.5, 36.2] | 46.2% [36.2, 57.5] | 56.2% [46.2, 67.5] | 0.00015 [0.00008, 0.00038] |
| LHASA-style | 28.0% [18.9, 39.2] | 40.1% [28.5, 45.1] | 44.9% [39.6, 100.0] | 2.5% [0.0, 6.2] | 8.8% [2.5, 16.2] | 30.0% [21.2, 41.2] | 48.8% [37.5, 60.0] | 0.00003 [0.00002, 0.00006] |
| logistic regression | 30.7% [19.2, 38.6] | 48.8% [31.8, 52.6] | 52.5% [42.9, 60.2] | 8.8% [3.7, 15.0] | 26.2% [17.5, 36.2] | 50.0% [40.0, 61.3] | 57.5% [47.5, 68.8] | 0.00017 [0.00008, 0.00050] |

Paired comparison (FA share at 90% recall):

| comparator | FA share: comparator minus model (95% CI) | share of resamples model better | verdict |
|---|---|---|---|
| intensity-duration | 0.0358 [-0.1308, 0.1337] | 0.76 | tie |
| LHASA-style | 0.1189 [-0.0504, 0.1855] | 0.89 | tie |
| logistic regression | 0.2067 [-0.0009, 0.2432] | 0.97 | tie |

## test_2018 at validation-chosen thresholds

Thresholds were fixed on validation; recall and false-alarm share are what they realise on test (95% CIs).

| scorer | validation-chosen threshold | raw score | realised recall | realised FA share |
|---|---|---|---|---|
| hazard model | recall_0.8 | 0.0718 | 70.0% [58.8, 80.0] | 12.3% [12.1, 12.5] |
| hazard model | recall_0.9 | 0.0472 | 78.8% [70.0, 87.5] | 18.1% [17.9, 18.3] |
| hazard model | recall_0.95 | 0.0271 | 91.2% [85.0, 97.5] | 30.7% [30.5, 31.0] |
| hazard model | fa_0.001 | 0.7416 | 2.5% [0.0, 6.2] | 0.1% [0.1, 0.1] |
| hazard model | fa_0.01 | 0.4332 | 20.0% [11.2, 28.7] | 0.8% [0.7, 0.8] |
| hazard model | fa_0.05 | 0.1772 | 51.2% [40.0, 62.5] | 4.5% [4.4, 4.6] |
| hazard model | fa_0.1 | 0.0954 | 67.5% [56.2, 77.5] | 9.2% [9.1, 9.4] |
| intensity-duration | recall_0.8 | 3.9267 | 77.5% [68.8, 86.2] | 22.7% [22.5, 22.9] |
| intensity-duration | recall_0.9 | 2.5263 | 85.0% [77.5, 92.5] | 30.5% [30.2, 30.7] |
| intensity-duration | recall_0.95 | 1.1095 | 96.2% [91.2, 100.0] | 44.4% [44.1, 44.6] |
| intensity-duration | fa_0.001 | 71.7717 | 5.0% [1.2, 10.0] | 0.1% [0.0, 0.1] |
| intensity-duration | fa_0.01 | 31.5326 | 23.8% [15.0, 32.5] | 0.8% [0.7, 0.8] |
| intensity-duration | fa_0.05 | 14.5818 | 46.2% [36.2, 57.5] | 4.4% [4.3, 4.5] |
| intensity-duration | fa_0.1 | 9.5067 | 53.8% [43.8, 63.7] | 9.0% [8.8, 9.1] |
| LHASA-style | recall_0.8 | 1.9808 | 77.5% [67.5, 86.2] | 26.4% [26.2, 26.6] |
| LHASA-style | recall_0.9 | 0.6152 | 86.2% [78.8, 93.8] | 37.6% [37.4, 37.9] |
| LHASA-style | recall_0.95 | 0.0000 | 100.0% [100.0, 100.0] | 100.0% [100.0, 100.0] |
| LHASA-style | fa_0.001 | 106.4489 | 1.2% [0.0, 3.8] | 0.1% [0.1, 0.1] |
| LHASA-style | fa_0.01 | 33.3894 | 7.5% [2.5, 13.8] | 0.9% [0.9, 1.0] |
| LHASA-style | fa_0.05 | 12.7072 | 30.0% [20.0, 41.2] | 4.8% [4.6, 4.9] |
| LHASA-style | fa_0.1 | 7.4259 | 48.8% [37.5, 60.0] | 9.6% [9.5, 9.8] |
| logistic regression | recall_0.8 | -0.3334 | 75.0% [65.0, 85.0] | 22.6% [22.4, 22.8] |
| logistic regression | recall_0.9 | -0.7760 | 86.2% [78.8, 93.8] | 38.1% [37.9, 38.4] |
| logistic regression | recall_0.95 | -0.9727 | 88.8% [81.2, 95.0] | 45.6% [45.4, 45.8] |
| logistic regression | fa_0.001 | 6.5963 | 3.8% [0.0, 8.8] | 0.0% [0.0, 0.0] |
| logistic regression | fa_0.01 | 2.3498 | 26.2% [17.5, 36.2] | 0.7% [0.7, 0.8] |
| logistic regression | fa_0.05 | 0.7887 | 50.0% [40.0, 61.3] | 4.3% [4.2, 4.4] |
| logistic regression | fa_0.1 | 0.2691 | 56.2% [46.2, 67.5] | 9.2% [9.0, 9.3] |

## test_2018 by region

**himalaya** (48 positives) - WARNING: only 48 positive cell-days (< 100): intervals are wide and unstable

| scorer | FA share @ 80% recall | FA share @ 90% recall | FA share @ 95% recall | recall @ FA 0.1% | recall @ FA 1.0% | recall @ FA 5.0% | recall @ FA 10.0% | weighted PR-AUC |
|---|---|---|---|---|---|---|---|---|
| hazard model | 27.3% [11.6, 30.8] | 31.1% [27.2, 49.4] | 40.4% [30.0, 63.2] | 6.2% [0.0, 14.6] | 20.8% [10.4, 33.3] | 45.8% [33.3, 58.4] | 66.7% [52.1, 79.2] | 0.00010 [0.00004, 0.00059] |
| intensity-duration | 28.8% [20.5, 36.3] | 38.7% [28.9, 67.4] | 55.1% [31.6, 68.1] | 2.1% [0.0, 6.2] | 20.8% [10.4, 33.3] | 37.5% [25.0, 52.1] | 52.1% [37.5, 66.7] | 0.00006 [0.00003, 0.00013] |
| LHASA-style | 30.6% [21.2, 43.1] | 46.2% [30.6, 100.0] | 100.0% [41.7, 100.0] | 0.0% [0.0, 8.3] | 8.3% [2.1, 16.7] | 25.0% [12.5, 37.5] | 43.8% [29.2, 56.2] | 0.00002 [0.00001, 0.00007] |
| logistic regression | 36.7% [19.8, 56.7] | 58.1% [36.9, 61.0] | 60.3% [49.6, 74.5] | 0.0% [0.0, 0.0] | 16.7% [6.2, 27.1] | 45.8% [31.2, 60.4] | 52.1% [37.5, 64.6] | 0.00004 [0.00002, 0.00008] |

| scorer | validation-chosen threshold | raw score | realised recall | realised FA share |
|---|---|---|---|---|
| hazard model | recall_0.9 | 0.0472 | 77.1% [64.6, 87.5] | 19.7% [19.5, 20.0] |
| intensity-duration | recall_0.9 | 2.5263 | 83.3% [72.9, 93.8] | 31.3% [31.1, 31.6] |
| LHASA-style | recall_0.9 | 0.6152 | 85.4% [75.0, 93.8] | 39.5% [39.2, 39.8] |
| logistic regression | recall_0.9 | -0.7760 | 83.3% [72.9, 91.7] | 44.3% [44.0, 44.6] |

**western_ghats** (32 positives) - WARNING: only 32 positive cell-days (< 100): intervals are wide and unstable

| scorer | FA share @ 80% recall | FA share @ 90% recall | FA share @ 95% recall | recall @ FA 0.1% | recall @ FA 1.0% | recall @ FA 5.0% | recall @ FA 10.0% | weighted PR-AUC |
|---|---|---|---|---|---|---|---|---|
| hazard model | 11.2% [5.2, 36.8] | 27.1% [10.9, 62.7] | 62.5% [12.8, 75.4] | 0.0% [0.0, 0.0] | 28.1% [12.5, 43.8] | 62.5% [46.9, 78.1] | 71.9% [56.2, 87.5] | 0.00021 [0.00012, 0.00044] |
| intensity-duration | 15.4% [10.4, 28.5] | 28.4% [13.1, 36.3] | 36.1% [17.2, 38.1] | 6.2% [0.0, 21.9] | 34.4% [18.8, 50.0] | 56.2% [37.5, 75.0] | 62.5% [43.8, 78.1] | 0.00038 [0.00015, 0.00119] |
| LHASA-style | 19.9% [7.6, 33.3] | 32.7% [19.6, 37.5] | 37.3% [22.9, 40.3] | 0.0% [0.0, 6.2] | 28.1% [12.5, 43.8] | 53.1% [34.4, 71.9] | 65.6% [50.0, 81.2] | 0.00017 [0.00009, 0.00039] |
| logistic regression | 11.9% [6.3, 23.2] | 15.6% [9.6, 28.8] | 28.6% [14.6, 31.5] | 21.9% [9.4, 37.5] | 40.6% [21.9, 59.4] | 62.5% [43.8, 78.1] | 78.1% [62.5, 90.6] | 0.00118 [0.00039, 0.00460] |

| scorer | validation-chosen threshold | raw score | realised recall | realised FA share |
|---|---|---|---|---|
| hazard model | recall_0.9 | 0.0472 | 81.2% [65.6, 93.8] | 12.1% [11.9, 12.3] |
| intensity-duration | recall_0.9 | 2.5263 | 87.5% [75.0, 96.9] | 27.4% [27.1, 27.7] |
| LHASA-style | recall_0.9 | 0.6152 | 87.5% [75.0, 96.9] | 30.8% [30.5, 31.1] |
| logistic regression | recall_0.9 | -0.7760 | 90.6% [78.1, 100.0] | 16.1% [15.9, 16.3] |

## Overall recall (out-of-domain positives count as misses)

| set | scorer | recall, in-domain | overall recall |
|---|---|---|---|
| test_2018 | hazard model | 78.8% [70.0, 87.5] | 74.1% [64.7, 83.5] |
| test_2018 | intensity-duration | 85.0% [76.2, 91.2] | 80.0% [70.6, 88.2] |
| test_2018 | LHASA-style | 86.2% [78.8, 92.5] | 81.2% [72.9, 89.4] |
| test_2018 | logistic regression | 86.2% [78.8, 93.8] | 81.2% [72.9, 89.4] |
| test_2018:himalaya | hazard model | 77.1% [64.6, 89.6] | 75.5% [63.3, 87.8] |
| test_2018:himalaya | intensity-duration | 83.3% [72.9, 93.8] | 81.6% [69.4, 91.8] |
| test_2018:himalaya | LHASA-style | 85.4% [75.0, 93.8] | 83.7% [73.5, 91.8] |
| test_2018:himalaya | logistic regression | 83.3% [70.8, 93.8] | 81.6% [69.4, 91.8] |
| test_2018:western_ghats | hazard model | 81.2% [65.6, 93.8] | 72.2% [58.3, 86.1] |
| test_2018:western_ghats | intensity-duration | 87.5% [75.0, 96.9] | 77.8% [63.9, 88.9] |
| test_2018:western_ghats | LHASA-style | 87.5% [75.0, 96.9] | 77.8% [63.9, 91.7] |
| test_2018:western_ghats | logistic regression | 90.6% [78.1, 100.0] | 80.6% [66.7, 91.7] |

## Sensitivity: buffer rows and the LHASA rule

| split | scorer | FA share @ 90% recall, buffer excluded | buffer rows counted as negatives |
|---|---|---|---|
| validation | hazard model | 0.1861 | 0.1875 |
| validation | intensity-duration | 0.3199 | 0.3212 |
| validation | LHASA-style | 0.3847 | 0.3859 |
| validation | logistic regression | 0.3933 | 0.3944 |
| test_2018 | hazard model | 0.2817 | 0.2828 |
| test_2018 | intensity-duration | 0.3175 | 0.3184 |
| test_2018 | LHASA-style | 0.4006 | 0.4013 |
| test_2018 | logistic regression | 0.4885 | 0.4894 |

LHASA-style rule point (susceptibility class >= 3 and rain_acc3_vs_clim >= 3):

| split | recall | FA share |
|---|---|---|
| validation | 24.9% [19.7, 31.0] | 4.7% [4.6, 4.9] |
| test_2018 | 32.5% [22.5, 43.8] | 4.5% [4.4, 4.6] |

## 2023 India window test

Threshold = each scorer's validation-chosen 90%-recall threshold. A window-positive cell is detected if the maximum score over the 46 window days of any of its 3x3 neighbourhood cells reaches it. Control cells are scored on their own cell only, so their any-alert share is an upper bound on false alarms (inventory partial) and is not like-for-like with the nine-cell detection chance.

| scorer | threshold | detected | detection share [95% CI] | controls alerted | control any-alert share [95% CI] | control cell-days alerted |
|---|---|---|---|---|---|---|
| hazard model | 0.0472 | 24/24 | 100.0% [100.0, 100.0] | 3096/4000 | 77.4% [76.1, 78.8] | 37.17% |
| intensity-duration | 2.5263 | 24/24 | 100.0% [100.0, 100.0] | 3999/4000 | 100.0% [99.9, 100.0] | 68.90% |
| LHASA-style | 0.6152 | 24/24 | 100.0% [100.0, 100.0] | 4000/4000 | 100.0% [100.0, 100.0] | 67.74% |
| logistic regression | -0.7760 | 24/24 | 100.0% [100.0, 100.0] | 3936/4000 | 98.4% [98.0, 98.8] | 66.46% |

## Case studies (scored only)

At each scorer's validation-chosen 90%-recall threshold.

| case | scorer | positive cell-days alerted | alerted share of other cell-days | alerted cell-days |
|---|---|---|---|---|
| case_kerala_2018 | hazard model | 22/23 | 24.82% | 43373 |
| case_kerala_2018 | intensity-duration | 21/23 | 56.17% | 92628 |
| case_kerala_2018 | LHASA-style | 23/23 | 55.71% | 91814 |
| case_kerala_2018 | logistic regression | 23/23 | 45.88% | 76712 |
| case_wayanad_2024 | hazard model | 0/0 | 57.21% | 1762 |
| case_wayanad_2024 | intensity-duration | 0/0 | 98.93% | 3047 |
| case_wayanad_2024 | LHASA-style | 0/0 | 98.80% | 3043 |
| case_wayanad_2024 | logistic regression | 0/0 | 94.06% | 2897 |

## Calibration

Probabilities are P(landslide on that cell-day) at the all-year operating base rate (a tiny number); `risk_per_100k = 1e5 * P`. The calibrator was fitted on validation, so the validation row is in-sample.

| set | base rate per 100k | mean predicted per 100k | ECE (deciles) per 100k | ECE / base rate |
|---|---|---|---|---|
| validation (in-sample) | 0.851 | 0.851 | 5.43e-15 | 6.37e-15 |
| test_2018 | 0.596 | 0.809 | 0.299 | 0.501 |

Reliability, top-decile tail bins (test_2018), per 100k cell-days:

| bin (low to high risk) | population | positives | mean predicted | observed |
|---|---|---|---|---|
| 0 | 91.44% | 28 | 0.278 | 0.228 |
| 1 | 7.64% | 33 | 4.670 | 3.218 |
| 2 | 0.83% | 15 | 13.004 | 13.471 |
| 3 | 0.09% | 4 | 99.423 | 32.514 |

Reliability by deciles of risk (test_2018), per 100k cell-days:

| decile | population | positives | mean predicted | observed |
|---|---|---|---|---|
| 0 | 27.30% | 1 | 0.000 | 0.027 |
| 2 | 8.15% | 1 | 0.045 | 0.091 |
| 3 | 5.67% | 1 | 0.065 | 0.131 |
| 4 | 20.42% | 3 | 0.090 | 0.109 |
| 6 | 11.05% | 4 | 0.206 | 0.270 |
| 7 | 9.34% | 7 | 0.381 | 0.558 |
| 8 | 9.50% | 11 | 1.787 | 0.862 |
| 9 | 8.56% | 52 | 6.492 | 4.525 |

Reliability, top-decile tail bins (validation), per 100k cell-days:

| bin (low to high risk) | population | positives | mean predicted | observed |
|---|---|---|---|---|
| 0 | 90.71% | 67 | 0.275 | 0.275 |
| 1 | 9.00% | 128 | 5.285 | 5.285 |
| 2 | 0.22% | 20 | 33.061 | 33.061 |
| 3 | 0.06% | 14 | 87.940 | 87.940 |

Reliability by deciles of risk (validation), per 100k cell-days:

| decile | population | positives | mean predicted | observed |
|---|---|---|---|---|
| 0 | 27.21% | 0 | 0.000 | 0.000 |
| 2 | 8.18% | 1 | 0.045 | 0.045 |
| 3 | 5.69% | 1 | 0.065 | 0.065 |
| 4 | 20.72% | 5 | 0.090 | 0.090 |
| 6 | 10.80% | 6 | 0.206 | 0.206 |
| 7 | 8.79% | 9 | 0.381 | 0.381 |
| 8 | 9.32% | 45 | 1.795 | 1.795 |
| 9 | 9.29% | 162 | 6.485 | 6.485 |

## Leave-region-out

The selected configuration (hyper-parameters, neg_mix and number of trees, no early stopping) is refitted on one region's train rows only and scored on the OTHER region's positives and universe; the full model on the same rows is shown for reference. Warnings flag positive counts below 100.

**himalaya -> western_ghats, validation** (30 positives) - WARNING: only 30 positive cell-days (< 100): intervals are wide and unstable

| scorer | FA share @ 80% recall | FA share @ 90% recall | FA share @ 95% recall | recall @ FA 0.1% | recall @ FA 1.0% | recall @ FA 5.0% | recall @ FA 10.0% | weighted PR-AUC |
|---|---|---|---|---|---|---|---|---|
| full model | 7.1% [4.8, 33.2] | 32.9% [6.7, 38.8] | 38.5% [7.9, 65.9] | 6.7% [0.0, 16.7] | 30.0% [13.3, 46.7] | 63.3% [46.7, 80.0] | 83.3% [70.0, 96.7] | 0.00025 [0.00008, 0.00152] |
| region-held-out model | 9.9% [4.6, 17.3] | 17.0% [7.8, 31.7] | 31.5% [11.3, 72.0] | 6.7% [0.0, 16.7] | 30.0% [13.3, 46.7] | 63.3% [46.7, 80.0] | 80.0% [63.3, 93.3] | 0.00015 [0.00006, 0.00087] |

FA share at 90% recall, held-out minus full model: -0.1592 [-0.1606, 0.0457] (tie)

**himalaya -> western_ghats, test_2018** (32 positives) - WARNING: only 32 positive cell-days (< 100): intervals are wide and unstable

| scorer | FA share @ 80% recall | FA share @ 90% recall | FA share @ 95% recall | recall @ FA 0.1% | recall @ FA 1.0% | recall @ FA 5.0% | recall @ FA 10.0% | weighted PR-AUC |
|---|---|---|---|---|---|---|---|---|
| full model | 11.2% [5.2, 36.8] | 27.1% [10.9, 62.7] | 62.5% [12.8, 75.4] | 0.0% [0.0, 0.0] | 28.1% [12.5, 43.8] | 62.5% [46.9, 78.1] | 71.9% [56.2, 87.5] | 0.00021 [0.00012, 0.00044] |
| region-held-out model | 7.8% [4.0, 22.7] | 16.7% [7.5, 38.3] | 38.1% [10.0, 64.7] | 0.0% [0.0, 0.0] | 28.1% [12.5, 43.8] | 68.8% [50.0, 84.4] | 84.4% [68.8, 93.8] | 0.00022 [0.00013, 0.00044] |

FA share at 90% recall, held-out minus full model: -0.1038 [-0.2461, -0.0060] (region_held_out_model better)

**western_ghats -> himalaya, validation** (199 positives)

| scorer | FA share @ 80% recall | FA share @ 90% recall | FA share @ 95% recall | recall @ FA 0.1% | recall @ FA 1.0% | recall @ FA 5.0% | recall @ FA 10.0% | weighted PR-AUC |
|---|---|---|---|---|---|---|---|---|
| full model | 14.6% [12.8, 17.6] | 20.7% [17.5, 26.9] | 30.5% [22.4, 38.7] | 8.0% [4.0, 12.1] | 21.1% [15.6, 27.1] | 51.8% [45.2, 58.8] | 69.3% [62.8, 75.9] | 0.00525 [0.00014, 0.02038] |
| region-held-out model | 22.4% [18.7, 26.4] | 33.4% [26.8, 41.9] | 46.2% [38.0, 48.4] | 1.5% [0.0, 3.5] | 10.6% [6.5, 15.1] | 37.2% [30.2, 43.7] | 55.8% [48.7, 62.8] | 0.00509 [0.00005, 0.01516] |

FA share at 90% recall, held-out minus full model: 0.1273 [0.0539, 0.1989] (model better)

**western_ghats -> himalaya, test_2018** (48 positives) - WARNING: only 48 positive cell-days (< 100): intervals are wide and unstable

| scorer | FA share @ 80% recall | FA share @ 90% recall | FA share @ 95% recall | recall @ FA 0.1% | recall @ FA 1.0% | recall @ FA 5.0% | recall @ FA 10.0% | weighted PR-AUC |
|---|---|---|---|---|---|---|---|---|
| full model | 27.3% [11.6, 30.8] | 31.1% [27.2, 49.4] | 40.4% [30.0, 63.2] | 6.2% [0.0, 14.6] | 20.8% [10.4, 33.3] | 45.8% [33.3, 58.4] | 66.7% [52.1, 79.2] | 0.00010 [0.00004, 0.00059] |
| region-held-out model | 28.3% [15.2, 39.2] | 40.9% [28.3, 46.8] | 45.5% [36.9, 57.2] | 0.0% [0.0, 4.2] | 18.8% [8.3, 31.2] | 41.7% [27.1, 56.2] | 56.2% [41.7, 68.8] | 0.00005 [0.00003, 0.00011] |

FA share at 90% recall, held-out minus full model: 0.0983 [-0.0474, 0.1653] (tie)

## Ablations

Each refit uses the validation-selected hyper-parameters (no new tuning, nothing on test). FA share at 90% recall, threshold chosen within each set; the last column is the paired difference to the full model (positive = ablated model has more false alarms).

**validation**

| variant | inputs | FA share @ 90% recall | PR-AUC | variant minus full [95% CI] |
|---|---|---|---|---|
| hazard model | 43 | 18.6% [16.4, 27.3] | 0.00458 [0.00014, 0.01771] | - |
| drop_src | 30 | 20.0% [16.0, 30.1] | 0.00017 [0.00012, 0.00033] | 0.0139 [-0.0395, 0.0894] (tie) |
| drop_wet | 37 | 21.9% [17.7, 29.2] | 0.00452 [0.00012, 0.01336] | 0.0329 [-0.0225, 0.0773] (tie) |
| drop_stat | 33 | 31.1% [27.2, 45.1] | 0.00009 [0.00007, 0.00012] | 0.1251 [0.0616, 0.2487] (full model better) |
| drop_disagreement | 36 | 20.0% [17.3, 27.8] | 0.00027 [0.00013, 0.01329] | 0.0144 [-0.0279, 0.0651] (tie) |
| neg_mix_matched_plus_universe | 43 | 19.5% [15.3, 24.8] | 0.00024 [0.00014, 0.01342] | 0.0087 [-0.0479, 0.0415] (tie) |
| no_monotone_constraints | 43 | 20.0% [17.3, 30.9] | 0.00452 [0.00011, 0.01340] | 0.0134 [-0.0398, 0.0789] (tie) |

**test_2018**

| variant | inputs | FA share @ 90% recall | PR-AUC | variant minus full [95% CI] |
|---|---|---|---|---|
| hazard model | 43 | 28.2% [21.0, 45.0] | 0.00011 [0.00006, 0.00030] | - |
| drop_src | 30 | 29.9% [19.5, 49.5] | 0.00009 [0.00006, 0.00020] | 0.0168 [-0.1005, 0.1511] (tie) |
| drop_wet | 37 | 26.5% [17.8, 42.8] | 0.00016 [0.00008, 0.00055] | -0.0170 [-0.1390, 0.0194] (tie) |
| drop_stat | 33 | 43.6% [31.7, 100.0] | 0.00008 [0.00005, 0.00015] | 0.1547 [-0.0532, 0.7156] (tie) |
| drop_disagreement | 36 | 33.0% [20.5, 42.4] | 0.00014 [0.00007, 0.00030] | 0.0487 [-0.0745, 0.1191] (tie) |
| neg_mix_matched_plus_universe | 43 | 29.6% [18.7, 37.8] | 0.00008 [0.00005, 0.00020] | 0.0146 [-0.1228, 0.0856] (tie) |
| no_monotone_constraints | 43 | 32.2% [19.5, 47.3] | 0.00010 [0.00006, 0.00023] | 0.0400 [-0.1084, 0.0661] (tie) |

## Monotonicity

Partial dependence of the mean raw score on a grid of each constrained feature (validation universe background).

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
| src_imd_acc_1 | +1 | yes | 0.00000000 |
| src_imd_acc_3 | +1 | yes | 0.00000000 |
| src_imd_acc_7 | +1 | yes | 0.00000000 |
| src_chi_acc_1 | +1 | yes | 0.00000000 |
| src_chi_acc_3 | +1 | yes | 0.00000000 |
| src_chi_acc_7 | +1 | yes | 0.00000000 |
| stat_relief | +1 | yes | 0.00000000 |
| stat_slope_mean | +1 | yes | 0.00000000 |
| stat_slope_p90 | +1 | yes | 0.00000000 |
| stat_slope_max | +1 | yes | 0.00000000 |

## Feature importance (gain, top 15)

| feature | share of gain |
|---|---|
| stat_elev_mean | 17.0% |
| rain_days_since_10mm | 8.2% |
| rain_acc_1 | 5.7% |
| stat_relief | 4.5% |
| stat_slope_max | 4.2% |
| stat_twi_proxy | 3.9% |
| src_chi_acc_1 | 3.3% |
| rain_share1_3 | 3.0% |
| src_imd_acc_1 | 3.0% |
| rain_acc_30 | 2.8% |
| stat_curvature_mean | 2.7% |
| wet_top_chg7 | 2.6% |
| wet_top_chg3 | 2.6% |
| rain_acc7_vs_clim | 2.5% |
| stat_aspect_sin | 2.4% |

## Baseline parameters (fitted on train only)

- **intensity-duration**: `{'percentile': 10.0, 'thresholds_mm': {'3': 4.5882, '5': 9.8067, '7': 17.3287, '14': 55.8998, '30': 124.6681}}`
- **LHASA-style**: `{'n_classes': 5, 'slope_mean_class_edges': [4.4728, 8.6477, 19.9135, 27.095], 'trigger_ratio': 3.0, 'rule_min_class': 3}`
- **logistic regression**: `{'columns': ['rain_acc_1', 'rain_acc_3', 'rain_acc_7', 'rain_acc_30', 'rain_acc3_vs_clim', 'wet_top', 'stat_slope_mean'], 'median_fill': [1.3743, 11.3468, 39.184, 196.4163, 0.5376, 0.77, 16.7659], 'missing_indicator_columns': [], 'coefficients_standardised': [0.5931, 0.0158, 0.1049, 0.1129, 0.2494, 0.4766, 0.5333], 'intercept': -0.4799}`

## Ensemble

20-member bootstrap ensemble; on validation the mean per-row std of the calibrated members is 0.0000267454 and the point estimate lies inside the 10th-90th percentile interval for 92.6% of rows. Coverage of events is not claimed.
