# Held-out verification, expanded (phase 7, W1)

**Held-out events: 92 against the 150-event gate: NOT MET, 58 short.** (87 distinct when events within 10 km and a day are merged.)

v3 against 3-day rain, a static map, the NASA LHASA v2 nowcast and a rainfall event-duration threshold, on the June-December panels of 2018-2025 (frozen model, training-style features). POD is the share of events whose highest level within tolerance reached the level; precision is the share of alert cell-days that an event lies within tolerance of. `tolerant` is 10 km and 1 day, `cell_exact` the same cell and day. Intervals are 95% percentile bootstraps (days resampled for precision, events for POD).

## Reading this report

- Ground truth after 2018 is very incomplete: the reported and catalog events are a small fraction of the slides that happened. Precision on S1925 and POOLED is therefore relative, for comparing models that raise the same burden, and is not an absolute false-alarm rate.
- Every benchmark except `rain_3d_devcuts` is burden-matched, season by season, to the shares v3 realised in that season, ranking the cell-days by its own score; the realised shares are in the tables. `lhasa_v2` has no score on days its archive lacks, so it can fall short of the target.
- `susceptibility` is computed from v3's risk over the season it is scored on (hindsight), an optimistic baseline.
- S2018 events are the June-September catalog events while the 2018 panel runs to December: alerts in October-December cannot be verified there, which lowers S2018 precision for every model alike.
- Every set holds the same panel cells, which are not all cells of India; an event is matched to the panel cells within tolerance.
- `lhasa_v2` covers 2018-2020 only, so it appears in S2018 and in L1820, which holds every model on the same days and events. Shift 0 (panel day D with LHASA day D) is primary; whether LHASA day D uses rain through the whole of UTC day D is not established, hence the -1 and +1 rows.
- `ed_threshold`: the rain event ending on the cell-day (consecutive IMD days with at least 1 mm of IMERG Late; E its total, D its length in days) over E = alpha * D^gamma. Published: Brunetti et al. 2021, HESS 25, 3267-3279, Table 1, IMERG Early run, 5% non-exceedance: E = 5.3 * D_hours^0.74, that is alpha = 55.7 for D in days; only the exponent shapes a burden-matched ranking. `ed_threshold_refit` is refitted: E = 3.67 * D^1.214 at the 5% non-exceedance of 592 of 647 development positives (the rest have no usable rain event ending on their day). A cell-day with no event never alerts.

## Seasons

| season | scored share of cell-days | days below half | v3 realised Watch+ / Warning+ / Emergency | events | LHASA |
|---|---|---|---|---|---|
| 2018 | 100.0% | 0 of 214 | 36.18% / 13.48% / 5.11% | 56 | yes |
| 2019 | 100.0% | 0 of 214 | 44.10% / 17.91% / 7.46% | 7 | yes |
| 2020 | 100.0% | 0 of 214 | 40.85% / 16.68% / 6.88% | 2 | yes |
| 2021 | 100.0% | 0 of 214 | 41.68% / 16.92% / 6.90% | 9 | no |
| 2022 | 100.0% | 0 of 214 | 40.15% / 16.39% / 6.85% | 4 | no |
| 2023 | 100.0% | 0 of 214 | 37.72% / 14.85% / 5.89% | 5 | no |
| 2024 | 100.0% | 0 of 214 | 41.26% / 18.06% / 8.23% | 6 | no |
| 2025 | 100.0% | 0 of 214 | 42.96% / 17.25% / 6.97% | 3 | no |

## S2018 (36,792 cells, 214 days, 56 events)

the 2018 panel; the in-domain season_2018 catalog events of June-September. Events by source: catalog_2018 56. 52 distinct when events within 10 km and a day are merged; 0 further events are dated outside the panel days and not scored.

