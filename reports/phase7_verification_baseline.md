# Verification baseline (phase 7, W0)

v3 against two simple models that raise the same alert burden: three 3-day rain cuts fitted to v3's development shares (`rain_3d`), and a static map (season-mean v3 risk) alerted at v3's shares of the evaluated set (`susceptibility`). POD is the share of events whose highest level within tolerance reached the level; precision is the share of alert cell-days that an event lies within tolerance of. `tolerant` is 10 km and 1 day, `cell_exact` the same cell and day. Intervals are 95% percentile bootstraps (days resampled for precision, events for POD).

## Reading this report

- 2018 is re-measured with the frozen v3 and is not a new held-out look. Its v3 cell-exact Watch+ / Warning+ / Emergency hits, 48 / 40 / 30, equal the published ones.
- Development panels hold every event cell and a seeded sample of universe cells. Alert cell-days, precision and alert share are counted on the universe-sample cells only (a random sample, so unbiased) and are not scaled up to the full universe; POD is over all development events.
- Tolerant matching on development panels only sees the panel cells, so the tolerant development POD is a lower bound. 2018 (all cells) is the primary tolerant measurement.
- The rain baseline's cuts are fitted on the development universe-sample cell-days and applied unchanged to 2018; on the development panels they are applied to the data they were fitted on.
- `susceptibility` is the static map (season-mean v3 risk): each day the scored cells of highest mean risk are alerted, with no rain.

## 2018 (36,792 cells, 122 days, 56 events)

| model | tolerance | level | events | hits | POD [95% CI] | alert cell-days | precision [95% CI] | realised share |
|---|---|---|---|---|---|---|---|---|
| v3 | tolerant | Watch+ | 56 | 55 | 98.2% [94.6, 100.0] | 2,468,948 | 0.054% [0.036, 0.073] | 55.46% |
| v3 | tolerant | Warning+ | 56 | 49 | 87.5% [78.6, 96.4] | 996,517 | 0.101% [0.066, 0.140] | 22.38% |
| v3 | tolerant | Emergency | 56 | 45 | 80.4% [69.6, 91.1] | 386,775 | 0.184% [0.106, 0.271] | 8.69% |
| v3 | cell_exact | Watch+ | 56 | 48 | 85.7% [76.8, 94.6] | 2,468,948 | 0.002% [0.001, 0.003] | 55.46% |
| v3 | cell_exact | Warning+ | 56 | 40 | 71.4% [58.9, 82.2] | 996,517 | 0.004% [0.002, 0.006] | 22.38% |
| v3 | cell_exact | Emergency | 56 | 30 | 53.6% [39.3, 66.1] | 386,775 | 0.008% [0.004, 0.012] | 8.69% |
| rain_3d | tolerant | Watch+ | 56 | 52 | 92.9% [85.7, 98.2] | 2,366,957 | 0.049% [0.032, 0.067] | 53.17% |
| rain_3d | tolerant | Warning+ | 56 | 39 | 69.6% [57.1, 82.1] | 914,624 | 0.086% [0.049, 0.127] | 20.54% |
| rain_3d | tolerant | Emergency | 56 | 33 | 58.9% [44.6, 71.4] | 370,131 | 0.168% [0.091, 0.254] | 8.31% |
| rain_3d | cell_exact | Watch+ | 56 | 42 | 75.0% [62.5, 85.8] | 2,366,957 | 0.002% [0.001, 0.003] | 53.17% |
| rain_3d | cell_exact | Warning+ | 56 | 29 | 51.8% [39.3, 64.3] | 914,624 | 0.003% [0.001, 0.005] | 20.54% |
| rain_3d | cell_exact | Emergency | 56 | 24 | 42.9% [30.4, 55.4] | 370,131 | 0.006% [0.003, 0.011] | 8.31% |
| susceptibility | tolerant | Watch+ | 56 | 55 | 98.2% [94.6, 100.0] | 2,468,948 | 0.058% [0.040, 0.077] | 55.46% |
| susceptibility | tolerant | Warning+ | 56 | 48 | 85.7% [76.8, 94.6] | 996,517 | 0.081% [0.056, 0.109] | 22.38% |
| susceptibility | tolerant | Emergency | 56 | 39 | 69.6% [57.1, 82.1] | 386,775 | 0.088% [0.057, 0.123] | 8.69% |
| susceptibility | cell_exact | Watch+ | 56 | 52 | 92.9% [85.7, 98.2] | 2,468,948 | 0.002% [0.001, 0.003] | 55.46% |
| susceptibility | cell_exact | Warning+ | 56 | 27 | 48.2% [33.9, 60.7] | 996,517 | 0.003% [0.002, 0.004] | 22.38% |
| susceptibility | cell_exact | Emergency | 56 | 13 | 23.2% [12.5, 35.7] | 386,775 | 0.003% [0.002, 0.005] | 8.69% |

