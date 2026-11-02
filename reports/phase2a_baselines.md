# Phase 2a - sensor-integrity baselines

Faults are injected into REAL clean station series (seeded); recall is at a 1% false-flag rate on clean days (scores) or reported as (recall, achieved false-flag rate) for rule flags. Intervals are 95% bootstrap CIs over stations. The real NOAA flags are a separate sanity check.

## Data coverage

- stations: 140 ({'IN': 138, 'NP': 2}); window 1990-01-01..2024-12-31; valid share of station-days 0.265
- clean real days (valid, unflagged, station-year >= 200 valid days): 231539 at 82 stations; 73 stations have >= 365 clean days (eligible)

| min valid days per station-year | clean days | stations with >= 365 clean days |
|---|---|---|
| 300 | 124412 | 55 |
| 200 | 231539 | 73 |
| 120 | 362513 | 105 |

| neighbour setting | k | max km | stations with < 2 neighbours | no neighbour | clean days with >= 2 valid neighbours | >= 3 |
|---|---|---|---|---|---|---|
| design | 5 | 150 | 65 | 17 | 0.051 | 0.010 |
| wide | 10 | 300 | 3 | 2 | 0.784 | 0.554 |

## Fault dataset (episodes / faulty days per type)

| split | stations (with episodes) | stuck_value | zero_fault | spike | scale_drift | offset_noise | duplicate_block |
|---|---|---|---|---|---|---|---|
| test | 28 (16) | 44 / 737 | 37 / 263 | 45 / 45 | 22 / 419 | 47 / 1198 | 46 / 496 |
| train | 84 (47) | 116 / 1874 | 106 / 1004 | 113 / 113 | 50 / 1171 | 122 / 3257 | 118 / 1250 |
| val | 28 (16) | 40 / 664 | 34 / 270 | 32 / 32 | 18 / 333 | 39 / 808 | 37 / 313 |

Calibration from the real flags: duplicate_block lengths 7-31 (real D runs are whole duplicated months (lengths [28, 31, 61, 62]); a block of 7+ days tests the L1 threshold, the upper end is the longest single-month run (two-month runs are two blocks)); stuck_value lengths 6-30 (real K flags mark isolated days, not streaks; the longest natural streak of identical positive values in the real series is 5 days, so injected stuck episodes start above it)

## L1 and rule false-flag rates on the real clean days

231539 real clean days; thresholds {'max_mm': 1500.0, 'stuck_min_run': 3, 'k_min_run': 10, 'dup_min_block': 7, 'dup_min_positive': 3}.

| rule | flagged | rate |
|---|---|---|
| bounds | 0 | 0.00000 |
| stuck | 173 | 0.00075 |
| stuck_k10 | 0 | 0.00000 |
| duplicate_block | 0 | 0.00000 |
| l1_flag | 173 | 0.00075 |
| range_check | 0 | 0.00000 |
| noaa_style design K | 0 | 0.00000 |
| noaa_style design D | 0 | 0.00000 |
| noaa_style design O | 7 | 0.00003 |
| noaa_style design S | 18 | 0.00008 |
| noaa_style design any | 25 | 0.00011 |
| noaa_style wide K | 0 | 0.00000 |
| noaa_style wide D | 0 | 0.00000 |
| noaa_style wide O | 7 | 0.00003 |
| noaa_style wide S | 1267 | 0.00547 |
| noaa_style wide any | 1273 | 0.00550 |

Sensitivity, clean days under the 300-valid-days rule (124412 days): bounds 0.00000; stuck 0.00072; stuck_k10 0.00000; duplicate_block 0.00000; l1_flag 0.00072; range_check 0.00000

Threshold sensitivity (same clean days): stuck run >= 2: 0.01150; stuck run >= 3: 0.00075; stuck run >= 4: 0.00007; stuck run >= 5: 0.00002; stuck run >= 10: 0.00000; duplicate block min positive days 1: 0.04623; duplicate block min positive days 2: 0.00115; duplicate block min positive days 3: 0.00000; duplicate block min positive days 4: 0.00000

## VAL stations (28)

### Recall per fault type (95% CI over stations)

