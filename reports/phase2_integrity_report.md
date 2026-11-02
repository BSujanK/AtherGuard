# Phase 2 - sensor-integrity engine: gate report

Faults are INJECTED into real clean 2007-2024 station series (not real faults); 95% bootstrap CIs over stations; zero-width intervals print as 'n/a (degenerate)'. Hyper-parameters, calibration and tau use the VAL stations only. `engine_score` is the model score alone at a 1% false-flag rate on the evaluated split's clean days (the protocol of the score baselines). `engine` is the COMBINED decision (L1 or model flag, minus the readings the arbiter retains) at the tau chosen on the VAL clean days so that this combined decision flags at most 1% of them; `engine_at_0.5pct` / `engine_at_2pct` use the 0.5% / 2% VAL-chosen taus. Rule and combined rows are shown as recall (realised false-flag rate on that split's clean days). `engine_oracle_matched_noaa_wide` (TEST only) picks tau ON THE TEST clean days to match noaa_style_qa_wide's false-flag rate: an oracle comparison, NOT a deployable threshold.

## Evaluation data

| split | stations with episodes | stuck_value | zero_fault | spike | scale_drift | offset_noise | duplicate_block |
|---|---|---|---|---|---|---|---|
| train | 33 | 71 | 76 | 67 | 31 | 58 | 67 |
| val | 11 | 27 | 29 | 29 | 12 | 22 | 28 |
| test | 11 | 22 | 21 | 23 | 14 | 19 | 23 |

scale_drift shortfall (reported, not hidden): the 150-day / density 0.15 dataset has 14 TEST and 31 TRAIN scale_drift episodes, below the 15 / 40 minimum; its recall rests on that few episodes.

## Training

Train rows {'ok': 171257, 'stuck_value': 5248, 'zero_fault': 4170, 'spike': 357, 'scale_drift': 6670, 'offset_noise': 1389, 'duplicate_block': 5264} (frozen seed plus 4 extra injection seeds), VAL rows {'ok': 12039, 'stuck_value': 373, 'zero_fault': 311, 'spike': 29, 'scale_drift': 450, 'offset_noise': 84, 'duplicate_block': 434}. Selected {'num_leaves': 31, 'min_child_samples': 20}; every candidate:

| params | best iteration | VAL macro recall @1% | VAL log-loss |
|---|---|---|---|
| {'num_leaves': 15, 'min_child_samples': 20} | 552 | 0.581 | 0.2561 |
| {'num_leaves': 15, 'min_child_samples': 60} | 582 | 0.583 | 0.2583 |
| {'num_leaves': 31, 'min_child_samples': 20} | 360 | 0.597 | 0.2532 |
| {'num_leaves': 31, 'min_child_samples': 60} | 323 | 0.586 | 0.2499 |

## TEST stations (28): recall per fault type

| method | stuck_value | zero_fault | spike | scale_drift | offset_noise | duplicate_block | macro |
|---|---|---|---|---|---|---|---|
| range_check | 0.00 (fpr 0.000) n/a (degenerate) | 0.00 (fpr 0.000) n/a (degenerate) | 0.00 (fpr 0.000) n/a (degenerate) | 0.00 (fpr 0.000) n/a (degenerate) | 0.00 (fpr 0.000) n/a (degenerate) | 0.00 (fpr 0.000) n/a (degenerate) | 0.00 |
| l1 | 1.00 (fpr 0.002) n/a (degenerate) | 0.00 (fpr 0.002) n/a (degenerate) | 0.00 (fpr 0.002) n/a (degenerate) | 0.00 (fpr 0.002) n/a (degenerate) | 0.03 (fpr 0.002) [0.00, 0.04] | 0.77 (fpr 0.002) [0.51, 1.00] | 0.30 |
| noaa_style_qa | 0.88 (fpr 0.001) [0.74, 0.96] | 0.03 (fpr 0.001) [0.00, 0.06] | 0.26 (fpr 0.001) [0.05, 0.53] | 0.00 (fpr 0.001) n/a (degenerate) | 0.00 (fpr 0.001) n/a (degenerate) | 0.00 (fpr 0.001) n/a (degenerate) | 0.20 |
| noaa_style_qa_wide | 0.89 (fpr 0.013) [0.76, 0.96] | 0.19 (fpr 0.013) [0.10, 0.33] | 0.35 (fpr 0.013) [0.14, 0.58] | 0.01 (fpr 0.013) [0.00, 0.02] | 0.00 (fpr 0.013) n/a (degenerate) | 0.06 (fpr 0.013) [0.03, 0.12] | 0.25 |
| robust_zscore | 0.16 [0.00, 0.33] | 0.00 n/a (degenerate) | 0.39 [0.05, 0.68] | 0.00 [0.00, 0.01] | 0.00 n/a (degenerate) | 0.03 [0.00, 0.06] | 0.10 |
| isolation_forest | 0.00 n/a (degenerate) | 0.00 n/a (degenerate) | 0.22 [0.00, 0.48] | 0.00 n/a (degenerate) | 0.00 n/a (degenerate) | 0.00 n/a (degenerate) | 0.04 |
| engine_score | 0.84 [0.80, 0.86] | 0.63 [0.47, 0.73] | 0.57 [0.33, 0.81] | 0.02 [0.00, 0.03] | 0.19 [0.14, 0.21] | 0.02 [0.00, 0.04] | 0.38 |
| engine | 0.97 (fpr 0.049) [0.94, 1.00] | 0.80 (fpr 0.049) [0.69, 0.87] | 0.87 (fpr 0.049) [0.76, 1.00] | 0.22 (fpr 0.049) [0.05, 0.31] | 0.51 (fpr 0.049) [0.38, 0.58] | 0.83 (fpr 0.049) [0.60, 1.00] | 0.70 |
| engine_no_arbiter | 1.00 (fpr 0.051) n/a (degenerate) | 0.80 (fpr 0.051) [0.69, 0.87] | 0.87 (fpr 0.051) [0.76, 1.00] | 0.28 (fpr 0.051) [0.09, 0.38] | 0.51 (fpr 0.051) [0.38, 0.58] | 0.84 (fpr 0.051) [0.61, 1.00] | 0.71 |
| engine_arbiter_no_imd | 1.00 (fpr 0.050) n/a (degenerate) | 0.80 (fpr 0.050) [0.69, 0.87] | 0.87 (fpr 0.050) [0.76, 1.00] | 0.24 (fpr 0.050) [0.07, 0.33] | 0.51 (fpr 0.050) [0.38, 0.58] | 0.84 (fpr 0.050) [0.61, 1.00] | 0.71 |
| engine_at_0.5pct | 0.97 (fpr 0.035) [0.94, 1.00] | 0.77 (fpr 0.035) [0.66, 0.86] | 0.83 (fpr 0.035) [0.68, 1.00] | 0.15 (fpr 0.035) [0.03, 0.21] | 0.43 (fpr 0.035) [0.34, 0.47] | 0.80 (fpr 0.035) [0.53, 1.00] | 0.66 |
| engine_at_2pct | 0.97 (fpr 0.068) [0.94, 1.00] | 0.82 (fpr 0.068) [0.73, 0.88] | 0.96 (fpr 0.068) [0.88, 1.00] | 0.29 (fpr 0.068) [0.09, 0.39] | 0.59 (fpr 0.068) [0.47, 0.66] | 0.86 (fpr 0.068) [0.64, 1.00] | 0.75 |
| ablation_own_only | 0.75 [0.69, 0.78] | 0.33 [0.16, 0.41] | 0.30 [0.10, 0.44] | 0.00 n/a (degenerate) | 0.14 [0.03, 0.16] | 0.00 [0.00, 0.02] | 0.25 |
| ablation_no_grid | 0.84 [0.79, 0.87] | 0.71 [0.58, 0.78] | 0.61 [0.27, 0.79] | 0.05 [0.00, 0.10] | 0.17 [0.13, 0.29] | 0.04 [0.00, 0.09] | 0.40 |
| ablation_no_nbr | 0.84 [0.80, 0.86] | 0.65 [0.47, 0.76] | 0.65 [0.55, 0.79] | 0.04 [0.01, 0.08] | 0.18 [0.12, 0.23] | 0.04 [0.00, 0.08] | 0.40 |
| ablation_no_wet | 0.83 [0.79, 0.85] | 0.56 [0.35, 0.66] | 0.48 [0.22, 0.74] | 0.01 [0.00, 0.01] | 0.12 [0.06, 0.14] | 0.01 [0.00, 0.03] | 0.33 |
| ablation_no_dropout | 0.84 [0.79, 0.86] | 0.63 [0.46, 0.73] | 0.57 [0.38, 0.74] | 0.03 [0.01, 0.05] | 0.13 [0.10, 0.24] | 0.03 [0.01, 0.06] | 0.37 |
| ablation_no_extra_seeds | 0.65 [0.53, 0.73] | 0.56 [0.44, 0.62] | 0.43 [0.26, 0.56] | 0.00 n/a (degenerate) | 0.01 [0.00, 0.02] | 0.01 [0.00, 0.03] | 0.28 |
| engine_oracle_matched_noaa_wide | 0.97 (fpr 0.013) [0.94, 1.00] | 0.65 (fpr 0.013) [0.51, 0.74] | 0.57 (fpr 0.013) [0.33, 0.81] | 0.03 (fpr 0.013) [0.00, 0.05] | 0.22 (fpr 0.013) [0.14, 0.24] | 0.78 (fpr 0.013) [0.51, 1.00] | 0.54 |

