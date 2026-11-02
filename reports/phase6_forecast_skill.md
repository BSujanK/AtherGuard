# Forecast-day skill (GFS) and interval widening

Spec section 5.3. Forecast days D+1..D+3 of the daily run use observed IMERG rain through D and the GFS 00Z IMD-day totals after D. This report measures how far GFS rain is from IMERG Late and how far the resulting v3 risk is from the risk of the observed rain; the second gap sets the widening of the forecast-day intervals.

## Rain skill: GFS against IMERG Late

June-September 2021-2024. 488 issue days (00Z cycle), 0 without an archive file. Lead k is IMD day D+k; the observed IMD day is 0.875 UTC(d-1) + 0.125 UTC(d) of IMERG Late. Statistics pool every pixel-day of the group; pairs with a missing value are dropped and counted. `domain` is every pixel of the 0.1 degree domain grid (sea included); `himalaya` and `western_ghats` are the pixels with at least 2 of their 4 cells in that region of `cell_regions`.

### Headline

| group | lead | days | n | bias (mm) | MAE (mm) | correlation | hit rate >=50 | FAR >=50 | hit rate >=100 | FAR >=100 |
|---|---|---|---|---|---|---|---|---|---|---|
| domain | 1 | 488 | 35526400 | -0.544 | 7.468 | 0.502 | 0.164 | 0.617 | 0.072 | 0.811 |
| domain | 2 | 488 | 35526400 | -0.553 | 7.868 | 0.454 | 0.143 | 0.672 | 0.055 | 0.845 |
| domain | 3 | 488 | 35526400 | -0.405 | 8.238 | 0.416 | 0.133 | 0.711 | 0.044 | 0.886 |
| himalaya | 1 | 488 | 8523896 | 0.195 | 7.172 | 0.474 | 0.206 | 0.719 | 0.125 | 0.872 |
| himalaya | 2 | 488 | 8523896 | 0.381 | 7.558 | 0.425 | 0.165 | 0.778 | 0.101 | 0.887 |
| himalaya | 3 | 488 | 8523896 | 0.282 | 7.848 | 0.373 | 0.123 | 0.818 | 0.068 | 0.910 |
| western_ghats | 1 | 488 | 2675216 | -0.980 | 7.118 | 0.539 | 0.257 | 0.594 | 0.107 | 0.820 |
| western_ghats | 2 | 488 | 2675216 | -1.970 | 7.306 | 0.485 | 0.197 | 0.615 | 0.076 | 0.836 |
| western_ghats | 3 | 488 | 2675216 | -2.176 | 7.645 | 0.432 | 0.161 | 0.669 | 0.052 | 0.874 |

Event counts (pixel-days): hits / misses / false alarms.

| group | lead | >=50 mm | >=100 mm |
|---|---|---|---|
| domain | 1 | 193075 / 983317 / 311073 | 16262 / 209926 / 69829 |
| domain | 2 | 168196 / 1010676 / 344864 | 12557 / 213727 / 68660 |
| domain | 3 | 157078 / 1022453 / 385592 | 10055 / 216348 / 78322 |
| himalaya | 1 | 40128 / 154792 / 102923 | 3448 / 24148 / 23524 |
| himalaya | 2 | 32196 / 162922 / 112659 | 2776 / 24830 / 21848 |
| himalaya | 3 | 23974 / 171668 / 107619 | 1879 / 25762 / 18891 |
| western_ghats | 1 | 21596 / 62575 / 31607 | 1705 / 14278 / 7784 |
| western_ghats | 2 | 16464 / 66976 / 26286 | 1189 / 14406 / 6051 |
| western_ghats | 3 | 13264 / 68975 / 26839 | 794 / 14542 / 5526 |

### Forecast / observed by observed-rain bin: domain

The ratio is taken where the observed rain is at least 0.1 mm; a forecast of no rain counts as 0.