| method | stuck_value | zero_fault | spike | scale_drift | offset_noise | duplicate_block | macro |
|---|---|---|---|---|---|---|---|
| range_check | 0.00 (fpr 0.000) n/a (degenerate) | 0.00 (fpr 0.000) n/a (degenerate) | 0.00 (fpr 0.000) n/a (degenerate) | 0.00 (fpr 0.000) n/a (degenerate) | 0.00 (fpr 0.000) n/a (degenerate) | 0.00 (fpr 0.000) n/a (degenerate) | 0.00 |
| l1 | 1.00 (fpr 0.001) n/a (degenerate) | 0.00 (fpr 0.001) n/a (degenerate) | 0.00 (fpr 0.001) n/a (degenerate) | 0.00 (fpr 0.001) n/a (degenerate) | 0.03 (fpr 0.001) [0.01, 0.05] | 0.64 (fpr 0.001) [0.48, 0.78] | 0.28 |
| noaa_style_qa | 0.94 (fpr 0.000) [0.87, 0.98] | 0.00 (fpr 0.000) n/a (degenerate) | 0.47 (fpr 0.000) [0.33, 0.63] | 0.00 (fpr 0.000) n/a (degenerate) | 0.00 (fpr 0.000) n/a (degenerate) | 0.13 (fpr 0.000) [0.01, 0.26] | 0.26 |
| noaa_style_qa_wide | 0.96 (fpr 0.004) [0.92, 0.99] | 0.02 (fpr 0.004) [0.00, 0.05] | 0.62 (fpr 0.004) [0.45, 0.81] | 0.01 (fpr 0.004) [0.00, 0.01] | 0.00 (fpr 0.004) n/a (degenerate) | 0.19 (fpr 0.004) [0.07, 0.32] | 0.30 |
| robust_zscore | 0.08 [0.00, 0.18] | 0.00 n/a (degenerate) | 0.72 [0.54, 0.90] | 0.07 [0.02, 0.12] | 0.00 n/a (degenerate) | 0.05 [0.03, 0.08] | 0.15 |
| isolation_forest | 0.08 [0.00, 0.15] | 0.00 n/a (degenerate) | 0.25 [0.07, 0.43] | 0.00 n/a (degenerate) | 0.00 n/a (degenerate) | 0.02 [0.00, 0.05] | 0.06 |

### Detection: episodes detected / total, median delay in days

| method | stuck_value | zero_fault | spike | scale_drift | offset_noise | duplicate_block |
|---|---|---|---|---|---|---|
| range_check | 0/40, n/a | 0/34, n/a | 0/32, n/a | 0/18, n/a | 0/39, n/a | 0/37, n/a |
| l1 | 40/40, 0.0 | 0/34, n/a | 0/32, n/a | 0/18, n/a | 7/39, 17.0 | 23/37, 0.0 |
| noaa_style_qa | 34/40, 0.0 | 0/34, n/a | 15/32, 0.0 | 0/18, n/a | 0/39, n/a | 5/37, 2.0 |
| noaa_style_qa_wide | 39/40, 0.0 | 4/34, 6.5 | 20/32, 0.0 | 2/18, 14.0 | 0/39, n/a | 17/37, 5.0 |
| robust_zscore | 3/40, 0.0 | 0/34, n/a | 23/32, 0.0 | 6/18, 3.0 | 0/39, n/a | 15/37, 5.0 |
| isolation_forest | 3/40, 5.0 | 0/34, n/a | 8/32, 0.0 | 0/18, n/a | 0/39, n/a | 1/37, 6.0 |

### PR-AUC per fault type (score methods)

| method | stuck_value | zero_fault | spike | scale_drift | offset_noise | duplicate_block |
|---|---|---|---|---|---|---|
| robust_zscore | 0.139 | 0.007 | 0.616 | 0.033 | 0.053 | 0.034 |
| isolation_forest | 0.275 | 0.019 | 0.113 | 0.042 | 0.081 | 0.041 |

### Genuine-extreme retention: all variants (retained / extremes); no single number is the safety result

Extremes: clean unflagged readings >= the station's 99.5th wet-day percentile. `design-strict` and `wide` need >= 2 neighbours reading >= 30% of the value (150 km / 300 km neighbour settings); `wide_1neighbour` needs 1 (300 km); `uncorroborated` has no neighbour condition: a proxy that includes unverified readings.

