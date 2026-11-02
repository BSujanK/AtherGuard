# Precision rules: terrain plausibility and per-level rain floors

Generated 2026-10-24T15:00:02Z. Design, floors' definition and the adoption criterion: docs/superpowers/specs/2026-10-14-aetherguard-live-global-design.md section 14 (written before any 2018 number of this study). Analysis only: the frozen model, the live run, `postrules.py` and the published tables are unchanged; the candidate rules are in `data/processed/alerts/post_rules_v4_candidate.json` and are not wired anywhere. Every number is read from the result files of `data/processed/alerts/precision_study/`.

## Summary

* Terrain variable chosen by the pre-declared rule: stat_relief < 180.4 (removes 4.3% of the development negative Warning+ cell-days).
* 2018 decision (spec 14.6): adoptable ['T', 'R']; recommended T. T: 1 Warning+ and 1 Emergency events lost, 4.3% of Warning+ cell-days removed; R: 1 Warning+ and 0 Emergency events lost, 3.6% of Warning+ cell-days removed; T+R: 2 Warning+ and 1 Emergency events lost, 7.8% of Warning+ cell-days removed.
* Development panels (in-sample for the floors): adoptable none; T loses 18 Warning+ and 16 Emergency of 539 / 402; R loses 2 Warning+ and 4 Emergency of 539 / 402; T+R loses 20 Warning+ and 20 Emergency of 539 / 402.
* Live 2026-10-24 (offline): cells lowered by each condition: T 364; R 3; T+R 366; T[stat_slope_p90] 340; T[stat_slope_mean] 260.
* The criterion is a loss and significance test, not a precision gain: compare the 'events lost per 1,000 removed cell-days' column with the baseline 'events per 1,000 alert cell-days' to see how selective the removed cell-days are.

## Floors chosen on the development years (2007-2017)