| lead | bin (mm) | n | mean obs | mean fcst | bias | MAE | ratio n | p10 | p25 | p50 | p75 | p90 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | <1 | 14619092 | 0.22 | 2.58 | 2.36 | 2.44 | 6748109 | 0.05 | 0.96 | 4.85 | 13.27 | 27.85 |
| 1 | 1-10 | 12689072 | 4.10 | 7.75 | 3.65 | 5.61 | 12689072 | 0.14 | 0.57 | 1.48 | 3.09 | 5.66 |
| 1 | 10-25 | 4741705 | 16.00 | 14.07 | -1.93 | 9.80 | 4741705 | 0.14 | 0.35 | 0.69 | 1.20 | 1.88 |
| 1 | 25-50 | 2300139 | 34.79 | 20.63 | -14.16 | 20.52 | 2300139 | 0.12 | 0.25 | 0.46 | 0.76 | 1.20 |
| 1 | 50-100 | 950204 | 67.32 | 29.61 | -37.71 | 43.52 | 950204 | 0.10 | 0.19 | 0.33 | 0.55 | 0.90 |
| 1 | >=100 | 226188 | 141.45 | 41.42 | -100.03 | 103.71 | 226188 | 0.07 | 0.12 | 0.22 | 0.38 | 0.65 |
| 2 | <1 | 14609405 | 0.22 | 2.84 | 2.62 | 2.71 | 6749100 | 0.04 | 0.88 | 4.91 | 14.22 | 30.76 |
| 2 | 1-10 | 12683152 | 4.10 | 7.92 | 3.82 | 5.91 | 12683152 | 0.11 | 0.51 | 1.44 | 3.16 | 5.95 |
| 2 | 10-25 | 4748935 | 16.00 | 13.88 | -2.12 | 10.33 | 4748935 | 0.11 | 0.31 | 0.65 | 1.18 | 1.91 |
| 2 | 25-50 | 2306036 | 34.79 | 19.91 | -14.89 | 21.26 | 2306036 | 0.10 | 0.22 | 0.43 | 0.75 | 1.20 |
| 2 | 50-100 | 952588 | 67.32 | 27.26 | -40.06 | 44.74 | 952588 | 0.08 | 0.16 | 0.30 | 0.52 | 0.85 |
| 2 | >=100 | 226284 | 141.36 | 36.39 | -104.97 | 107.42 | 226284 | 0.06 | 0.11 | 0.19 | 0.34 | 0.56 |
| 3 | <1 | 14584047 | 0.22 | 3.14 | 2.92 | 3.01 | 6747059 | 0.05 | 0.95 | 5.27 | 15.39 | 33.72 |
| 3 | 1-10 | 12694112 | 4.10 | 8.16 | 4.06 | 6.20 | 12694112 | 0.10 | 0.50 | 1.45 | 3.25 | 6.25 |
| 3 | 10-25 | 4758458 | 16.00 | 13.92 | -2.08 | 10.70 | 4758458 | 0.10 | 0.29 | 0.64 | 1.18 | 1.94 |
| 3 | 25-50 | 2310252 | 34.79 | 19.63 | -15.16 | 21.92 | 2310252 | 0.08 | 0.20 | 0.41 | 0.73 | 1.21 |
| 3 | 50-100 | 953128 | 67.32 | 26.21 | -41.11 | 45.78 | 953128 | 0.07 | 0.15 | 0.28 | 0.50 | 0.83 |
| 3 | >=100 | 226403 | 141.20 | 33.40 | -107.81 | 109.85 | 226403 | 0.05 | 0.09 | 0.18 | 0.31 | 0.53 |

### Forecast / observed by observed-rain bin: himalaya

The ratio is taken where the observed rain is at least 0.1 mm; a forecast of no rain counts as 0.