| method | clean-day false-flag rate | design-strict | wide | wide_1neighbour | uncorroborated (proxy) |
|---|---|---|---|---|---|
| range_check | 0.0000 | 2/2 = 1.000 n/a (degenerate) | 3/3 = 1.000 n/a (degenerate) | 10/10 = 1.000 n/a (degenerate) | 50/50 = 1.000 n/a (degenerate) |
| l1 | 0.0007 | 2/2 = 1.000 n/a (degenerate) | 3/3 = 1.000 n/a (degenerate) | 10/10 = 1.000 n/a (degenerate) | 50/50 = 1.000 n/a (degenerate) |
| noaa_style_qa | 0.0002 | 2/2 = 1.000 n/a (degenerate) | 3/3 = 1.000 n/a (degenerate) | 10/10 = 1.000 n/a (degenerate) | 50/50 = 1.000 n/a (degenerate) |
| noaa_style_qa_wide | 0.0035 | 2/2 = 1.000 n/a (degenerate) | 3/3 = 1.000 n/a (degenerate) | 10/10 = 1.000 n/a (degenerate) | 47/50 = 0.940 [0.86, 1.00] |
| robust_zscore | 0.0096 | 2/2 = 1.000 n/a (degenerate) | 2/3 = 0.667 [0.00, 1.00] | 4/10 = 0.400 [0.00, 0.67] | 20/50 = 0.400 [0.23, 0.56] |
| isolation_forest | 0.0099 | 2/2 = 1.000 n/a (degenerate) | 3/3 = 1.000 n/a (degenerate) | 10/10 = 1.000 n/a (degenerate) | 48/50 = 0.960 [0.87, 1.00] |

## TEST stations (28)

### Recall per fault type (95% CI over stations)

| method | stuck_value | zero_fault | spike | scale_drift | offset_noise | duplicate_block | macro |
|---|---|---|---|---|---|---|---|
| range_check | 0.00 (fpr 0.000) n/a (degenerate) | 0.00 (fpr 0.000) n/a (degenerate) | 0.00 (fpr 0.000) n/a (degenerate) | 0.00 (fpr 0.000) n/a (degenerate) | 0.00 (fpr 0.000) n/a (degenerate) | 0.00 (fpr 0.000) n/a (degenerate) | 0.00 |
| l1 | 1.00 (fpr 0.001) n/a (degenerate) | 0.00 (fpr 0.001) n/a (degenerate) | 0.00 (fpr 0.001) n/a (degenerate) | 0.00 (fpr 0.001) n/a (degenerate) | 0.04 (fpr 0.001) [0.02, 0.06] | 0.75 (fpr 0.001) [0.64, 0.85] | 0.30 |
| noaa_style_qa | 0.89 (fpr 0.000) [0.83, 0.94] | 0.01 (fpr 0.000) [0.00, 0.02] | 0.38 (fpr 0.000) [0.25, 0.51] | 0.00 (fpr 0.000) n/a (degenerate) | 0.00 (fpr 0.000) n/a (degenerate) | 0.08 (fpr 0.000) [0.00, 0.19] | 0.23 |
| noaa_style_qa_wide | 0.92 (fpr 0.006) [0.86, 0.96] | 0.07 (fpr 0.006) [0.04, 0.09] | 0.60 (fpr 0.006) [0.52, 0.70] | 0.00 (fpr 0.006) [0.00, 0.01] | 0.00 (fpr 0.006) n/a (degenerate) | 0.18 (fpr 0.006) [0.11, 0.28] | 0.30 |
| robust_zscore | 0.07 [0.01, 0.14] | 0.00 n/a (degenerate) | 0.76 [0.59, 0.91] | 0.04 [0.01, 0.11] | 0.00 n/a (degenerate) | 0.04 [0.02, 0.08] | 0.15 |
| isolation_forest | 0.00 n/a (degenerate) | 0.01 [0.00, 0.04] | 0.36 [0.18, 0.53] | 0.00 [0.00, 0.01] | 0.00 n/a (degenerate) | 0.00 n/a (degenerate) | 0.06 |

### Detection: episodes detected / total, median delay in days