### TEST: detection (episodes detected / total, median delay days)

| method | stuck_value | zero_fault | spike | scale_drift | offset_noise | duplicate_block |
|---|---|---|---|---|---|---|
| range_check | 0/22, n/a | 0/21, n/a | 0/23, n/a | 0/14, n/a | 0/19, n/a | 0/23, n/a |
| l1 | 22/22, 0.0 | 0/21, n/a | 0/23, n/a | 0/14, n/a | 3/19, 23.0 | 18/23, 0.0 |
| noaa_style_qa | 16/22, 0.0 | 3/21, 7.0 | 6/23, 0.0 | 0/14, n/a | 0/19, n/a | 0/23, n/a |
| noaa_style_qa_wide | 18/22, 0.0 | 12/21, 1.0 | 8/23, 0.0 | 1/14, 31.0 | 0/19, n/a | 10/23, 4.0 |
| robust_zscore | 4/22, 0.0 | 0/21, n/a | 9/23, 0.0 | 1/14, 4.0 | 0/19, n/a | 4/23, 0.5 |
| isolation_forest | 0/22, n/a | 0/21, n/a | 5/23, 0.0 | 0/14, n/a | 0/19, n/a | 0/23, n/a |
| engine_score | 22/22, 2.0 | 16/21, 3.5 | 13/23, 0.0 | 3/14, 27.0 | 13/19, 15.0 | 4/23, 10.0 |
| engine | 22/22, 0.0 | 19/21, 3.0 | 20/23, 0.0 | 7/14, 12.0 | 16/19, 12.0 | 20/23, 0.0 |
| engine_no_arbiter | 22/22, 0.0 | 19/21, 3.0 | 20/23, 0.0 | 7/14, 10.0 | 16/19, 12.0 | 20/23, 0.0 |
| engine_arbiter_no_imd | 22/22, 0.0 | 19/21, 3.0 | 20/23, 0.0 | 7/14, 10.0 | 16/19, 12.0 | 20/23, 0.0 |
| engine_at_0.5pct | 22/22, 0.0 | 19/21, 3.0 | 19/23, 0.0 | 7/14, 21.0 | 15/19, 13.0 | 19/23, 0.0 |
| engine_at_2pct | 22/22, 0.0 | 19/21, 3.0 | 22/23, 0.0 | 8/14, 11.5 | 18/19, 10.0 | 21/23, 0.0 |
| engine_oracle_matched_noaa_wide | 22/22, 0.0 | 18/21, 4.0 | 13/23, 0.0 | 3/14, 21.0 | 14/19, 14.5 | 18/23, 0.0 |

### TEST: PR-AUC (score methods)

| method | stuck_value | zero_fault | spike | scale_drift | offset_noise | duplicate_block |
|---|---|---|---|---|---|---|
| robust_zscore | 0.129 | 0.021 | 0.325 | 0.061 | 0.036 | 0.040 |
| isolation_forest | 0.115 | 0.067 | 0.139 | 0.068 | 0.050 | 0.054 |
| engine_score | 0.847 | 0.639 | 0.385 | 0.096 | 0.181 | 0.064 |
| ablation_own_only | 0.803 | 0.296 | 0.283 | 0.058 | 0.162 | 0.028 |
| ablation_no_grid | 0.869 | 0.655 | 0.473 | 0.101 | 0.151 | 0.057 |
| ablation_no_nbr | 0.864 | 0.659 | 0.288 | 0.099 | 0.163 | 0.059 |
| ablation_no_wet | 0.838 | 0.542 | 0.368 | 0.066 | 0.114 | 0.042 |
| ablation_no_dropout | 0.851 | 0.655 | 0.416 | 0.083 | 0.108 | 0.053 |
| ablation_no_extra_seeds | 0.674 | 0.525 | 0.262 | 0.049 | 0.048 | 0.036 |