Alert shares, target against realised:

| model | target Watch+ / Warning+ / Emergency | realised |
|---|---|---|
| v3 | n/a | 55.46% / 22.38% / 8.69% |
| rain_3d | 57.98% / 24.72% / 10.19% | 53.17% / 20.54% / 8.31% |
| susceptibility | 55.46% / 22.38% / 8.69% | 55.46% / 22.38% / 8.69% |

## Development 2007-2017, out of fold (5,415 cells, of which 5,000 universe-sample cells counted for alerts; 1342 days, 636 events)

| model | tolerance | level | events | hits | POD [95% CI] | alert cell-days | precision [95% CI] | realised share |
|---|---|---|---|---|---|---|---|---|
| v3 | tolerant | Watch+ | 636 | 628 | 98.7% [97.8, 99.5] | 3,890,709 | 0.056% [0.051, 0.062] | 57.98% |
| v3 | tolerant | Warning+ | 636 | 595 | 93.6% [91.5, 95.4] | 1,658,817 | 0.105% [0.095, 0.116] | 24.72% |
| v3 | tolerant | Emergency | 636 | 521 | 81.9% [78.6, 84.7] | 683,446 | 0.171% [0.152, 0.191] | 10.19% |
| v3 | cell_exact | Watch+ | 636 | 618 | 97.2% [95.8, 98.4] | 3,890,709 | 0.002% [0.002, 0.003] | 57.98% |
| v3 | cell_exact | Warning+ | 636 | 539 | 84.7% [81.9, 87.6] | 1,658,817 | 0.005% [0.004, 0.006] | 24.72% |
| v3 | cell_exact | Emergency | 636 | 402 | 63.2% [59.3, 66.8] | 683,446 | 0.009% [0.007, 0.011] | 10.19% |
| rain_3d | tolerant | Watch+ | 636 | 619 | 97.3% [95.9, 98.4] | 3,890,705 | 0.053% [0.048, 0.058] | 57.98% |
| rain_3d | tolerant | Warning+ | 636 | 531 | 83.5% [80.5, 86.3] | 1,658,818 | 0.088% [0.079, 0.097] | 24.72% |
| rain_3d | tolerant | Emergency | 636 | 404 | 63.5% [59.7, 67.3] | 683,446 | 0.128% [0.111, 0.145] | 10.19% |
| rain_3d | cell_exact | Watch+ | 636 | 585 | 92.0% [89.9, 93.9] | 3,890,705 | 0.002% [0.002, 0.003] | 57.98% |
| rain_3d | cell_exact | Warning+ | 636 | 435 | 68.4% [64.9, 71.9] | 1,658,818 | 0.004% [0.003, 0.005] | 24.72% |
| rain_3d | cell_exact | Emergency | 636 | 277 | 43.6% [39.6, 47.5] | 683,446 | 0.006% [0.004, 0.008] | 10.19% |
| susceptibility | tolerant | Watch+ | 636 | 626 | 98.4% [97.3, 99.4] | 3,890,711 | 0.055% [0.050, 0.060] | 57.98% |
| susceptibility | tolerant | Warning+ | 636 | 543 | 85.4% [82.4, 88.2] | 1,658,822 | 0.093% [0.083, 0.102] | 24.72% |
| susceptibility | tolerant | Emergency | 636 | 402 | 63.2% [59.3, 66.8] | 683,441 | 0.127% [0.112, 0.140] | 10.19% |
| susceptibility | cell_exact | Watch+ | 636 | 616 | 96.9% [95.4, 98.1] | 3,890,711 | 0.002% [0.002, 0.003] | 57.98% |
| susceptibility | cell_exact | Warning+ | 636 | 470 | 73.9% [70.3, 77.4] | 1,658,822 | 0.004% [0.003, 0.005] | 24.72% |
| susceptibility | cell_exact | Emergency | 636 | 285 | 44.8% [40.9, 48.7] | 683,441 | 0.007% [0.005, 0.009] | 10.19% |

Alert shares on the universe-sample cells, target against realised:

| model | target Watch+ / Warning+ / Emergency | realised |
|---|---|---|
| v3 | n/a | 57.98% / 24.72% / 10.19% |
| rain_3d | 57.98% / 24.72% / 10.19% | 57.98% / 24.72% / 10.19% |
| susceptibility | 57.98% / 24.72% / 10.19% | 57.98% / 24.72% / 10.19% |