| method | stuck_value | zero_fault | spike | scale_drift | offset_noise | duplicate_block |
|---|---|---|---|---|---|---|
| range_check | 0/44, n/a | 0/37, n/a | 0/45, n/a | 0/22, n/a | 0/47, n/a | 0/46, n/a |
| l1 | 44/44, 0.0 | 0/37, n/a | 0/45, n/a | 0/22, n/a | 14/47, 8.5 | 37/46, 0.0 |
| noaa_style_qa | 34/44, 0.0 | 2/37, 2.0 | 17/45, 0.0 | 0/22, n/a | 0/47, n/a | 6/46, 0.0 |
| noaa_style_qa_wide | 38/44, 0.0 | 10/37, 4.5 | 27/45, 0.0 | 2/22, 36.0 | 0/47, n/a | 24/46, 3.5 |
| robust_zscore | 5/44, 0.0 | 0/37, n/a | 34/45, 0.0 | 7/22, 17.0 | 0/47, n/a | 10/46, 4.5 |
| isolation_forest | 0/44, n/a | 1/37, 1.0 | 16/45, 0.0 | 2/22, 17.0 | 0/47, n/a | 0/46, n/a |

### PR-AUC per fault type (score methods)

| method | stuck_value | zero_fault | spike | scale_drift | offset_noise | duplicate_block |
|---|---|---|---|---|---|---|
| robust_zscore | 0.143 | 0.005 | 0.633 | 0.029 | 0.066 | 0.040 |
| isolation_forest | 0.265 | 0.015 | 0.120 | 0.042 | 0.089 | 0.035 |

### Genuine-extreme retention: all variants (retained / extremes); no single number is the safety result

Extremes: clean unflagged readings >= the station's 99.5th wet-day percentile. `design-strict` and `wide` need >= 2 neighbours reading >= 30% of the value (150 km / 300 km neighbour settings); `wide_1neighbour` needs 1 (300 km); `uncorroborated` has no neighbour condition: a proxy that includes unverified readings.

| method | clean-day false-flag rate | design-strict | wide | wide_1neighbour | uncorroborated (proxy) |
|---|---|---|---|---|---|
| range_check | 0.0000 | 0/0 (not measurable at this density) | 6/6 = 1.000 n/a (degenerate) | 18/18 = 1.000 n/a (degenerate) | 64/64 = 1.000 n/a (degenerate) |
| l1 | 0.0010 | 0/0 (not measurable at this density) | 6/6 = 1.000 n/a (degenerate) | 18/18 = 1.000 n/a (degenerate) | 64/64 = 1.000 n/a (degenerate) |
| noaa_style_qa | 0.0005 | 0/0 (not measurable at this density) | 6/6 = 1.000 n/a (degenerate) | 18/18 = 1.000 n/a (degenerate) | 64/64 = 1.000 n/a (degenerate) |
| noaa_style_qa_wide | 0.0060 | 0/0 (not measurable at this density) | 6/6 = 1.000 n/a (degenerate) | 18/18 = 1.000 n/a (degenerate) | 59/64 = 0.922 [0.80, 1.00] |
| robust_zscore | 0.0100 | 0/0 (not measurable at this density) | 4/6 = 0.667 [0.00, 1.00] | 12/18 = 0.667 [0.17, 0.93] | 40/64 = 0.625 [0.36, 0.80] |
| isolation_forest | 0.0099 | 0/0 (not measurable at this density) | 4/6 = 0.667 [0.50, 1.00] | 16/18 = 0.889 [0.76, 1.00] | 56/64 = 0.875 [0.77, 0.94] |

## Real NOAA flags (sanity check, whole history)

391 flagged values ({'D': 241, 'G': 29, 'K': 5, 'O': 41, 'S': 75}); 10 in 2007-2024. Score methods use the validation-split 1% false-flag thresholds.

| method | real flags flagged | of which 2007-2024 | by NOAA flag | false-flag rate on unflagged days |
|---|---|---|---|---|
| range_check | 0 / 391 | 0 / 10 | {} | 0.0000 |
| l1 | 71 / 391 | 0 / 10 | {'D': 71} | 0.0006 |
| noaa_style_qa | 178 / 391 | 6 / 10 | {'D': 121, 'G': 27, 'O': 23, 'S': 7} | 0.0010 |
| noaa_style_qa_wide | 194 / 391 | 6 / 10 | {'D': 126, 'G': 27, 'K': 5, 'O': 24, 'S': 12} | 0.0133 |
| robust_zscore | 70 / 391 | 0 / 10 | {'D': 8, 'G': 15, 'K': 5, 'O': 17, 'S': 25} | 0.0092 |
| isolation_forest | 58 / 391 | 0 / 10 | {'G': 14, 'O': 8, 'S': 36} | 0.0021 |