## VAL stations (28): recall per fault type

| method | stuck_value | zero_fault | spike | scale_drift | offset_noise | duplicate_block | macro |
|---|---|---|---|---|---|---|---|
| range_check | 0.00 (fpr 0.000) n/a (degenerate) | 0.00 (fpr 0.000) n/a (degenerate) | 0.00 (fpr 0.000) n/a (degenerate) | 0.00 (fpr 0.000) n/a (degenerate) | 0.00 (fpr 0.000) n/a (degenerate) | 0.00 (fpr 0.000) n/a (degenerate) | 0.00 |
| l1 | 1.00 (fpr 0.001) n/a (degenerate) | 0.00 (fpr 0.001) n/a (degenerate) | 0.00 (fpr 0.001) n/a (degenerate) | 0.00 (fpr 0.001) n/a (degenerate) | 0.00 (fpr 0.001) n/a (degenerate) | 0.71 (fpr 0.001) [0.59, 0.83] | 0.29 |
| noaa_style_qa | 0.77 (fpr 0.001) [0.57, 0.92] | 0.03 (fpr 0.001) [0.00, 0.09] | 0.21 (fpr 0.001) [0.07, 0.38] | 0.00 (fpr 0.001) n/a (degenerate) | 0.00 (fpr 0.001) n/a (degenerate) | 0.08 (fpr 0.001) [0.00, 0.27] | 0.18 |
| noaa_style_qa_wide | 0.77 (fpr 0.015) [0.57, 0.92] | 0.16 (fpr 0.015) [0.06, 0.34] | 0.24 (fpr 0.015) [0.10, 0.41] | 0.00 (fpr 0.015) [0.00, 0.01] | 0.00 (fpr 0.015) n/a (degenerate) | 0.12 (fpr 0.015) [0.03, 0.31] | 0.22 |
| robust_zscore | 0.05 [0.00, 0.13] | 0.00 n/a (degenerate) | 0.38 [0.20, 0.54] | 0.00 [0.00, 0.01] | 0.00 n/a (degenerate) | 0.02 [0.00, 0.04] | 0.07 |
| isolation_forest | 0.00 n/a (degenerate) | 0.00 n/a (degenerate) | 0.10 [0.00, 0.24] | 0.00 [0.00, 0.01] | 0.00 n/a (degenerate) | 0.00 n/a (degenerate) | 0.02 |
| engine_score | 0.90 [0.85, 0.93] | 0.79 [0.72, 0.85] | 0.90 [0.77, 1.00] | 0.38 [0.27, 0.47] | 0.44 [0.29, 0.53] | 0.18 [0.10, 0.26] | 0.60 |
| engine | 0.99 (fpr 0.010) [0.97, 1.00] | 0.79 (fpr 0.010) [0.73, 0.85] | 0.90 (fpr 0.010) [0.77, 1.00] | 0.29 (fpr 0.010) [0.22, 0.38] | 0.44 (fpr 0.010) [0.29, 0.53] | 0.76 (fpr 0.010) [0.63, 0.89] | 0.70 |
| engine_no_arbiter | 1.00 (fpr 0.012) n/a (degenerate) | 0.79 (fpr 0.012) [0.73, 0.85] | 0.90 (fpr 0.012) [0.77, 1.00] | 0.39 (fpr 0.012) [0.29, 0.48] | 0.44 (fpr 0.012) [0.29, 0.53] | 0.76 (fpr 0.012) [0.63, 0.89] | 0.71 |
| engine_arbiter_no_imd | 1.00 (fpr 0.011) n/a (degenerate) | 0.79 (fpr 0.011) [0.73, 0.85] | 0.90 (fpr 0.011) [0.77, 1.00] | 0.35 (fpr 0.011) [0.27, 0.42] | 0.44 (fpr 0.011) [0.29, 0.53] | 0.76 (fpr 0.011) [0.63, 0.89] | 0.71 |
| engine_at_0.5pct | 0.99 (fpr 0.005) [0.97, 1.00] | 0.76 (fpr 0.005) [0.69, 0.82] | 0.86 (fpr 0.005) [0.73, 0.96] | 0.21 (fpr 0.005) [0.15, 0.28] | 0.31 (fpr 0.005) [0.20, 0.41] | 0.74 (fpr 0.005) [0.60, 0.87] | 0.64 |
| engine_at_2pct | 0.99 (fpr 0.020) [0.97, 1.00] | 0.82 (fpr 0.020) [0.77, 0.88] | 0.90 (fpr 0.020) [0.77, 1.00] | 0.34 (fpr 0.020) [0.27, 0.44] | 0.54 (fpr 0.020) [0.39, 0.62] | 0.80 (fpr 0.020) [0.68, 0.92] | 0.73 |
| ablation_own_only | 0.85 [0.79, 0.89] | 0.75 [0.69, 0.81] | 0.52 [0.18, 0.78] | 0.25 [0.15, 0.34] | 0.36 [0.29, 0.40] | 0.02 [0.00, 0.03] | 0.46 |
| ablation_no_grid | 0.88 [0.82, 0.91] | 0.77 [0.71, 0.84] | 0.79 [0.62, 0.92] | 0.31 [0.24, 0.37] | 0.43 [0.31, 0.52] | 0.04 [0.02, 0.07] | 0.54 |
| ablation_no_nbr | 0.88 [0.84, 0.91] | 0.79 [0.73, 0.86] | 0.90 [0.77, 1.00] | 0.35 [0.22, 0.47] | 0.42 [0.32, 0.49] | 0.15 [0.09, 0.20] | 0.58 |
| ablation_no_wet | 0.89 [0.86, 0.91] | 0.77 [0.72, 0.83] | 0.86 [0.74, 0.97] | 0.33 [0.27, 0.40] | 0.44 [0.31, 0.53] | 0.14 [0.08, 0.20] | 0.57 |
| ablation_no_dropout | 0.89 [0.85, 0.92] | 0.80 [0.74, 0.86] | 0.93 [0.81, 1.00] | 0.37 [0.27, 0.47] | 0.45 [0.32, 0.54] | 0.21 [0.12, 0.30] | 0.61 |
| ablation_no_extra_seeds | 0.81 [0.73, 0.91] | 0.81 [0.75, 0.86] | 0.90 [0.78, 1.00] | 0.34 [0.23, 0.41] | 0.35 [0.20, 0.45] | 0.13 [0.08, 0.18] | 0.55 |