| lead | bin (mm) | n | mean obs | mean fcst | bias | MAE | ratio n | p10 | p25 | p50 | p75 | p90 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | <1 | 3459706 | 0.21 | 2.31 | 2.10 | 2.20 | 1485835 | 0.00 | 0.46 | 3.62 | 12.12 | 27.62 |
| 1 | 1-10 | 3146014 | 4.18 | 8.01 | 3.84 | 6.17 | 3146014 | 0.06 | 0.41 | 1.35 | 3.08 | 5.94 |
| 1 | 10-25 | 1214402 | 15.91 | 14.01 | -1.90 | 10.77 | 1214402 | 0.09 | 0.29 | 0.65 | 1.19 | 1.96 |
| 1 | 25-50 | 508854 | 34.37 | 20.04 | -14.33 | 22.01 | 508854 | 0.08 | 0.20 | 0.41 | 0.75 | 1.27 |
| 1 | 50-100 | 167324 | 66.23 | 31.56 | -34.67 | 43.86 | 167324 | 0.07 | 0.16 | 0.32 | 0.60 | 1.10 |
| 1 | >=100 | 27596 | 132.07 | 49.31 | -82.76 | 89.36 | 27596 | 0.07 | 0.13 | 0.26 | 0.51 | 0.87 |
| 2 | <1 | 3465543 | 0.20 | 2.58 | 2.38 | 2.48 | 1485314 | 0.00 | 0.49 | 3.91 | 13.30 | 30.72 |
| 2 | 1-10 | 3140561 | 4.18 | 8.53 | 4.35 | 6.65 | 3140561 | 0.06 | 0.43 | 1.40 | 3.26 | 6.40 |
| 2 | 10-25 | 1213381 | 15.91 | 14.14 | -1.77 | 11.06 | 1213381 | 0.08 | 0.28 | 0.64 | 1.21 | 2.01 |
| 2 | 25-50 | 509293 | 34.37 | 19.41 | -14.96 | 22.36 | 509293 | 0.07 | 0.19 | 0.40 | 0.73 | 1.24 |
| 2 | 50-100 | 167512 | 66.23 | 27.75 | -38.48 | 45.16 | 167512 | 0.06 | 0.14 | 0.28 | 0.53 | 0.96 |
| 2 | >=100 | 27606 | 132.06 | 43.33 | -88.73 | 93.95 | 27606 | 0.06 | 0.11 | 0.22 | 0.42 | 0.77 |
| 3 | <1 | 3458178 | 0.20 | 2.93 | 2.73 | 2.82 | 1480991 | 0.00 | 0.56 | 4.36 | 14.58 | 33.83 |
| 3 | 1-10 | 3142429 | 4.18 | 8.68 | 4.50 | 6.80 | 3142429 | 0.06 | 0.44 | 1.43 | 3.34 | 6.62 |
| 3 | 10-25 | 1216481 | 15.91 | 13.59 | -2.32 | 11.02 | 1216481 | 0.07 | 0.26 | 0.61 | 1.16 | 1.95 |
| 3 | 25-50 | 511166 | 34.37 | 17.68 | -16.69 | 22.78 | 511166 | 0.06 | 0.17 | 0.36 | 0.67 | 1.15 |
| 3 | 50-100 | 168001 | 66.22 | 23.57 | -42.66 | 47.26 | 168001 | 0.05 | 0.11 | 0.24 | 0.44 | 0.81 |
| 3 | >=100 | 27641 | 132.03 | 35.85 | -96.19 | 100.18 | 27641 | 0.04 | 0.08 | 0.17 | 0.34 | 0.65 |

### Forecast / observed by observed-rain bin: western_ghats

The ratio is taken where the observed rain is at least 0.1 mm; a forecast of no rain counts as 0.