| model | tolerance | level | events | hits | POD [95% CI] | alert cell-days | precision [95% CI] | realised share |
|---|---|---|---|---|---|---|---|---|
| v3 | tolerant | Watch+ | 56 | 54 | 96.4% [91.1, 100.0] | 2,848,957 | 0.047% [0.033, 0.063] | 36.18% |
| v3 | tolerant | Warning+ | 56 | 48 | 85.7% [75.0, 94.6] | 1,061,600 | 0.097% [0.064, 0.132] | 13.48% |
| v3 | tolerant | Emergency | 56 | 45 | 80.4% [69.6, 89.3] | 402,433 | 0.175% [0.102, 0.253] | 5.11% |
| v3 | cell_exact | Watch+ | 56 | 49 | 87.5% [78.6, 94.6] | 2,848,957 | 0.002% [0.001, 0.003] | 36.18% |
| v3 | cell_exact | Warning+ | 56 | 42 | 75.0% [62.5, 85.7] | 1,061,600 | 0.004% [0.002, 0.006] | 13.48% |
| v3 | cell_exact | Emergency | 56 | 30 | 53.6% [41.1, 67.9] | 402,433 | 0.007% [0.004, 0.012] | 5.11% |
| rain_3d | tolerant | Watch+ | 56 | 53 | 94.6% [87.5, 100.0] | 2,848,947 | 0.043% [0.029, 0.058] | 36.18% |
| rain_3d | tolerant | Warning+ | 56 | 40 | 71.4% [58.9, 82.1] | 1,061,602 | 0.076% [0.044, 0.111] | 13.48% |
| rain_3d | tolerant | Emergency | 56 | 33 | 58.9% [46.4, 71.4] | 402,432 | 0.158% [0.086, 0.234] | 5.11% |
| rain_3d | cell_exact | Watch+ | 56 | 44 | 78.6% [67.9, 89.3] | 2,848,947 | 0.002% [0.001, 0.002] | 36.18% |
| rain_3d | cell_exact | Warning+ | 56 | 32 | 57.1% [44.6, 69.6] | 1,061,602 | 0.003% [0.001, 0.005] | 13.48% |
| rain_3d | cell_exact | Emergency | 56 | 24 | 42.9% [30.4, 57.1] | 402,432 | 0.006% [0.003, 0.010] | 5.11% |
| rain_3d_devcuts | tolerant | Watch+ | 56 | 51 | 91.1% [82.1, 98.2] | 2,624,631 | 0.045% [0.030, 0.062] | 33.34% |
| rain_3d_devcuts | tolerant | Warning+ | 56 | 39 | 69.6% [57.1, 80.4] | 978,344 | 0.081% [0.047, 0.118] | 12.43% |
| rain_3d_devcuts | tolerant | Emergency | 56 | 33 | 58.9% [46.4, 71.4] | 385,981 | 0.164% [0.090, 0.244] | 4.90% |
| rain_3d_devcuts | cell_exact | Watch+ | 56 | 43 | 76.8% [66.1, 87.5] | 2,624,631 | 0.002% [0.001, 0.002] | 33.34% |
| rain_3d_devcuts | cell_exact | Warning+ | 56 | 31 | 55.4% [42.9, 69.6] | 978,344 | 0.003% [0.001, 0.005] | 12.43% |
| rain_3d_devcuts | cell_exact | Emergency | 56 | 24 | 42.9% [30.4, 57.1] | 385,981 | 0.006% [0.003, 0.010] | 4.90% |
| susceptibility | tolerant | Watch+ | 56 | 52 | 92.9% [85.7, 98.2] | 2,848,957 | 0.044% [0.030, 0.059] | 36.18% |
| susceptibility | tolerant | Warning+ | 56 | 45 | 80.4% [69.6, 89.3] | 1,061,600 | 0.048% [0.032, 0.066] | 13.48% |
| susceptibility | tolerant | Emergency | 56 | 30 | 53.6% [41.1, 66.1] | 402,433 | 0.055% [0.034, 0.079] | 5.11% |
| susceptibility | cell_exact | Watch+ | 56 | 48 | 85.7% [76.8, 94.6] | 2,848,957 | 0.002% [0.001, 0.002] | 36.18% |
| susceptibility | cell_exact | Warning+ | 56 | 19 | 33.9% [21.4, 46.4] | 1,061,600 | 0.002% [0.001, 0.003] | 13.48% |
| susceptibility | cell_exact | Emergency | 56 | 13 | 23.2% [12.5, 33.9] | 402,433 | 0.003% [0.001, 0.005] | 5.11% |
| lhasa_v2_m1 | tolerant | Watch+ | 56 | 53 | 94.6% [87.5, 100.0] | 2,835,636 | 0.046% [0.031, 0.062] | 36.01% |
| lhasa_v2_m1 | tolerant | Warning+ | 56 | 47 | 83.9% [75.0, 92.9] | 1,056,631 | 0.077% [0.047, 0.110] | 13.42% |
| lhasa_v2_m1 | tolerant | Emergency | 56 | 35 | 62.5% [50.0, 75.0] | 400,542 | 0.141% [0.074, 0.211] | 5.09% |
| lhasa_v2_m1 | cell_exact | Watch+ | 56 | 48 | 85.7% [76.8, 94.6] | 2,835,636 | 0.002% [0.001, 0.003] | 36.01% |
| lhasa_v2_m1 | cell_exact | Warning+ | 56 | 30 | 53.6% [41.1, 66.1] | 1,056,631 | 0.003% [0.001, 0.004] | 13.42% |
| lhasa_v2_m1 | cell_exact | Emergency | 56 | 21 | 37.5% [25.0, 50.0] | 400,542 | 0.005% [0.002, 0.009] | 5.09% |
| lhasa_v2 | tolerant | Watch+ | 56 | 53 | 94.6% [87.5, 100.0] | 2,848,955 | 0.047% [0.032, 0.063] | 36.18% |
| lhasa_v2 | tolerant | Warning+ | 56 | 46 | 82.1% [71.4, 91.1] | 1,062,499 | 0.084% [0.051, 0.120] | 13.49% |
| lhasa_v2 | tolerant | Emergency | 56 | 34 | 60.7% [48.2, 73.2] | 402,433 | 0.137% [0.074, 0.206] | 5.11% |
| lhasa_v2 | cell_exact | Watch+ | 56 | 52 | 92.9% [85.7, 98.2] | 2,848,955 | 0.002% [0.001, 0.003] | 36.18% |
| lhasa_v2 | cell_exact | Warning+ | 56 | 33 | 58.9% [46.4, 71.4] | 1,062,499 | 0.003% [0.001, 0.005] | 13.49% |
| lhasa_v2 | cell_exact | Emergency | 56 | 24 | 42.9% [30.4, 55.4] | 402,433 | 0.006% [0.003, 0.010] | 5.11% |
| lhasa_v2_p1 | tolerant | Watch+ | 56 | 52 | 92.9% [85.7, 98.2] | 2,835,642 | 0.046% [0.031, 0.062] | 36.02% |
| lhasa_v2_p1 | tolerant | Warning+ | 56 | 40 | 71.4% [58.9, 82.1] | 1,055,348 | 0.080% [0.049, 0.116] | 13.40% |
| lhasa_v2_p1 | tolerant | Emergency | 56 | 32 | 57.1% [44.6, 69.6] | 400,552 | 0.112% [0.058, 0.173] | 5.09% |
| lhasa_v2_p1 | cell_exact | Watch+ | 56 | 48 | 85.7% [76.8, 94.6] | 2,835,642 | 0.002% [0.001, 0.002] | 36.02% |
| lhasa_v2_p1 | cell_exact | Warning+ | 56 | 33 | 58.9% [46.4, 71.4] | 1,055,348 | 0.003% [0.002, 0.005] | 13.40% |
| lhasa_v2_p1 | cell_exact | Emergency | 56 | 18 | 32.1% [21.4, 44.6] | 400,552 | 0.004% [0.001, 0.008] | 5.09% |
| ed_threshold | tolerant | Watch+ | 56 | 54 | 96.4% [91.1, 100.0] | 2,848,474 | 0.041% [0.027, 0.056] | 36.18% |
| ed_threshold | tolerant | Warning+ | 56 | 40 | 71.4% [58.9, 82.1] | 1,061,426 | 0.079% [0.047, 0.113] | 13.48% |
| ed_threshold | tolerant | Emergency | 56 | 30 | 53.6% [41.1, 67.9] | 402,365 | 0.150% [0.080, 0.226] | 5.11% |
| ed_threshold | cell_exact | Watch+ | 56 | 46 | 82.1% [71.4, 92.9] | 2,848,474 | 0.002% [0.001, 0.002] | 36.18% |
| ed_threshold | cell_exact | Warning+ | 56 | 34 | 60.7% [48.2, 73.2] | 1,061,426 | 0.003% [0.002, 0.005] | 13.48% |
| ed_threshold | cell_exact | Emergency | 56 | 24 | 42.9% [30.4, 57.1] | 402,365 | 0.006% [0.003, 0.010] | 5.11% |
| ed_threshold_refit | tolerant | Watch+ | 56 | 54 | 96.4% [91.1, 100.0] | 2,848,485 | 0.041% [0.027, 0.056] | 36.18% |
| ed_threshold_refit | tolerant | Warning+ | 56 | 41 | 73.2% [60.7, 83.9] | 1,061,426 | 0.080% [0.048, 0.116] | 13.48% |
| ed_threshold_refit | tolerant | Emergency | 56 | 33 | 58.9% [46.4, 71.4] | 402,365 | 0.137% [0.070, 0.213] | 5.11% |
| ed_threshold_refit | cell_exact | Watch+ | 56 | 45 | 80.4% [69.6, 91.1] | 2,848,485 | 0.002% [0.001, 0.002] | 36.18% |
| ed_threshold_refit | cell_exact | Warning+ | 56 | 34 | 60.7% [48.2, 73.2] | 1,061,426 | 0.003% [0.001, 0.005] | 13.48% |
| ed_threshold_refit | cell_exact | Emergency | 56 | 25 | 44.6% [32.1, 57.1] | 402,365 | 0.006% [0.003, 0.010] | 5.11% |