### VAL: detection (episodes detected / total, median delay days)

| method | stuck_value | zero_fault | spike | scale_drift | offset_noise | duplicate_block |
|---|---|---|---|---|---|---|
| range_check | 0/27, n/a | 0/29, n/a | 0/29, n/a | 0/12, n/a | 0/22, n/a | 0/28, n/a |
| l1 | 27/27, 0.0 | 0/29, n/a | 0/29, n/a | 0/12, n/a | 0/22, n/a | 22/28, 0.0 |
| noaa_style_qa | 16/27, 0.0 | 3/29, 8.0 | 6/29, 0.0 | 0/12, n/a | 0/22, n/a | 2/28, 0.0 |
| noaa_style_qa_wide | 16/27, 0.0 | 12/29, 3.0 | 7/29, 0.0 | 2/12, 18.5 | 0/22, n/a | 9/28, 1.0 |
| robust_zscore | 2/27, 1.0 | 0/29, n/a | 11/29, 0.0 | 1/12, 6.0 | 0/22, n/a | 4/28, 8.0 |
| isolation_forest | 0/27, n/a | 0/29, n/a | 3/29, 0.0 | 1/12, 38.0 | 0/22, n/a | 0/28, n/a |
| engine_score | 27/27, 1.0 | 28/29, 3.0 | 26/29, 0.0 | 12/12, 22.5 | 19/22, 8.0 | 19/28, 6.0 |
| engine | 27/27, 0.0 | 28/29, 3.0 | 26/29, 0.0 | 12/12, 23.0 | 19/22, 8.0 | 26/28, 0.0 |
| engine_no_arbiter | 27/27, 0.0 | 28/29, 3.0 | 26/29, 0.0 | 12/12, 20.0 | 19/22, 8.0 | 26/28, 0.0 |
| engine_arbiter_no_imd | 27/27, 0.0 | 28/29, 3.0 | 26/29, 0.0 | 12/12, 22.0 | 19/22, 8.0 | 26/28, 0.0 |
| engine_at_0.5pct | 27/27, 0.0 | 28/29, 3.0 | 25/29, 0.0 | 11/12, 24.0 | 14/22, 9.0 | 23/28, 0.0 |
| engine_at_2pct | 27/27, 0.0 | 28/29, 2.0 | 26/29, 0.0 | 12/12, 14.5 | 20/22, 8.0 | 26/28, 0.0 |

### VAL: PR-AUC (score methods)

| method | stuck_value | zero_fault | spike | scale_drift | offset_noise | duplicate_block |
|---|---|---|---|---|---|---|
| robust_zscore | 0.058 | 0.030 | 0.084 | 0.050 | 0.008 | 0.054 |
| isolation_forest | 0.301 | 0.244 | 0.059 | 0.162 | 0.026 | 0.120 |
| engine_score | 0.903 | 0.792 | 0.738 | 0.452 | 0.243 | 0.232 |
| ablation_own_only | 0.880 | 0.737 | 0.419 | 0.336 | 0.159 | 0.064 |
| ablation_no_grid | 0.889 | 0.767 | 0.694 | 0.419 | 0.191 | 0.118 |
| ablation_no_nbr | 0.901 | 0.787 | 0.806 | 0.432 | 0.237 | 0.221 |
| ablation_no_wet | 0.902 | 0.774 | 0.751 | 0.411 | 0.236 | 0.207 |
| ablation_no_dropout | 0.900 | 0.795 | 0.777 | 0.454 | 0.268 | 0.259 |
| ablation_no_extra_seeds | 0.836 | 0.811 | 0.675 | 0.430 | 0.176 | 0.188 |

## Ablations (TEST macro recall of the model score at 1%; delta against the full model)

| variant | macro recall | delta |
|---|---|---|
| full model | 0.377 | 0 |
| own_only | 0.255 | -0.123 |
| no_grid | 0.404 | 0.026 |
| no_nbr | 0.400 | 0.022 |
| no_wet | 0.333 | -0.044 |
| no_dropout | 0.370 | -0.008 |
| no_extra_seeds | 0.277 | -0.101 |

## TEST: genuine-extreme retention, all variants (retained / extremes), and the spike trade-off

No single number is the safety result. `design-strict` and `wide` need >= 2 neighbours >= 30% of the value; `wide_1neighbour` needs 1; `uncorroborated` has no neighbour condition (proxy, includes unverified readings).

| method | design-strict | wide | wide_1neighbour | uncorroborated (proxy) | spike recall |
|---|---|---|---|---|---|
| engine | 3/3 = 1.000 n/a (degenerate) | 9/9 = 1.000 n/a (degenerate) | 17/18 = 0.944 [0.85, 1.00] | 24/26 = 0.923 [0.76, 1.00] | 0.87 (fpr 0.049) [0.76, 1.00] |
| engine_no_arbiter | 3/3 = 1.000 n/a (degenerate) | 9/9 = 1.000 n/a (degenerate) | 17/18 = 0.944 [0.85, 1.00] | 24/26 = 0.923 [0.76, 1.00] | 0.87 (fpr 0.051) [0.76, 1.00] |
| engine_arbiter_no_imd | 3/3 = 1.000 n/a (degenerate) | 9/9 = 1.000 n/a (degenerate) | 17/18 = 0.944 [0.85, 1.00] | 24/26 = 0.923 [0.76, 1.00] | 0.87 (fpr 0.050) [0.76, 1.00] |
| engine_score | 3/3 = 1.000 n/a (degenerate) | 9/9 = 1.000 n/a (degenerate) | 18/18 = 1.000 n/a (degenerate) | 25/26 = 0.962 [0.81, 1.00] | 0.57 [0.33, 0.81] |
| robust_zscore | 3/3 = 1.000 n/a (degenerate) | 5/9 = 0.556 [0.10, 1.00] | 13/18 = 0.722 [0.36, 1.00] | 21/26 = 0.808 [0.44, 1.00] | 0.39 [0.05, 0.68] |
| isolation_forest | 3/3 = 1.000 n/a (degenerate) | 7/9 = 0.778 [0.57, 1.00] | 16/18 = 0.889 [0.76, 1.00] | 24/26 = 0.923 [0.80, 1.00] | 0.22 [0.00, 0.48] |
| noaa_style_qa_wide | 3/3 = 1.000 n/a (degenerate) | 9/9 = 1.000 n/a (degenerate) | 18/18 = 1.000 n/a (degenerate) | 26/26 = 1.000 n/a (degenerate) | 0.35 (fpr 0.013) [0.14, 0.58] |
| l1 | 3/3 = 1.000 n/a (degenerate) | 9/9 = 1.000 n/a (degenerate) | 18/18 = 1.000 n/a (degenerate) | 26/26 = 1.000 n/a (degenerate) | 0.00 (fpr 0.002) n/a (degenerate) |

