# Heavy-rain warnings v2: shipped calibration, levels at target frequencies, the test on June-September 2025

Spec: `docs/superpowers/specs/2026-11-14-aetherguard-rain-warnings.md section 12`, committed before any 2025 data was fetched. Research prototype: not validated for public warnings; it does not change any landslide alert level. Base report: `reports/phase8_rain_warnings.md`.

## Development (June-September 2023 + 2024 only)

Candidate A = the section 4 predictors; B = A plus the season-state predictor. Cross-season log loss summed over D+1..D+3 and the five thresholds: A 2218243.7, B 2213367.9. Shipped: **B** (lead 0 keeps A). Calibration file `data/processed/rainwarn/calibration_v2.json` (sha256 b552d20cf27d).

| lead | threshold | candidate | cross-season log loss (sum) | test 2024: BSS, mean p / base rate | test 2023: BSS, mean p / base rate |
|---|---|---|---|---|---|
| D (today, mostly observed) | heavy | A | 43196.0 | 0.680, 1.00 | 0.676, 0.99 |
| D (today, mostly observed) | very_heavy | A | 13469.3 | 0.595, 0.94 | 0.466, 1.22 |
| D (today, mostly observed) | extremely_heavy | A | 1474.8 | 0.442, 0.94 | 0.414, 1.20 |
| D (today, mostly observed) | p95 | A | 97188.4 | 0.671, 1.00 | 0.685, 1.01 |
| D (today, mostly observed) | p99 | A | 34296.3 | 0.610, 1.04 | 0.561, 0.95 |
| D+1 | heavy | A | 165610.4 | 0.180, 0.94 | 0.130, 1.18 |
| D+1 | heavy | B | 166177.7 | 0.180, 0.93 | 0.120, 1.01 |
| D+1 | very_heavy | A | 45136.1 | 0.100, 0.62 | 0.017, 1.87 |
| D+1 | very_heavy | B | 45243.7 | 0.098, 0.60 | 0.024, 1.52 |
| D+1 | extremely_heavy | A | 5909.7 | 0.008, 0.14 | -0.077, 8.59 |
| D+1 | extremely_heavy | B | 5771.0 | 0.008, 0.15 | -0.015, 5.65 |
| D+1 | p95 | A | 375666.8 | 0.131, 0.95 | 0.114, 1.10 |
| D+1 | p95 | B | 375359.5 | 0.131, 0.98 | 0.114, 0.98 |
| D+1 | p99 | A | 128763.0 | 0.088, 0.83 | 0.059, 1.32 |
| D+1 | p99 | B | 127586.3 | 0.089, 0.90 | 0.062, 1.07 |
| D+2 | heavy | A | 170692.7 | 0.133, 0.95 | 0.098, 1.21 |
| D+2 | heavy | B | 170705.1 | 0.133, 0.96 | 0.091, 1.05 |
| D+2 | very_heavy | A | 46300.3 | 0.058, 0.58 | -0.009, 1.96 |
| D+2 | very_heavy | B | 45950.4 | 0.059, 0.60 | 0.004, 1.65 |
| D+2 | extremely_heavy | A | 5760.7 | 0.004, 0.11 | -0.100, 8.93 |
| D+2 | extremely_heavy | B | 5542.5 | 0.005, 0.14 | -0.041, 6.21 |
| D+2 | p95 | A | 386435.3 | 0.100, 0.94 | 0.094, 1.12 |
| D+2 | p95 | B | 385837.7 | 0.100, 0.99 | 0.095, 1.01 |
| D+2 | p99 | A | 131971.4 | 0.060, 0.83 | 0.025, 1.35 |
| D+2 | p99 | B | 130635.5 | 0.061, 0.95 | 0.034, 1.11 |
| D+3 | heavy | A | 173643.7 | 0.111, 0.91 | 0.087, 1.18 |
| D+3 | heavy | B | 173974.9 | 0.111, 0.91 | 0.081, 1.04 |
| D+3 | very_heavy | A | 46999.5 | 0.045, 0.52 | -0.010, 1.95 |
| D+3 | very_heavy | B | 46988.2 | 0.044, 0.51 | -0.001, 1.68 |
| D+3 | extremely_heavy | A | 5985.2 | 0.002, 0.11 | -0.034, 8.70 |
| D+3 | extremely_heavy | B | 5814.9 | 0.003, 0.13 | -0.010, 6.68 |
| D+3 | p95 | A | 395845.6 | 0.079, 0.93 | 0.081, 1.10 |
| D+3 | p95 | B | 395323.4 | 0.078, 0.97 | 0.081, 1.01 |
| D+3 | p99 | A | 133523.2 | 0.049, 0.83 | 0.027, 1.29 |
| D+3 | p99 | B | 132457.1 | 0.050, 0.92 | 0.031, 1.11 |