Alert shares, target against realised (pooled over the set's seasons):

| model | target Watch+ / Warning+ / Emergency | realised |
|---|---|---|
| v3 | n/a | 36.18% / 13.48% / 5.11% |
| rain_3d | 36.18% / 13.48% / 5.11% | 36.18% / 13.48% / 5.11% |
| rain_3d_devcuts | 57.98% / 24.72% / 10.19% | 33.34% / 12.43% / 4.90% |
| susceptibility | 36.18% / 13.48% / 5.11% | 36.18% / 13.48% / 5.11% |
| lhasa_v2_m1 | 36.18% / 13.48% / 5.11% | 36.01% / 13.42% / 5.09% |
| lhasa_v2 | 36.18% / 13.48% / 5.11% | 36.18% / 13.49% / 5.11% |
| lhasa_v2_p1 | 36.18% / 13.48% / 5.11% | 36.02% / 13.40% / 5.09% |
| ed_threshold | 36.18% / 13.48% / 5.11% | 36.18% / 13.48% / 5.11% |
| ed_threshold_refit | 36.18% / 13.48% / 5.11% | 36.18% / 13.48% / 5.11% |

## S1925 (36,792 cells, 1498 days, 36 events)

the 2019-2025 panels; admitted reported events and in-domain test_sparse catalog events. Events by source: catalog_sparse 6, reported 30. 35 distinct when events within 10 km and a day are merged; 1 further events are dated outside the panel days and not scored.

| model | tolerance | level | events | hits | POD [95% CI] | alert cell-days | precision [95% CI] | realised share |
|---|---|---|---|---|---|---|---|---|
| v3 | tolerant | Watch+ | 36 | 36 | 100.0% [100.0, 100.0] | 22,733,080 | 0.004% [0.003, 0.005] | 41.25% |
| v3 | tolerant | Warning+ | 36 | 36 | 100.0% [100.0, 100.0] | 9,295,268 | 0.008% [0.006, 0.010] | 16.87% |
| v3 | tolerant | Emergency | 36 | 33 | 91.7% [80.6, 100.0] | 3,872,871 | 0.014% [0.010, 0.018] | 7.03% |
| v3 | cell_exact | Watch+ | 36 | 35 | 97.2% [91.7, 100.0] | 22,733,080 | 0.000% [0.000, 0.000] | 41.25% |
| v3 | cell_exact | Warning+ | 36 | 27 | 75.0% [61.1, 88.9] | 9,295,268 | 0.000% [0.000, 0.000] | 16.87% |
| v3 | cell_exact | Emergency | 36 | 22 | 61.1% [44.4, 77.8] | 3,872,871 | 0.001% [0.000, 0.001] | 7.03% |
| rain_3d | tolerant | Watch+ | 36 | 35 | 97.2% [91.7, 100.0] | 22,733,122 | 0.004% [0.003, 0.005] | 41.25% |
| rain_3d | tolerant | Warning+ | 36 | 30 | 83.3% [69.4, 94.4] | 9,295,247 | 0.006% [0.005, 0.008] | 16.87% |
| rain_3d | tolerant | Emergency | 36 | 26 | 72.2% [58.3, 86.1] | 3,872,867 | 0.012% [0.008, 0.016] | 7.03% |
| rain_3d | cell_exact | Watch+ | 36 | 32 | 88.9% [77.8, 97.2] | 22,733,122 | 0.000% [0.000, 0.000] | 41.25% |
| rain_3d | cell_exact | Warning+ | 36 | 21 | 58.3% [41.7, 75.0] | 9,295,247 | 0.000% [0.000, 0.000] | 16.87% |
| rain_3d | cell_exact | Emergency | 36 | 18 | 50.0% [33.3, 66.7] | 3,872,867 | 0.000% [0.000, 0.001] | 7.03% |
| rain_3d_devcuts | tolerant | Watch+ | 36 | 35 | 97.2% [91.7, 100.0] | 21,393,231 | 0.004% [0.003, 0.005] | 38.82% |
| rain_3d_devcuts | tolerant | Warning+ | 36 | 30 | 83.3% [69.4, 94.4] | 8,651,024 | 0.007% [0.005, 0.009] | 15.70% |
| rain_3d_devcuts | tolerant | Emergency | 36 | 25 | 69.4% [52.8, 83.3] | 3,629,613 | 0.012% [0.008, 0.017] | 6.59% |
| rain_3d_devcuts | cell_exact | Watch+ | 36 | 30 | 83.3% [69.4, 94.4] | 21,393,231 | 0.000% [0.000, 0.000] | 38.82% |
| rain_3d_devcuts | cell_exact | Warning+ | 36 | 21 | 58.3% [41.7, 75.0] | 8,651,024 | 0.000% [0.000, 0.000] | 15.70% |
| rain_3d_devcuts | cell_exact | Emergency | 36 | 18 | 50.0% [33.3, 66.7] | 3,629,613 | 0.000% [0.000, 0.001] | 6.59% |
| susceptibility | tolerant | Watch+ | 36 | 36 | 100.0% [100.0, 100.0] | 22,733,080 | 0.004% [0.003, 0.005] | 41.25% |
| susceptibility | tolerant | Warning+ | 36 | 32 | 88.9% [77.8, 97.2] | 9,295,268 | 0.004% [0.003, 0.005] | 16.87% |
| susceptibility | tolerant | Emergency | 36 | 24 | 66.7% [50.0, 80.6] | 3,872,871 | 0.004% [0.003, 0.005] | 7.03% |
| susceptibility | cell_exact | Watch+ | 36 | 31 | 86.1% [75.0, 97.2] | 22,733,080 | 0.000% [0.000, 0.000] | 41.25% |
| susceptibility | cell_exact | Warning+ | 36 | 13 | 36.1% [22.2, 52.8] | 9,295,268 | 0.000% [0.000, 0.000] | 16.87% |
| susceptibility | cell_exact | Emergency | 36 | 6 | 16.7% [5.6, 30.6] | 3,872,871 | 0.000% [0.000, 0.000] | 7.03% |
| ed_threshold | tolerant | Watch+ | 36 | 34 | 94.4% [86.1, 100.0] | 22,730,871 | 0.004% [0.003, 0.005] | 41.24% |
| ed_threshold | tolerant | Warning+ | 36 | 30 | 83.3% [69.4, 94.4] | 9,294,381 | 0.007% [0.005, 0.009] | 16.86% |
| ed_threshold | tolerant | Emergency | 36 | 26 | 72.2% [55.6, 86.1] | 3,872,506 | 0.011% [0.008, 0.015] | 7.03% |
| ed_threshold | cell_exact | Watch+ | 36 | 33 | 91.7% [80.6, 100.0] | 22,730,871 | 0.000% [0.000, 0.000] | 41.24% |
| ed_threshold | cell_exact | Warning+ | 36 | 25 | 69.4% [55.6, 83.3] | 9,294,381 | 0.000% [0.000, 0.000] | 16.86% |
| ed_threshold | cell_exact | Emergency | 36 | 18 | 50.0% [33.3, 66.7] | 3,872,506 | 0.000% [0.000, 0.001] | 7.03% |
| ed_threshold_refit | tolerant | Watch+ | 36 | 35 | 97.2% [91.7, 100.0] | 22,730,892 | 0.004% [0.003, 0.005] | 41.24% |
| ed_threshold_refit | tolerant | Warning+ | 36 | 32 | 88.9% [77.8, 97.2] | 9,294,374 | 0.007% [0.005, 0.009] | 16.86% |
| ed_threshold_refit | tolerant | Emergency | 36 | 27 | 75.0% [61.1, 88.9] | 3,872,497 | 0.011% [0.007, 0.015] | 7.03% |
| ed_threshold_refit | cell_exact | Watch+ | 36 | 33 | 91.7% [80.6, 100.0] | 22,730,892 | 0.000% [0.000, 0.000] | 41.24% |
| ed_threshold_refit | cell_exact | Warning+ | 36 | 23 | 63.9% [47.2, 77.8] | 9,294,374 | 0.000% [0.000, 0.000] | 16.86% |
| ed_threshold_refit | cell_exact | Emergency | 36 | 18 | 50.0% [33.3, 66.7] | 3,872,497 | 0.000% [0.000, 0.001] | 7.03% |

Alert shares, target against realised (pooled over the set's seasons):

| model | target Watch+ / Warning+ / Emergency | realised |
|---|---|---|
| v3 | n/a | 41.25% / 16.87% / 7.03% |
| rain_3d | 41.25% / 16.87% / 7.03% | 41.25% / 16.87% / 7.03% |
| rain_3d_devcuts | 57.98% / 24.72% / 10.19% | 38.82% / 15.70% / 6.59% |
| susceptibility | 41.25% / 16.87% / 7.03% | 41.25% / 16.87% / 7.03% |
| ed_threshold | 41.25% / 16.87% / 7.03% | 41.24% / 16.86% / 7.03% |
| ed_threshold_refit | 41.25% / 16.87% / 7.03% | 41.24% / 16.86% / 7.03% |

## POOLED (36,792 cells, 1712 days, 92 events)

S2018 and S1925 together. Events by source: catalog_2018 56, catalog_sparse 6, reported 30. 87 distinct when events within 10 km and a day are merged; 1 further events are dated outside the panel days and not scored.

| model | tolerance | level | events | hits | POD [95% CI] | alert cell-days | precision [95% CI] | realised share |
|---|---|---|---|---|---|---|---|---|
| v3 | tolerant | Watch+ | 92 | 90 | 97.8% [94.6, 100.0] | 25,582,037 | 0.009% [0.007, 0.011] | 40.61% |
| v3 | tolerant | Warning+ | 92 | 84 | 91.3% [84.8, 96.7] | 10,356,868 | 0.017% [0.013, 0.021] | 16.44% |
| v3 | tolerant | Emergency | 92 | 78 | 84.8% [77.2, 91.3] | 4,275,304 | 0.029% [0.021, 0.038] | 6.79% |
| v3 | cell_exact | Watch+ | 92 | 84 | 91.3% [84.8, 96.7] | 25,582,037 | 0.000% [0.000, 0.000] | 40.61% |
| v3 | cell_exact | Warning+ | 92 | 69 | 75.0% [66.3, 83.7] | 10,356,868 | 0.001% [0.000, 0.001] | 16.44% |
| v3 | cell_exact | Emergency | 92 | 52 | 56.5% [45.7, 67.4] | 4,275,304 | 0.001% [0.001, 0.002] | 6.79% |
| rain_3d | tolerant | Watch+ | 92 | 88 | 95.7% [91.3, 98.9] | 25,582,069 | 0.008% [0.006, 0.010] | 40.61% |
| rain_3d | tolerant | Warning+ | 92 | 70 | 76.1% [67.4, 84.8] | 10,356,849 | 0.013% [0.010, 0.018] | 16.44% |
| rain_3d | tolerant | Emergency | 92 | 59 | 64.1% [54.3, 73.9] | 4,275,299 | 0.026% [0.017, 0.034] | 6.79% |
| rain_3d | cell_exact | Watch+ | 92 | 76 | 82.6% [75.0, 90.2] | 25,582,069 | 0.000% [0.000, 0.000] | 40.61% |
| rain_3d | cell_exact | Warning+ | 92 | 53 | 57.6% [47.8, 67.4] | 10,356,849 | 0.001% [0.000, 0.001] | 16.44% |
| rain_3d | cell_exact | Emergency | 92 | 42 | 45.7% [35.9, 56.5] | 4,275,299 | 0.001% [0.001, 0.001] | 6.79% |
| rain_3d_devcuts | tolerant | Watch+ | 92 | 86 | 93.5% [88.0, 97.8] | 24,017,862 | 0.008% [0.007, 0.011] | 38.13% |
| rain_3d_devcuts | tolerant | Warning+ | 92 | 69 | 75.0% [66.3, 83.7] | 9,629,368 | 0.014% [0.010, 0.019] | 15.29% |
| rain_3d_devcuts | tolerant | Emergency | 92 | 58 | 63.0% [53.3, 72.8] | 4,015,594 | 0.027% [0.018, 0.037] | 6.38% |
| rain_3d_devcuts | cell_exact | Watch+ | 92 | 73 | 79.3% [71.7, 87.0] | 24,017,862 | 0.000% [0.000, 0.000] | 38.13% |
| rain_3d_devcuts | cell_exact | Warning+ | 92 | 52 | 56.5% [46.7, 66.3] | 9,629,368 | 0.001% [0.000, 0.001] | 15.29% |
| rain_3d_devcuts | cell_exact | Emergency | 92 | 42 | 45.7% [35.9, 56.5] | 4,015,594 | 0.001% [0.001, 0.002] | 6.38% |
| susceptibility | tolerant | Watch+ | 92 | 88 | 95.7% [91.3, 98.9] | 25,582,037 | 0.008% [0.006, 0.010] | 40.61% |
| susceptibility | tolerant | Warning+ | 92 | 77 | 83.7% [75.0, 91.3] | 10,356,868 | 0.009% [0.007, 0.011] | 16.44% |
| susceptibility | tolerant | Emergency | 92 | 54 | 58.7% [47.8, 68.5] | 4,275,304 | 0.009% [0.006, 0.011] | 6.79% |
| susceptibility | cell_exact | Watch+ | 92 | 79 | 85.9% [78.3, 92.4] | 25,582,037 | 0.000% [0.000, 0.000] | 40.61% |
| susceptibility | cell_exact | Warning+ | 92 | 32 | 34.8% [25.0, 44.6] | 10,356,868 | 0.000% [0.000, 0.000] | 16.44% |
| susceptibility | cell_exact | Emergency | 92 | 19 | 20.7% [13.0, 29.3] | 4,275,304 | 0.000% [0.000, 0.001] | 6.79% |
| ed_threshold | tolerant | Watch+ | 92 | 88 | 95.7% [91.3, 98.9] | 25,579,345 | 0.008% [0.006, 0.010] | 40.61% |
| ed_threshold | tolerant | Warning+ | 92 | 70 | 76.1% [67.4, 84.8] | 10,355,807 | 0.014% [0.011, 0.019] | 16.44% |
| ed_threshold | tolerant | Emergency | 92 | 56 | 60.9% [51.1, 70.7] | 4,274,871 | 0.024% [0.016, 0.033] | 6.79% |
| ed_threshold | cell_exact | Watch+ | 92 | 79 | 85.9% [78.3, 92.4] | 25,579,345 | 0.000% [0.000, 0.000] | 40.61% |
| ed_threshold | cell_exact | Warning+ | 92 | 59 | 64.1% [54.3, 73.9] | 10,355,807 | 0.001% [0.000, 0.001] | 16.44% |
| ed_threshold | cell_exact | Emergency | 92 | 42 | 45.7% [35.8, 55.4] | 4,274,871 | 0.001% [0.001, 0.001] | 6.79% |
| ed_threshold_refit | tolerant | Watch+ | 92 | 89 | 96.7% [92.4, 100.0] | 25,579,377 | 0.008% [0.006, 0.010] | 40.61% |
| ed_threshold_refit | tolerant | Warning+ | 92 | 73 | 79.3% [70.7, 88.0] | 10,355,800 | 0.014% [0.011, 0.019] | 16.44% |
| ed_threshold_refit | tolerant | Emergency | 92 | 60 | 65.2% [55.4, 75.0] | 4,274,862 | 0.023% [0.015, 0.031] | 6.79% |
| ed_threshold_refit | cell_exact | Watch+ | 92 | 78 | 84.8% [77.2, 91.3] | 25,579,377 | 0.000% [0.000, 0.000] | 40.61% |
| ed_threshold_refit | cell_exact | Warning+ | 92 | 57 | 62.0% [52.2, 71.7] | 10,355,800 | 0.001% [0.000, 0.001] | 16.44% |
| ed_threshold_refit | cell_exact | Emergency | 92 | 43 | 46.7% [37.0, 56.5] | 4,274,862 | 0.001% [0.001, 0.001] | 6.79% |

Alert shares, target against realised (pooled over the set's seasons):

| model | target Watch+ / Warning+ / Emergency | realised |
|---|---|---|
| v3 | n/a | 40.61% / 16.44% / 6.79% |
| rain_3d | 40.61% / 16.44% / 6.79% | 40.61% / 16.44% / 6.79% |
| rain_3d_devcuts | 57.98% / 24.72% / 10.19% | 38.13% / 15.29% / 6.38% |
| susceptibility | 40.61% / 16.44% / 6.79% | 40.61% / 16.44% / 6.79% |
| ed_threshold | 40.61% / 16.44% / 6.79% | 40.61% / 16.44% / 6.79% |
| ed_threshold_refit | 40.61% / 16.44% / 6.79% | 40.61% / 16.44% / 6.79% |

## L1820 (36,792 cells, 642 days, 65 events)

2018-2020, the years LHASA covers: every model, LHASA included, on the same days and events. Events by source: catalog_2018 56, catalog_sparse 4, reported 5. 60 distinct when events within 10 km and a day are merged; 1 further events are dated outside the panel days and not scored.

| model | tolerance | level | events | hits | POD [95% CI] | alert cell-days | precision [95% CI] | realised share |
|---|---|---|---|---|---|---|---|---|
| v3 | tolerant | Watch+ | 65 | 63 | 96.9% [92.3, 100.0] | 9,537,743 | 0.016% [0.011, 0.022] | 40.38% |
| v3 | tolerant | Warning+ | 65 | 57 | 87.7% [78.5, 95.4] | 3,785,006 | 0.032% [0.021, 0.043] | 16.02% |
| v3 | tolerant | Emergency | 65 | 54 | 83.1% [72.3, 90.8] | 1,531,755 | 0.056% [0.034, 0.080] | 6.48% |
| v3 | cell_exact | Watch+ | 65 | 58 | 89.2% [81.5, 95.4] | 9,537,743 | 0.001% [0.000, 0.001] | 40.38% |
| v3 | cell_exact | Warning+ | 65 | 50 | 76.9% [66.2, 86.2] | 3,785,006 | 0.001% [0.001, 0.002] | 16.02% |
| v3 | cell_exact | Emergency | 65 | 37 | 56.9% [44.6, 69.2] | 1,531,755 | 0.002% [0.001, 0.004] | 6.48% |
| rain_3d | tolerant | Watch+ | 65 | 62 | 95.4% [89.2, 100.0] | 9,537,731 | 0.015% [0.010, 0.020] | 40.38% |
| rain_3d | tolerant | Warning+ | 65 | 48 | 73.8% [63.1, 84.6] | 3,785,005 | 0.026% [0.016, 0.038] | 16.02% |
| rain_3d | tolerant | Emergency | 65 | 41 | 63.1% [50.8, 75.4] | 1,531,748 | 0.051% [0.030, 0.074] | 6.48% |
| rain_3d | cell_exact | Watch+ | 65 | 53 | 81.5% [72.3, 90.8] | 9,537,731 | 0.001% [0.000, 0.001] | 40.38% |
| rain_3d | cell_exact | Warning+ | 65 | 39 | 60.0% [47.7, 70.8] | 3,785,005 | 0.001% [0.001, 0.002] | 16.02% |
| rain_3d | cell_exact | Emergency | 65 | 31 | 47.7% [35.4, 60.0] | 1,531,748 | 0.002% [0.001, 0.003] | 6.48% |
| rain_3d_devcuts | tolerant | Watch+ | 65 | 60 | 92.3% [86.2, 98.5] | 8,928,673 | 0.016% [0.011, 0.021] | 37.80% |
| rain_3d_devcuts | tolerant | Warning+ | 65 | 47 | 72.3% [60.0, 83.1] | 3,526,512 | 0.027% [0.017, 0.039] | 14.93% |
| rain_3d_devcuts | tolerant | Emergency | 65 | 41 | 63.1% [50.8, 75.4] | 1,469,526 | 0.053% [0.032, 0.077] | 6.22% |
| rain_3d_devcuts | cell_exact | Watch+ | 65 | 52 | 80.0% [69.2, 89.2] | 8,928,673 | 0.001% [0.000, 0.001] | 37.80% |
| rain_3d_devcuts | cell_exact | Warning+ | 65 | 38 | 58.5% [44.6, 70.8] | 3,526,512 | 0.001% [0.001, 0.002] | 14.93% |
| rain_3d_devcuts | cell_exact | Emergency | 65 | 31 | 47.7% [35.4, 60.0] | 1,469,526 | 0.002% [0.001, 0.003] | 6.22% |
| susceptibility | tolerant | Watch+ | 65 | 61 | 93.8% [87.7, 98.5] | 9,537,743 | 0.015% [0.011, 0.020] | 40.38% |
| susceptibility | tolerant | Warning+ | 65 | 53 | 81.5% [72.3, 89.3] | 3,785,006 | 0.016% [0.011, 0.022] | 16.02% |
| susceptibility | tolerant | Emergency | 65 | 36 | 55.4% [43.1, 66.2] | 1,531,755 | 0.017% [0.011, 0.024] | 6.48% |
| susceptibility | cell_exact | Watch+ | 65 | 57 | 87.7% [78.5, 95.4] | 9,537,743 | 0.001% [0.000, 0.001] | 40.38% |
| susceptibility | cell_exact | Warning+ | 65 | 22 | 33.8% [23.1, 44.6] | 3,785,006 | 0.001% [0.000, 0.001] | 16.02% |
| susceptibility | cell_exact | Emergency | 65 | 14 | 21.5% [12.3, 32.3] | 1,531,755 | 0.001% [0.000, 0.001] | 6.48% |
| lhasa_v2_m1 | tolerant | Watch+ | 65 | 62 | 95.4% [90.8, 100.0] | 9,493,480 | 0.016% [0.011, 0.021] | 40.19% |
| lhasa_v2_m1 | tolerant | Warning+ | 65 | 55 | 84.6% [75.4, 92.3] | 3,767,420 | 0.026% [0.017, 0.037] | 15.95% |
| lhasa_v2_m1 | tolerant | Emergency | 65 | 43 | 66.2% [53.8, 78.5] | 1,524,589 | 0.047% [0.028, 0.070] | 6.45% |
| lhasa_v2_m1 | cell_exact | Watch+ | 65 | 57 | 87.7% [78.5, 95.4] | 9,493,480 | 0.001% [0.000, 0.001] | 40.19% |
| lhasa_v2_m1 | cell_exact | Warning+ | 65 | 38 | 58.5% [46.2, 70.8] | 3,767,420 | 0.001% [0.001, 0.002] | 15.95% |
| lhasa_v2_m1 | cell_exact | Emergency | 65 | 28 | 43.1% [30.8, 55.4] | 1,524,589 | 0.002% [0.001, 0.003] | 6.45% |
| lhasa_v2 | tolerant | Watch+ | 65 | 62 | 95.4% [90.8, 100.0] | 9,534,700 | 0.016% [0.011, 0.022] | 40.37% |
| lhasa_v2 | tolerant | Warning+ | 65 | 54 | 83.1% [73.8, 90.8] | 3,785,923 | 0.028% [0.018, 0.040] | 16.03% |
| lhasa_v2 | tolerant | Emergency | 65 | 42 | 64.6% [52.3, 76.9] | 1,531,745 | 0.047% [0.028, 0.068] | 6.48% |
| lhasa_v2 | cell_exact | Watch+ | 65 | 61 | 93.8% [87.7, 98.5] | 9,534,700 | 0.001% [0.000, 0.001] | 40.37% |
| lhasa_v2 | cell_exact | Warning+ | 65 | 41 | 63.1% [50.8, 73.8] | 3,785,923 | 0.001% [0.001, 0.002] | 16.03% |
| lhasa_v2 | cell_exact | Emergency | 65 | 32 | 49.2% [36.9, 61.5] | 1,531,745 | 0.002% [0.001, 0.003] | 6.48% |
| lhasa_v2_p1 | tolerant | Watch+ | 65 | 61 | 93.8% [87.7, 98.5] | 9,492,906 | 0.016% [0.011, 0.021] | 40.19% |
| lhasa_v2_p1 | tolerant | Warning+ | 65 | 48 | 73.8% [61.5, 83.1] | 3,766,028 | 0.027% [0.017, 0.038] | 15.94% |
| lhasa_v2_p1 | tolerant | Emergency | 65 | 40 | 61.5% [49.2, 72.3] | 1,524,582 | 0.040% [0.025, 0.059] | 6.45% |
| lhasa_v2_p1 | cell_exact | Watch+ | 65 | 56 | 86.2% [76.9, 93.8] | 9,492,906 | 0.001% [0.000, 0.001] | 40.19% |
| lhasa_v2_p1 | cell_exact | Warning+ | 65 | 41 | 63.1% [50.8, 73.9] | 3,766,028 | 0.001% [0.001, 0.002] | 15.94% |
| lhasa_v2_p1 | cell_exact | Emergency | 65 | 25 | 38.5% [26.2, 50.8] | 1,524,582 | 0.002% [0.001, 0.003] | 6.45% |
| ed_threshold | tolerant | Watch+ | 65 | 63 | 96.9% [92.3, 100.0] | 9,536,428 | 0.015% [0.010, 0.020] | 40.37% |
| ed_threshold | tolerant | Warning+ | 65 | 49 | 75.4% [64.6, 84.7] | 3,784,502 | 0.027% [0.017, 0.039] | 16.02% |
| ed_threshold | tolerant | Emergency | 65 | 37 | 56.9% [44.6, 67.7] | 1,531,552 | 0.049% [0.028, 0.072] | 6.48% |
| ed_threshold | cell_exact | Watch+ | 65 | 55 | 84.6% [75.4, 92.3] | 9,536,428 | 0.001% [0.000, 0.001] | 40.37% |
| ed_threshold | cell_exact | Warning+ | 65 | 42 | 64.6% [52.3, 75.4] | 3,784,502 | 0.001% [0.001, 0.002] | 16.02% |
| ed_threshold | cell_exact | Emergency | 65 | 31 | 47.7% [35.4, 60.0] | 1,531,552 | 0.002% [0.001, 0.003] | 6.48% |
| ed_threshold_refit | tolerant | Watch+ | 65 | 63 | 96.9% [92.3, 100.0] | 9,536,455 | 0.014% [0.010, 0.020] | 40.37% |
| ed_threshold_refit | tolerant | Warning+ | 65 | 50 | 76.9% [66.2, 86.2] | 3,784,499 | 0.028% [0.017, 0.039] | 16.02% |
| ed_threshold_refit | tolerant | Emergency | 65 | 41 | 63.1% [50.8, 73.8] | 1,531,549 | 0.046% [0.026, 0.069] | 6.48% |
| ed_threshold_refit | cell_exact | Watch+ | 65 | 54 | 83.1% [73.8, 92.3] | 9,536,455 | 0.001% [0.000, 0.001] | 40.37% |
| ed_threshold_refit | cell_exact | Warning+ | 65 | 42 | 64.6% [52.3, 75.4] | 3,784,499 | 0.001% [0.001, 0.002] | 16.02% |
| ed_threshold_refit | cell_exact | Emergency | 65 | 32 | 49.2% [36.9, 61.5] | 1,531,549 | 0.002% [0.001, 0.004] | 6.48% |

Alert shares, target against realised (pooled over the set's seasons):

| model | target Watch+ / Warning+ / Emergency | realised |
|---|---|---|
| v3 | n/a | 40.38% / 16.02% / 6.48% |
| rain_3d | 40.38% / 16.02% / 6.48% | 40.38% / 16.02% / 6.48% |
| rain_3d_devcuts | 57.98% / 24.72% / 10.19% | 37.80% / 14.93% / 6.22% |
| susceptibility | 40.38% / 16.02% / 6.48% | 40.38% / 16.02% / 6.48% |
| lhasa_v2_m1 | 40.38% / 16.02% / 6.48% | 40.19% / 15.95% / 6.45% |
| lhasa_v2 | 40.38% / 16.02% / 6.48% | 40.37% / 16.03% / 6.48% |
| lhasa_v2_p1 | 40.38% / 16.02% / 6.48% | 40.19% / 15.94% / 6.45% |
| ed_threshold | 40.38% / 16.02% / 6.48% | 40.37% / 16.02% / 6.48% |
| ed_threshold_refit | 40.38% / 16.02% / 6.48% | 40.37% / 16.02% / 6.48% |