| lead | bin (mm) | n | mean obs | mean fcst | bias | MAE | ratio n | p10 | p25 | p50 | p75 | p90 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | <1 | 1086733 | 0.22 | 2.05 | 1.83 | 1.93 | 518491 | 0.04 | 0.55 | 2.68 | 8.61 | 20.85 |
| 1 | 1-10 | 961588 | 4.07 | 6.28 | 2.21 | 5.06 | 961588 | 0.06 | 0.28 | 0.92 | 2.30 | 4.71 |
| 1 | 10-25 | 370691 | 16.03 | 13.13 | -2.90 | 11.09 | 370691 | 0.09 | 0.24 | 0.55 | 1.10 | 1.90 |
| 1 | 25-50 | 172033 | 34.57 | 22.04 | -12.53 | 22.18 | 172033 | 0.09 | 0.21 | 0.44 | 0.81 | 1.38 |
| 1 | 50-100 | 68188 | 67.97 | 35.12 | -32.85 | 41.29 | 68188 | 0.11 | 0.20 | 0.39 | 0.68 | 1.05 |
| 1 | >=100 | 15983 | 130.65 | 51.82 | -78.82 | 83.27 | 15983 | 0.10 | 0.17 | 0.34 | 0.54 | 0.80 |
| 2 | <1 | 1085329 | 0.22 | 1.88 | 1.66 | 1.79 | 518063 | 0.00 | 0.34 | 1.92 | 7.11 | 18.98 |
| 2 | 1-10 | 961211 | 4.08 | 5.58 | 1.50 | 4.93 | 961211 | 0.04 | 0.18 | 0.68 | 1.94 | 4.31 |
| 2 | 10-25 | 372551 | 16.03 | 11.23 | -4.80 | 11.68 | 372551 | 0.04 | 0.14 | 0.42 | 0.94 | 1.73 |
| 2 | 25-50 | 172685 | 34.55 | 18.63 | -15.93 | 23.59 | 172685 | 0.04 | 0.13 | 0.34 | 0.71 | 1.23 |
| 2 | 50-100 | 67845 | 67.95 | 29.00 | -38.95 | 44.74 | 67845 | 0.06 | 0.13 | 0.30 | 0.59 | 0.93 |
| 2 | >=100 | 15595 | 129.80 | 44.79 | -85.01 | 90.22 | 15595 | 0.06 | 0.13 | 0.28 | 0.46 | 0.68 |
| 3 | <1 | 1088575 | 0.22 | 2.12 | 1.89 | 2.03 | 519848 | 0.02 | 0.35 | 1.92 | 7.35 | 20.82 |
| 3 | 1-10 | 962043 | 4.07 | 5.62 | 1.54 | 5.20 | 962043 | 0.03 | 0.15 | 0.61 | 1.89 | 4.43 |
| 3 | 10-25 | 371012 | 16.03 | 10.70 | -5.32 | 12.20 | 371012 | 0.03 | 0.10 | 0.36 | 0.90 | 1.72 |
| 3 | 25-50 | 171347 | 34.55 | 16.14 | -18.41 | 24.13 | 171347 | 0.03 | 0.09 | 0.28 | 0.63 | 1.13 |
| 3 | 50-100 | 66903 | 67.92 | 25.61 | -42.31 | 47.18 | 66903 | 0.04 | 0.10 | 0.25 | 0.52 | 0.84 |
| 3 | >=100 | 15336 | 129.78 | 37.97 | -91.81 | 93.23 | 15336 | 0.05 | 0.11 | 0.25 | 0.41 | 0.61 |

## Hazard skill and interval widening

v3 model `data/processed/hazard/model_v3_live` (FROZEN.json sha256 6e16b42a99918704995fa54d917634d3881f3ccc08ec4b66e239e20757e706e9). Thresholds from the model card (card.alert_levels): Watch 3.01e-06, Warning 1.18e-05, Emergency 4.81e-05. 488 issue days (0 without a GFS file); 2536 cells (a seeded sample of the scored cells plus 36 labelled cells, seed 20261015). The forecast side uses observed IMERG rain through D and GFS after D; the observed side is the training feature row of the target day. Observed rain of D is the full Late series here (the live D comes from Early plus GFS 0-3 h, measured by the operational backtest).

### Widening factors

Ratio = observed risk / forecast risk over informative cell-days (either risk >= the floor). The factors multiply `risk_lo` (lo) and `risk_hi` (hi); lo is clamped to at most 1 and hi to at least 1. Informative = at least one risk of the two >= 0.1 x Watch (3.01e-07); at least 200 needed per lead.