Level cutoffs per lead, set on the 2023 + 2024 pixel-days so that red fires on 0.3%, orange or above on 1.5% and yellow or above on 6.0%:

| lead | red: P_vh >= | orange: max(P_h, P_99) >= | yellow: max(P_h, P_95) >= | pixel-days |
|---|---|---|---|---|
| D (today, mostly observed) | 0.7421 | 0.8700 | 0.5318 | 1260294 |
| D+1 | 0.1858 | 0.2883 | 0.2110 | 2293508 |
| D+2 | 0.1779 | 0.2675 | 0.1994 | 2293508 |
| D+3 | 0.1534 | 0.2436 | 0.1868 | 2293508 |

In sample (2023 + 2024, shipped calibration, v2 levels):

| lead | level | share of pixel-days | observed >= heavy | share of heavy events | share of very heavy events |
|---|---|---|---|---|---|
| D (today, mostly observed) | none | 94.000% | 0.4% | 11.8% | 1.1% |
| D (today, mostly observed) | yellow | 4.500% | 29.1% | 43.2% | 7.2% |
| D (today, mostly observed) | orange | 1.200% | 88.6% | 35.1% | 51.4% |
| D (today, mostly observed) | red | 0.300% | 99.7% | 9.9% | 40.4% |
| D+1 | none | 94.000% | 1.1% | 47.9% | 33.0% |
| D+1 | yellow | 4.500% | 10.4% | 20.9% | 17.3% |
| D+1 | orange | 1.200% | 40.6% | 21.7% | 27.1% |
| D+1 | red | 0.300% | 71.2% | 9.5% | 22.6% |
| D+2 | none | 94.000% | 1.2% | 51.6% | 36.1% |
| D+2 | yellow | 4.500% | 10.1% | 20.5% | 17.8% |
| D+2 | orange | 1.200% | 36.1% | 19.6% | 26.2% |
| D+2 | red | 0.300% | 62.0% | 8.4% | 19.9% |
| D+3 | none | 94.000% | 1.3% | 53.8% | 38.9% |
| D+3 | yellow | 4.500% | 9.5% | 19.4% | 18.0% |
| D+3 | orange | 1.200% | 37.0% | 20.2% | 28.2% |
| D+3 | red | 0.300% | 48.2% | 6.6% | 14.8% |

## The one test on June-September 2025

Issue days with an ECMWF file: 122 (2025-06-01..2025-09-30); calibration sha256 b552d20cf27d. No GFS and no IMD grid exist locally for 2025, so the GFS baseline and the IMD second opinion are absent; the ECMWF ensemble-mean and HRES baselines are scored.

**Verdict: FAIL** (spec section 12.4).