Development positives (in-domain, train + validation samples): 789. Baseline check (the study's section 11 levels equal `hardening_dev.season_levels` on every season): passed (11/11 seasons).

### Rule T: which terrain variable

| variable | 5th-percentile floor | negative Warning+ point cell-days | below the floor | share removed | event cell-days (Warning+ point) below the floor |
|---|---|---|---|---|---|
| stat_slope_p90 | 9.719 | 1,318,961 | 54,234 | 4.1% | 15/520 |
| stat_slope_mean | 4.284 | 1,318,961 | 43,570 | 3.3% | 16/520 |
| stat_relief | 180.438 | 1,318,961 | 56,964 | 4.3% | 17/520 |

Chosen: **stat_relief < 180.438**, which removes 4.3% of the development negative Warning+ point cell-days (sampled universe cells; the universe is already limited to a mean slope of at least the frozen slope floor).

### Rule R: per-level rain floors (5th percentile over development positives reaching the level)

| level | positives | 1-day mm | 3-day mm | 7-day mm | windows used | rule |
|---|---|---|---|---|---|---|
| Warning | 520 | 3.180 | 13.252 | 42.355 | 1, 3, 7 | irain_acc_1 >= 3.18 mm OR irain_acc_3 >= 13.3 mm OR irain_acc_7 >= 42.4 mm |
| Emergency | 363 | 8.316 | 25.309 | 52.067 | 1, 3, 7 | irain_acc_1 >= 8.32 mm OR irain_acc_3 >= 25.3 mm OR irain_acc_7 >= 52.1 mm |

Conditions evaluated: baseline, T, R, T+R.

## Development panels (out of fold; the floors were selected on them, so this is in-sample for the floors)

Cell-day counts are of the 5,000 sampled universe cells (the precision proxy scales them to all 36,792).

| condition | level or above | events detected | alert cell-days | share of cell-days | cell-days on cells below the terrain floor | events per 1,000 alert cell-days |
|---|---|---|---|---|---|---|
| baseline | Watch | 618/636 | 3,890,709 | 58.0% | 257,955 | 0.0216 |
| baseline | Warning | 539/636 | 1,658,817 | 24.7% | 71,863 | 0.0442 |
| baseline | Emergency | 402/636 | 683,446 | 10.2% | 32,624 | 0.0799 |
| T | Watch | 618/636 | 3,890,137 | 58.0% | 257,383 | 0.0216 |
| T | Warning | 521/636 | 1,586,954 | 23.7% | 0 | 0.0446 |
| T | Emergency | 386/636 | 650,822 | 9.7% | 0 | 0.0806 |
| R | Watch | 618/636 | 3,890,712 | 58.0% | 257,954 | 0.0216 |
| R | Warning | 537/636 | 1,618,785 | 24.1% | 71,437 | 0.0451 |
| R | Emergency | 398/636 | 669,163 | 10.0% | 32,548 | 0.0808 |
| T+R | Watch | 618/636 | 3,890,141 | 58.0% | 257,383 | 0.0216 |
| T+R | Warning | 519/636 | 1,547,348 | 23.1% | 0 | 0.0456 |
| T+R | Emergency | 382/636 | 636,615 | 9.5% | 0 | 0.0815 |

Change against the section 11 baseline:

| condition | level or above | cell-days removed | removed per day, paired bootstrap 95% CI | events lost | events lost per 1,000 removed cell-days | detection change (paired bootstrap 95% CI) |
|---|---|---|---|---|---|---|
| T | Watch | 572 (0.0%) | 0.4 [0.4, 0.5] | 0 | 0.0000 | +0.0 pp [+0.0, +0.0] |
| T | Warning | 71,863 (4.3%) | 53.5 [52.2, 54.8] | 18 | 0.0340 | -2.8 pp [-4.2, -1.7] |
| T | Emergency | 32,624 (4.8%) | 24.3 [23.4, 25.2] | 16 | 0.0666 | -2.5 pp [-3.8, -1.4] |
| R | Watch | -3 (-0.0%) | -0.0 [-0.0, 0.0] | 0 | n/a | +0.0 pp [+0.0, +0.0] |
| R | Warning | 40,032 (2.4%) | 29.8 [28.9, 30.8] | 2 | 0.0068 | -0.3 pp [-0.8, +0.0] |
| R | Emergency | 14,283 (2.1%) | 10.6 [10.3, 11.0] | 4 | 0.0381 | -0.6 pp [-1.3, -0.2] |
| T+R | Watch | 568 (0.0%) | 0.4 [0.4, 0.5] | 0 | 0.0000 | +0.0 pp [+0.0, +0.0] |
| T+R | Warning | 111,469 (6.7%) | 83.1 [81.5, 84.5] | 20 | 0.0244 | -3.1 pp [-4.6, -1.9] |
| T+R | Emergency | 46,831 (6.9%) | 34.9 [33.9, 35.9] | 20 | 0.0580 | -3.1 pp [-4.6, -1.9] |

Pre-declared criterion (spec 14.6):

| condition | Watch+ lost | Warning+ lost | Emergency lost | Warning+ reduction CI excludes 0 | decision |
|---|---|---|---|---|---|
| T | 0 | 18 | 16 | yes | not adopted |
| R | 0 | 2 | 4 | yes | not adopted |
| T+R | 0 | 20 | 20 | yes | not adopted |

Adoptable: none; recommended: none.

## 2018, the single look

2018 operational panel: 36792 cells, 122 days, 56 events. Baseline equals the published `evaluation.json` hits ({'Watch': 48, 'Warning': 40, 'Emergency': 30}): True.

| condition | level or above | events detected | alert cell-days | share of cell-days | cell-days on cells below the terrain floor | events per 1,000 alert cell-days |
|---|---|---|---|---|---|---|
| baseline | Watch | 48/56 | 2,468,948 | 55.5% | 149,950 | 0.0194 |
| baseline | Warning | 40/56 | 996,517 | 22.4% | 42,541 | 0.0401 |
| baseline | Emergency | 30/56 | 386,775 | 8.7% | 20,433 | 0.0776 |
| T | Watch | 48/56 | 2,468,591 | 55.5% | 149,593 | 0.0194 |
| T | Warning | 39/56 | 953,976 | 21.4% | 0 | 0.0409 |
| T | Emergency | 29/56 | 366,342 | 8.2% | 0 | 0.0792 |
| R | Watch | 48/56 | 2,468,978 | 55.5% | 149,951 | 0.0194 |
| R | Warning | 39/56 | 960,672 | 21.6% | 42,268 | 0.0406 |
| R | Emergency | 30/56 | 374,630 | 8.4% | 20,377 | 0.0801 |
| T+R | Watch | 48/56 | 2,468,620 | 55.5% | 149,593 | 0.0194 |
| T+R | Warning | 38/56 | 918,404 | 20.6% | 0 | 0.0414 |
| T+R | Emergency | 29/56 | 354,253 | 8.0% | 0 | 0.0819 |

Change against the section 11 baseline:

| condition | level or above | cell-days removed | removed per day, paired bootstrap 95% CI | events lost | events lost per 1,000 removed cell-days | detection change (paired bootstrap 95% CI) |
|---|---|---|---|---|---|---|
| T | Watch | 357 (0.0%) | 2.9 [1.7, 4.5] | 0 | 0.0000 | +0.0 pp [+0.0, +0.0] |
| T | Warning | 42,541 (4.3%) | 348.7 [307.8, 389.8] | 1 | 0.0235 | -1.8 pp [-5.4, +0.0] |
| T | Emergency | 20,433 (5.3%) | 167.5 [140.4, 194.6] | 1 | 0.0489 | -1.8 pp [-5.4, +0.0] |
| R | Watch | -30 (-0.0%) | -0.2 [-0.4, -0.1] | 0 | n/a | +0.0 pp [+0.0, +0.0] |
| R | Warning | 35,845 (3.6%) | 293.8 [271.5, 318.0] | 1 | 0.0279 | -1.8 pp [-5.4, +0.0] |
| R | Emergency | 12,145 (3.1%) | 99.5 [90.7, 108.4] | 0 | 0.0000 | +0.0 pp [+0.0, +0.0] |
| T+R | Watch | 328 (0.0%) | 2.7 [1.5, 4.2] | 0 | 0.0000 | +0.0 pp [+0.0, +0.0] |
| T+R | Warning | 78,113 (7.8%) | 640.3 [598.5, 681.4] | 2 | 0.0256 | -3.6 pp [-8.9, +0.0] |
| T+R | Emergency | 32,522 (8.4%) | 266.6 [239.3, 293.7] | 1 | 0.0307 | -1.8 pp [-5.4, +0.0] |

Pre-declared criterion (spec 14.6):

| condition | Watch+ lost | Warning+ lost | Emergency lost | Warning+ reduction CI excludes 0 | decision |
|---|---|---|---|---|---|
| T | 0 | 1 | 1 | yes | ADOPT |
| R | 0 | 1 | 0 | yes | ADOPT |
| T+R | 0 | 2 | 1 | yes | not adopted |

Adoptable: ['T', 'R']; recommended: T.

## Terrain variable sensitivity (development panels only; NOT evaluated on 2018)

The two terrain variables that the pre-declared rule did not choose, at their own development floors. Descriptive: the choice above stands and 2018 was not looked at for these.

| condition | level or above | events detected | alert cell-days | share of cell-days | cell-days on cells below the terrain floor | events per 1,000 alert cell-days |
|---|---|---|---|---|---|---|
| baseline | Watch | 618/636 | 3,890,709 | 58.0% | 294,359 | 0.0216 |
| baseline | Warning | 539/636 | 1,658,817 | 24.7% | 70,486 | 0.0442 |
| baseline | Emergency | 402/636 | 683,446 | 10.2% | 30,051 | 0.0799 |
| T[stat_slope_p90] | Watch | 618/636 | 3,889,973 | 58.0% | 293,623 | 0.0216 |
| T[stat_slope_p90] | Warning | 523/636 | 1,588,331 | 23.7% | 0 | 0.0447 |
| T[stat_slope_p90] | Emergency | 388/636 | 653,395 | 9.7% | 0 | 0.0807 |
| T[stat_slope_mean] | Watch | 618/636 | 3,889,970 | 58.0% | 293,751 | 0.0216 |
| T[stat_slope_mean] | Warning | 521/636 | 1,600,465 | 23.9% | 20,277 | 0.0442 |
| T[stat_slope_mean] | Emergency | 388/636 | 659,979 | 9.8% | 8,880 | 0.0799 |

| condition | level or above | cell-days removed | removed per day, paired bootstrap 95% CI | events lost | events lost per 1,000 removed cell-days | detection change (paired bootstrap 95% CI) |
|---|---|---|---|---|---|---|
| T[stat_slope_p90] | Watch | 736 (0.0%) | 0.5 [0.5, 0.6] | 0 | 0.0000 | +0.0 pp [+0.0, +0.0] |
| T[stat_slope_p90] | Warning | 70,486 (4.2%) | 52.5 [51.2, 53.8] | 16 | 0.0308 | -2.5 pp [-3.8, -1.4] |
| T[stat_slope_p90] | Emergency | 30,051 (4.4%) | 22.4 [21.5, 23.3] | 14 | 0.0633 | -2.2 pp [-3.5, -1.1] |
| T[stat_slope_mean] | Watch | 739 (0.0%) | 0.6 [0.5, 0.6] | 0 | 0.0000 | +0.0 pp [+0.0, +0.0] |
| T[stat_slope_mean] | Warning | 58,352 (3.5%) | 43.5 [42.4, 44.5] | 18 | 0.0419 | -2.8 pp [-4.2, -1.6] |
| T[stat_slope_mean] | Emergency | 23,467 (3.4%) | 17.5 [16.8, 18.1] | 14 | 0.0811 | -2.2 pp [-3.3, -1.1] |

## Live replay 2026-10-16..2026-10-24 (offline, nothing written to `data/live`)

A continuous chain from 2026-10-09 through the stored published raw level and point risk. Baseline chain equals the published levels except on 0 cell-days from 2026-10-16.

| condition | cells lowered on 2026-10-24 | level transitions on 2026-10-24 | alerts lowered / alerts, by class |
|---|---|---|---|
| T | 364 | {"Watch->Normal": 0, "Warning->Normal": 0, "Warning->Watch": 225, "Emergency->Normal": 0, "Emergency->Watch": 139, "Emergency->Warning": 0} | flat_cell_alerts (slope_mean<5 deg, Watch+): 286/773; low_elevation_alerts (elev_mean<100 m, Watch+): 363/760; flat_cell_warning_plus: 286/366; low_rain_warning_plus (3-day IMERG<20 mm): 3/55 |
| R | 3 | {"Watch->Normal": 0, "Warning->Normal": 0, "Warning->Watch": 3, "Emergency->Normal": 0, "Emergency->Watch": 0, "Emergency->Warning": 0} | flat_cell_alerts (slope_mean<5 deg, Watch+): 2/773; low_elevation_alerts (elev_mean<100 m, Watch+): 1/760; flat_cell_warning_plus: 2/366; low_rain_warning_plus (3-day IMERG<20 mm): 3/55 |
| T+R | 366 | {"Watch->Normal": 0, "Warning->Normal": 0, "Warning->Watch": 227, "Emergency->Normal": 0, "Emergency->Watch": 139, "Emergency->Warning": 0} | flat_cell_alerts (slope_mean<5 deg, Watch+): 287/773; low_elevation_alerts (elev_mean<100 m, Watch+): 363/760; flat_cell_warning_plus: 287/366; low_rain_warning_plus (3-day IMERG<20 mm): 5/55 |
| T[stat_slope_p90] | 340 | {"Watch->Normal": 0, "Warning->Normal": 0, "Warning->Watch": 215, "Emergency->Normal": 0, "Emergency->Watch": 125, "Emergency->Warning": 0} | flat_cell_alerts (slope_mean<5 deg, Watch+): 314/773; low_elevation_alerts (elev_mean<100 m, Watch+): 321/760; flat_cell_warning_plus: 314/366; low_rain_warning_plus (3-day IMERG<20 mm): 3/55 |
| T[stat_slope_mean] | 260 | {"Watch->Normal": 0, "Warning->Normal": 0, "Warning->Watch": 168, "Emergency->Normal": 0, "Emergency->Watch": 92, "Emergency->Warning": 0} | flat_cell_alerts (slope_mean<5 deg, Watch+): 260/773; low_elevation_alerts (elev_mean<100 m, Watch+): 233/760; flat_cell_warning_plus: 260/366; low_rain_warning_plus (3-day IMERG<20 mm): 5/55 |

Named cells (levels per replay day, oldest first):

| cell | position | terrain | IMERG 1/3/7 mm | published | T | R | T+R | T[stat_slope_p90] | T[stat_slope_mean] |
|---|---|---|---|---|---|---|---|---|---|
| 19625150 | 8.125N 77.525E | slope 2.8/p90 4.4, relief 328, elev 31 | 0.2/82.9/102.8 | 3 | 3 | 3 | 3 | 1 | 1 |
| 24615097 | 33.075N 74.875E | slope 18.3/p90 37.3, relief 1339, elev 771 | 14.2/16.3/16.3 | 2 | 2 | 2 | 2 | 2 | 2 |
| 24625092 | 33.125N 74.625E | slope 14.2/p90 31.3, relief 866, elev 791 | 11.9/13.6/13.6 | 2 | 2 | 2 | 2 | 2 | 2 |
| 24625093 | 33.125N 74.675E | slope 26.4/p90 39.2, relief 1344, elev 1031 | 11.9/13.6/13.6 | 2 | 2 | 2 | 2 | 2 | 2 |
| 24625094 | 33.125N 74.725E | slope 27.8/p90 41.1, relief 1371, elev 1288 | 16.8/19.2/19.2 | 2 | 2 | 2 | 2 | 2 | 2 |
| 24625095 | 33.125N 74.775E | slope 31.1/p90 43.3, relief 1603, elev 1001 | 16.8/19.2/19.2 | 2 | 2 | 2 | 2 | 2 | 2 |
| 24635092 | 33.175N 74.625E | slope 21.2/p90 35.3, relief 987, elev 1308 | 11.9/13.6/13.6 | 2 | 2 | 2 | 2 | 2 | 2 |
| 24635093 | 33.175N 74.675E | slope 25.7/p90 42.0, relief 1172, elev 1304 | 11.9/13.6/13.6 | 2 | 2 | 2 | 2 | 2 | 2 |
| 24635094 | 33.175N 74.725E | slope 24.8/p90 36.3, relief 1057, elev 956 | 16.8/19.2/19.2 | 2 | 2 | 2 | 2 | 2 | 2 |
| 24645092 | 33.225N 74.625E | slope 23.6/p90 31.4, relief 834, elev 1486 | 12.9/14.8/14.8 | 2 | 2 | 2 | 2 | 2 | 2 |
| 24645093 | 33.225N 74.675E | slope 25.6/p90 34.0, relief 1134, elev 1172 | 12.9/14.8/14.8 | 2 | 2 | 2 | 2 | 2 | 2 |
| 24655092 | 33.275N 74.625E | slope 24.1/p90 32.5, relief 1124, elev 1599 | 12.9/14.8/14.8 | 2 | 2 | 2 | 2 | 2 | 2 |
| 24655093 | 33.275N 74.675E | slope 27.3/p90 36.5, relief 1526, elev 1804 | 12.9/14.8/14.8 | 2 | 2 | 2 | 2 | 2 | 2 |
| 24665092 | 33.325N 74.625E | slope 21.7/p90 32.5, relief 1044, elev 1870 | 9.7/11.1/11.6 | 2 | 2 | 2 | 2 | 2 | 2 |
| 24665093 | 33.325N 74.675E | slope 20.7/p90 29.1, relief 1124, elev 1779 | 9.7/11.1/11.6 | 2 | 2 | 2 | 2 | 2 | 2 |
| 24665094 | 33.325N 74.725E | slope 21.5/p90 29.7, relief 1556, elev 1787 | 9.0/10.5/11.8 | 2 | 2 | 2 | 2 | 2 | 2 |

Jammu box (33.1N 74.7E +/- 0.25): 33 Watch+ cells in the published table.

## Diagnosis (not a rule): low-elevation positives and the model's dependence on elevation

Development positives on cells with stat_slope_mean < 5 degrees or stat_elev_mean < 100 m:

| group | positives | mean slope < 5 | mean elevation < 100 m | either |
|---|---|---|---|---|
| all | 789 | 65 (8.2%) | 87 (11.0%) | 103 (13.1%) |
| himalaya | 682 | 31 (4.5%) | 33 (4.8%) | 46 (6.7%) |
| western_ghats | 107 | 34 (31.8%) | 54 (50.5%) | 57 (53.3%) |
| coolr_reports | 107 | 34 (31.8%) | 54 (50.5%) | 57 (53.3%) |
| hma | 682 | 31 (4.5%) | 33 (4.8%) | 46 (6.7%) |
| 0-1 km | 33 | 2 (6.1%) | 5 (15.2%) | 6 (18.2%) |
| 1-5 km | 217 | 22 (10.1%) | 30 (13.8%) | 37 (17.1%) |
| >=5 km | 539 | 41 (7.6%) | 52 (9.6%) | 60 (11.1%) |

Positive share of the development samples by elevation band:

| mean elevation (m) | positives | negatives | positive share |
|---|---|---|---|
| 0-50 | 38 | 79 | 32.48% |
| 50-100 | 49 | 179 | 21.49% |
| 100-200 | 20 | 366 | 5.18% |
| 200-500 | 51 | 1894 | 2.62% |
| 500-1000 | 161 | 1980 | 7.52% |
| 1000-2000 | 346 | 1290 | 21.15% |
| >=2000 | 124 | 2452 | 4.81% |

Partial dependence of the frozen v3-live model on `stat_elev_mean` (seeded sample, seed 20261024):

| rows | n | PD decreasing up to 300 m | PD(50 m) - PD(300 m), log-odds | PD(50 m) - PD(1000 m) | ICE curves with 50 m above 300 m | elevation of the PD maximum (m) |
|---|---|---|---|---|---|---|
| all | 1789 | yes | +1.16 | +0.88 | 100.0% | 0 |
| region_himalaya | 1525 | yes | +1.10 | +0.84 | 100.0% | 0 |
| region_western_ghats | 264 | yes | +1.51 | +1.13 | 100.0% | 0 |
| rows_below_300m | 250 | yes | +1.84 | +1.41 | 100.0% | 1500 |

Monotone constraint on `stat_elev_mean` in the model: 0 (0 = none).

| elevation (m) | 0 | 10 | 25 | 50 | 75 | 100 | 150 | 200 | 300 | 500 | 750 | 1000 | 1500 | 2000 | 3000 | 4000 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| PD log-odds, all rows | -1.32 | -1.32 | -1.32 | -2.01 | -2.01 | -2.64 | -2.81 | -3.17 | -3.17 | -3.15 | -3.01 | -2.90 | -1.79 | -2.14 | -2.88 | -3.30 |

## Limits

* The development evaluation is in-sample for the floors; only 2018 decides, and it is one season with 56 events.
* The universe is limited to cells with a mean slope above the frozen floor, so the dev and 2018 counts of 'cells below the terrain floor' describe that universe, not the whole grid.
* Alert cell-days are a false-alarm proxy (events are rare), not a verified count of false alarms.
* Runtime of the runs: dev 19 s, 2018 7 s, replay 1 s.