Spike days 23: flagged without the arbiter 20, with it 20; the arbiter retains 0 injected spike days as 'genuine extremes' (that is its spike-recall cost).

## VAL: genuine-extreme retention, all variants (retained / extremes), and the spike trade-off

No single number is the safety result. `design-strict` and `wide` need >= 2 neighbours >= 30% of the value; `wide_1neighbour` needs 1; `uncorroborated` has no neighbour condition (proxy, includes unverified readings).

| method | design-strict | wide | wide_1neighbour | uncorroborated (proxy) | spike recall |
|---|---|---|---|---|---|
| engine | 8/8 = 1.000 n/a (degenerate) | 13/13 = 1.000 n/a (degenerate) | 26/26 = 1.000 n/a (degenerate) | 36/38 = 0.947 [0.91, 1.00] | 0.90 (fpr 0.010) [0.77, 1.00] |
| engine_no_arbiter | 8/8 = 1.000 n/a (degenerate) | 13/13 = 1.000 n/a (degenerate) | 25/26 = 0.962 [0.90, 1.00] | 35/38 = 0.921 [0.88, 1.00] | 0.90 (fpr 0.012) [0.77, 1.00] |
| engine_arbiter_no_imd | 8/8 = 1.000 n/a (degenerate) | 13/13 = 1.000 n/a (degenerate) | 25/26 = 0.962 [0.90, 1.00] | 35/38 = 0.921 [0.88, 1.00] | 0.90 (fpr 0.011) [0.77, 1.00] |
| engine_score | 8/8 = 1.000 n/a (degenerate) | 13/13 = 1.000 n/a (degenerate) | 25/26 = 0.962 [0.90, 1.00] | 35/38 = 0.921 [0.88, 1.00] | 0.90 [0.77, 1.00] |
| robust_zscore | 8/8 = 1.000 n/a (degenerate) | 12/13 = 0.923 [0.75, 1.00] | 21/26 = 0.808 [0.66, 0.97] | 33/38 = 0.868 [0.74, 0.98] | 0.38 [0.20, 0.54] |
| isolation_forest | 8/8 = 1.000 n/a (degenerate) | 13/13 = 1.000 n/a (degenerate) | 26/26 = 1.000 n/a (degenerate) | 38/38 = 1.000 n/a (degenerate) | 0.10 [0.00, 0.24] |
| noaa_style_qa_wide | 8/8 = 1.000 n/a (degenerate) | 13/13 = 1.000 n/a (degenerate) | 26/26 = 1.000 n/a (degenerate) | 38/38 = 1.000 n/a (degenerate) | 0.24 (fpr 0.015) [0.10, 0.41] |
| l1 | 8/8 = 1.000 n/a (degenerate) | 13/13 = 1.000 n/a (degenerate) | 26/26 = 1.000 n/a (degenerate) | 38/38 = 1.000 n/a (degenerate) | 0.00 (fpr 0.001) n/a (degenerate) |

Spike days 29: flagged without the arbiter 26, with it 26; the arbiter retains 0 injected spike days as 'genuine extremes' (that is its spike-recall cost).

## Repair (flagged, non-retained injected-fault days with a reference)

### TEST: 1365 faulty days, 900 flagged and not retained, 773 with a repair, 688 on the common set

| estimate | MAE mm | median abs error mm |
|---|---|---|
| engine_repair | 11.24 | 6.00 |
| previous_day | 19.44 | 12.10 |
| neighbour_mean | 15.34 | 8.35 |
| zero_fill | 13.17 | 5.10 |
| no_repair_observed | 27.71 | 11.65 |

Band (10th-90th residual percentile) coverage 0.755; hazard-safe: 40 repaired days with true rain >= 50 mm, share repaired >= 50% of truth 0.425.

### VAL: 1681 faulty days, 1140 flagged and not retained, 1140 with a repair, 870 on the common set

| estimate | MAE mm | median abs error mm |
|---|---|---|
| engine_repair | 11.37 | 4.76 |
| previous_day | 21.15 | 13.80 |
| neighbour_mean | 17.24 | 7.43 |
| zero_fill | 17.94 | 6.10 |
| no_repair_observed | 33.07 | 14.00 |

Band (10th-90th residual percentile) coverage 0.781; hazard-safe: 96 repaired days with true rain >= 50 mm, share repaired >= 50% of truth 0.615.

## Stability across injection seeds (TEST stations, engine trained once)

| seed | macro recall (score @1%) | macro recall (full engine) | full-engine false-flag rate |
|---|---|---|---|
| frozen | 0.377 | 0.702 | 0.0492 |
| 20261201 | 0.393 | 0.649 | 0.0555 |
| 20261202 | 0.412 | 0.681 | 0.0473 |
| 20261203 | 0.393 | 0.684 | 0.0571 |
| score_at_1pct: mean [min, max] | 0.394 [0.377, 0.412] | | |
| full_engine_flags: mean [min, max] | 0.679 [0.649, 0.702] | | |

Per-type range (score @1%): stuck_value 0.83 [0.82, 0.85]; zero_fault 0.60 [0.56, 0.63]; spike 0.73 [0.57, 0.81]; scale_drift 0.02 [0.02, 0.02]; offset_noise 0.16 [0.12, 0.19]; duplicate_block 0.02 [0.00, 0.03]

## Real NOAA flags 2007-2024 (sanity check)

n = 10 real flagged values ({'G': 3, 'O': 7}), 2007+ only: too few to rank methods. Real flags are single-day O/G/S extremes, not streaks or duplicates.

| method | real flags flagged | by NOAA flag | false-flag rate on unflagged days |
|---|---|---|---|
| range_check | 0 / 10 | {} | 0.0000 |
| l1 | 0 / 10 | {} | 0.0018 |
| noaa_style_qa | 6 / 10 | {'G': 2, 'O': 4} | 0.0013 |
| noaa_style_qa_wide | 6 / 10 | {'G': 2, 'O': 4} | 0.0184 |
| robust_zscore | 1 / 10 | {'O': 1} | 0.0018 |
| isolation_forest | 0 / 10 | {} | 0.0001 |
| engine | 9 / 10 | {'G': 3, 'O': 6} | 0.0102 |
| engine_no_arbiter | 9 / 10 | {'G': 3, 'O': 6} | 0.0110 |