| check | value | rule | met |
|---|---|---|---|
| issue days D+1 | 122 | >= 90 | yes |
| issue days D+2 | 122 | >= 90 | yes |
| issue days D+3 | 121 | >= 90 | yes |
| D+1 heavy enough events | [17446, 117] | section 6 | yes |
| D+1 heavy BSS lower bound | 0.051 | > 0 | yes |
| D+1 heavy mean p / base rate | 1.344 | 0.67..1.5 | yes |
| D+2 heavy enough events | [17387, 117] | section 6 | yes |
| D+2 heavy BSS lower bound | 0.023 | > 0 | yes |
| D+2 heavy mean p / base rate | 1.424 | 0.67..1.5 | yes |
| D+3 heavy enough events | [17377, 116] | section 6 | yes |
| D+3 heavy BSS lower bound | -0.009 | > 0 | NO |
| D+3 heavy mean p / base rate | 1.506 | 0.67..1.5 | NO |
| D+1 very_heavy enough events | [2188, 88] | section 6 | yes |
| D+1 very_heavy BSS lower bound | -0.010 | > 0 | NO |
| D+1 very_heavy mean p / base rate | 1.654 | 0.67..1.5 | NO |
| D+2 very_heavy enough events | [2170, 88] | section 6 | yes |
| D+2 very_heavy BSS lower bound | -0.034 | > 0 | NO |
| D+2 very_heavy mean p / base rate | 1.758 | 0.67..1.5 | NO |
| D+1 share of heavy events under none | 0.606 | <= 0.4 | NO |
| D+2 share of heavy events under none | 0.645 | <= 0.5 | NO |
| D+3 share of heavy events under none | 0.720 | <= 0.5 | NO |

### All rows (product = shipped v2 calibration)

