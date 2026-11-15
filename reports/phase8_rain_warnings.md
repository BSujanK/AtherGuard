# Probabilistic heavy-rain warnings: verification

Spec: `docs/superpowers/specs/2026-11-14-aetherguard-rain-warnings.md` (criteria declared before any number). Research prototype: not validated for issuing real public warnings. This product does not read or change any landslide alert level.

Truth: IMERG V07 Late, IMD day = 0.875 UTC(d-1) + 0.125 UTC(d). Forecast: ECMWF IFS ensemble (open data, CC BY 4.0) mean / p10 / p50 / p90 of the IMD-day total. Domain: 11354 pixels of 0.1 degree holding the assessed cells (himalaya 7663, western_ghats 2214). Issue days with an ECMWF file: 230. Climatology: IMERG Late 2007-2022, +-15 days, percentile thresholds floored at 15.6 mm. Intervals: 1000 bootstrap resamples of test days (each day keeps all its pixels).

Statement rules (spec section 6): enough events = at least 100 event pixel-days on at least 10 distinct days; skilful = BSS 95% interval above 0 (reference: the pixel's climatology for the day of year); beats the baselines = BS(product) - BS(baseline) interval below 0 for every 0/1 baseline of the lead (lead 0: the observed total thresholded; leads 1-3: GFS, ECMWF ensemble mean, ECMWF HRES); reliable = REL/UNC at most 0.1 and mean probability / base rate within [0.8, 1.25]; discriminates = ROC-area interval above 0.5.

## Test set `test_2024` (primary): test 2024-06-01..2024-09-30, fitted on 2023-06-01..2023-09-30

Test issue days with an ECMWF file: 122 (2024-06-01..2024-09-30).

### Statements (pre-declared tests)

- D (today, mostly observed), heavy: domain: skilful; beats every baseline; reliable; discriminates (28919 event pixel-days on 76 days); himalaya: skilful; beats every baseline; reliable; discriminates (12291 event pixel-days on 76 days); western_ghats: skilful; beats every baseline; reliable; discriminates (14542 event pixel-days on 68 days)
- D (today, mostly observed), very_heavy: domain: skilful; beats every baseline; reliable; discriminates (7598 event pixel-days on 72 days); himalaya: skilful; beats every baseline; reliable; discriminates (3238 event pixel-days on 63 days); western_ghats: skilful; beats every baseline; reliable; discriminates (3823 event pixel-days on 51 days)
- D (today, mostly observed), extremely_heavy: domain: skilful; beats every baseline; reliable; discriminates (678 event pixel-days on 34 days); himalaya: skilful; beats every baseline; reliable; discriminates (332 event pixel-days on 18 days); western_ghats: skilful; beats every baseline; reliable; discriminates (281 event pixel-days on 21 days)
- D (today, mostly observed), p95: domain: skilful; beats every baseline; reliable; discriminates (59950 event pixel-days on 76 days); himalaya: skilful; beats every baseline; reliable; discriminates (30394 event pixel-days on 76 days); western_ghats: skilful; beats every baseline; reliable; discriminates (23011 event pixel-days on 73 days)
- D (today, mostly observed), p99: domain: skilful; beats every baseline; reliable; discriminates (17948 event pixel-days on 76 days); himalaya: skilful; beats every baseline; reliable; discriminates (8498 event pixel-days on 74 days); western_ghats: skilful; beats every baseline; reliable; discriminates (7659 event pixel-days on 62 days)
- D+1, heavy: domain: skilful; beats every baseline; reliable; discriminates (36894 event pixel-days on 122 days); himalaya: skilful; beats every baseline; reliable; discriminates (17349 event pixel-days on 120 days); western_ghats: skilful; beats every baseline; NOT reliable; discriminates (16677 event pixel-days on 91 days)
- D+1, very_heavy: domain: skilful; beats every baseline; NOT reliable; discriminates (8655 event pixel-days on 107 days); himalaya: skilful; beats every baseline; reliable; discriminates (3948 event pixel-days on 91 days); western_ghats: skilful; beats every baseline; NOT reliable; discriminates (4087 event pixel-days on 65 days)
- D+1, extremely_heavy: domain: skilful; beats every baseline; NOT reliable; discriminates (777 event pixel-days on 38 days); himalaya: skilful; beats every baseline; NOT reliable; discriminates (428 event pixel-days on 22 days); western_ghats: skilful; does not beat gfs; NOT reliable; discriminates (282 event pixel-days on 22 days)
- D+1, p95: domain: skilful; beats every baseline; reliable; discriminates (83956 event pixel-days on 122 days); himalaya: skilful; beats every baseline; reliable; discriminates (46842 event pixel-days on 122 days); western_ghats: skilful; beats every baseline; NOT reliable; discriminates (27072 event pixel-days on 104 days)
- D+1, p99: domain: skilful; beats every baseline; reliable; discriminates (23005 event pixel-days on 122 days); himalaya: skilful; beats every baseline; reliable; discriminates (12135 event pixel-days on 117 days); western_ghats: skilful; beats every baseline; NOT reliable; discriminates (8363 event pixel-days on 84 days)
- D+2, heavy: domain: skilful; beats every baseline; reliable; discriminates (36438 event pixel-days on 122 days); himalaya: skilful; beats every baseline; reliable; discriminates (17337 event pixel-days on 120 days); western_ghats: skilful; beats every baseline; NOT reliable; discriminates (16318 event pixel-days on 91 days)
- D+2, very_heavy: domain: skilful; beats every baseline; NOT reliable; discriminates (8466 event pixel-days on 107 days); himalaya: skilful; beats every baseline; NOT reliable; discriminates (3951 event pixel-days on 91 days); western_ghats: skilful; beats every baseline; NOT reliable; discriminates (3936 event pixel-days on 64 days)
- D+2, extremely_heavy: domain: skilful; beats every baseline; NOT reliable; discriminates (743 event pixel-days on 37 days); himalaya: skilful; beats every baseline; NOT reliable; discriminates (428 event pixel-days on 22 days); western_ghats: skilful; beats every baseline; NOT reliable; discriminates (257 event pixel-days on 21 days)
- D+2, p95: domain: skilful; beats every baseline; reliable; discriminates (83181 event pixel-days on 122 days); himalaya: skilful; beats every baseline; reliable; discriminates (46868 event pixel-days on 122 days); western_ghats: skilful; beats every baseline; NOT reliable; discriminates (26421 event pixel-days on 104 days)
- D+2, p99: domain: skilful; beats every baseline; reliable; discriminates (22439 event pixel-days on 122 days); himalaya: skilful; beats every baseline; reliable; discriminates (12146 event pixel-days on 117 days); western_ghats: skilful; beats every baseline; NOT reliable; discriminates (7897 event pixel-days on 84 days)
- D+3, heavy: domain: skilful; beats every baseline; reliable; discriminates (36000 event pixel-days on 122 days); himalaya: skilful; beats every baseline; reliable; discriminates (17339 event pixel-days on 120 days); western_ghats: skilful; beats every baseline; NOT reliable; discriminates (15933 event pixel-days on 91 days)
- D+3, very_heavy: domain: skilful; beats every baseline; NOT reliable; discriminates (8380 event pixel-days on 106 days); himalaya: skilful; beats every baseline; NOT reliable; discriminates (3951 event pixel-days on 91 days); western_ghats: skilful; beats every baseline; NOT reliable; discriminates (3864 event pixel-days on 63 days)
- D+3, extremely_heavy: domain: NOT skilful; beats every baseline; NOT reliable; discriminates (733 event pixel-days on 36 days); himalaya: NOT skilful; beats every baseline; NOT reliable; discriminates (428 event pixel-days on 22 days); western_ghats: NOT skilful; beats every baseline; NOT reliable; discriminates (251 event pixel-days on 20 days)
- D+3, p95: domain: skilful; beats every baseline; reliable; discriminates (82511 event pixel-days on 122 days); himalaya: skilful; beats every baseline; reliable; discriminates (46916 event pixel-days on 122 days); western_ghats: skilful; beats every baseline; NOT reliable; discriminates (25825 event pixel-days on 104 days)
- D+3, p99: domain: skilful; beats every baseline; reliable; discriminates (21885 event pixel-days on 122 days); himalaya: skilful; beats every baseline; reliable; discriminates (12145 event pixel-days on 116 days); western_ghats: skilful; beats every baseline; NOT reliable; discriminates (7433 event pixel-days on 84 days)

### Headline (product = calibrated probability)

| lead | threshold | region | event pixel-days | event days | BSS (95% CI) | ROC area (CI) | REL/UNC | mean p / base rate | verdict |
|---|---|---|---|---|---|---|---|---|---|
| D (today, mostly observed) | heavy | domain | 28919 | 76 | 0.680 [+0.643, +0.709] | 0.989 [+0.982, +0.993] | 0.005 | 1.00 | skilful; beats every baseline; reliable; discriminates |
| D (today, mostly observed) | heavy | himalaya | 12291 | 76 | 0.610 [+0.536, +0.665] | 0.983 [+0.967, +0.992] | 0.011 | 1.01 | skilful; beats every baseline; reliable; discriminates |
| D (today, mostly observed) | heavy | western_ghats | 14542 | 68 | 0.748 [+0.715, +0.778] | 0.991 [+0.989, +0.993] | 0.002 | 0.99 | skilful; beats every baseline; reliable; discriminates |
| D (today, mostly observed) | very_heavy | domain | 7598 | 72 | 0.595 [+0.543, +0.641] | 0.992 [+0.984, +0.997] | 0.004 | 0.94 | skilful; beats every baseline; reliable; discriminates |
| D (today, mostly observed) | very_heavy | himalaya | 3238 | 63 | 0.571 [+0.474, +0.636] | 0.988 [+0.966, +0.997] | 0.006 | 0.90 | skilful; beats every baseline; reliable; discriminates |
| D (today, mostly observed) | very_heavy | western_ghats | 3823 | 51 | 0.612 [+0.541, +0.673] | 0.993 [+0.991, +0.995] | 0.004 | 0.97 | skilful; beats every baseline; reliable; discriminates |
| D (today, mostly observed) | extremely_heavy | domain | 678 | 34 | 0.442 [+0.310, +0.530] | 0.997 [+0.991, +0.999] | 0.006 | 0.94 | skilful; beats every baseline; reliable; discriminates |
| D (today, mostly observed) | extremely_heavy | himalaya | 332 | 18 | 0.405 [+0.175, +0.535] | 0.995 [+0.974, +1.000] | 0.019 | 0.83 | skilful; beats every baseline; reliable; discriminates |
| D (today, mostly observed) | extremely_heavy | western_ghats | 281 | 21 | 0.452 [+0.240, +0.575] | 0.998 [+0.997, +0.999] | 0.005 | 1.12 | skilful; beats every baseline; reliable; discriminates |
| D (today, mostly observed) | p95 | domain | 59950 | 76 | 0.671 [+0.641, +0.698] | 0.980 [+0.973, +0.985] | 0.003 | 1.00 | skilful; beats every baseline; reliable; discriminates |
| D (today, mostly observed) | p95 | himalaya | 30394 | 76 | 0.623 [+0.577, +0.662] | 0.975 [+0.962, +0.984] | 0.006 | 1.00 | skilful; beats every baseline; reliable; discriminates |
| D (today, mostly observed) | p95 | western_ghats | 23011 | 73 | 0.738 [+0.704, +0.772] | 0.983 [+0.979, +0.986] | 0.001 | 0.98 | skilful; beats every baseline; reliable; discriminates |
| D (today, mostly observed) | p99 | domain | 17948 | 76 | 0.610 [+0.561, +0.653] | 0.988 [+0.981, +0.992] | 0.008 | 1.04 | skilful; beats every baseline; reliable; discriminates |
| D (today, mostly observed) | p99 | himalaya | 8498 | 74 | 0.561 [+0.489, +0.619] | 0.985 [+0.970, +0.993] | 0.011 | 1.02 | skilful; beats every baseline; reliable; discriminates |
| D (today, mostly observed) | p99 | western_ghats | 7659 | 62 | 0.663 [+0.596, +0.719] | 0.988 [+0.983, +0.992] | 0.006 | 1.05 | skilful; beats every baseline; reliable; discriminates |
| D+1 | heavy | domain | 36894 | 122 | 0.180 [+0.135, +0.224] | 0.900 [+0.878, +0.918] | 0.003 | 0.94 | skilful; beats every baseline; reliable; discriminates |
| D+1 | heavy | himalaya | 17349 | 120 | 0.141 [+0.075, +0.201] | 0.899 [+0.877, +0.917] | 0.005 | 1.10 | skilful; beats every baseline; reliable; discriminates |
| D+1 | heavy | western_ghats | 16677 | 91 | 0.234 [+0.163, +0.292] | 0.892 [+0.852, +0.923] | 0.011 | 0.75 | skilful; beats every baseline; NOT reliable; discriminates |
| D+1 | very_heavy | domain | 8655 | 107 | 0.100 [+0.068, +0.130] | 0.926 [+0.890, +0.952] | 0.027 | 0.62 | skilful; beats every baseline; NOT reliable; discriminates |
| D+1 | very_heavy | himalaya | 3948 | 91 | 0.128 [+0.071, +0.172] | 0.951 [+0.930, +0.966] | 0.025 | 0.81 | skilful; beats every baseline; reliable; discriminates |
| D+1 | very_heavy | western_ghats | 4087 | 65 | 0.077 [+0.046, +0.102] | 0.888 [+0.826, +0.939] | 0.042 | 0.44 | skilful; beats every baseline; NOT reliable; discriminates |
| D+1 | extremely_heavy | domain | 777 | 38 | 0.008 [+0.004, +0.011] | 0.875 [+0.776, +0.938] | 0.001 | 0.14 | skilful; beats every baseline; NOT reliable; discriminates |
| D+1 | extremely_heavy | himalaya | 428 | 22 | 0.012 [+0.005, +0.017] | 0.953 [+0.872, +0.988] | 0.001 | 0.18 | skilful; beats every baseline; NOT reliable; discriminates |
| D+1 | extremely_heavy | western_ghats | 282 | 22 | 0.003 [+0.001, +0.004] | 0.763 [+0.602, +0.877] | 0.001 | 0.09 | skilful; does not beat gfs; NOT reliable; discriminates |
| D+1 | p95 | domain | 83956 | 122 | 0.131 [+0.104, +0.159] | 0.844 [+0.830, +0.858] | 0.001 | 0.95 | skilful; beats every baseline; reliable; discriminates |
| D+1 | p95 | himalaya | 46842 | 122 | 0.124 [+0.083, +0.167] | 0.843 [+0.825, +0.862] | 0.003 | 1.10 | skilful; beats every baseline; reliable; discriminates |
| D+1 | p95 | western_ghats | 27072 | 104 | 0.149 [+0.109, +0.185] | 0.839 [+0.809, +0.864] | 0.037 | 0.64 | skilful; beats every baseline; NOT reliable; discriminates |
| D+1 | p99 | domain | 23005 | 122 | 0.088 [+0.055, +0.123] | 0.873 [+0.850, +0.893] | 0.003 | 0.83 | skilful; beats every baseline; reliable; discriminates |
| D+1 | p99 | himalaya | 12135 | 117 | 0.110 [+0.054, +0.161] | 0.890 [+0.865, +0.912] | 0.003 | 1.04 | skilful; beats every baseline; reliable; discriminates |
| D+1 | p99 | western_ghats | 8363 | 84 | 0.067 [+0.034, +0.102] | 0.841 [+0.799, +0.883] | 0.024 | 0.49 | skilful; beats every baseline; NOT reliable; discriminates |
| D+2 | heavy | domain | 36438 | 122 | 0.133 [+0.093, +0.170] | 0.895 [+0.876, +0.912] | 0.001 | 0.95 | skilful; beats every baseline; reliable; discriminates |
| D+2 | heavy | himalaya | 17337 | 120 | 0.087 [+0.020, +0.144] | 0.884 [+0.861, +0.903] | 0.008 | 1.17 | skilful; beats every baseline; reliable; discriminates |
| D+2 | heavy | western_ghats | 16318 | 91 | 0.191 [+0.132, +0.244] | 0.896 [+0.863, +0.926] | 0.016 | 0.70 | skilful; beats every baseline; NOT reliable; discriminates |
| D+2 | very_heavy | domain | 8466 | 107 | 0.058 [+0.036, +0.080] | 0.931 [+0.903, +0.953] | 0.016 | 0.58 | skilful; beats every baseline; NOT reliable; discriminates |
| D+2 | very_heavy | himalaya | 3951 | 91 | 0.070 [+0.026, +0.108] | 0.942 [+0.916, +0.958] | 0.012 | 0.78 | skilful; beats every baseline; NOT reliable; discriminates |
| D+2 | very_heavy | western_ghats | 3936 | 64 | 0.045 [+0.025, +0.063] | 0.904 [+0.853, +0.944] | 0.036 | 0.36 | skilful; beats every baseline; NOT reliable; discriminates |
| D+2 | extremely_heavy | domain | 743 | 37 | 0.004 [+0.001, +0.006] | 0.915 [+0.846, +0.960] | 0.000 | 0.11 | skilful; beats every baseline; NOT reliable; discriminates |
| D+2 | extremely_heavy | himalaya | 428 | 22 | 0.005 [+0.000, +0.009] | 0.965 [+0.922, +0.984] | 0.000 | 0.13 | skilful; beats every baseline; NOT reliable; discriminates |
| D+2 | extremely_heavy | western_ghats | 257 | 21 | 0.002 [+0.001, +0.004] | 0.816 [+0.668, +0.918] | 0.001 | 0.08 | skilful; beats every baseline; NOT reliable; discriminates |
| D+2 | p95 | domain | 83181 | 122 | 0.100 [+0.075, +0.128] | 0.827 [+0.812, +0.841] | 0.001 | 0.94 | skilful; beats every baseline; reliable; discriminates |
| D+2 | p95 | himalaya | 46868 | 122 | 0.093 [+0.053, +0.133] | 0.824 [+0.803, +0.842] | 0.004 | 1.10 | skilful; beats every baseline; reliable; discriminates |
| D+2 | p95 | western_ghats | 26421 | 104 | 0.122 [+0.088, +0.158] | 0.834 [+0.808, +0.858] | 0.038 | 0.61 | skilful; beats every baseline; NOT reliable; discriminates |
| D+2 | p99 | domain | 22439 | 122 | 0.060 [+0.033, +0.086] | 0.863 [+0.840, +0.881] | 0.002 | 0.83 | skilful; beats every baseline; reliable; discriminates |
| D+2 | p99 | himalaya | 12146 | 117 | 0.073 [+0.027, +0.113] | 0.871 [+0.843, +0.893] | 0.004 | 1.05 | skilful; beats every baseline; reliable; discriminates |
| D+2 | p99 | western_ghats | 7897 | 84 | 0.050 [+0.025, +0.075] | 0.850 [+0.813, +0.883] | 0.020 | 0.46 | skilful; beats every baseline; NOT reliable; discriminates |
| D+3 | heavy | domain | 36000 | 122 | 0.111 [+0.074, +0.143] | 0.888 [+0.871, +0.905] | 0.001 | 0.91 | skilful; beats every baseline; reliable; discriminates |
| D+3 | heavy | himalaya | 17339 | 120 | 0.059 [+0.000, +0.113] | 0.869 [+0.842, +0.892] | 0.007 | 1.10 | skilful; beats every baseline; reliable; discriminates |
| D+3 | heavy | western_ghats | 15933 | 91 | 0.176 [+0.121, +0.224] | 0.898 [+0.864, +0.924] | 0.016 | 0.70 | skilful; beats every baseline; NOT reliable; discriminates |
| D+3 | very_heavy | domain | 8380 | 106 | 0.045 [+0.025, +0.065] | 0.928 [+0.900, +0.950] | 0.016 | 0.52 | skilful; beats every baseline; NOT reliable; discriminates |
| D+3 | very_heavy | himalaya | 3951 | 91 | 0.049 [+0.007, +0.086] | 0.936 [+0.909, +0.953] | 0.010 | 0.66 | skilful; beats every baseline; NOT reliable; discriminates |
| D+3 | very_heavy | western_ghats | 3864 | 63 | 0.040 [+0.024, +0.056] | 0.903 [+0.849, +0.946] | 0.028 | 0.37 | skilful; beats every baseline; NOT reliable; discriminates |
| D+3 | extremely_heavy | domain | 733 | 36 | 0.002 [-0.000, +0.005] | 0.906 [+0.851, +0.947] | 0.000 | 0.11 | NOT skilful; beats every baseline; NOT reliable; discriminates |
| D+3 | extremely_heavy | himalaya | 428 | 22 | 0.003 [-0.001, +0.008] | 0.944 [+0.878, +0.973] | 0.000 | 0.12 | NOT skilful; beats every baseline; NOT reliable; discriminates |
| D+3 | extremely_heavy | western_ghats | 251 | 20 | 0.001 [-0.000, +0.003] | 0.822 [+0.732, +0.926] | 0.001 | 0.08 | NOT skilful; beats every baseline; NOT reliable; discriminates |
| D+3 | p95 | domain | 82511 | 122 | 0.079 [+0.056, +0.102] | 0.808 [+0.791, +0.824] | 0.001 | 0.93 | skilful; beats every baseline; reliable; discriminates |
| D+3 | p95 | himalaya | 46916 | 122 | 0.063 [+0.027, +0.098] | 0.802 [+0.780, +0.823] | 0.005 | 1.09 | skilful; beats every baseline; reliable; discriminates |
| D+3 | p95 | western_ghats | 25825 | 104 | 0.113 [+0.077, +0.151] | 0.820 [+0.789, +0.847] | 0.030 | 0.61 | skilful; beats every baseline; NOT reliable; discriminates |
| D+3 | p99 | domain | 21885 | 122 | 0.049 [+0.026, +0.073] | 0.844 [+0.819, +0.868] | 0.003 | 0.83 | skilful; beats every baseline; reliable; discriminates |
| D+3 | p99 | himalaya | 12145 | 116 | 0.050 [+0.010, +0.088] | 0.851 [+0.819, +0.878] | 0.002 | 1.02 | skilful; beats every baseline; reliable; discriminates |
| D+3 | p99 | western_ghats | 7433 | 84 | 0.054 [+0.027, +0.083] | 0.836 [+0.796, +0.880] | 0.018 | 0.49 | skilful; beats every baseline; NOT reliable; discriminates |

### Against the deterministic baselines and the raw ensemble (domain)

| lead | threshold | BS product | BS climatology | BS raw ensemble | baseline: BS, diff (95% CI), hit rate, FAR |
|---|---|---|---|---|---|
| D (today, mostly observed) | heavy | 0.00976 | 0.03052 | - | observed: 0.01416, -0.00441 [-0.00508, -0.00377], 0.816, 0.226 |
| D (today, mostly observed) | very_heavy | 0.00348 | 0.00860 | - | observed: 0.00513, -0.00165 [-0.00206, -0.00128], 0.756, 0.309 |
| D (today, mostly observed) | extremely_heavy | 0.00044 | 0.00078 | - | observed: 0.00074, -0.00030 [-0.00046, -0.00017], 0.671, 0.476 |
| D (today, mostly observed) | p95 | 0.02095 | 0.06360 | - | observed: 0.03033, -0.00938 [-0.01065, -0.00824], 0.823, 0.240 |
| D (today, mostly observed) | p99 | 0.00795 | 0.02037 | - | observed: 0.01181, -0.00385 [-0.00456, -0.00323], 0.795, 0.313 |
| D+1 | heavy | 0.02020 | 0.02464 | 0.02314 | gfs: 0.03051, -0.01031 [-0.01210, -0.00843], 0.186, 0.640; ens_mean: 0.02732, -0.00712 [-0.00861, -0.00558], 0.181, 0.533; hres: 0.03034, -0.01015 [-0.01195, -0.00839], 0.193, 0.633 |
| D+1 | very_heavy | 0.00551 | 0.00612 | 0.00600 | gfs: 0.00828, -0.00277 [-0.00346, -0.00214], 0.063, 0.860; ens_mean: 0.00637, -0.00086 [-0.00122, -0.00054], 0.066, 0.564; hres: 0.00723, -0.00172 [-0.00226, -0.00121], 0.085, 0.740 |
| D+1 | extremely_heavy | 0.00056 | 0.00056 | 0.00057 | gfs: 0.00076, -0.00020 [-0.00034, -0.00010], 0.019, 0.951; ens_mean: 0.00057, -0.00001 [-0.00002, -0.00000], 0.001, 0.923; hres: 0.00071, -0.00015 [-0.00024, -0.00008], 0.036, 0.892 |
| D+1 | p95 | 0.04878 | 0.05614 | 0.05448 | gfs: 0.07107, -0.02229 [-0.02523, -0.01895], 0.218, 0.642; ens_mean: 0.06686, -0.01808 [-0.02097, -0.01516], 0.197, 0.604; hres: 0.07317, -0.02440 [-0.02787, -0.02099], 0.215, 0.662 |
| D+1 | p99 | 0.01488 | 0.01631 | 0.01620 | gfs: 0.02161, -0.00673 [-0.00791, -0.00557], 0.145, 0.755; ens_mean: 0.01848, -0.00359 [-0.00465, -0.00260], 0.108, 0.671; hres: 0.02108, -0.00620 [-0.00758, -0.00482], 0.125, 0.759 |
| D+2 | heavy | 0.02107 | 0.02432 | 0.02344 | gfs: 0.03234, -0.01126 [-0.01346, -0.00919], 0.140, 0.725; ens_mean: 0.02727, -0.00619 [-0.00755, -0.00487], 0.145, 0.556; hres: 0.03081, -0.00973 [-0.01133, -0.00794], 0.176, 0.664 |
| D+2 | very_heavy | 0.00564 | 0.00599 | 0.00595 | gfs: 0.00789, -0.00225 [-0.00283, -0.00170], 0.067, 0.842; ens_mean: 0.00623, -0.00059 [-0.00082, -0.00039], 0.037, 0.602; hres: 0.00758, -0.00194 [-0.00256, -0.00138], 0.076, 0.807 |
| D+2 | extremely_heavy | 0.00053 | 0.00054 | 0.00054 | gfs: 0.00075, -0.00021 [-0.00036, -0.00009], 0.022, 0.951; ens_mean: 0.00055, -0.00002 [-0.00005, -0.00000], 0.000, 1.000; hres: 0.00079, -0.00025 [-0.00040, -0.00014], 0.016, 0.968 |
| D+2 | p95 | 0.05006 | 0.05565 | 0.05486 | gfs: 0.07659, -0.02654 [-0.03016, -0.02278], 0.165, 0.727; ens_mean: 0.06791, -0.01785 [-0.02069, -0.01526], 0.164, 0.643; hres: 0.07529, -0.02524 [-0.02857, -0.02203], 0.190, 0.700 |
| D+2 | p99 | 0.01495 | 0.01591 | 0.01584 | gfs: 0.02207, -0.00711 [-0.00857, -0.00571], 0.103, 0.819; ens_mean: 0.01764, -0.00268 [-0.00358, -0.00184], 0.079, 0.680; hres: 0.02085, -0.00590 [-0.00718, -0.00457], 0.101, 0.794 |
| D+3 | heavy | 0.02134 | 0.02400 | 0.02374 | gfs: 0.03193, -0.01059 [-0.01262, -0.00870], 0.085, 0.787; ens_mean: 0.02754, -0.00620 [-0.00740, -0.00501], 0.100, 0.615; hres: 0.03249, -0.01114 [-0.01303, -0.00945], 0.152, 0.725 |
| D+3 | very_heavy | 0.00566 | 0.00592 | 0.00600 | gfs: 0.00752, -0.00187 [-0.00239, -0.00138], 0.024, 0.917; ens_mean: 0.00620, -0.00055 [-0.00080, -0.00034], 0.028, 0.656; hres: 0.00811, -0.00245 [-0.00324, -0.00176], 0.063, 0.865 |
| D+3 | extremely_heavy | 0.00053 | 0.00053 | 0.00055 | gfs: 0.00066, -0.00013 [-0.00023, -0.00006], 0.000, 1.000; ens_mean: 0.00055, -0.00003 [-0.00007, -0.00000], 0.000, 1.000; hres: 0.00093, -0.00040 [-0.00066, -0.00018], 0.027, 0.966 |
| D+3 | p95 | 0.05085 | 0.05521 | 0.05544 | gfs: 0.07738, -0.02653 [-0.03060, -0.02308], 0.127, 0.770; ens_mean: 0.06784, -0.01699 [-0.01989, -0.01436], 0.127, 0.676; hres: 0.07761, -0.02676 [-0.03008, -0.02364], 0.164, 0.740 |
| D+3 | p99 | 0.01476 | 0.01552 | 0.01567 | gfs: 0.02193, -0.00716 [-0.00880, -0.00580], 0.052, 0.894; ens_mean: 0.01660, -0.00183 [-0.00240, -0.00132], 0.053, 0.660; hres: 0.02154, -0.00678 [-0.00816, -0.00554], 0.089, 0.836 |

### Raw quantile probability (uncalibrated) beside the product (domain)

| lead | threshold | raw BSS (CI) | raw ROC area | raw mean p / base rate | calibrated BSS |
|---|---|---|---|---|---|
| D+1 | heavy | 0.061 [+0.011, +0.109] | 0.843 | 0.59 | 0.180 |
| D+1 | very_heavy | 0.020 [-0.025, +0.063] | 0.815 | 0.41 | 0.100 |
| D+1 | extremely_heavy | -0.008 [-0.054, +0.017] | 0.757 | 0.45 | 0.008 |
| D+1 | p95 | 0.030 [-0.012, +0.068] | 0.809 | 0.74 | 0.131 |
| D+1 | p99 | 0.007 [-0.047, +0.059] | 0.798 | 0.60 | 0.088 |
| D+2 | heavy | 0.036 [-0.017, +0.087] | 0.841 | 0.62 | 0.133 |
| D+2 | very_heavy | 0.006 [-0.049, +0.054] | 0.821 | 0.46 | 0.058 |
| D+2 | extremely_heavy | -0.008 [-0.078, +0.025] | 0.771 | 0.56 | 0.004 |
| D+2 | p95 | 0.014 [-0.026, +0.055] | 0.794 | 0.77 | 0.100 |
| D+2 | p99 | 0.005 [-0.057, +0.064] | 0.796 | 0.62 | 0.060 |
| D+3 | heavy | 0.011 [-0.041, +0.059] | 0.842 | 0.62 | 0.111 |
| D+3 | very_heavy | -0.012 [-0.067, +0.038] | 0.835 | 0.45 | 0.045 |
| D+3 | extremely_heavy | -0.033 [-0.106, +0.005] | 0.761 | 0.61 | 0.002 |
| D+3 | p95 | -0.004 [-0.043, +0.035] | 0.780 | 0.77 | 0.079 |
| D+3 | p99 | -0.009 [-0.062, +0.046] | 0.788 | 0.63 | 0.049 |

### Reliability (domain)

Lead D+1, heavy, domain:

| probability bin | pixel-days | mean probability | observed frequency |
|---|---|---|---|
| 0.00-0.05 | 1237530 | 0.0068 | 0.0089 |
| 0.05-0.10 | 63550 | 0.0703 | 0.0634 |
| 0.10-0.20 | 41311 | 0.1408 | 0.1335 |
| 0.20-0.30 | 17553 | 0.2450 | 0.2271 |
| 0.30-0.40 | 10173 | 0.3464 | 0.3392 |
| 0.40-0.50 | 6604 | 0.4471 | 0.4567 |
| 0.50-0.60 | 4546 | 0.5478 | 0.5957 |
| 0.60-0.70 | 2834 | 0.6438 | 0.7936 |
| 0.70-0.80 | 968 | 0.7366 | 0.8967 |
| 0.80-0.90 | 119 | 0.8280 | 1.0000 |

Lead D+1, very_heavy, domain:

| probability bin | pixel-days | mean probability | observed frequency |
|---|---|---|---|
| 0.00-0.05 | 1360938 | 0.0021 | 0.0031 |
| 0.05-0.10 | 15268 | 0.0698 | 0.1070 |
| 0.10-0.20 | 7098 | 0.1346 | 0.2588 |
| 0.20-0.30 | 1257 | 0.2394 | 0.3938 |
| 0.30-0.40 | 488 | 0.3425 | 0.6803 |
| 0.40-0.50 | 113 | 0.4403 | 0.8142 |
| 0.50-0.60 | 26 | 0.5191 | 0.1923 |

Lead D+1, p95, domain:

| probability bin | pixel-days | mean probability | observed frequency |
|---|---|---|---|
| 0.00-0.05 | 943831 | 0.0148 | 0.0168 |
| 0.05-0.10 | 204072 | 0.0714 | 0.0760 |
| 0.10-0.20 | 144776 | 0.1397 | 0.1498 |
| 0.20-0.30 | 49368 | 0.2425 | 0.2587 |
| 0.30-0.40 | 21495 | 0.3440 | 0.3478 |
| 0.40-0.50 | 10841 | 0.4445 | 0.4081 |
| 0.50-0.60 | 5930 | 0.5454 | 0.5258 |
| 0.60-0.70 | 3062 | 0.6432 | 0.5927 |
| 0.70-0.80 | 1492 | 0.7425 | 0.7051 |
| 0.80-0.90 | 320 | 0.8309 | 0.7344 |
| 0.90-1.00 | 1 | 0.9038 | 0.0000 |

Lead D (today, mostly observed), heavy, domain:

| probability bin | pixel-days | mean probability | observed frequency |
|---|---|---|---|
| 0.00-0.05 | 814678 | 0.0006 | 0.0022 |
| 0.05-0.10 | 6034 | 0.0717 | 0.1144 |
| 0.10-0.20 | 5838 | 0.1444 | 0.1697 |
| 0.20-0.30 | 3638 | 0.2475 | 0.2647 |
| 0.30-0.40 | 2695 | 0.3484 | 0.3143 |
| 0.40-0.50 | 2359 | 0.4496 | 0.4061 |
| 0.50-0.60 | 2274 | 0.5496 | 0.4824 |
| 0.60-0.70 | 2250 | 0.6508 | 0.5427 |
| 0.70-0.80 | 2604 | 0.7522 | 0.6402 |
| 0.80-0.90 | 3613 | 0.8542 | 0.7526 |
| 0.90-1.00 | 16921 | 0.9772 | 0.9446 |

### Second opinion: IMD gridded rainfall (0.25 degree, India only)

| lead | threshold | region | pixel-days | events | BSS vs sample climatology (CI) | ROC area | mean p / IMD base rate |
|---|---|---|---|---|---|---|---|
| D (today, mostly observed) | heavy | domain | 753844 | 21531 | -0.110 [-0.238, -0.002] | 0.869 | 1.24 |
| D (today, mostly observed) | heavy | himalaya | 476672 | 9883 | -0.205 [-0.349, -0.069] | 0.813 | 1.02 |
| D (today, mostly observed) | heavy | western_ghats | 168264 | 9606 | -0.042 [-0.282, +0.125] | 0.914 | 1.50 |
| D (today, mostly observed) | very_heavy | domain | 753844 | 5082 | -0.428 [-0.693, -0.246] | 0.859 | 1.33 |
| D (today, mostly observed) | very_heavy | himalaya | 476672 | 2196 | -0.519 [-0.773, -0.326] | 0.780 | 1.16 |
| D (today, mostly observed) | very_heavy | western_ghats | 168264 | 2427 | -0.384 [-0.875, -0.091] | 0.920 | 1.52 |
| D (today, mostly observed) | extremely_heavy | domain | 753844 | 634 | -0.263 [-0.610, -0.093] | 0.830 | 0.95 |
| D (today, mostly observed) | extremely_heavy | himalaya | 476672 | 338 | -0.202 [-0.522, -0.055] | 0.756 | 0.72 |
| D (today, mostly observed) | extremely_heavy | western_ghats | 168264 | 260 | -0.321 [-1.231, -0.027] | 0.918 | 1.21 |
| D+1 | heavy | domain | 1210118 | 28977 | 0.200 [+0.157, +0.236] | 0.915 | 1.05 |
| D+1 | heavy | himalaya | 765184 | 14183 | 0.125 [+0.077, +0.171] | 0.894 | 1.06 |
| D+1 | heavy | western_ghats | 270108 | 11576 | 0.295 [+0.228, +0.349] | 0.936 | 1.08 |
| D+1 | very_heavy | domain | 1210118 | 6496 | 0.067 [+0.050, +0.083] | 0.948 | 0.72 |
| D+1 | very_heavy | himalaya | 765184 | 2965 | 0.054 [+0.028, +0.077] | 0.936 | 0.83 |
| D+1 | very_heavy | western_ghats | 270108 | 2840 | 0.080 [+0.054, +0.101] | 0.946 | 0.64 |
| D+1 | extremely_heavy | domain | 1210118 | 800 | 0.002 [+0.001, +0.004] | 0.906 | 0.12 |
| D+1 | extremely_heavy | himalaya | 765184 | 447 | 0.003 [+0.001, +0.006] | 0.914 | 0.13 |
| D+1 | extremely_heavy | western_ghats | 270108 | 296 | 0.001 [-0.000, +0.002] | 0.884 | 0.09 |
| D+2 | heavy | domain | 1210118 | 28894 | 0.170 [+0.127, +0.205] | 0.904 | 1.05 |
| D+2 | heavy | himalaya | 765184 | 14128 | 0.095 [+0.042, +0.143] | 0.882 | 1.14 |
| D+2 | heavy | western_ghats | 270108 | 11552 | 0.261 [+0.192, +0.316] | 0.927 | 0.99 |
| D+2 | very_heavy | domain | 1210118 | 6477 | 0.048 [+0.033, +0.061] | 0.935 | 0.65 |
| D+2 | very_heavy | himalaya | 765184 | 2947 | 0.045 [+0.022, +0.064] | 0.921 | 0.82 |
| D+2 | very_heavy | western_ghats | 270108 | 2840 | 0.049 [+0.026, +0.066] | 0.936 | 0.50 |
| D+2 | extremely_heavy | domain | 1210118 | 800 | 0.001 [+0.001, +0.002] | 0.903 | 0.09 |
| D+2 | extremely_heavy | himalaya | 765184 | 447 | 0.002 [+0.001, +0.003] | 0.915 | 0.10 |
| D+2 | extremely_heavy | western_ghats | 270108 | 296 | -0.000 [-0.001, +0.001] | 0.876 | 0.07 |
| D+3 | heavy | domain | 1210118 | 28764 | 0.149 [+0.108, +0.184] | 0.894 | 1.01 |
| D+3 | heavy | himalaya | 765184 | 14023 | 0.076 [+0.024, +0.127] | 0.865 | 1.09 |
| D+3 | heavy | western_ghats | 270108 | 11538 | 0.239 [+0.168, +0.295] | 0.923 | 0.96 |
| D+3 | very_heavy | domain | 1210118 | 6427 | 0.041 [+0.027, +0.054] | 0.924 | 0.59 |
| D+3 | very_heavy | himalaya | 765184 | 2902 | 0.032 [+0.014, +0.048] | 0.903 | 0.71 |
| D+3 | very_heavy | western_ghats | 270108 | 2840 | 0.049 [+0.029, +0.068] | 0.931 | 0.50 |
| D+3 | extremely_heavy | domain | 1210118 | 800 | 0.001 [+0.000, +0.001] | 0.876 | 0.08 |
| D+3 | extremely_heavy | himalaya | 765184 | 447 | 0.001 [+0.001, +0.002] | 0.903 | 0.09 |
| D+3 | extremely_heavy | western_ghats | 270108 | 296 | -0.000 [-0.001, +0.000] | 0.827 | 0.07 |

### Warning levels on this test set (domain)

| lead | level | share of pixel-days | pixel-days | observed >= heavy | observed >= very heavy | share of heavy events | share of very heavy events |
|---|---|---|---|---|---|---|---|
| D (today, mostly observed) | none | 92.297% | 796434 | 0.2% | 0.0% | 6.7% | 0.8% |
| D (today, mostly observed) | yellow | 3.886% | 33534 | 10.0% | 0.2% | 11.5% | 1.0% |
| D (today, mostly observed) | orange | 3.071% | 26500 | 65.2% | 9.2% | 59.8% | 32.0% |
| D (today, mostly observed) | red | 0.746% | 6436 | 98.6% | 78.2% | 22.0% | 66.2% |
| D+1 | none | 96.276% | 1333598 | 1.5% | 0.2% | 52.5% | 33.6% |
| D+1 | yellow | 3.077% | 42620 | 27.0% | 6.9% | 31.2% | 34.2% |
| D+1 | orange | 0.646% | 8944 | 67.3% | 31.1% | 16.3% | 32.1% |
| D+1 | red | 0.002% | 26 | 100.0% | 19.2% | 0.1% | 0.1% |
| D+2 | none | 96.632% | 1338529 | 1.6% | 0.2% | 58.5% | 38.1% |
| D+2 | yellow | 2.985% | 41353 | 28.4% | 8.6% | 32.2% | 41.8% |
| D+2 | orange | 0.381% | 5281 | 63.5% | 32.1% | 9.2% | 20.0% |
| D+2 | red | 0.002% | 25 | 20.0% | 16.0% | 0.0% | 0.0% |
| D+3 | none | 97.161% | 1345867 | 1.7% | 0.3% | 63.5% | 44.4% |
| D+3 | yellow | 2.543% | 35231 | 30.8% | 10.1% | 30.1% | 42.6% |
| D+3 | orange | 0.295% | 4090 | 55.9% | 26.7% | 6.3% | 13.0% |
| D+3 | red | 0.000% | 0 | - | - | 0.0% | 0.0% |

## Test set `test_2023` (secondary): test 2023-06-01..2023-09-30, fitted on 2024-06-01..2024-09-30

Test issue days with an ECMWF file: 80 (2023-07-13..2023-09-30).

### Statements (pre-declared tests)

- D (today, mostly observed), heavy: domain: skilful; beats every baseline; reliable; discriminates (9234 event pixel-days on 35 days); himalaya: skilful; beats every baseline; reliable; discriminates (4580 event pixel-days on 35 days); western_ghats: skilful; beats every baseline; reliable; discriminates (3886 event pixel-days on 15 days)
- D (today, mostly observed), very_heavy: domain: skilful; beats every baseline; reliable; discriminates (901 event pixel-days on 30 days); himalaya: skilful; beats every baseline; reliable; discriminates (458 event pixel-days on 30 days); western_ghats: skilful; beats every baseline; NOT reliable; discriminates (380 event pixel-days on 12 days)
- D (today, mostly observed), extremely_heavy: domain: too few events to conclude (13 event pixel-days on 5 days); himalaya: too few events to conclude (12 event pixel-days on 4 days); western_ghats: too few events to conclude (0 event pixel-days on 0 days)
- D (today, mostly observed), p95: domain: skilful; beats every baseline; reliable; discriminates (24643 event pixel-days on 35 days); himalaya: skilful; beats every baseline; reliable; discriminates (14945 event pixel-days on 35 days); western_ghats: skilful; does not beat observed; reliable; discriminates (6479 event pixel-days on 24 days)
- D (today, mostly observed), p99: domain: skilful; beats every baseline; reliable; discriminates (5401 event pixel-days on 34 days); himalaya: skilful; beats every baseline; reliable; discriminates (3440 event pixel-days on 34 days); western_ghats: skilful; does not beat observed; NOT reliable; discriminates (1282 event pixel-days on 18 days)
- D+1, heavy: domain: skilful; beats every baseline; reliable; discriminates (14632 event pixel-days on 80 days); himalaya: skilful; beats every baseline; NOT reliable; discriminates (8582 event pixel-days on 79 days); western_ghats: skilful; beats every baseline; reliable; discriminates (4789 event pixel-days on 36 days)
- D+1, very_heavy: domain: NOT skilful; does not beat ens_mean; NOT reliable; discriminates (1757 event pixel-days on 61 days); himalaya: NOT skilful; does not beat ens_mean; NOT reliable; discriminates (1139 event pixel-days on 55 days); western_ghats: NOT skilful; does not beat ens_mean, hres; NOT reliable; discriminates (488 event pixel-days on 20 days)
- D+1, extremely_heavy: domain: too few events to conclude (30 event pixel-days on 7 days); himalaya: too few events to conclude (30 event pixel-days on 7 days); western_ghats: too few events to conclude (0 event pixel-days on 0 days)
- D+1, p95: domain: skilful; beats every baseline; reliable; discriminates (40916 event pixel-days on 80 days); himalaya: skilful; beats every baseline; reliable; discriminates (26511 event pixel-days on 80 days); western_ghats: skilful; beats every baseline; reliable; discriminates (8974 event pixel-days on 57 days)
- D+1, p99: domain: skilful; beats every baseline; NOT reliable; discriminates (8538 event pixel-days on 79 days); himalaya: skilful; beats every baseline; NOT reliable; discriminates (5787 event pixel-days on 75 days); western_ghats: NOT skilful; beats every baseline; NOT reliable; discriminates (1618 event pixel-days on 39 days)
- D+2, heavy: domain: skilful; beats every baseline; reliable; discriminates (14404 event pixel-days on 80 days); himalaya: NOT skilful; beats every baseline; NOT reliable; discriminates (8459 event pixel-days on 79 days); western_ghats: skilful; beats every baseline; reliable; discriminates (4699 event pixel-days on 36 days)
- D+2, very_heavy: domain: NOT skilful; does not beat ens_mean; NOT reliable; discriminates (1720 event pixel-days on 61 days); himalaya: NOT skilful; does not beat ens_mean; NOT reliable; discriminates (1132 event pixel-days on 54 days); western_ghats: NOT skilful; does not beat gfs, ens_mean; NOT reliable; discriminates (465 event pixel-days on 20 days)
- D+2, extremely_heavy: domain: too few events to conclude (30 event pixel-days on 7 days); himalaya: too few events to conclude (30 event pixel-days on 7 days); western_ghats: too few events to conclude (0 event pixel-days on 0 days)
- D+2, p95: domain: skilful; beats every baseline; reliable; discriminates (40651 event pixel-days on 80 days); himalaya: skilful; beats every baseline; reliable; discriminates (26292 event pixel-days on 80 days); western_ghats: skilful; beats every baseline; reliable; discriminates (8910 event pixel-days on 57 days)
- D+2, p99: domain: NOT skilful; beats every baseline; NOT reliable; discriminates (8473 event pixel-days on 79 days); himalaya: NOT skilful; beats every baseline; NOT reliable; discriminates (5740 event pixel-days on 75 days); western_ghats: NOT skilful; beats every baseline; NOT reliable; discriminates (1602 event pixel-days on 39 days)
- D+3, heavy: domain: skilful; beats every baseline; reliable; discriminates (14381 event pixel-days on 80 days); himalaya: NOT skilful; beats every baseline; NOT reliable; discriminates (8437 event pixel-days on 79 days); western_ghats: skilful; beats every baseline; reliable; discriminates (4693 event pixel-days on 35 days)
- D+3, very_heavy: domain: NOT skilful; does not beat ens_mean; NOT reliable; discriminates (1698 event pixel-days on 61 days); himalaya: NOT skilful; does not beat ens_mean; NOT reliable; discriminates (1110 event pixel-days on 54 days); western_ghats: NOT skilful; does not beat gfs, ens_mean; NOT reliable; discriminates (465 event pixel-days on 20 days)
- D+3, extremely_heavy: domain: too few events to conclude (30 event pixel-days on 7 days); himalaya: too few events to conclude (30 event pixel-days on 7 days); western_ghats: too few events to conclude (0 event pixel-days on 0 days)
- D+3, p95: domain: skilful; beats every baseline; reliable; discriminates (40492 event pixel-days on 80 days); himalaya: skilful; beats every baseline; reliable; discriminates (26128 event pixel-days on 80 days); western_ghats: skilful; beats every baseline; reliable; discriminates (8924 event pixel-days on 57 days)
- D+3, p99: domain: NOT skilful; beats every baseline; NOT reliable; discriminates (8477 event pixel-days on 79 days); himalaya: NOT skilful; beats every baseline; NOT reliable; discriminates (5730 event pixel-days on 75 days); western_ghats: NOT skilful; beats every baseline; NOT reliable; discriminates (1612 event pixel-days on 40 days)

### Headline (product = calibrated probability)

| lead | threshold | region | event pixel-days | event days | BSS (95% CI) | ROC area (CI) | REL/UNC | mean p / base rate | verdict |
|---|---|---|---|---|---|---|---|---|---|
| D (today, mostly observed) | heavy | domain | 9234 | 35 | 0.676 [+0.644, +0.706] | 0.996 [+0.995, +0.997] | 0.018 | 0.99 | skilful; beats every baseline; reliable; discriminates |
| D (today, mostly observed) | heavy | himalaya | 4580 | 35 | 0.608 [+0.559, +0.650] | 0.995 [+0.993, +0.996] | 0.010 | 1.09 | skilful; beats every baseline; reliable; discriminates |
| D (today, mostly observed) | heavy | western_ghats | 3886 | 15 | 0.769 [+0.720, +0.809] | 0.998 [+0.996, +0.999] | 0.034 | 0.89 | skilful; beats every baseline; reliable; discriminates |
| D (today, mostly observed) | very_heavy | domain | 901 | 30 | 0.466 [+0.385, +0.528] | 0.998 [+0.996, +0.999] | 0.023 | 1.22 | skilful; beats every baseline; reliable; discriminates |
| D (today, mostly observed) | very_heavy | himalaya | 458 | 30 | 0.442 [+0.335, +0.538] | 0.997 [+0.994, +0.999] | 0.008 | 1.18 | skilful; beats every baseline; reliable; discriminates |
| D (today, mostly observed) | very_heavy | western_ghats | 380 | 12 | 0.502 [+0.375, +0.577] | 0.998 [+0.997, +0.999] | 0.064 | 1.27 | skilful; beats every baseline; NOT reliable; discriminates |
| D (today, mostly observed) | extremely_heavy | domain | 13 | 5 | 0.414 [+0.156, +0.501] | 1.000 [+0.999, +1.000] | 0.174 | 1.20 | too few events to conclude |
| D (today, mostly observed) | extremely_heavy | himalaya | 12 | 4 | 0.435 [+0.148, +0.509] | 1.000 [+0.999, +1.000] | 0.189 | 0.95 | too few events to conclude |
| D (today, mostly observed) | extremely_heavy | western_ghats | 0 | 0 | 0.544 [+0.012, +0.953] | - - | - | - | too few events to conclude |
| D (today, mostly observed) | p95 | domain | 24643 | 35 | 0.685 [+0.667, +0.704] | 0.991 [+0.989, +0.992] | 0.012 | 1.01 | skilful; beats every baseline; reliable; discriminates |
| D (today, mostly observed) | p95 | himalaya | 14945 | 35 | 0.656 [+0.629, +0.683] | 0.989 [+0.987, +0.991] | 0.009 | 1.12 | skilful; beats every baseline; reliable; discriminates |
| D (today, mostly observed) | p95 | western_ghats | 6479 | 24 | 0.739 [+0.713, +0.762] | 0.995 [+0.992, +0.997] | 0.052 | 0.82 | skilful; does not beat observed; reliable; discriminates |
| D (today, mostly observed) | p99 | domain | 5401 | 34 | 0.561 [+0.511, +0.612] | 0.995 [+0.993, +0.996] | 0.019 | 0.95 | skilful; beats every baseline; reliable; discriminates |
| D (today, mostly observed) | p99 | himalaya | 3440 | 34 | 0.578 [+0.523, +0.629] | 0.995 [+0.993, +0.996] | 0.008 | 1.04 | skilful; beats every baseline; reliable; discriminates |
| D (today, mostly observed) | p99 | western_ghats | 1282 | 18 | 0.510 [+0.420, +0.607] | 0.994 [+0.990, +0.998] | 0.069 | 0.78 | skilful; does not beat observed; NOT reliable; discriminates |
| D+1 | heavy | domain | 14632 | 80 | 0.130 [+0.086, +0.174] | 0.915 [+0.901, +0.928] | 0.006 | 1.18 | skilful; beats every baseline; reliable; discriminates |
| D+1 | heavy | himalaya | 8582 | 79 | 0.077 [+0.026, +0.130] | 0.880 [+0.859, +0.901] | 0.010 | 1.25 | skilful; beats every baseline; NOT reliable; discriminates |
| D+1 | heavy | western_ghats | 4789 | 36 | 0.228 [+0.174, +0.273] | 0.964 [+0.953, +0.974] | 0.021 | 1.01 | skilful; beats every baseline; reliable; discriminates |
| D+1 | very_heavy | domain | 1757 | 61 | 0.017 [-0.044, +0.086] | 0.930 [+0.902, +0.954] | 0.027 | 1.87 | NOT skilful; does not beat ens_mean; NOT reliable; discriminates |
| D+1 | very_heavy | himalaya | 1139 | 55 | 0.016 [-0.047, +0.091] | 0.904 [+0.866, +0.935] | 0.024 | 1.70 | NOT skilful; does not beat ens_mean; NOT reliable; discriminates |
| D+1 | very_heavy | western_ghats | 488 | 20 | -0.001 [-0.092, +0.051] | 0.974 [+0.964, +0.983] | 0.045 | 2.13 | NOT skilful; does not beat ens_mean, hres; NOT reliable; discriminates |
| D+1 | extremely_heavy | domain | 30 | 7 | -0.077 [-0.184, -0.019] | 0.924 [+0.798, +0.991] | 0.055 | 8.59 | too few events to conclude |
| D+1 | extremely_heavy | himalaya | 30 | 7 | -0.044 [-0.128, -0.008] | 0.925 [+0.799, +0.991] | 0.037 | 5.52 | too few events to conclude |
| D+1 | extremely_heavy | western_ghats | 0 | 0 | -1.099 [-2.494, +0.164] | - - | - | - | too few events to conclude |
| D+1 | p95 | domain | 40916 | 80 | 0.114 [+0.084, +0.146] | 0.855 [+0.841, +0.870] | 0.003 | 1.10 | skilful; beats every baseline; reliable; discriminates |
| D+1 | p95 | himalaya | 26511 | 80 | 0.086 [+0.050, +0.125] | 0.829 [+0.809, +0.850] | 0.008 | 1.16 | skilful; beats every baseline; reliable; discriminates |
| D+1 | p95 | western_ghats | 8974 | 57 | 0.166 [+0.128, +0.203] | 0.905 [+0.882, +0.926] | 0.009 | 0.95 | skilful; beats every baseline; reliable; discriminates |
| D+1 | p99 | domain | 8538 | 79 | 0.059 [+0.006, +0.121] | 0.877 [+0.852, +0.902] | 0.011 | 1.32 | skilful; beats every baseline; NOT reliable; discriminates |
| D+1 | p99 | himalaya | 5787 | 75 | 0.058 [+0.002, +0.130] | 0.857 [+0.825, +0.889] | 0.015 | 1.33 | skilful; beats every baseline; NOT reliable; discriminates |
| D+1 | p99 | western_ghats | 1618 | 39 | 0.042 [-0.020, +0.083] | 0.913 [+0.878, +0.949] | 0.006 | 1.29 | NOT skilful; beats every baseline; NOT reliable; discriminates |
| D+2 | heavy | domain | 14404 | 80 | 0.098 [+0.052, +0.134] | 0.903 [+0.885, +0.918] | 0.004 | 1.21 | skilful; beats every baseline; reliable; discriminates |
| D+2 | heavy | himalaya | 8459 | 79 | 0.037 [-0.012, +0.081] | 0.866 [+0.840, +0.889] | 0.014 | 1.31 | NOT skilful; beats every baseline; NOT reliable; discriminates |
| D+2 | heavy | western_ghats | 4699 | 36 | 0.217 [+0.155, +0.272] | 0.955 [+0.939, +0.969] | 0.017 | 1.01 | skilful; beats every baseline; reliable; discriminates |
| D+2 | very_heavy | domain | 1720 | 61 | -0.009 [-0.078, +0.043] | 0.914 [+0.876, +0.942] | 0.031 | 1.96 | NOT skilful; does not beat ens_mean; NOT reliable; discriminates |
| D+2 | very_heavy | himalaya | 1132 | 54 | -0.013 [-0.081, +0.044] | 0.881 [+0.834, +0.920] | 0.024 | 1.78 | NOT skilful; does not beat ens_mean; NOT reliable; discriminates |
| D+2 | very_heavy | western_ghats | 465 | 20 | -0.012 [-0.107, +0.049] | 0.973 [+0.960, +0.983] | 0.055 | 2.28 | NOT skilful; does not beat gfs, ens_mean; NOT reliable; discriminates |
| D+2 | extremely_heavy | domain | 30 | 7 | -0.100 [-0.547, -0.021] | 0.909 [+0.733, +0.985] | 0.055 | 8.93 | too few events to conclude |
| D+2 | extremely_heavy | himalaya | 30 | 7 | -0.063 [-0.414, +0.001] | 0.910 [+0.732, +0.985] | 0.041 | 5.67 | too few events to conclude |
| D+2 | extremely_heavy | western_ghats | 0 | 0 | -2.912 [-6.161, -0.246] | - - | - | - | too few events to conclude |
| D+2 | p95 | domain | 40651 | 80 | 0.094 [+0.066, +0.124] | 0.843 [+0.826, +0.861] | 0.001 | 1.12 | skilful; beats every baseline; reliable; discriminates |
| D+2 | p95 | himalaya | 26292 | 80 | 0.066 [+0.031, +0.100] | 0.818 [+0.796, +0.840] | 0.006 | 1.19 | skilful; beats every baseline; reliable; discriminates |
| D+2 | p95 | western_ghats | 8910 | 57 | 0.153 [+0.110, +0.201] | 0.896 [+0.868, +0.921] | 0.008 | 0.95 | skilful; beats every baseline; reliable; discriminates |
| D+2 | p99 | domain | 8473 | 79 | 0.025 [-0.021, +0.072] | 0.857 [+0.822, +0.888] | 0.013 | 1.35 | NOT skilful; beats every baseline; NOT reliable; discriminates |
| D+2 | p99 | himalaya | 5740 | 75 | 0.018 [-0.030, +0.068] | 0.840 [+0.802, +0.875] | 0.016 | 1.37 | NOT skilful; beats every baseline; NOT reliable; discriminates |
| D+2 | p99 | western_ghats | 1602 | 39 | 0.038 [-0.040, +0.097] | 0.891 [+0.825, +0.948] | 0.008 | 1.33 | NOT skilful; beats every baseline; NOT reliable; discriminates |
| D+3 | heavy | domain | 14381 | 80 | 0.087 [+0.053, +0.116] | 0.896 [+0.875, +0.912] | 0.004 | 1.18 | skilful; beats every baseline; reliable; discriminates |
| D+3 | heavy | himalaya | 8437 | 79 | 0.031 [-0.010, +0.068] | 0.856 [+0.829, +0.881] | 0.010 | 1.29 | NOT skilful; beats every baseline; NOT reliable; discriminates |
| D+3 | heavy | western_ghats | 4693 | 35 | 0.195 [+0.149, +0.233] | 0.953 [+0.935, +0.966] | 0.024 | 0.97 | skilful; beats every baseline; reliable; discriminates |
| D+3 | very_heavy | domain | 1698 | 61 | -0.010 [-0.058, +0.023] | 0.911 [+0.878, +0.936] | 0.025 | 1.95 | NOT skilful; does not beat ens_mean; NOT reliable; discriminates |
| D+3 | very_heavy | himalaya | 1110 | 54 | -0.021 [-0.078, +0.016] | 0.877 [+0.828, +0.914] | 0.026 | 1.85 | NOT skilful; does not beat ens_mean; NOT reliable; discriminates |
| D+3 | very_heavy | western_ghats | 465 | 20 | 0.004 [-0.069, +0.054] | 0.968 [+0.952, +0.981] | 0.036 | 2.13 | NOT skilful; does not beat gfs, ens_mean; NOT reliable; discriminates |
| D+3 | extremely_heavy | domain | 30 | 7 | -0.034 [-0.175, -0.003] | 0.907 [+0.772, +0.979] | 0.008 | 8.70 | too few events to conclude |
| D+3 | extremely_heavy | himalaya | 30 | 7 | -0.024 [-0.149, +0.005] | 0.906 [+0.770, +0.980] | 0.007 | 5.80 | too few events to conclude |
| D+3 | extremely_heavy | western_ghats | 0 | 0 | -1.175 [-2.976, +0.199] | - - | - | - | too few events to conclude |
| D+3 | p95 | domain | 40492 | 80 | 0.081 [+0.055, +0.106] | 0.833 [+0.814, +0.850] | 0.001 | 1.10 | skilful; beats every baseline; reliable; discriminates |
| D+3 | p95 | himalaya | 26128 | 80 | 0.053 [+0.020, +0.086] | 0.806 [+0.779, +0.831] | 0.006 | 1.17 | skilful; beats every baseline; reliable; discriminates |
| D+3 | p95 | western_ghats | 8924 | 57 | 0.136 [+0.107, +0.162] | 0.890 [+0.863, +0.915] | 0.013 | 0.94 | skilful; beats every baseline; reliable; discriminates |
| D+3 | p99 | domain | 8477 | 79 | 0.027 [-0.013, +0.066] | 0.843 [+0.810, +0.875] | 0.006 | 1.29 | NOT skilful; beats every baseline; NOT reliable; discriminates |
| D+3 | p99 | himalaya | 5730 | 75 | 0.022 [-0.024, +0.064] | 0.823 [+0.779, +0.862] | 0.008 | 1.32 | NOT skilful; beats every baseline; NOT reliable; discriminates |
| D+3 | p99 | western_ghats | 1612 | 40 | 0.030 [-0.022, +0.069] | 0.892 [+0.835, +0.937] | 0.008 | 1.27 | NOT skilful; beats every baseline; NOT reliable; discriminates |

### Against the deterministic baselines and the raw ensemble (domain)

| lead | threshold | BS product | BS climatology | BS raw ensemble | baseline: BS, diff (95% CI), hit rate, FAR |
|---|---|---|---|---|---|
| D (today, mostly observed) | heavy | 0.00697 | 0.02153 | - | observed: 0.00957, -0.00260 [-0.00347, -0.00173], 0.822, 0.221 |
| D (today, mostly observed) | very_heavy | 0.00121 | 0.00226 | - | observed: 0.00163, -0.00042 [-0.00063, -0.00024], 0.658, 0.364 |
| D (today, mostly observed) | extremely_heavy | 0.00002 | 0.00003 | - | observed: 0.00002, -0.00000 [-0.00001, +0.00001], 0.538, 0.222 |
| D (today, mostly observed) | p95 | 0.01818 | 0.05772 | - | observed: 0.02431, -0.00613 [-0.00754, -0.00473], 0.857, 0.225 |
| D (today, mostly observed) | p99 | 0.00589 | 0.01341 | - | observed: 0.00784, -0.00195 [-0.00275, -0.00120], 0.762, 0.308 |
| D+1 | heavy | 0.01326 | 0.01525 | 0.01521 | gfs: 0.02302, -0.00976 [-0.01251, -0.00742], 0.171, 0.778; ens_mean: 0.01704, -0.00378 [-0.00516, -0.00248], 0.099, 0.613; hres: 0.01856, -0.00530 [-0.00685, -0.00386], 0.101, 0.715 |
| D+1 | very_heavy | 0.00189 | 0.00192 | 0.00202 | gfs: 0.00418, -0.00228 [-0.00338, -0.00143], 0.088, 0.934; ens_mean: 0.00198, -0.00009 [-0.00026, +0.00003], 0.052, 0.601; hres: 0.00247, -0.00058 [-0.00112, -0.00021], 0.059, 0.852 |
| D+1 | extremely_heavy | 0.00004 | 0.00003 | 0.00005 | gfs: 0.00027, -0.00023 [-0.00039, -0.00010], 0.000, 1.000; ens_mean: 0.00004, -0.00000 [-0.00001, +0.00000], 0.000, 1.000; hres: 0.00015, -0.00011 [-0.00032, +0.00000], 0.033, 0.990 |
| D+1 | p95 | 0.03769 | 0.04255 | 0.04233 | gfs: 0.05870, -0.02101 [-0.02518, -0.01708], 0.190, 0.722; ens_mean: 0.05123, -0.01354 [-0.01671, -0.01070], 0.140, 0.664; hres: 0.05461, -0.01692 [-0.02011, -0.01404], 0.152, 0.705 |
| D+1 | p99 | 0.00876 | 0.00930 | 0.00948 | gfs: 0.01531, -0.00655 [-0.00862, -0.00479], 0.122, 0.860; ens_mean: 0.01038, -0.00162 [-0.00250, -0.00090], 0.101, 0.670; hres: 0.01126, -0.00250 [-0.00341, -0.00165], 0.102, 0.746 |
| D+2 | heavy | 0.01356 | 0.01504 | 0.01524 | gfs: 0.02127, -0.00771 [-0.00985, -0.00592], 0.108, 0.806; ens_mean: 0.01759, -0.00403 [-0.00578, -0.00252], 0.091, 0.688; hres: 0.01970, -0.00614 [-0.00813, -0.00445], 0.103, 0.771 |
| D+2 | very_heavy | 0.00190 | 0.00189 | 0.00204 | gfs: 0.00286, -0.00096 [-0.00157, -0.00047], 0.063, 0.901; ens_mean: 0.00208, -0.00018 [-0.00058, +0.00004], 0.008, 0.929; hres: 0.00309, -0.00118 [-0.00206, -0.00051], 0.058, 0.922 |
| D+2 | extremely_heavy | 0.00004 | 0.00003 | 0.00004 | gfs: 0.00012, -0.00008 [-0.00024, -0.00000], 0.000, 1.000; ens_mean: 0.00003, +0.00000 [+0.00000, +0.00001], 0.000, -; hres: 0.00021, -0.00017 [-0.00041, -0.00002], 0.000, 1.000 |
| D+2 | p95 | 0.03830 | 0.04228 | 0.04215 | gfs: 0.05804, -0.01974 [-0.02331, -0.01621], 0.150, 0.749; ens_mean: 0.05100, -0.01270 [-0.01601, -0.00966], 0.123, 0.681; hres: 0.05596, -0.01766 [-0.02168, -0.01412], 0.153, 0.725 |
| D+2 | p99 | 0.00900 | 0.00923 | 0.00971 | gfs: 0.01375, -0.00475 [-0.00627, -0.00335], 0.092, 0.860; ens_mean: 0.01076, -0.00176 [-0.00301, -0.00081], 0.067, 0.767; hres: 0.01248, -0.00349 [-0.00474, -0.00231], 0.091, 0.825 |
| D+3 | heavy | 0.01370 | 0.01501 | 0.01547 | gfs: 0.02008, -0.00638 [-0.00824, -0.00469], 0.082, 0.810; ens_mean: 0.01731, -0.00361 [-0.00510, -0.00233], 0.054, 0.732; hres: 0.02112, -0.00742 [-0.00990, -0.00506], 0.099, 0.814 |
| D+3 | very_heavy | 0.00188 | 0.00186 | 0.00198 | gfs: 0.00280, -0.00092 [-0.00138, -0.00052], 0.032, 0.943; ens_mean: 0.00192, -0.00004 [-0.00014, +0.00004], 0.000, 1.000; hres: 0.00383, -0.00195 [-0.00331, -0.00098], 0.032, 0.971 |
| D+3 | extremely_heavy | 0.00003 | 0.00003 | 0.00004 | gfs: 0.00010, -0.00006 [-0.00014, -0.00000], 0.000, 1.000; ens_mean: 0.00003, +0.00000 [+0.00000, +0.00000], 0.000, -; hres: 0.00025, -0.00022 [-0.00045, -0.00006], 0.000, 1.000 |
| D+3 | p95 | 0.03873 | 0.04212 | 0.04276 | gfs: 0.05692, -0.01819 [-0.02184, -0.01476], 0.108, 0.781; ens_mean: 0.05106, -0.01233 [-0.01573, -0.00909], 0.103, 0.707; hres: 0.05797, -0.01924 [-0.02311, -0.01540], 0.147, 0.752 |
| D+3 | p99 | 0.00899 | 0.00924 | 0.00973 | gfs: 0.01290, -0.00392 [-0.00492, -0.00300], 0.071, 0.864; ens_mean: 0.01032, -0.00133 [-0.00221, -0.00066], 0.041, 0.782; hres: 0.01392, -0.00493 [-0.00695, -0.00312], 0.096, 0.860 |

### Raw quantile probability (uncalibrated) beside the product (domain)

| lead | threshold | raw BSS (CI) | raw ROC area | raw mean p / base rate | calibrated BSS |
|---|---|---|---|---|---|
| D+1 | heavy | 0.003 [-0.053, +0.064] | 0.838 | 0.50 | 0.130 |
| D+1 | very_heavy | -0.048 [-0.151, +0.039] | 0.736 | 0.63 | 0.017 |
| D+1 | extremely_heavy | -0.441 [-0.981, -0.048] | 0.662 | 3.99 | -0.077 |
| D+1 | p95 | 0.005 [-0.040, +0.047] | 0.820 | 0.66 | 0.114 |
| D+1 | p99 | -0.019 [-0.094, +0.068] | 0.774 | 0.58 | 0.059 |
| D+2 | heavy | -0.013 [-0.085, +0.053] | 0.848 | 0.60 | 0.098 |
| D+2 | very_heavy | -0.083 [-0.278, +0.032] | 0.791 | 0.87 | -0.009 |
| D+2 | extremely_heavy | -0.214 [-1.301, -0.029] | 0.708 | 5.29 | -0.100 |
| D+2 | p95 | 0.003 [-0.047, +0.052] | 0.817 | 0.72 | 0.094 |
| D+2 | p99 | -0.052 [-0.155, +0.036] | 0.791 | 0.69 | 0.025 |
| D+3 | heavy | -0.030 [-0.095, +0.033] | 0.839 | 0.63 | 0.087 |
| D+3 | very_heavy | -0.065 [-0.167, +0.015] | 0.757 | 0.84 | -0.010 |
| D+3 | extremely_heavy | -0.116 [-0.602, -0.009] | 0.657 | 4.70 | -0.034 |
| D+3 | p95 | -0.015 [-0.071, +0.033] | 0.804 | 0.73 | 0.081 |
| D+3 | p99 | -0.053 [-0.133, +0.017] | 0.764 | 0.72 | 0.027 |

### Reliability (domain)

Lead D+1, heavy, domain:

| probability bin | pixel-days | mean probability | observed frequency |
|---|---|---|---|
| 0.00-0.05 | 823288 | 0.0073 | 0.0055 |
| 0.05-0.10 | 46293 | 0.0699 | 0.0524 |
| 0.10-0.20 | 24157 | 0.1380 | 0.1032 |
| 0.20-0.30 | 7841 | 0.2414 | 0.2393 |
| 0.30-0.40 | 3434 | 0.3473 | 0.3937 |
| 0.40-0.50 | 2071 | 0.4447 | 0.5263 |
| 0.50-0.60 | 996 | 0.5385 | 0.6667 |
| 0.60-0.70 | 175 | 0.6336 | 0.7886 |
| 0.70-0.80 | 65 | 0.7364 | 1.0000 |

Lead D+1, very_heavy, domain:

| probability bin | pixel-days | mean probability | observed frequency |
|---|---|---|---|
| 0.00-0.05 | 895452 | 0.0022 | 0.0012 |
| 0.05-0.10 | 8294 | 0.0694 | 0.0379 |
| 0.10-0.20 | 3667 | 0.1369 | 0.0704 |
| 0.20-0.30 | 774 | 0.2345 | 0.0866 |
| 0.30-0.40 | 76 | 0.3265 | 0.3947 |
| 0.40-0.50 | 30 | 0.4491 | 0.8000 |
| 0.50-0.60 | 27 | 0.5467 | 0.5926 |

Lead D+1, p95, domain:

| probability bin | pixel-days | mean probability | observed frequency |
|---|---|---|---|
| 0.00-0.05 | 639752 | 0.0139 | 0.0114 |
| 0.05-0.10 | 132953 | 0.0716 | 0.0667 |
| 0.10-0.20 | 90493 | 0.1387 | 0.1304 |
| 0.20-0.30 | 27264 | 0.2424 | 0.2245 |
| 0.30-0.40 | 10683 | 0.3422 | 0.3151 |
| 0.40-0.50 | 4029 | 0.4421 | 0.3269 |
| 0.50-0.60 | 1596 | 0.5442 | 0.5495 |
| 0.60-0.70 | 908 | 0.6459 | 0.7148 |
| 0.70-0.80 | 538 | 0.7381 | 0.9238 |
| 0.80-0.90 | 104 | 0.8386 | 1.0000 |

Lead D (today, mostly observed), heavy, domain:

| probability bin | pixel-days | mean probability | observed frequency |
|---|---|---|---|
| 0.00-0.05 | 374009 | 0.0013 | 0.0003 |
| 0.05-0.10 | 5119 | 0.0718 | 0.0256 |
| 0.10-0.20 | 4627 | 0.1439 | 0.0886 |
| 0.20-0.30 | 2614 | 0.2473 | 0.1970 |
| 0.30-0.40 | 1904 | 0.3483 | 0.3913 |
| 0.40-0.50 | 1709 | 0.4497 | 0.5190 |
| 0.50-0.60 | 1504 | 0.5495 | 0.6762 |
| 0.60-0.70 | 1428 | 0.6488 | 0.8088 |
| 0.70-0.80 | 1442 | 0.7499 | 0.9126 |
| 0.80-0.90 | 1497 | 0.8505 | 0.9626 |
| 0.90-1.00 | 1537 | 0.9467 | 0.9909 |

### Second opinion: IMD gridded rainfall (0.25 degree, India only)

| lead | threshold | region | pixel-days | events | BSS vs sample climatology (CI) | ROC area | mean p / IMD base rate |
|---|---|---|---|---|---|---|---|
| D (today, mostly observed) | heavy | domain | 347165 | 9267 | 0.181 [+0.073, +0.261] | 0.917 | 0.87 |
| D (today, mostly observed) | heavy | himalaya | 219520 | 4140 | -0.065 [-0.288, +0.102] | 0.863 | 0.95 |
| D (today, mostly observed) | heavy | western_ghats | 77490 | 4184 | 0.410 [+0.334, +0.476] | 0.961 | 0.82 |
| D (today, mostly observed) | very_heavy | domain | 347165 | 2142 | 0.057 [-0.033, +0.115] | 0.928 | 0.46 |
| D (today, mostly observed) | very_heavy | himalaya | 219520 | 666 | -0.151 [-0.389, -0.035] | 0.839 | 0.65 |
| D (today, mostly observed) | very_heavy | western_ghats | 77490 | 1266 | 0.164 [+0.085, +0.230] | 0.966 | 0.38 |
| D (today, mostly observed) | extremely_heavy | domain | 347165 | 256 | -0.002 [-0.025, +0.007] | 0.718 | 0.05 |
| D (today, mostly observed) | extremely_heavy | himalaya | 219520 | 86 | -0.020 [-0.066, +0.001] | 0.566 | 0.11 |
| D (today, mostly observed) | extremely_heavy | western_ghats | 77490 | 151 | 0.006 [-0.000, +0.009] | 0.815 | 0.02 |
| D+1 | heavy | domain | 793520 | 13625 | 0.223 [+0.158, +0.278] | 0.925 | 1.11 |
| D+1 | heavy | himalaya | 501760 | 6790 | 0.125 [+0.038, +0.216] | 0.893 | 1.27 |
| D+1 | heavy | western_ghats | 177120 | 5260 | 0.344 [+0.269, +0.392] | 0.962 | 0.92 |
| D+1 | very_heavy | domain | 793520 | 2926 | 0.122 [+0.071, +0.186] | 0.966 | 1.00 |
| D+1 | very_heavy | himalaya | 501760 | 1214 | 0.097 [+0.002, +0.206] | 0.943 | 1.30 |
| D+1 | very_heavy | western_ghats | 177120 | 1379 | 0.134 [+0.095, +0.166] | 0.978 | 0.75 |
| D+1 | extremely_heavy | domain | 793520 | 374 | 0.057 [+0.002, +0.133] | 0.981 | 0.61 |
| D+1 | extremely_heavy | himalaya | 501760 | 180 | 0.080 [-0.008, +0.160] | 0.976 | 0.75 |
| D+1 | extremely_heavy | western_ghats | 177120 | 153 | 0.011 [-0.001, +0.018] | 0.980 | 0.40 |
| D+2 | heavy | domain | 793520 | 13583 | 0.193 [+0.128, +0.242] | 0.918 | 1.12 |
| D+2 | heavy | himalaya | 501760 | 6800 | 0.085 [+0.008, +0.152] | 0.883 | 1.31 |
| D+2 | heavy | western_ghats | 177120 | 5215 | 0.332 [+0.253, +0.383] | 0.957 | 0.91 |
| D+2 | very_heavy | domain | 793520 | 2905 | 0.092 [+0.047, +0.130] | 0.957 | 1.03 |
| D+2 | very_heavy | himalaya | 501760 | 1202 | 0.046 [-0.029, +0.106] | 0.926 | 1.37 |
| D+2 | very_heavy | western_ghats | 177120 | 1376 | 0.130 [+0.092, +0.163] | 0.975 | 0.77 |
| D+2 | extremely_heavy | domain | 793520 | 374 | 0.029 [-0.014, +0.059] | 0.973 | 0.63 |
| D+2 | extremely_heavy | himalaya | 501760 | 180 | 0.034 [-0.038, +0.071] | 0.964 | 0.77 |
| D+2 | extremely_heavy | western_ghats | 177120 | 153 | 0.016 [-0.011, +0.031] | 0.973 | 0.44 |
| D+3 | heavy | domain | 793520 | 13565 | 0.172 [+0.117, +0.216] | 0.914 | 1.08 |
| D+3 | heavy | himalaya | 501760 | 6811 | 0.066 [+0.005, +0.119] | 0.880 | 1.27 |
| D+3 | heavy | western_ghats | 177120 | 5184 | 0.312 [+0.237, +0.359] | 0.953 | 0.88 |
| D+3 | very_heavy | domain | 793520 | 2915 | 0.078 [+0.045, +0.107] | 0.955 | 0.99 |
| D+3 | very_heavy | himalaya | 501760 | 1212 | 0.022 [-0.027, +0.061] | 0.927 | 1.35 |
| D+3 | very_heavy | western_ghats | 177120 | 1376 | 0.125 [+0.088, +0.165] | 0.973 | 0.72 |
| D+3 | extremely_heavy | domain | 793520 | 374 | 0.015 [-0.002, +0.025] | 0.971 | 0.59 |
| D+3 | extremely_heavy | himalaya | 501760 | 180 | 0.013 [-0.008, +0.027] | 0.963 | 0.74 |
| D+3 | extremely_heavy | western_ghats | 177120 | 153 | 0.014 [-0.003, +0.025] | 0.971 | 0.41 |

### Warning levels on this test set (domain)

| lead | level | share of pixel-days | pixel-days | observed >= heavy | observed >= very heavy | share of heavy events | share of very heavy events |
|---|---|---|---|---|---|---|---|
| D (today, mostly observed) | none | 93.095% | 369950 | 0.1% | 0.0% | 2.3% | 0.0% |
| D (today, mostly observed) | yellow | 4.654% | 18495 | 12.1% | 0.1% | 24.1% | 1.2% |
| D (today, mostly observed) | orange | 2.138% | 8495 | 74.7% | 6.2% | 68.7% | 58.6% |
| D (today, mostly observed) | red | 0.113% | 450 | 99.6% | 80.4% | 4.9% | 40.2% |
| D+1 | none | 98.096% | 891027 | 1.0% | 0.1% | 63.6% | 56.3% |
| D+1 | yellow | 1.722% | 15643 | 27.2% | 3.6% | 29.0% | 32.3% |
| D+1 | orange | 0.179% | 1623 | 64.8% | 11.3% | 7.2% | 10.4% |
| D+1 | red | 0.003% | 27 | 100.0% | 59.3% | 0.2% | 0.9% |
| D+2 | none | 98.226% | 892207 | 1.1% | 0.1% | 67.1% | 61.4% |
| D+2 | yellow | 1.604% | 14565 | 27.6% | 3.3% | 27.9% | 27.9% |
| D+2 | orange | 0.170% | 1548 | 46.8% | 11.9% | 5.0% | 10.7% |
| D+2 | red | 0.000% | 0 | - | - | 0.0% | 0.0% |
| D+3 | none | 98.557% | 895215 | 1.2% | 0.1% | 72.2% | 67.4% |
| D+3 | yellow | 1.377% | 12510 | 29.5% | 4.1% | 25.6% | 30.4% |
| D+3 | orange | 0.066% | 595 | 51.3% | 6.2% | 2.1% | 2.2% |
| D+3 | red | 0.000% | 0 | - | - | 0.0% | 0.0% |

## Test set `test_2026` (out_of_season): test 2026-10-01..2026-11-30, fitted on 2023-06-01..2023-09-30, 2024-06-01..2024-09-30

Test issue days with an ECMWF file: 28 (2026-10-09..2026-11-15).

### Statements (pre-declared tests)

- D (today, mostly observed), heavy: domain: skilful; beats every baseline; reliable; discriminates (189 event pixel-days on 13 days); himalaya: too few events to conclude (95 event pixel-days on 9 days); western_ghats: too few events to conclude (79 event pixel-days on 4 days)
- D (today, mostly observed), very_heavy: domain: too few events to conclude (5 event pixel-days on 2 days); himalaya: too few events to conclude (0 event pixel-days on 0 days); western_ghats: too few events to conclude (2 event pixel-days on 2 days)
- D (today, mostly observed), extremely_heavy: domain: too few events to conclude (0 event pixel-days on 0 days); himalaya: too few events to conclude (0 event pixel-days on 0 days); western_ghats: too few events to conclude (0 event pixel-days on 0 days)
- D (today, mostly observed), p95: domain: skilful; beats every baseline; NOT reliable; discriminates (1832 event pixel-days on 23 days); himalaya: skilful; beats every baseline; NOT reliable; discriminates (938 event pixel-days on 16 days); western_ghats: skilful; beats every baseline; reliable; discriminates (724 event pixel-days on 16 days)
- D (today, mostly observed), p99: domain: skilful; beats every baseline; reliable; discriminates (303 event pixel-days on 15 days); himalaya: too few events to conclude (104 event pixel-days on 8 days); western_ghats: too few events to conclude (175 event pixel-days on 7 days)
- D+1, heavy: domain: NOT skilful; does not beat ens_mean, hres; NOT reliable; discriminates (308 event pixel-days on 11 days); himalaya: too few events to conclude (149 event pixel-days on 8 days); western_ghats: too few events to conclude (136 event pixel-days on 4 days)
- D+1, very_heavy: domain: too few events to conclude (13 event pixel-days on 2 days); himalaya: too few events to conclude (0 event pixel-days on 0 days); western_ghats: too few events to conclude (12 event pixel-days on 2 days)
- D+1, extremely_heavy: domain: too few events to conclude (0 event pixel-days on 0 days); himalaya: too few events to conclude (0 event pixel-days on 0 days); western_ghats: too few events to conclude (0 event pixel-days on 0 days)
- D+1, p95: domain: skilful; beats every baseline; reliable; discriminates (2241 event pixel-days on 23 days); himalaya: skilful; beats every baseline; NOT reliable; discriminates (1012 event pixel-days on 18 days); western_ghats: NOT skilful; beats every baseline; NOT reliable; discriminates (953 event pixel-days on 15 days)
- D+1, p99: domain: NOT skilful; beats every baseline; NOT reliable; discriminates (416 event pixel-days on 13 days); himalaya: too few events to conclude (129 event pixel-days on 7 days); western_ghats: too few events to conclude (243 event pixel-days on 7 days)
- D+2, heavy: domain: NOT skilful; does not beat ens_mean; NOT reliable; discriminates (395 event pixel-days on 11 days); himalaya: too few events to conclude (245 event pixel-days on 8 days); western_ghats: too few events to conclude (130 event pixel-days on 4 days)
- D+2, very_heavy: domain: too few events to conclude (39 event pixel-days on 3 days); himalaya: too few events to conclude (23 event pixel-days on 1 days); western_ghats: too few events to conclude (12 event pixel-days on 2 days)
- D+2, extremely_heavy: domain: too few events to conclude (0 event pixel-days on 0 days); himalaya: too few events to conclude (0 event pixel-days on 0 days); western_ghats: too few events to conclude (0 event pixel-days on 0 days)
- D+2, p95: domain: skilful; beats every baseline; reliable; discriminates (2462 event pixel-days on 22 days); himalaya: skilful; beats every baseline; NOT reliable; discriminates (1198 event pixel-days on 17 days); western_ghats: NOT skilful; beats every baseline; NOT reliable; discriminates (975 event pixel-days on 15 days)
- D+2, p99: domain: NOT skilful; beats every baseline; NOT reliable; discriminates (487 event pixel-days on 14 days); himalaya: too few events to conclude (228 event pixel-days on 7 days); western_ghats: too few events to conclude (221 event pixel-days on 7 days)
- D+3, heavy: domain: too few events to conclude (297 event pixel-days on 9 days); himalaya: too few events to conclude (175 event pixel-days on 8 days); western_ghats: too few events to conclude (105 event pixel-days on 2 days)
- D+3, very_heavy: domain: too few events to conclude (12 event pixel-days on 1 days); himalaya: too few events to conclude (0 event pixel-days on 0 days); western_ghats: too few events to conclude (11 event pixel-days on 1 days)
- D+3, extremely_heavy: domain: too few events to conclude (0 event pixel-days on 0 days); himalaya: too few events to conclude (0 event pixel-days on 0 days); western_ghats: too few events to conclude (0 event pixel-days on 0 days)
- D+3, p95: domain: skilful; beats every baseline; reliable; discriminates (2466 event pixel-days on 22 days); himalaya: skilful; beats every baseline; NOT reliable; discriminates (1217 event pixel-days on 17 days); western_ghats: NOT skilful; beats every baseline; NOT reliable; discriminates (950 event pixel-days on 14 days)
- D+3, p99: domain: NOT skilful; beats every baseline; NOT reliable; discriminates (428 event pixel-days on 13 days); himalaya: too few events to conclude (149 event pixel-days on 7 days); western_ghats: too few events to conclude (235 event pixel-days on 6 days)

### Headline (product = calibrated probability)

| lead | threshold | region | event pixel-days | event days | BSS (95% CI) | ROC area (CI) | REL/UNC | mean p / base rate | verdict |
|---|---|---|---|---|---|---|---|---|---|
| D (today, mostly observed) | heavy | domain | 189 | 13 | 0.281 [+0.100, +0.398] | 0.999 [+0.998, +1.000] | 0.035 | 0.83 | skilful; beats every baseline; reliable; discriminates |
| D (today, mostly observed) | heavy | himalaya | 95 | 9 | 0.224 [-0.171, +0.420] | 0.999 [+0.998, +1.000] | 0.040 | 0.72 | too few events to conclude |
| D (today, mostly observed) | heavy | western_ghats | 79 | 4 | 0.308 [+0.243, +0.579] | 0.999 [+0.997, +1.000] | 0.060 | 0.99 | too few events to conclude |
| D (today, mostly observed) | very_heavy | domain | 5 | 2 | 0.148 [+0.032, +0.728] | 1.000 [+0.999, +1.000] | 0.168 | 1.50 | too few events to conclude |
| D (today, mostly observed) | very_heavy | himalaya | 0 | 0 | 0.622 [-0.097, +0.996] | - - | - | - | too few events to conclude |
| D (today, mostly observed) | very_heavy | western_ghats | 2 | 2 | 0.031 [-0.310, +1.000] | 1.000 [+0.998, +1.000] | 0.082 | 1.68 | too few events to conclude |
| D (today, mostly observed) | extremely_heavy | domain | 0 | 0 | 1.000 [+0.999, +1.000] | - - | - | - | too few events to conclude |
| D (today, mostly observed) | extremely_heavy | himalaya | 0 | 0 | 1.000 [+1.000, +1.000] | - - | - | - | too few events to conclude |
| D (today, mostly observed) | extremely_heavy | western_ghats | 0 | 0 | 1.000 [+0.999, +1.000] | - - | - | - | too few events to conclude |
| D (today, mostly observed) | p95 | domain | 1832 | 23 | 0.549 [+0.458, +0.630] | 0.998 [+0.997, +0.999] | 0.045 | 0.75 | skilful; beats every baseline; NOT reliable; discriminates |
| D (today, mostly observed) | p95 | himalaya | 938 | 16 | 0.472 [+0.247, +0.567] | 0.998 [+0.997, +0.999] | 0.049 | 0.72 | skilful; beats every baseline; NOT reliable; discriminates |
| D (today, mostly observed) | p95 | western_ghats | 724 | 16 | 0.652 [+0.546, +0.774] | 0.998 [+0.997, +0.999] | 0.049 | 0.80 | skilful; beats every baseline; reliable; discriminates |
| D (today, mostly observed) | p99 | domain | 303 | 15 | 0.428 [+0.229, +0.540] | 0.999 [+0.999, +1.000] | 0.036 | 0.86 | skilful; beats every baseline; reliable; discriminates |
| D (today, mostly observed) | p99 | himalaya | 104 | 8 | 0.249 [-0.249, +0.427] | 0.999 [+0.998, +1.000] | 0.039 | 0.91 | too few events to conclude |
| D (today, mostly observed) | p99 | western_ghats | 175 | 7 | 0.534 [+0.316, +0.661] | 0.999 [+0.998, +1.000] | 0.063 | 0.84 | too few events to conclude |
| D+1 | heavy | domain | 308 | 11 | 0.026 [-0.001, +0.047] | 0.945 [+0.839, +0.974] | 0.009 | 0.75 | NOT skilful; does not beat ens_mean, hres; NOT reliable; discriminates |
| D+1 | heavy | himalaya | 149 | 8 | 0.045 [+0.016, +0.112] | 0.933 [+0.781, +0.976] | 0.006 | 0.65 | too few events to conclude |
| D+1 | heavy | western_ghats | 136 | 4 | 0.008 [-0.098, +0.078] | 0.954 [+0.909, +0.978] | 0.012 | 0.84 | too few events to conclude |
| D+1 | very_heavy | domain | 13 | 2 | 0.022 [+0.005, +0.707] | 0.986 [+0.969, +0.992] | 0.000 | 3.00 | too few events to conclude |
| D+1 | very_heavy | himalaya | 0 | 0 | 0.644 [+0.141, +0.975] | - - | - | - | too few events to conclude |
| D+1 | very_heavy | western_ghats | 12 | 2 | 0.002 [-0.047, +0.868] | 0.968 [+0.919, +0.986] | 0.000 | 1.29 | too few events to conclude |
| D+1 | extremely_heavy | domain | 0 | 0 | 0.901 [+0.788, +0.985] | - - | - | - | too few events to conclude |
| D+1 | extremely_heavy | himalaya | 0 | 0 | 0.890 [+0.724, +0.999] | - - | - | - | too few events to conclude |
| D+1 | extremely_heavy | western_ghats | 0 | 0 | 0.941 [+0.867, +0.996] | - - | - | - | too few events to conclude |
| D+1 | p95 | domain | 2241 | 23 | 0.150 [+0.069, +0.206] | 0.959 [+0.913, +0.978] | 0.013 | 0.92 | skilful; beats every baseline; reliable; discriminates |
| D+1 | p95 | himalaya | 1012 | 18 | 0.162 [+0.088, +0.209] | 0.949 [+0.841, +0.983] | 0.131 | 0.58 | skilful; beats every baseline; NOT reliable; discriminates |
| D+1 | p95 | western_ghats | 953 | 15 | 0.127 [-0.020, +0.241] | 0.959 [+0.936, +0.975] | 0.027 | 1.27 | NOT skilful; beats every baseline; NOT reliable; discriminates |
| D+1 | p99 | domain | 416 | 13 | 0.010 [-0.156, +0.067] | 0.973 [+0.934, +0.986] | 0.042 | 1.27 | NOT skilful; beats every baseline; NOT reliable; discriminates |
| D+1 | p99 | himalaya | 129 | 7 | -0.017 [-0.476, +0.073] | 0.958 [+0.830, +0.989] | 0.075 | 1.37 | too few events to conclude |
| D+1 | p99 | western_ghats | 243 | 7 | 0.018 [-0.203, +0.099] | 0.965 [+0.939, +0.985] | 0.035 | 1.17 | too few events to conclude |
| D+2 | heavy | domain | 395 | 11 | 0.012 [-0.044, +0.043] | 0.941 [+0.833, +0.972] | 0.014 | 0.69 | NOT skilful; does not beat ens_mean; NOT reliable; discriminates |
| D+2 | heavy | himalaya | 245 | 8 | 0.022 [+0.012, +0.151] | 0.948 [+0.771, +0.969] | 0.003 | 0.31 | too few events to conclude |
| D+2 | heavy | western_ghats | 130 | 4 | -0.003 [-0.421, +0.046] | 0.959 [+0.918, +0.981] | 0.035 | 1.34 | too few events to conclude |
| D+2 | very_heavy | domain | 39 | 3 | 0.004 [-0.054, +0.437] | 0.957 [+0.923, +0.997] | 0.000 | 1.27 | too few events to conclude |
| D+2 | very_heavy | himalaya | 23 | 1 | 0.012 [+0.001, +0.987] | 0.965 [+0.934, +0.975] | 0.000 | 0.80 | too few events to conclude |
| D+2 | very_heavy | western_ghats | 12 | 2 | -0.007 [-1.349, +0.297] | 0.974 [+0.845, +0.994] | 0.001 | 2.21 | too few events to conclude |
| D+2 | extremely_heavy | domain | 0 | 0 | 0.821 [+0.601, +0.969] | - - | - | - | too few events to conclude |
| D+2 | extremely_heavy | himalaya | 0 | 0 | 0.856 [+0.588, +0.999] | - - | - | - | too few events to conclude |
| D+2 | extremely_heavy | western_ghats | 0 | 0 | 0.761 [+0.410, +0.993] | - - | - | - | too few events to conclude |
| D+2 | p95 | domain | 2462 | 22 | 0.097 [+0.002, +0.179] | 0.953 [+0.921, +0.975] | 0.021 | 0.96 | skilful; beats every baseline; reliable; discriminates |
| D+2 | p95 | himalaya | 1198 | 17 | 0.109 [+0.064, +0.219] | 0.955 [+0.842, +0.978] | 0.037 | 0.44 | skilful; beats every baseline; NOT reliable; discriminates |
| D+2 | p95 | western_ghats | 975 | 15 | 0.080 [-0.095, +0.224] | 0.958 [+0.934, +0.973] | 0.072 | 1.54 | NOT skilful; beats every baseline; NOT reliable; discriminates |
| D+2 | p99 | domain | 487 | 14 | -0.028 [-0.407, +0.059] | 0.960 [+0.926, +0.983] | 0.068 | 1.34 | NOT skilful; beats every baseline; NOT reliable; discriminates |
| D+2 | p99 | himalaya | 228 | 7 | 0.003 [-0.318, +0.084] | 0.957 [+0.800, +0.978] | 0.022 | 0.75 | too few events to conclude |
| D+2 | p99 | western_ghats | 221 | 7 | -0.059 [-0.846, +0.095] | 0.963 [+0.930, +0.982] | 0.121 | 1.81 | too few events to conclude |
| D+3 | heavy | domain | 297 | 9 | 0.004 [-0.160, +0.043] | 0.917 [+0.727, +0.971] | 0.030 | 0.95 | too few events to conclude |
| D+3 | heavy | himalaya | 175 | 8 | 0.039 [+0.023, +0.111] | 0.909 [+0.686, +0.980] | 0.001 | 0.42 | too few events to conclude |
| D+3 | heavy | western_ghats | 105 | 2 | -0.052 [-7.717, +0.061] | 0.943 [+0.894, +0.973] | 0.076 | 1.76 | too few events to conclude |
| D+3 | very_heavy | domain | 12 | 1 | -0.013 [-2.717, +0.608] | 0.990 [+0.985, +0.996] | 0.020 | 4.80 | too few events to conclude |
| D+3 | very_heavy | himalaya | 0 | 0 | 0.690 [+0.209, +0.975] | - - | - | - | too few events to conclude |
| D+3 | very_heavy | western_ghats | 11 | 1 | -0.037 [-15.569, +0.607] | 0.974 [+0.945, +0.994] | 0.021 | 2.94 | too few events to conclude |
| D+3 | extremely_heavy | domain | 0 | 0 | 0.632 [+0.082, +0.943] | - - | - | - | too few events to conclude |
| D+3 | extremely_heavy | himalaya | 0 | 0 | 0.845 [+0.621, +0.998] | - - | - | - | too few events to conclude |
| D+3 | extremely_heavy | western_ghats | 0 | 0 | 0.080 [-1.778, +0.985] | - - | - | - | too few events to conclude |
| D+3 | p95 | domain | 2466 | 22 | 0.096 [+0.003, +0.155] | 0.949 [+0.911, +0.971] | 0.025 | 0.93 | skilful; beats every baseline; reliable; discriminates |
| D+3 | p95 | himalaya | 1217 | 17 | 0.103 [+0.076, +0.169] | 0.948 [+0.847, +0.978] | 0.103 | 0.39 | skilful; beats every baseline; NOT reliable; discriminates |
| D+3 | p95 | western_ghats | 950 | 14 | 0.083 [-0.146, +0.205] | 0.959 [+0.942, +0.975] | 0.062 | 1.57 | NOT skilful; beats every baseline; NOT reliable; discriminates |
| D+3 | p99 | domain | 428 | 13 | -0.008 [-0.269, +0.064] | 0.964 [+0.912, +0.985] | 0.053 | 1.48 | NOT skilful; beats every baseline; NOT reliable; discriminates |
| D+3 | p99 | himalaya | 149 | 7 | 0.029 [-0.019, +0.070] | 0.949 [+0.824, +0.992] | 0.015 | 1.03 | too few events to conclude |
| D+3 | p99 | western_ghats | 235 | 6 | -0.033 [-1.032, +0.082] | 0.958 [+0.930, +0.983] | 0.086 | 1.69 | too few events to conclude |

### Against the deterministic baselines and the raw ensemble (domain)

| lead | threshold | BS product | BS climatology | BS raw ensemble | baseline: BS, diff (95% CI), hit rate, FAR |
|---|---|---|---|---|---|
| D (today, mostly observed) | heavy | 0.00049 | 0.00069 | - | observed: 0.00074, -0.00025 [-0.00056, -0.00004], 0.455, 0.557 |
| D (today, mostly observed) | very_heavy | 0.00002 | 0.00002 | - | observed: 0.00002, -0.00000 [-0.00000, +0.00000], 0.200, 0.500 |
| D (today, mostly observed) | extremely_heavy | 0.00000 | 0.00000 | - | observed: 0.00000, +0.00000 [+0.00000, +0.00000], -, - |
| D (today, mostly observed) | p95 | 0.00287 | 0.00636 | - | observed: 0.00392, -0.00106 [-0.00183, -0.00039], 0.731, 0.317 |
| D (today, mostly observed) | p99 | 0.00061 | 0.00107 | - | observed: 0.00093, -0.00032 [-0.00062, -0.00009], 0.584, 0.438 |
| D+1 | heavy | 0.00107 | 0.00110 | 0.00110 | gfs: 0.00165, -0.00057 [-0.00144, -0.00006], 0.075, 0.888; ens_mean: 0.00109, -0.00001 [-0.00005, +0.00002], 0.000, -; hres: 0.00114, -0.00007 [-0.00016, +0.00000], 0.000, 1.000 |
| D+1 | very_heavy | 0.00005 | 0.00005 | 0.00005 | gfs: 0.00009, -0.00004 [-0.00013, +0.00000], 0.000, 1.000; ens_mean: 0.00005, +0.00000 [-0.00000, +0.00000], 0.000, -; hres: 0.00005, +0.00000 [-0.00000, +0.00000], 0.000, - |
| D+1 | extremely_heavy | 0.00000 | 0.00000 | 0.00000 | gfs: 0.00000, +0.00000 [+0.00000, +0.00000], -, -; ens_mean: 0.00000, +0.00000 [+0.00000, +0.00000], -, -; hres: 0.00000, +0.00000 [+0.00000, +0.00000], -, - |
| D+1 | p95 | 0.00658 | 0.00775 | 0.00697 | gfs: 0.01216, -0.00558 [-0.00877, -0.00309], 0.237, 0.767; ens_mean: 0.00896, -0.00237 [-0.00426, -0.00070], 0.267, 0.600; hres: 0.00979, -0.00320 [-0.00603, -0.00089], 0.301, 0.642 |
| D+1 | p99 | 0.00146 | 0.00147 | 0.00188 | gfs: 0.00304, -0.00159 [-0.00353, -0.00029], 0.221, 0.854; ens_mean: 0.00219, -0.00073 [-0.00196, -0.00005], 0.017, 0.968; hres: 0.00238, -0.00092 [-0.00227, -0.00015], 0.067, 0.911 |
| D+2 | heavy | 0.00145 | 0.00147 | 0.00156 | gfs: 0.00203, -0.00058 [-0.00132, -0.00000], 0.086, 0.850; ens_mean: 0.00145, -0.00000 [-0.00005, +0.00004], 0.000, -; hres: 0.00168, -0.00023 [-0.00046, -0.00005], 0.000, 1.000 |
| D+2 | very_heavy | 0.00014 | 0.00014 | 0.00014 | gfs: 0.00021, -0.00007 [-0.00021, +0.00000], 0.000, 1.000; ens_mean: 0.00014, +0.00000 [-0.00000, +0.00000], 0.000, -; hres: 0.00014, +0.00000 [-0.00000, +0.00000], 0.000, - |
| D+2 | extremely_heavy | 0.00000 | 0.00000 | 0.00000 | gfs: 0.00000, +0.00000 [+0.00000, +0.00000], -, -; ens_mean: 0.00000, +0.00000 [+0.00000, +0.00000], -, -; hres: 0.00000, +0.00000 [+0.00000, +0.00000], -, - |
| D+2 | p95 | 0.00799 | 0.00885 | 0.00933 | gfs: 0.01375, -0.00575 [-0.00932, -0.00280], 0.246, 0.757; ens_mean: 0.01336, -0.00537 [-0.00894, -0.00201], 0.255, 0.742; hres: 0.01398, -0.00598 [-0.00982, -0.00246], 0.320, 0.731 |
| D+2 | p99 | 0.00185 | 0.00180 | 0.00239 | gfs: 0.00374, -0.00189 [-0.00388, -0.00041], 0.138, 0.900; ens_mean: 0.00272, -0.00087 [-0.00188, -0.00018], 0.012, 0.978; hres: 0.00324, -0.00139 [-0.00262, -0.00043], 0.016, 0.981 |
| D+3 | heavy | 0.00115 | 0.00116 | 0.00134 | gfs: 0.00183, -0.00068 [-0.00129, -0.00017], 0.000, 1.000; ens_mean: 0.00120, -0.00005 [-0.00015, +0.00002], 0.000, 1.000; hres: 0.00133, -0.00018 [-0.00042, -0.00002], 0.000, 1.000 |
| D+3 | very_heavy | 0.00005 | 0.00005 | 0.00006 | gfs: 0.00008, -0.00004 [-0.00012, +0.00001], 0.000, 1.000; ens_mean: 0.00005, +0.00000 [-0.00000, +0.00001], 0.000, -; hres: 0.00005, +0.00000 [-0.00000, +0.00001], 0.000, - |
| D+3 | extremely_heavy | 0.00000 | 0.00000 | 0.00000 | gfs: 0.00000, +0.00000 [+0.00000, +0.00000], -, -; ens_mean: 0.00000, +0.00000 [+0.00000, +0.00000], -, -; hres: 0.00000, +0.00000 [+0.00000, +0.00000], -, - |
| D+3 | p95 | 0.00831 | 0.00919 | 0.00916 | gfs: 0.01530, -0.00698 [-0.01031, -0.00356], 0.197, 0.806; ens_mean: 0.01428, -0.00597 [-0.01065, -0.00241], 0.253, 0.751; hres: 0.01508, -0.00676 [-0.01126, -0.00293], 0.292, 0.752 |
| D+3 | p99 | 0.00166 | 0.00165 | 0.00218 | gfs: 0.00358, -0.00192 [-0.00313, -0.00078], 0.019, 0.985; ens_mean: 0.00245, -0.00078 [-0.00166, -0.00016], 0.014, 0.973; hres: 0.00315, -0.00149 [-0.00313, -0.00035], 0.014, 0.985 |

### Raw quantile probability (uncalibrated) beside the product (domain)

| lead | threshold | raw BSS (CI) | raw ROC area | raw mean p / base rate | calibrated BSS |
|---|---|---|---|---|---|
| D+1 | heavy | 0.005 [-0.056, +0.039] | 0.794 | 0.29 | 0.026 |
| D+1 | very_heavy | 0.031 [+0.008, +0.995] | 0.497 | 0.28 | 0.022 |
| D+1 | extremely_heavy | 0.989 [+0.964, +1.000] | - | - | 0.901 |
| D+1 | p95 | 0.101 [-0.202, +0.268] | 0.916 | 0.92 | 0.150 |
| D+1 | p99 | -0.278 [-1.709, +0.061] | 0.909 | 1.01 | 0.010 |
| D+2 | heavy | -0.064 [-0.237, +0.007] | 0.847 | 0.54 | 0.012 |
| D+2 | very_heavy | -0.001 [-0.071, +0.392] | 0.533 | 0.43 | 0.004 |
| D+2 | extremely_heavy | 0.817 [+0.466, +1.000] | - | - | 0.821 |
| D+2 | p95 | -0.054 [-0.390, +0.127] | 0.933 | 1.19 | 0.097 |
| D+2 | p99 | -0.329 [-1.788, -0.044] | 0.862 | 1.33 | -0.028 |
| D+3 | heavy | -0.162 [-1.062, +0.007] | 0.873 | 1.40 | 0.004 |
| D+3 | very_heavy | -0.304 [-20.243, +0.007] | 0.531 | 4.92 | -0.013 |
| D+3 | extremely_heavy | -4.505 [-14.188, +0.902] | - | - | 0.632 |
| D+3 | p95 | 0.004 [-0.326, +0.180] | 0.924 | 1.30 | 0.096 |
| D+3 | p99 | -0.320 [-1.445, -0.013] | 0.928 | 1.88 | -0.008 |

### Reliability (domain)

Lead D+1, heavy, domain:

| probability bin | pixel-days | mean probability | observed frequency |
|---|---|---|---|
| 0.00-0.05 | 283383 | 0.0007 | 0.0011 |
| 0.05-0.10 | 370 | 0.0691 | 0.0081 |
| 0.10-0.20 | 97 | 0.1236 | 0.0103 |

Lead D+1, very_heavy, domain:

| probability bin | pixel-days | mean probability | observed frequency |
|---|---|---|---|
| 0.00-0.05 | 283850 | 0.0001 | 0.0000 |

Lead D+1, p95, domain:

| probability bin | pixel-days | mean probability | observed frequency |
|---|---|---|---|
| 0.00-0.05 | 275003 | 0.0022 | 0.0020 |
| 0.05-0.10 | 3377 | 0.0716 | 0.0962 |
| 0.10-0.20 | 3095 | 0.1412 | 0.2032 |
| 0.20-0.30 | 1164 | 0.2434 | 0.2577 |
| 0.30-0.40 | 699 | 0.3448 | 0.3534 |
| 0.40-0.50 | 310 | 0.4437 | 0.3290 |
| 0.50-0.60 | 118 | 0.5450 | 0.3051 |
| 0.60-0.70 | 66 | 0.6465 | 0.5455 |
| 0.70-0.80 | 18 | 0.7221 | 0.3333 |

Lead D (today, mostly observed), heavy, domain:

| probability bin | pixel-days | mean probability | observed frequency |
|---|---|---|---|
| 0.00-0.05 | 283296 | 0.0001 | 0.0001 |
| 0.05-0.10 | 181 | 0.0712 | 0.1436 |
| 0.10-0.20 | 151 | 0.1434 | 0.2384 |
| 0.20-0.30 | 76 | 0.2458 | 0.2500 |
| 0.30-0.40 | 39 | 0.3533 | 0.3846 |
| 0.40-0.50 | 32 | 0.4489 | 0.5938 |
| 0.50-0.60 | 22 | 0.5434 | 0.3636 |
| 0.60-0.70 | 20 | 0.6386 | 0.4000 |
| 0.70-0.80 | 19 | 0.7534 | 0.4737 |
| 0.80-0.90 | 11 | 0.8501 | 0.7273 |
| 0.90-1.00 | 3 | 0.9261 | 1.0000 |

### Warning levels on this test set (domain)

| lead | level | share of pixel-days | pixel-days | observed >= heavy | observed >= very heavy | share of heavy events | share of very heavy events |
|---|---|---|---|---|---|---|---|
| D (today, mostly observed) | none | 99.573% | 282639 | 0.0% | 0.0% | 18.0% | 0.0% |
| D (today, mostly observed) | yellow | 0.342% | 970 | 10.9% | 0.1% | 56.1% | 20.0% |
| D (today, mostly observed) | orange | 0.085% | 241 | 20.3% | 1.7% | 25.9% | 80.0% |
| D (today, mostly observed) | red | 0.000% | 0 | - | - | 0.0% | 0.0% |
| D+1 | none | 99.820% | 283338 | 0.1% | 0.0% | 100.0% | 100.0% |
| D+1 | yellow | 0.172% | 488 | 0.0% | 0.0% | 0.0% | 0.0% |
| D+1 | orange | 0.008% | 24 | 0.0% | 0.0% | 0.0% | 0.0% |
| D+1 | red | 0.000% | 0 | - | - | 0.0% | 0.0% |
| D+2 | none | 99.746% | 271803 | 0.1% | 0.0% | 100.0% | 100.0% |
| D+2 | yellow | 0.239% | 650 | 0.0% | 0.0% | 0.0% | 0.0% |
| D+2 | orange | 0.016% | 43 | 0.0% | 0.0% | 0.0% | 0.0% |
| D+2 | red | 0.000% | 0 | - | - | 0.0% | 0.0% |
| D+3 | none | 99.825% | 260684 | 0.1% | 0.0% | 100.0% | 100.0% |
| D+3 | yellow | 0.170% | 444 | 0.0% | 0.0% | 0.0% | 0.0% |
| D+3 | orange | 0.005% | 14 | 0.0% | 0.0% | 0.0% | 0.0% |
| D+3 | red | 0.000% | 0 | - | - | 0.0% | 0.0% |

## Shipped calibration (fitted on June-September 2023 + 2024)

File: `data/processed/rainwarn/calibration_shipped.json`. Expected level frequency = the in-sample share on its fitting days:

| lead | level | share of pixel-days | pixel-days | observed >= heavy | observed >= very heavy | share of heavy events | share of very heavy events |
|---|---|---|---|---|---|---|---|
| D (today, mostly observed) | none | 92.521% | 1166041 | 0.2% | 0.0% | 5.0% | 0.7% |
| D (today, mostly observed) | yellow | 4.263% | 53722 | 11.2% | 0.2% | 15.8% | 1.1% |
| D (today, mostly observed) | orange | 2.695% | 33965 | 69.8% | 9.1% | 62.1% | 36.3% |
| D (today, mostly observed) | red | 0.521% | 6566 | 98.9% | 80.2% | 17.0% | 61.9% |
| D+1 | none | 97.160% | 2228371 | 1.3% | 0.2% | 56.5% | 38.4% |
| D+1 | yellow | 2.416% | 55420 | 28.5% | 6.5% | 30.7% | 34.8% |
| D+1 | orange | 0.415% | 9516 | 67.5% | 27.8% | 12.5% | 25.5% |
| D+1 | red | 0.009% | 201 | 99.5% | 68.7% | 0.4% | 1.3% |
| D+2 | none | 97.470% | 2235474 | 1.4% | 0.2% | 61.6% | 43.0% |
| D+2 | yellow | 2.216% | 50815 | 29.4% | 7.4% | 29.4% | 36.7% |
| D+2 | orange | 0.309% | 7094 | 63.2% | 28.2% | 8.8% | 19.6% |
| D+2 | red | 0.005% | 125 | 57.6% | 51.2% | 0.1% | 0.6% |
| D+3 | none | 97.790% | 2242811 | 1.5% | 0.2% | 66.4% | 48.9% |
| D+3 | yellow | 2.001% | 45893 | 31.2% | 8.6% | 28.4% | 39.1% |
| D+3 | orange | 0.203% | 4666 | 55.2% | 24.8% | 5.1% | 11.5% |
| D+3 | red | 0.006% | 138 | 49.3% | 37.0% | 0.1% | 0.5% |

Chosen neighbourhood radius per lead and threshold:

| lead | threshold | radius (pixels) | fitting pixel-days | events | log loss by radius |
|---|---|---|---|---|---|
| D (today, mostly observed) | heavy | 2 | 1260294 | 38153 | r0: 0.03152, r1: 0.03136, r2: 0.03133, r3: 0.03134 |
| D (today, mostly observed) | very_heavy | 2 | 1260294 | 8499 | r0: 0.00977, r1: 0.00970, r2: 0.00969, r3: 0.00970 |
| D (today, mostly observed) | extremely_heavy | 3 | 1260294 | 691 | r0: 0.00116, r1: 0.00114, r2: 0.00113, r3: 0.00113 |
| D (today, mostly observed) | p95 | 3 | 1260294 | 84593 | r0: 0.07115, r1: 0.07088, r2: 0.07081, r3: 0.07079 |
| D (today, mostly observed) | p99 | 3 | 1260294 | 23349 | r0: 0.02511, r1: 0.02506, r2: 0.02506, r3: 0.02505 |
| D+1 | heavy | 3 | 2293508 | 51526 | r0: 0.07296, r1: 0.07251, r2: 0.07205, r3: 0.07169 |
| D+1 | very_heavy | 3 | 2293508 | 10412 | r0: 0.01953, r1: 0.01937, r2: 0.01919, r3: 0.01905 |
| D+1 | extremely_heavy | 3 | 2293508 | 807 | r0: 0.00221, r1: 0.00220, r2: 0.00217, r3: 0.00215 |
| D+1 | p95 | 3 | 2293508 | 124872 | r0: 0.16540, r1: 0.16452, r2: 0.16372, r3: 0.16309 |
| D+1 | p99 | 3 | 2293508 | 31543 | r0: 0.05654, r1: 0.05621, r2: 0.05587, r3: 0.05561 |
| D+2 | heavy | 3 | 2293508 | 50842 | r0: 0.07448, r1: 0.07410, r2: 0.07368, r3: 0.07335 |
| D+2 | very_heavy | 3 | 2293508 | 10186 | r0: 0.01945, r1: 0.01929, r2: 0.01912, r3: 0.01899 |
| D+2 | extremely_heavy | 3 | 2293508 | 773 | r0: 0.00207, r1: 0.00205, r2: 0.00202, r3: 0.00201 |
| D+2 | p95 | 3 | 2293508 | 123832 | r0: 0.16942, r1: 0.16872, r2: 0.16798, r3: 0.16740 |
| D+2 | p99 | 3 | 2293508 | 30912 | r0: 0.05709, r1: 0.05681, r2: 0.05651, r3: 0.05629 |
| D+3 | heavy | 3 | 2293508 | 50381 | r0: 0.07623, r1: 0.07596, r2: 0.07565, r3: 0.07537 |
| D+3 | very_heavy | 3 | 2293508 | 10078 | r0: 0.02000, r1: 0.01989, r2: 0.01977, r3: 0.01967 |
| D+3 | extremely_heavy | 3 | 2293508 | 763 | r0: 0.00218, r1: 0.00216, r2: 0.00214, r3: 0.00212 |
| D+3 | p95 | 3 | 2293508 | 123003 | r0: 0.17352, r1: 0.17297, r2: 0.17238, r3: 0.17191 |
| D+3 | p99 | 3 | 2293508 | 30362 | r0: 0.05825, r1: 0.05805, r2: 0.05782, r3: 0.05764 |

## How much of the D (today) skill is observation, not forecast

At the run time (05:30 UTC of D) IMD day D has ended. 21 of its 24 hours are already observed by IMERG Early (UTC day D-1); only 00-03 UTC of D comes from a forecast, the GFS 00Z 0-3 h tail (in the archive the tail is persistence of D-1, so the study's lead 0 contains no forecast at all). Lead 0 is therefore a calibrated observation of rain that has already fallen, not a forecast. Its truth, IMERG Late, is the same satellite algorithm as Early run later with more input, so the two agree far better than either agrees with rain gauges. The table separates the parts: `observed 0/1` is the Early total thresholded (no calibration); the product adds the logistic map from Early to Late; `D+1` is the first real forecast; `IMD` scores the lead-0 product against the IMD gauge grid instead (sample-climatology reference).

| test set | threshold | lead-0 days scored | BSS observed 0/1 | BSS lead-0 product | BSS D+1 product | lead-0 BSS vs IMD (CI) | lead-0 ROC area vs IMD |
|---|---|---|---|---|---|---|---|
| test_2024 | heavy | 76 of 122 | 0.536 | 0.680 | 0.180 | -0.110 [-0.238, -0.002] | 0.869 |
| test_2024 | very_heavy | 76 of 122 | 0.403 | 0.595 | 0.100 | -0.428 [-0.693, -0.246] | 0.859 |
| test_2024 | extremely_heavy | 76 of 122 | 0.060 | 0.442 | 0.008 | -0.263 [-0.610, -0.093] | 0.830 |
| test_2024 | p95 | 76 of 122 | 0.523 | 0.671 | 0.131 | - - | - |
| test_2024 | p99 | 76 of 122 | 0.420 | 0.610 | 0.088 | - - | - |
| test_2023 | heavy | 35 of 80 | 0.556 | 0.676 | 0.130 | 0.181 [+0.073, +0.261] | 0.917 |
| test_2023 | very_heavy | 35 of 80 | 0.279 | 0.466 | 0.017 | 0.057 [-0.033, +0.115] | 0.928 |
| test_2023 | extremely_heavy | 35 of 80 | 0.401 | 0.414 | -0.077 | -0.002 [-0.025, +0.007] | 0.718 |
| test_2023 | p95 | 35 of 80 | 0.579 | 0.685 | 0.114 | - - | - |
| test_2023 | p99 | 35 of 80 | 0.416 | 0.561 | 0.059 | - - | - |
| test_2026 | heavy | 25 of 28 | -0.083 | 0.281 | 0.026 | - - | - |
| test_2026 | very_heavy | 25 of 28 | 0.099 | 0.148 | 0.022 | - - | - |
| test_2026 | p95 | 25 of 28 | 0.383 | 0.549 | 0.150 | - - | - |
| test_2026 | p99 | 25 of 28 | 0.129 | 0.428 | 0.010 | - - | - |

Reading: for heavy, very heavy and the two percentiles in the monsoon sets, most of the lead-0 Brier skill is already in the observed total thresholded; for the rarer rows the calibration, which learns how Early totals map onto Late totals, adds most of it. None of it is forecast skill, and against the independent IMD grid the lead-0 skill is much smaller and in some rows below zero. Lead-0 days without IMERG Early in the local store (16 August to 30 September of 2023 and 2024 are not in it) are not scored; the column gives the count.

## The rows marked NOT reliable at D+1..D+3

`mean p / base rate` below 1 means the probabilities are too low on average (the event happens more often than forecast), above 1 too high. Each calibration is fitted on one season and tested on the other, so the two monsoon test sets swap roles:

| lead | threshold | test set | fitting base rate | test base rate | mean p / base rate | REL/UNC | fitting events (pixel-days) | BSS (CI) |
|---|---|---|---|---|---|---|---|---|
| D+1 | very_heavy | test_2024 | 0.193% | 0.625% | 0.62 | 0.027 | 1757 | 0.100 [+0.068, +0.130] |
| D+1 | very_heavy | test_2023 | 0.625% | 0.193% | 1.87 | 0.027 | 8655 | 0.017 [-0.044, +0.086] |
| D+1 | extremely_heavy | test_2024 | 0.003% | 0.056% | 0.14 | 0.001 | 30 | 0.008 [+0.004, +0.011] |
| D+1 | extremely_heavy | test_2023 | 0.056% | 0.003% | 8.59 | 0.055 | 777 | -0.077 [-0.184, -0.019] |
| D+1 | heavy | test_2024 | 1.611% | 2.663% | 0.94 | 0.003 | 14632 | 0.180 [+0.135, +0.224] |
| D+1 | heavy | test_2023 | 2.663% | 1.611% | 1.18 | 0.006 | 36894 | 0.130 [+0.086, +0.174] |
| D+2 | very_heavy | test_2024 | 0.189% | 0.611% | 0.58 | 0.016 | 1720 | 0.058 [+0.036, +0.080] |
| D+2 | very_heavy | test_2023 | 0.611% | 0.189% | 1.96 | 0.031 | 8466 | -0.009 [-0.078, +0.043] |
| D+2 | extremely_heavy | test_2024 | 0.003% | 0.054% | 0.11 | 0.000 | 30 | 0.004 [+0.001, +0.006] |
| D+2 | extremely_heavy | test_2023 | 0.054% | 0.003% | 8.93 | 0.055 | 743 | -0.100 [-0.547, -0.021] |
| D+2 | heavy | test_2024 | 1.586% | 2.631% | 0.95 | 0.001 | 14404 | 0.133 [+0.093, +0.170] |
| D+2 | heavy | test_2023 | 2.631% | 1.586% | 1.21 | 0.004 | 36438 | 0.098 [+0.052, +0.134] |
| D+3 | very_heavy | test_2024 | 0.187% | 0.605% | 0.52 | 0.016 | 1698 | 0.045 [+0.025, +0.065] |
| D+3 | very_heavy | test_2023 | 0.605% | 0.187% | 1.95 | 0.025 | 8380 | -0.010 [-0.058, +0.023] |
| D+3 | extremely_heavy | test_2024 | 0.003% | 0.053% | 0.11 | 0.000 | 30 | 0.002 [-0.000, +0.005] |
| D+3 | extremely_heavy | test_2023 | 0.053% | 0.003% | 8.70 | 0.008 | 733 | -0.034 [-0.175, -0.003] |
| D+3 | heavy | test_2024 | 1.583% | 2.599% | 0.91 | 0.001 | 14381 | 0.111 [+0.074, +0.143] |
| D+3 | heavy | test_2023 | 2.599% | 1.583% | 1.18 | 0.004 | 36000 | 0.087 [+0.053, +0.116] |

What it means in practice: the shape of the calibration holds (REL/UNC stays small and the ROC area high, so higher probabilities do mark wetter pixels), but its level is set by how often very heavy and extremely heavy rain happened in the one fitting season. The two monsoon seasons differ by several times in that frequency, so a map fitted on the drier season under-warns in the wetter one (orange and red issued too rarely) and the reverse. For extremely heavy rain the fitting season can hold only tens of event pixel-days on a handful of days, so that calibration is barely constrained.

Is a recalibration on more training days the fix? Partly. Fitting on both seasons (the shipped calibration) averages the two base rates and gives the extremely heavy fit several times more events, which removes the worst of the under- and over-forecasting seen here; that is expected, not shown, because no third monsoon season is left to test it on. It cannot remove the season-to-season swing itself: no fixed map knows in advance whether a monsoon will be wet. That needs either more seasons (so the average is a good one and the swing is measured) or a predictor that carries the season's state (for example the observed rain of the past weeks), and a third season (June-September 2025 from the open ECMWF buckets) to test it. Until then the very heavy and extremely heavy probabilities at D+1..D+3 should be read as a ranking of where the risk is highest, not as calibrated frequencies.

## What this can and cannot conclude

- The truth is IMERG Late, a satellite estimate. Skill against IMERG is not skill against rain gauges; the IMD grid is
  shown as a second opinion at 0.25 degree, with the sample base rate as reference, and its day convention in the local
  store is marked unconfirmed.
- Lead 0 is fitted on IMERG Early against IMERG Late. The two runs share the algorithm and most of the microwave input,
  so the lead-0 scores against Late are optimistic; the IMD second opinion is the independent check of lead 0.
- Pixel-days are not independent: rain on one day covers many neighbouring pixels. The intervals resample whole days,
  and a statement needs a minimum number of distinct event days, so a large pixel-day count alone does not make a
  conclusion.
- The ensemble archive is two monsoon seasons; the 2026 set is October-November, where heavy rain is rare. A threshold
  marked "too few events" carries no conclusion, in either direction.
- The ensemble is summarised by four stored statistics; the raw probability is rebuilt from them, not counted from
  members.

## What a longer archive would add

The ECMWF open-data buckets hold every ensemble member from 2023 on, anonymously. Fetching June-September 2025 (an
existing command, `ingest.ecmwf.fetch_archive`) would add a third monsoon season, so the calibration could be fitted on
two seasons and tested on a third; adding the non-monsoon months would allow a seasonal calibration; storing the member
fraction above each threshold in the day file would replace the rebuilt CDF with the real one. Extremely heavy days
per region would then be numerous enough for a statement.

## Wiring into the daily run (branch only; not done)

`configs/live_run.yaml` carries `rain_warnings.enabled: false`. To switch it on, the live run would call
`aetherguard.rainwarn.product.run_day` for day D after its landslide tables are written, with the run directory as
both input and output and the shipped calibration, inside a guard that records a failure in `run.json` without failing
the run. It reads only `features_D0.parquet` and the ECMWF day file that the run has already fetched, adds
`rain_warnings.parquet` and `rain_warnings.md`, and changes no landslide table (a test checks the bytes);
`GET /api/rain-warnings` then serves it. That switch is the lead's step after the user's yes.

