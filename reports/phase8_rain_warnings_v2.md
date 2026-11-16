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

## June-September 2025

Not run yet.