## Combined engine at the VAL-chosen threshold: realised false-flag rate and macro recall

| target | combined tau | VAL realised fpr | VAL macro recall | TEST realised fpr | TEST macro recall |
|---|---|---|---|---|---|
| 0.005 | 0.714 | 0.0050 | 0.643 | 0.0348 | 0.658 |
| 0.01 | 0.507 | 0.0100 | 0.695 | 0.0492 | 0.702 |
| 0.02 | 0.344 | 0.0199 | 0.730 | 0.0684 | 0.747 |

Secondary: the MODEL-ONLY threshold (no L1, no arbiter) at the same targets:

| target | model-only tau | VAL realised fpr | VAL macro recall | TEST realised fpr | TEST macro recall |
|---|---|---|---|---|---|
| 0.005 | 0.714 | 0.0050 | 0.544 | 0.0358 | 0.536 |
| 0.01 | 0.507 | 0.0100 | 0.597 | 0.0481 | 0.588 |
| 0.02 | 0.344 | 0.0199 | 0.646 | 0.0657 | 0.641 |

## Why the realised TEST false-flag rate differs from the target

- Combined engine at the 1% target: VAL 0.0100, TEST 0.0492 (without the arbiter: VAL 0.0120, TEST 0.0510).
- Union effect: L1 alone flags 0.0014 of VAL and 0.0015 of TEST clean days; the combined tau (0.5072) vs the model-only tau (0.5072) accounts for it on VAL.
- Isotonic ties: 12039 distinct calibrated scores over 12039 VAL clean days; 0.00008 of them equal the model-only tau, so plateau ties do not move the rate.
- Clean-day definition: selection and evaluation use the same mask: clean real day (valid, unflagged, station-year >= 150 valid days) outside every episode window, with an observed value.
- Model-only flags at the model-only tau: VAL 0.0100, TEST 0.0481.
- Concentration: 496 of 545 TEST false flags (91%) come from the two Nepal stations, which hold 51% of the TEST clean days; the other TEST stations realise 0.0089. Both Nepal stations are in TEST (none in TRAIN or VAL).
- Nepal model false flags by month: {'1': 16, '2': 6, '3': 5, '4': 1, '5': 10, '6': 20, '7': 46, '8': 72, '9': 40, '10': 136, '11': 122, '12': 9}; by predicted class: {'zero_fault': 358, 'scale_drift': 118, 'offset_noise': 7}.
- Missing references do not explain it: VAL model false-flag rate with columns removed {'none': 0.01, 'imd columns': 0.0087, 'all grid_ columns': 0.0105, 'nbr_ columns': 0.0125}.

| TEST station | country | upland | clean days | false flags | rate |
|---|---|---|---|---|---|
| NP000444540 | NP | True | 3254 | 329 | 0.1011 |
| NPM00044477 | NP | True | 2341 | 167 | 0.0713 |
| IN003050500 | IN | False | 3217 | 26 | 0.0081 |
| IN003030100 | IN | False | 565 | 8 | 0.0142 |
| IN009120100 | IN | False | 259 | 6 | 0.0232 |
| IN017121000 | IN | False | 253 | 4 | 0.0158 |

### TEST without the two Nepal stations (26 stations; post-hoc sensitivity, not used for any selection)