| lead | threshold | region | event pixel-days | event days | BSS (95% CI) | ROC area (CI) | REL/UNC | mean p / base rate | verdict |
|---|---|---|---|---|---|---|---|---|---|
| D+1 | heavy | domain | 17446 | 117 | 0.092 [+0.051, +0.132] | 0.897 [+0.881, +0.912] | 0.005 | 1.34 | skilful; beats every baseline; NOT reliable; discriminates |
| D+1 | heavy | himalaya | 10594 | 116 | 0.048 [+0.018, +0.077] | 0.866 [+0.846, +0.886] | 0.007 | 1.28 | skilful; beats every baseline; NOT reliable; discriminates |
| D+1 | heavy | western_ghats | 5324 | 72 | 0.180 [+0.080, +0.265] | 0.947 [+0.929, +0.961] | 0.008 | 1.44 | skilful; beats every baseline; NOT reliable; discriminates |
| D+1 | very_heavy | domain | 2188 | 88 | 0.033 [-0.010, +0.076] | 0.925 [+0.900, +0.947] | 0.009 | 1.65 | NOT skilful; beats every baseline; NOT reliable; discriminates |
| D+1 | very_heavy | himalaya | 1415 | 82 | 0.029 [+0.003, +0.052] | 0.901 [+0.867, +0.926] | 0.003 | 1.40 | skilful; beats every baseline; NOT reliable; discriminates |
| D+1 | very_heavy | western_ghats | 607 | 25 | 0.039 [-0.155, +0.142] | 0.973 [+0.950, +0.987] | 0.037 | 2.18 | NOT skilful; does not beat ens_mean; NOT reliable; discriminates |
| D+1 | extremely_heavy | domain | 97 | 18 | 0.001 [-0.013, +0.017] | 0.785 [+0.608, +0.965] | 0.002 | 1.79 | too few events to conclude |
| D+1 | extremely_heavy | himalaya | 93 | 15 | 0.010 [+0.002, +0.028] | 0.779 [+0.597, +0.966] | 0.000 | 0.94 | too few events to conclude |
| D+1 | extremely_heavy | western_ghats | 1 | 1 | -0.550 [-4.503, +0.041] | 0.971 [+0.955, +0.983] | 0.158 | 70.92 | too few events to conclude |
| D+1 | p95 | domain | 60020 | 122 | 0.120 [+0.098, +0.144] | 0.846 [+0.832, +0.861] | 0.001 | 1.10 | skilful; beats every baseline; reliable; discriminates |
| D+1 | p95 | himalaya | 40479 | 122 | 0.108 [+0.079, +0.136] | 0.831 [+0.813, +0.849] | 0.002 | 1.08 | skilful; beats every baseline; reliable; discriminates |
| D+1 | p95 | western_ghats | 11617 | 103 | 0.149 [+0.104, +0.189] | 0.882 [+0.859, +0.903] | 0.003 | 1.15 | skilful; beats every baseline; reliable; discriminates |
| D+1 | p99 | domain | 12102 | 116 | 0.067 [+0.029, +0.108] | 0.889 [+0.868, +0.908] | 0.002 | 1.13 | skilful; beats every baseline; reliable; discriminates |
| D+1 | p99 | himalaya | 9444 | 111 | 0.081 [+0.036, +0.128] | 0.883 [+0.856, +0.907] | 0.013 | 0.97 | skilful; beats every baseline; reliable; discriminates |
| D+1 | p99 | western_ghats | 1356 | 66 | -0.014 [-0.114, +0.048] | 0.911 [+0.884, +0.934] | 0.057 | 2.08 | NOT skilful; beats every baseline; NOT reliable; discriminates |
| D+2 | heavy | domain | 17387 | 117 | 0.060 [+0.023, +0.097] | 0.884 [+0.866, +0.900] | 0.012 | 1.42 | skilful; beats every baseline; NOT reliable; discriminates |
| D+2 | heavy | himalaya | 10521 | 116 | 0.015 [-0.011, +0.041] | 0.847 [+0.824, +0.866] | 0.020 | 1.41 | NOT skilful; beats every baseline; NOT reliable; discriminates |
| D+2 | heavy | western_ghats | 5324 | 72 | 0.152 [+0.065, +0.224] | 0.942 [+0.924, +0.956] | 0.010 | 1.43 | skilful; beats every baseline; NOT reliable; discriminates |
| D+2 | very_heavy | domain | 2170 | 88 | 0.011 [-0.034, +0.053] | 0.909 [+0.878, +0.934] | 0.017 | 1.76 | NOT skilful; beats every baseline; NOT reliable; discriminates |
| D+2 | very_heavy | himalaya | 1396 | 82 | 0.012 [-0.016, +0.040] | 0.876 [+0.833, +0.908] | 0.008 | 1.53 | NOT skilful; beats every baseline; NOT reliable; discriminates |
| D+2 | very_heavy | western_ghats | 607 | 25 | 0.005 [-0.188, +0.104] | 0.969 [+0.945, +0.983] | 0.051 | 2.23 | NOT skilful; does not beat ens_mean; NOT reliable; discriminates |
| D+2 | extremely_heavy | domain | 97 | 18 | -0.003 [-0.030, +0.018] | 0.762 [+0.572, +0.968] | 0.005 | 1.84 | too few events to conclude |
| D+2 | extremely_heavy | himalaya | 93 | 15 | 0.010 [+0.001, +0.029] | 0.756 [+0.563, +0.973] | 0.000 | 0.95 | too few events to conclude |
| D+2 | extremely_heavy | western_ghats | 1 | 1 | -0.768 [-7.024, +0.027] | 0.970 [+0.954, +0.983] | 0.430 | 75.91 | too few events to conclude |
| D+2 | p95 | domain | 60139 | 122 | 0.088 [+0.070, +0.105] | 0.829 [+0.812, +0.844] | 0.003 | 1.15 | skilful; beats every baseline; reliable; discriminates |
| D+2 | p95 | himalaya | 40544 | 122 | 0.074 [+0.050, +0.096] | 0.811 [+0.790, +0.829] | 0.004 | 1.15 | skilful; beats every baseline; reliable; discriminates |
| D+2 | p95 | western_ghats | 11617 | 103 | 0.126 [+0.089, +0.161] | 0.871 [+0.845, +0.893] | 0.005 | 1.14 | skilful; beats every baseline; reliable; discriminates |
| D+2 | p99 | domain | 12086 | 116 | 0.036 [+0.008, +0.065] | 0.871 [+0.844, +0.893] | 0.004 | 1.20 | skilful; beats every baseline; reliable; discriminates |
| D+2 | p99 | himalaya | 9418 | 111 | 0.047 [+0.017, +0.080] | 0.861 [+0.826, +0.890] | 0.003 | 1.04 | skilful; beats every baseline; reliable; discriminates |
| D+2 | p99 | western_ghats | 1356 | 66 | -0.023 [-0.107, +0.026] | 0.907 [+0.881, +0.928] | 0.060 | 2.15 | NOT skilful; beats every baseline; NOT reliable; discriminates |
| D+3 | heavy | domain | 17377 | 116 | 0.029 [-0.009, +0.066] | 0.863 [+0.843, +0.882] | 0.022 | 1.51 | NOT skilful; beats every baseline; NOT reliable; discriminates |
| D+3 | heavy | himalaya | 10509 | 115 | -0.007 [-0.028, +0.012] | 0.820 [+0.799, +0.840] | 0.029 | 1.46 | NOT skilful; beats every baseline; NOT reliable; discriminates |
| D+3 | heavy | western_ghats | 5324 | 72 | 0.104 [-0.003, +0.181] | 0.932 [+0.913, +0.947] | 0.022 | 1.59 | NOT skilful; beats every baseline; NOT reliable; discriminates |
| D+3 | very_heavy | domain | 2171 | 89 | 0.001 [-0.043, +0.039] | 0.895 [+0.864, +0.922] | 0.018 | 1.91 | NOT skilful; does not beat ens_mean; NOT reliable; discriminates |
| D+3 | very_heavy | himalaya | 1397 | 83 | 0.002 [-0.015, +0.020] | 0.859 [+0.822, +0.891] | 0.006 | 1.63 | NOT skilful; does not beat ens_mean; NOT reliable; discriminates |
| D+3 | very_heavy | western_ghats | 607 | 25 | -0.004 [-0.215, +0.092] | 0.967 [+0.943, +0.981] | 0.055 | 2.51 | NOT skilful; does not beat ens_mean; NOT reliable; discriminates |
| D+3 | extremely_heavy | domain | 97 | 18 | 0.002 [-0.009, +0.013] | 0.819 [+0.712, +0.943] | 0.000 | 2.13 | too few events to conclude |
| D+3 | extremely_heavy | himalaya | 93 | 15 | 0.008 [+0.001, +0.025] | 0.818 [+0.706, +0.949] | 0.000 | 1.13 | too few events to conclude |
| D+3 | extremely_heavy | western_ghats | 1 | 1 | -0.409 [-3.839, +0.067] | 0.962 [+0.946, +0.976] | 0.054 | 84.25 | too few events to conclude |
| D+3 | p95 | domain | 60118 | 121 | 0.057 [+0.040, +0.072] | 0.802 [+0.785, +0.820] | 0.004 | 1.16 | skilful; beats every baseline; reliable; discriminates |
| D+3 | p95 | himalaya | 40526 | 121 | 0.046 [+0.028, +0.064] | 0.784 [+0.764, +0.806] | 0.004 | 1.14 | skilful; beats every baseline; reliable; discriminates |
| D+3 | p95 | western_ghats | 11618 | 104 | 0.092 [+0.044, +0.132] | 0.847 [+0.816, +0.873] | 0.008 | 1.21 | skilful; beats every baseline; reliable; discriminates |
| D+3 | p99 | domain | 12093 | 116 | 0.013 [-0.003, +0.030] | 0.839 [+0.812, +0.866] | 0.007 | 1.23 | NOT skilful; beats every baseline; reliable; discriminates |
| D+3 | p99 | himalaya | 9426 | 111 | 0.020 [+0.004, +0.040] | 0.828 [+0.794, +0.862] | 0.001 | 1.04 | skilful; beats every baseline; reliable; discriminates |
| D+3 | p99 | western_ghats | 1356 | 66 | -0.022 [-0.100, +0.023] | 0.889 [+0.861, +0.913] | 0.050 | 2.32 | NOT skilful; beats every baseline; NOT reliable; discriminates |