| lead | informative cell-days | lo | hi | raw p10 | raw p90 | pairs scored | not scorable |
|---|---|---|---|---|---|---|---|
| 1 | 575662 | 0.176 | 4.098 | 0.176 | 4.098 | 1237568 | 0 |
| 2 | 579003 | 0.176 | 5.675 | 0.176 | 5.675 | 1237568 | 0 |
| 3 | 587259 | 0.169 | 5.917 | 0.169 | 5.917 | 1237568 | 0 |

### Observed / forecast risk ratio (informative cell-days)

| lead | p1 | p5 | p10 | p25 | p50 | p75 | p90 | p95 | p99 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 0.0503 | 0.111 | 0.176 | 0.383 | 1 | 1.65 | 4.1 | 7.45 | 19.7 |
| 2 | 0.0461 | 0.109 | 0.176 | 0.38 | 1 | 2.03 | 5.67 | 9.38 | 26.8 |
| 3 | 0.0363 | 0.102 | 0.169 | 0.335 | 1 | 2.1 | 5.92 | 9.77 | 36.2 |

### Level agreement (all scored pairs)

Level from the point risk against the card thresholds; the observed-feature level is the reference.

| lead | pairs | same level | within one | Watch+ both | observed only | forecast only | recall of observed Watch+ | precision of forecast Watch+ |
|---|---|---|---|---|---|---|---|---|
| 1 | 1237568 | 0.862 | 0.984 | 222814 | 34113 | 52385 | 0.867 | 0.810 |
| 2 | 1237568 | 0.851 | 0.980 | 216659 | 40937 | 54434 | 0.841 | 0.799 |
| 3 | 1237568 | 0.840 | 0.976 | 212266 | 46200 | 58887 | 0.821 | 0.783 |

### Labels

3 day-exact positive cell-days, 24 cells of the 2023 inventory window (event day unknown inside 2023-06-16..2023-07-31) and 9 cells of the Wayanad 2024 case (event day 2024-07-30) fall in the archive years (0, 0 and 0 more are in cells that are not scored). This is far too thin to estimate a detection rate; the counts below say only whether the forecast side reaches Watch where an event happened, against the observed side.

| lead | day-exact events with data | observed Watch+ | forecast Watch+ | window cells with data | observed Watch+ | forecast Watch+ | Wayanad with data | observed Watch+ | forecast Watch+ |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 3/3 | 3 | 3 | 24/24 | 24 | 24 | 1/1 | 1 | 1 |
| 2 | 3/3 | 3 | 3 | 24/24 | 24 | 24 | 1/1 | 1 | 1 |
| 3 | 3/3 | 3 | 3 | 24/24 | 24 | 24 | 1/1 | 1 | 1 |

Day-exact events:

| cell | event day | lead | observed risk | forecast risk | observed Watch+ | forecast Watch+ |
|---|---|---|---|---|---|---|
| 22745454 | 2021-06-12 | 1 | 0.000107 | 1.79e-05 | True | True |
| 22745454 | 2021-06-12 | 2 | 0.000107 | 1.38e-05 | True | True |
| 22745454 | 2021-06-12 | 3 | 0.000107 | 2.51e-05 | True | True |
| 21625071 | 2021-07-22 | 1 | 0.000197 | 4.81e-05 | True | True |
| 21625071 | 2021-07-22 | 2 | 0.000197 | 2.56e-05 | True | True |
| 21625071 | 2021-07-22 | 3 | 0.000197 | 7.08e-05 | True | True |
| 19965135 | 2022-08-29 | 1 | 4.81e-05 | 2.56e-05 | True | True |
| 19965135 | 2022-08-29 | 2 | 4.81e-05 | 1.37e-05 | True | True |
| 19965135 | 2022-08-29 | 3 | 4.81e-05 | 2.56e-05 | True | True |

Wayanad 2024 (maximum over the case cells on the event day):

| lead | cells scored | observed max risk | forecast max risk | observed Watch+ cells | forecast Watch+ cells |
|---|---|---|---|---|---|
| 1 | 9/9 | 0.000418 | 0.000197 | 9 | 9 |
| 2 | 9/9 | 0.000418 | 0.000197 | 9 | 9 |
| 3 | 9/9 | 0.000418 | 0.000146 | 9 | 9 |