| method | stuck_value | zero_fault | spike | scale_drift | offset_noise | duplicate_block | macro |
|---|---|---|---|---|---|---|---|
| range_check | 0.00 (fpr 0.000) n/a (degenerate) | 0.00 (fpr 0.000) n/a (degenerate) | 0.00 (fpr 0.000) n/a (degenerate) | 0.00 (fpr 0.000) n/a (degenerate) | 0.00 (fpr 0.000) n/a (degenerate) | 0.00 (fpr 0.000) n/a (degenerate) | 0.00 |
| l1 | 1.00 (fpr 0.002) n/a (degenerate) | 0.00 (fpr 0.002) n/a (degenerate) | 0.00 (fpr 0.002) n/a (degenerate) | 0.00 (fpr 0.002) n/a (degenerate) | 0.00 (fpr 0.002) n/a (degenerate) | 0.85 (fpr 0.002) [0.52, 1.00] | 0.31 |
| noaa_style_qa | 0.85 (fpr 0.001) [0.57, 0.94] | 0.05 (fpr 0.001) [0.00, 0.07] | 0.43 (fpr 0.001) [0.10, 0.67] | 0.00 (fpr 0.001) n/a (degenerate) | 0.00 (fpr 0.001) n/a (degenerate) | 0.00 (fpr 0.001) n/a (degenerate) | 0.22 |
| noaa_style_qa_wide | 0.86 (fpr 0.014) [0.62, 0.94] | 0.25 (fpr 0.014) [0.18, 0.44] | 0.50 (fpr 0.014) [0.25, 0.69] | 0.00 (fpr 0.014) n/a (degenerate) | 0.00 (fpr 0.014) n/a (degenerate) | 0.08 (fpr 0.014) [0.03, 0.17] | 0.28 |
| robust_zscore | 0.01 [0.00, 0.05] | 0.00 n/a (degenerate) | 0.14 [0.00, 0.27] | 0.00 n/a (degenerate) | 0.00 n/a (degenerate) | 0.02 [0.00, 0.07] | 0.03 |
| isolation_forest | 0.00 n/a (degenerate) | 0.00 n/a (degenerate) | 0.07 [0.00, 0.30] | 0.00 n/a (degenerate) | 0.00 n/a (degenerate) | 0.00 n/a (degenerate) | 0.01 |
| engine_score | 0.88 [0.85, 0.89] | 0.85 [0.77, 0.94] | 0.93 [0.73, 1.00] | 0.30 [0.02, 0.41] | 0.43 [0.30, 0.73] | 0.22 [0.11, 0.37] | 0.60 |
| engine | 0.95 (fpr 0.009) [0.92, 0.98] | 0.85 (fpr 0.009) [0.77, 0.94] | 0.93 (fpr 0.009) [0.73, 1.00] | 0.23 (fpr 0.009) [0.02, 0.31] | 0.43 (fpr 0.009) [0.30, 0.73] | 0.91 (fpr 0.009) [0.72, 1.00] | 0.72 |
| engine_no_arbiter | 1.00 (fpr 0.011) n/a (degenerate) | 0.85 (fpr 0.011) [0.77, 0.94] | 0.93 (fpr 0.011) [0.73, 1.00] | 0.30 (fpr 0.011) [0.02, 0.41] | 0.43 (fpr 0.011) [0.30, 0.73] | 0.92 (fpr 0.011) [0.74, 1.00] | 0.74 |
| engine_arbiter_no_imd | 1.00 (fpr 0.010) n/a (degenerate) | 0.85 (fpr 0.010) [0.77, 0.94] | 0.93 (fpr 0.010) [0.73, 1.00] | 0.25 (fpr 0.010) [0.02, 0.34] | 0.43 (fpr 0.010) [0.30, 0.73] | 0.92 (fpr 0.010) [0.74, 1.00] | 0.73 |
| engine_at_0.5pct | 0.95 (fpr 0.005) [0.92, 0.98] | 0.83 (fpr 0.005) [0.73, 0.94] | 0.93 (fpr 0.005) [0.73, 1.00] | 0.13 (fpr 0.005) [0.02, 0.18] | 0.37 (fpr 0.005) [0.24, 0.57] | 0.86 (fpr 0.005) [0.58, 1.00] | 0.68 |
| engine_at_2pct | 0.95 (fpr 0.018) [0.92, 0.98] | 0.87 (fpr 0.018) [0.80, 0.94] | 1.00 (fpr 0.018) n/a (degenerate) | 0.31 (fpr 0.018) [0.08, 0.40] | 0.52 (fpr 0.018) [0.42, 0.76] | 0.94 (fpr 0.018) [0.80, 1.00] | 0.76 |
| ablation_own_only | 0.83 [0.77, 0.86] | 0.81 [0.68, 0.85] | 0.36 [0.00, 0.62] | 0.25 [0.05, 0.33] | 0.54 [0.44, 0.83] | 0.01 [0.00, 0.02] | 0.47 |
| ablation_no_grid | 0.87 [0.83, 0.89] | 0.83 [0.73, 0.91] | 0.71 [0.36, 0.92] | 0.27 [0.03, 0.36] | 0.50 [0.40, 0.74] | 0.05 [0.01, 0.11] | 0.54 |
| ablation_no_nbr | 0.88 [0.83, 0.90] | 0.85 [0.77, 0.94] | 0.86 [0.64, 1.00] | 0.32 [0.02, 0.44] | 0.41 [0.19, 0.57] | 0.19 [0.10, 0.26] | 0.58 |
| ablation_no_wet | 0.87 [0.83, 0.89] | 0.84 [0.77, 0.91] | 0.79 [0.50, 0.95] | 0.29 [0.02, 0.39] | 0.48 [0.38, 0.65] | 0.15 [0.04, 0.26] | 0.57 |
| ablation_no_dropout | 0.88 [0.82, 0.90] | 0.87 [0.83, 0.94] | 0.93 [0.85, 1.00] | 0.32 [0.00, 0.50] | 0.43 [0.32, 0.59] | 0.20 [0.08, 0.30] | 0.60 |
| ablation_no_extra_seeds | 0.64 [0.44, 0.82] | 0.87 [0.83, 0.94] | 0.71 [0.45, 0.89] | 0.24 [0.02, 0.36] | 0.24 [0.15, 0.40] | 0.09 [0.03, 0.18] | 0.47 |


## SUPPLEMENT: 5-fold station-grouped cross-validation (55 stations with episodes)

Held-out stations scored by engines trained on the other folds (frozen-seed dataset only); NOT the headline.

| method | stuck_value | zero_fault | spike | scale_drift | offset_noise | duplicate_block | macro |
|---|---|---|---|---|---|---|---|
| engine_oof | 0.98 (fpr 0.032) [0.97, 0.98] | 0.80 (fpr 0.032) [0.75, 0.84] | 0.82 (fpr 0.032) [0.74, 0.88] | 0.23 (fpr 0.032) [0.19, 0.27] | 0.30 (fpr 0.032) [0.24, 0.38] | 0.67 (fpr 0.032) [0.57, 0.77] | 0.63 |
| l1 | 1.00 (fpr 0.002) n/a (degenerate) | 0.00 (fpr 0.002) n/a (degenerate) | 0.00 (fpr 0.002) n/a (degenerate) | 0.00 (fpr 0.002) n/a (degenerate) | 0.02 (fpr 0.002) [0.00, 0.03] | 0.63 (fpr 0.002) [0.54, 0.75] | 0.28 |
| noaa_style_qa_wide | 0.85 (fpr 0.016) [0.78, 0.91] | 0.24 (fpr 0.016) [0.18, 0.31] | 0.33 (fpr 0.016) [0.25, 0.43] | 0.00 (fpr 0.016) [0.00, 0.01] | 0.00 (fpr 0.016) n/a (degenerate) | 0.08 (fpr 0.016) [0.04, 0.14] | 0.25 |
| robust_zscore | 0.05 [0.01, 0.11] | 0.00 n/a (degenerate) | 0.29 [0.20, 0.39] | 0.00 [0.00, 0.01] | 0.00 n/a (degenerate) | 0.01 [0.00, 0.02] | 0.06 |

OOF outputs (real series, `engine_outputs_2007_oof.parquet`): 920500 rows, trust NaN share 0.769 (days without a value), flagged 0.0158 of observed days, 251 genuine-extreme days, 83.5 MB.

## Gate assessment (TEST)

At the VAL-chosen 1% tau the combined engine flags 0.0100 of VAL clean days but 0.0492 of TEST clean days. 91% of the TEST false flags (496 of 545) come from the two Nepal stations, which hold 51% of the TEST clean days and are the only TEST stations outside the training distribution of Indian stations; without them the TEST rate is 0.0089. The threshold does not transfer to those stations: the engine is NOT at 1% on TEST, so the full-engine recalls below are at a higher false-flag rate than the baselines (read the oracle-matched rows and the model-score rows for matched-rate comparisons).

### Primary: the combined engine at the VAL-chosen 1% tau against each baseline (recall CIs over stations)