### Warning levels on 2025 (domain)

| lead | level | share of pixel-days | observed >= heavy | share of heavy events | share of very heavy events |
|---|---|---|---|---|---|
| D (today, mostly observed) | none | - | - | - | - |
| D (today, mostly observed) | yellow | - | - | - | - |
| D (today, mostly observed) | orange | - | - | - | - |
| D (today, mostly observed) | red | - | - | - | - |
| D+1 | none | 96.065% | 0.8% | 60.6% | 46.4% |
| D+1 | yellow | 3.432% | 9.2% | 25.1% | 25.3% |
| D+1 | orange | 0.428% | 32.4% | 11.0% | 21.0% |
| D+1 | red | 0.076% | 53.4% | 3.2% | 7.2% |
| D+2 | none | 95.662% | 0.8% | 64.5% | 49.8% |
| D+2 | yellow | 3.759% | 7.6% | 22.7% | 25.0% |
| D+2 | orange | 0.505% | 25.7% | 10.4% | 21.2% |
| D+2 | red | 0.074% | 42.5% | 2.5% | 4.0% |
| D+3 | none | 95.523% | 1.0% | 72.0% | 59.6% |
| D+3 | yellow | 3.793% | 5.4% | 16.2% | 18.7% |
| D+3 | orange | 0.591% | 19.4% | 9.1% | 17.5% |
| D+3 | red | 0.092% | 37.2% | 2.7% | 4.2% |