- [combined engine @ VAL-chosen 1% tau, realised TEST false-flag rate 0.0492] stuck_value (recall 0.97 [0.94, 1.00], 316 days): range_check: beats; l1: loses; noaa_style_qa: ties (CIs overlap); noaa_style_qa_wide: ties (CIs overlap); robust_zscore: beats; isolation_forest: beats
- [combined engine @ VAL-chosen 1% tau, realised TEST false-flag rate 0.0492] zero_fault (recall 0.80 [0.69, 0.87], 212 days): range_check: beats; l1: beats; noaa_style_qa: beats; noaa_style_qa_wide: beats; robust_zscore: beats; isolation_forest: beats
- [combined engine @ VAL-chosen 1% tau, realised TEST false-flag rate 0.0492] spike (recall 0.87 [0.76, 1.00], 23 days): range_check: beats; l1: beats; noaa_style_qa: beats; noaa_style_qa_wide: beats; robust_zscore: beats; isolation_forest: beats
- [combined engine @ VAL-chosen 1% tau, realised TEST false-flag rate 0.0492] scale_drift (recall 0.22 [0.05, 0.31], 330 days): range_check: beats; l1: beats; noaa_style_qa: beats; noaa_style_qa_wide: beats; robust_zscore: beats; isolation_forest: beats
- [combined engine @ VAL-chosen 1% tau, realised TEST false-flag rate 0.0492] offset_noise (recall 0.51 [0.38, 0.58], 230 days): range_check: beats; l1: beats; noaa_style_qa: beats; noaa_style_qa_wide: beats; robust_zscore: beats; isolation_forest: beats
- [combined engine @ VAL-chosen 1% tau, realised TEST false-flag rate 0.0492] duplicate_block (recall 0.83 [0.60, 1.00], 254 days): range_check: beats; l1: ties (CIs overlap); noaa_style_qa: beats; noaa_style_qa_wide: beats; robust_zscore: beats; isolation_forest: beats

### Secondary: the model score alone at a matched 1% on the TEST clean days

- [model score only, 1% on the TEST clean days] stuck_value (recall 0.84 [0.80, 0.86], 316 days): range_check: beats; l1: loses; noaa_style_qa: ties (CIs overlap); noaa_style_qa_wide: ties (CIs overlap); robust_zscore: beats; isolation_forest: beats
- [model score only, 1% on the TEST clean days] zero_fault (recall 0.63 [0.47, 0.73], 212 days): range_check: beats; l1: beats; noaa_style_qa: beats; noaa_style_qa_wide: beats; robust_zscore: beats; isolation_forest: beats
- [model score only, 1% on the TEST clean days] spike (recall 0.57 [0.33, 0.81], 23 days): range_check: beats; l1: beats; noaa_style_qa: ties (CIs overlap); noaa_style_qa_wide: ties (CIs overlap); robust_zscore: ties (CIs overlap); isolation_forest: ties (CIs overlap)
- [model score only, 1% on the TEST clean days] scale_drift (recall 0.02 [0.00, 0.03], 330 days): range_check: ties (CIs overlap); l1: ties (CIs overlap); noaa_style_qa: ties (CIs overlap); noaa_style_qa_wide: ties (CIs overlap); robust_zscore: ties (CIs overlap); isolation_forest: ties (CIs overlap)
- [model score only, 1% on the TEST clean days] offset_noise (recall 0.19 [0.14, 0.21], 230 days): range_check: beats; l1: beats; noaa_style_qa: beats; noaa_style_qa_wide: beats; robust_zscore: beats; isolation_forest: beats
- [model score only, 1% on the TEST clean days] duplicate_block (recall 0.02 [0.00, 0.04], 254 days): range_check: ties (CIs overlap); l1: loses; noaa_style_qa: ties (CIs overlap); noaa_style_qa_wide: ties (CIs overlap); robust_zscore: ties (CIs overlap); isolation_forest: ties (CIs overlap)

### Oracle-matched comparison (tau picked on TEST to equal noaa_style_qa_wide's false-flag rate; not deployable)

- [oracle-matched to noaa_style_qa_wide's TEST rate 0.0126 (engine realises 0.0126; not deployable)] stuck_value (recall 0.97 [0.94, 1.00], 316 days): range_check: beats; l1: loses; noaa_style_qa: ties (CIs overlap); noaa_style_qa_wide: ties (CIs overlap); robust_zscore: beats; isolation_forest: beats
- [oracle-matched to noaa_style_qa_wide's TEST rate 0.0126 (engine realises 0.0126; not deployable)] zero_fault (recall 0.65 [0.51, 0.74], 212 days): range_check: beats; l1: beats; noaa_style_qa: beats; noaa_style_qa_wide: beats; robust_zscore: beats; isolation_forest: beats
- [oracle-matched to noaa_style_qa_wide's TEST rate 0.0126 (engine realises 0.0126; not deployable)] spike (recall 0.57 [0.33, 0.81], 23 days): range_check: beats; l1: beats; noaa_style_qa: ties (CIs overlap); noaa_style_qa_wide: ties (CIs overlap); robust_zscore: ties (CIs overlap); isolation_forest: ties (CIs overlap)
- [oracle-matched to noaa_style_qa_wide's TEST rate 0.0126 (engine realises 0.0126; not deployable)] scale_drift (recall 0.03 [0.00, 0.05], 330 days): range_check: ties (CIs overlap); l1: ties (CIs overlap); noaa_style_qa: ties (CIs overlap); noaa_style_qa_wide: ties (CIs overlap); robust_zscore: ties (CIs overlap); isolation_forest: ties (CIs overlap)
- [oracle-matched to noaa_style_qa_wide's TEST rate 0.0126 (engine realises 0.0126; not deployable)] offset_noise (recall 0.22 [0.14, 0.24], 230 days): range_check: beats; l1: beats; noaa_style_qa: beats; noaa_style_qa_wide: beats; robust_zscore: beats; isolation_forest: beats
- [oracle-matched to noaa_style_qa_wide's TEST rate 0.0126 (engine realises 0.0126; not deployable)] duplicate_block (recall 0.78 [0.51, 1.00], 254 days): range_check: beats; l1: ties (CIs overlap); noaa_style_qa: beats; noaa_style_qa_wide: beats; robust_zscore: beats; isolation_forest: beats

Limits: only 11 TEST stations (and 11 VAL) carry injected episodes and scale_drift has the fewest; the CHIRPS-aligned reference correlates only about 0.38 with the stations; IMD is not independent of the gauges (arbiter variants with and without IMD are both reported); every fault is injected into real series, so recall measures detection of synthetic faults, not of the faults real gauges produce (the 10 real flags are too few to say); references exist only from 2007, so none of the 1990-2004 clean data is used.

Runtime (s): {'train_main_s': 150.3, 'train_ablations_s': 197.3, 'evaluate_s': 169.4, 'total_s': 629.2}.