### Reliability on 2025 (domain)

Lead D+1, heavy, domain:

| probability bin | pixel-days | mean probability | observed frequency |
|---|---|---|---|
| 0.00-0.05 | 1270063 | 0.0076 | 0.0052 |
| 0.05-0.10 | 67335 | 0.0695 | 0.0493 |
| 0.10-0.20 | 32979 | 0.1375 | 0.1062 |
| 0.20-0.30 | 9152 | 0.2405 | 0.1910 |
| 0.30-0.40 | 3008 | 0.3423 | 0.3152 |
| 0.40-0.50 | 1396 | 0.4446 | 0.4334 |
| 0.50-0.60 | 830 | 0.5446 | 0.5241 |
| 0.60-0.70 | 396 | 0.6385 | 0.5657 |
| 0.70-0.80 | 29 | 0.7138 | 0.6552 |

Lead D+1, very_heavy, domain:

| probability bin | pixel-days | mean probability | observed frequency |
|---|---|---|---|
| 0.00-0.05 | 1375766 | 0.0019 | 0.0011 |
| 0.05-0.10 | 6161 | 0.0679 | 0.0403 |
| 0.10-0.20 | 2406 | 0.1376 | 0.1342 |
| 0.20-0.30 | 710 | 0.2406 | 0.1437 |
| 0.30-0.40 | 141 | 0.3246 | 0.1206 |
| 0.40-0.50 | 4 | 0.4112 | 0.0000 |

Lead D+1, p95, domain:

| probability bin | pixel-days | mean probability | observed frequency |
|---|---|---|---|
| 0.00-0.05 | 982629 | 0.0157 | 0.0125 |
| 0.05-0.10 | 212647 | 0.0708 | 0.0607 |
| 0.10-0.20 | 134431 | 0.1386 | 0.1276 |
| 0.20-0.30 | 34821 | 0.2408 | 0.2557 |
| 0.30-0.40 | 12335 | 0.3413 | 0.3706 |
| 0.40-0.50 | 4918 | 0.4428 | 0.4343 |
| 0.50-0.60 | 1886 | 0.5431 | 0.5488 |
| 0.60-0.70 | 1134 | 0.6462 | 0.6720 |
| 0.70-0.80 | 363 | 0.7337 | 0.7713 |
| 0.80-0.90 | 24 | 0.8133 | 1.0000 |

