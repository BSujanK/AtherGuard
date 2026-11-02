# Phase 6 operational backtest of the v3-live model

Generated 2026-10-15T23:16:05Z with the frozen model in `data/processed/hazard/model_v3_live` (card sha256 `8fffe291f8708f54`). For every day of each window the same frozen model is scored twice on the same cells: with the features the 11:00 IST live run would have had (Late through UTC D-2, Early for UTC D-1, the GFS or persisted 00-03 UTC tail, nothing issued after the cut-off) and with the training-style features (Late run for every UTC day including all of UTC D). The difference is the **train/live gap** that the spec section 10 substitutions cause. Local stores only: no network was used.

Reading guide. *Model Watch rule*: raw score at or above the frozen recall-first threshold, the rule of the test_2018 evaluation. *Alert levels*: calibrated risk against each region's card thresholds, the `uncertain_high` rule and the hysteresis of the live state, run over consecutive days; the alert engine's source-agreement, gauge and blind-escalation rules are not applied (no IMD real-time archive or gauge history is on disk). Events are the labelled cell-days; a cell-day without a score (an input day missing from the local stores) counts as a miss in the 'of all events' column and is dropped in the 'of scored events' column. Intervals are 95% percentile bootstraps (events resampled, or days resampled for shares).

Reference, test_2018 evaluation (training-style inputs, whole year, `reports/phase6_live_model_report.md`): detection 83.8% [75.0, 91.2], share of cell-days on alert 21.2% [21.0, 21.4]. The backtest covers the monsoon season only, so its alert share is not the annual one.

## Summary

| set | rule | detection, operational (own cell) | detection, training-style | alert share, operational | alert share, training-style | persist_d1 days |
|---|---|---|---|---|---|---|
| season_2018 | model Watch rule (raw score) | 82% [71, 91] | 86% [75, 95] | 39.09% | 38.83% | 100% |
| season_2018 | alert levels (risk, hysteresis) | 91% [82, 98] | 91% [82, 98] | 56.37% | 55.47% | 100% |
| window_2023 | model Watch rule (raw score) | - | - | 48.09% | 47.64% | 0% |
| window_2023 | alert levels (risk, hysteresis) | - | - | 64.68% | 63.84% | 0% |
| kerala_2018 | model Watch rule (raw score) | 96% [87, 100] | 100% [100, 100] | 28.82% | 28.51% | 100% |
| kerala_2018 | alert levels (risk, hysteresis) | 100% [100, 100] | 100% [100, 100] | 44.27% | 43.13% | 100% |
| wayanad_2024 | model Watch rule (raw score) | - | - | 78.44% | 86.59% | 0% |
| wayanad_2024 | alert levels (risk, hysteresis) | - | - | 96.04% | 97.01% | 0% |

## 2018 monsoon season (1 Jun - 30 Sep), universe cells, test_2018 positives

universe cells and the in-domain test_2018 positives of the window. 36,792 cells (himalaya 28,744, western_ghats 8,048), 122 days from 2018-06-01, 7 warm-up days scored before it for the hysteresis state; ran in 1142 s.

Input products over 122 days: 00-03 UTC tail of IMD day D: persist_d1 122; UTC D-1: early 121, missing 1. `persist_d1` share: 100.0% of days (122/122). Days with no operational score at all: 1; with no training-style score: 0.

### Detection of the labelled events

| rule | features | events | scored | own cell, of all events [95% CI] | own cell, of scored events | 3x3 footprint, of all events | Watch+ within 7 days up to the event | median lead (days) | chance rate: any scored cell Watch+ within 7 days |
|---|---|---|---|---|---|---|---|---|---|
| model Watch rule (raw score) | operational (live inputs) | 56 | 55 | 82.1% [71.4, 91.1] | 83.6% [72.7, 92.7] | 91.1% [82.1, 98.2] | 89.3% [80.4, 96.4] | 7.0 | 55.59% |
| model Watch rule (raw score) | training-style (Late only) | 56 | 56 | 85.7% [75.0, 94.6] | 85.7% [75.0, 94.6] | 92.9% [85.7, 98.2] | 91.1% [82.1, 98.2] | 7.0 | 54.09% |
| alert levels (risk, hysteresis) | operational (live inputs) | 56 | 55 | 91.1% [82.1, 98.2] | 92.7% [85.5, 98.2] | 96.4% [91.1, 100.0] | 92.9% [85.7, 98.2] | 7.0 | 68.37% |
| alert levels (risk, hysteresis) | training-style (Late only) | 56 | 56 | 91.1% [82.1, 98.2] | 91.1% [82.1, 98.2] | 98.2% [94.6, 100.0] | 94.6% [87.5, 100.0] | 7.0 | 66.96% |

The lead time saturates at 7 days whenever the alert share is high. The last column is the share of all scored cell-days with a Watch+ day among the 7 days before and the day itself, i.e. what an event cell would show by luck; a lead or a 7-day detection is informative only against that rate.

### Share of scored cell-days at Watch or above (mean over days, bootstrap over days)

| rule | features | mean daily share [95% CI] | median | max | by region | levels |
|---|---|---|---|---|---|---|
| model Watch rule (raw score) | operational (live inputs) | 39.09% [37.84, 40.30] | 39.77% | 52.02% | himalaya 42.13%, western_ghats 28.22% | - |
| model Watch rule (raw score) | training-style (Late only) | 38.83% [37.70, 39.96] | 39.81% | 50.35% | himalaya 41.96%, western_ghats 27.65% | - |
| alert levels (risk, hysteresis) | operational (live inputs) | 56.37% [55.15, 57.58] | 57.18% | 68.24% | himalaya 60.35%, western_ghats 42.18% | Warning+ 22.65%, Emergency 8.71% |
| alert levels (risk, hysteresis) | training-style (Late only) | 55.47% [54.36, 56.61] | 56.55% | 67.03% | himalaya 59.54%, western_ghats 40.94% | Warning+ 21.49%, Emergency 8.20% |

### The train/live gap (operational minus training-style, same cells and days)

| rule | change in the daily alert share | Watch+ set overlap (Jaccard, mean over days) | events |
|---|---|---|---|
| model Watch rule (raw score) | +0.15 points [-0.03, +0.33] | 0.916 | both 45, only operational 1, only training-style 3, neither 7 |
| alert levels (risk, hysteresis) | +0.82 points [+0.69, +0.95] | 0.951 | both 50, only operational 1, only training-style 1, neither 4 |

Mean absolute difference of the features: 1-day rain 2.14 mm, 3-day rain 2.36 mm. Rank correlation of the raw scores of the two variants over the same cells: mean 0.9881, worst day 0.9752.

Alert levels with the pooled risk thresholds, as `live/run.py` applies them today (region-calibrated risk against the pooled card thresholds), against the region thresholds above: operational Watch+ share 50.87% (pooled) versus 56.37% (region).

Event detection, own cell: 91.1% [82.1, 98.2] (pooled) versus 91.1% [82.1, 98.2] (region).

## 2023 India window (16 Jun - 31 Jul), window cells

window-positive cells with their 8 neighbours and the control cells of the frozen window table. 4,093 cells (himalaya 4,093), 46 days from 2023-06-16, 7 warm-up days scored before it for the hysteresis state; ran in 92 s.

Input products over 46 days: 00-03 UTC tail of IMD day D: gfs_00z_0_3h 46; UTC D-1: early 46. `persist_d1` share: 0.0% of days (0/46). Days with no operational score at all: 0; with no training-style score: 0.

### Window test (maximum over the window days of the 3x3 neighbourhood of each window-positive cell)

| rule | features | detected | detection share [95% CI] | controls alerted | control any-alert share [95% CI] | control cell-days alerted |
|---|---|---|---|---|---|---|
| model Watch rule (raw score) | operational (live inputs) | 24/24 | 100.0% [100.0, 100.0] | 3175/4000 | 79.4% [78.1, 80.7] | 47.2% |
| model Watch rule (raw score) | training-style (Late only) | 24/24 | 100.0% [100.0, 100.0] | 3113/4000 | 77.8% [76.6, 79.2] | 46.8% |
| alert levels (risk, hysteresis) | operational (live inputs) | 24/24 | 100.0% [100.0, 100.0] | 3587/4000 | 89.7% [88.7, 90.6] | 63.9% |
| alert levels (risk, hysteresis) | training-style (Late only) | 24/24 | 100.0% [100.0, 100.0] | 3542/4000 | 88.5% [87.5, 89.5] | 63.1% |

### Share of scored cell-days at Watch or above (mean over days, bootstrap over days)

| rule | features | mean daily share [95% CI] | median | max | by region | levels |
|---|---|---|---|---|---|---|
| model Watch rule (raw score) | operational (live inputs) | 48.09% [46.43, 49.71] | 49.82% | 57.95% | himalaya 48.09% | - |
| model Watch rule (raw score) | training-style (Late only) | 47.64% [46.00, 49.22] | 49.57% | 56.83% | himalaya 47.64% | - |
| alert levels (risk, hysteresis) | operational (live inputs) | 64.68% [62.94, 66.34] | 66.61% | 72.88% | himalaya 64.68% | Warning+ 30.47%, Emergency 13.24% |
| alert levels (risk, hysteresis) | training-style (Late only) | 63.84% [62.17, 65.42] | 65.34% | 72.44% | himalaya 63.84% | Warning+ 29.49%, Emergency 12.58% |

### The train/live gap (operational minus training-style, same cells and days)

| rule | change in the daily alert share | Watch+ set overlap (Jaccard, mean over days) | events |
|---|---|---|---|
| model Watch rule (raw score) | +0.45 points [+0.15, +0.73] | 0.927 | - |
| alert levels (risk, hysteresis) | +0.84 points [+0.60, +1.09] | 0.954 | - |

Mean absolute difference of the features: 1-day rain 3.16 mm, 3-day rain 3.47 mm. Rank correlation of the raw scores of the two variants over the same cells: mean 0.9847, worst day 0.9721.

Alert levels with the pooled risk thresholds, as `live/run.py` applies them today (region-calibrated risk against the pooled card thresholds), against the region thresholds above: operational Watch+ share 58.10% (pooled) versus 64.68% (region).

## Kerala 2018 case (1 - 20 Aug), western-ghats universe cells

every western-ghats universe cell; positives are the case table's cell-days. 8,048 cells (western_ghats 8,048), 20 days from 2018-08-01, 7 warm-up days scored before it for the hysteresis state; ran in 49 s.

Input products over 20 days: 00-03 UTC tail of IMD day D: persist_d1 20; UTC D-1: early 20. `persist_d1` share: 100.0% of days (20/20). Days with no operational score at all: 0; with no training-style score: 0.

### Detection of the labelled events

| rule | features | events | scored | own cell, of all events [95% CI] | own cell, of scored events | 3x3 footprint, of all events | Watch+ within 7 days up to the event | median lead (days) | chance rate: any scored cell Watch+ within 7 days |
|---|---|---|---|---|---|---|---|---|---|
| model Watch rule (raw score) | operational (live inputs) | 23 | 23 | 95.7% [87.0, 100.0] | 95.7% [87.0, 100.0] | 100.0% [100.0, 100.0] | 100.0% [100.0, 100.0] | 7.0 | 47.71% |
| model Watch rule (raw score) | training-style (Late only) | 23 | 23 | 100.0% [100.0, 100.0] | 100.0% [100.0, 100.0] | 100.0% [100.0, 100.0] | 100.0% [100.0, 100.0] | 7.0 | 45.22% |
| alert levels (risk, hysteresis) | operational (live inputs) | 23 | 23 | 100.0% [100.0, 100.0] | 100.0% [100.0, 100.0] | 100.0% [100.0, 100.0] | 100.0% [100.0, 100.0] | 7.0 | 57.88% |
| alert levels (risk, hysteresis) | training-style (Late only) | 23 | 23 | 100.0% [100.0, 100.0] | 100.0% [100.0, 100.0] | 100.0% [100.0, 100.0] | 100.0% [100.0, 100.0] | 7.0 | 56.51% |

The lead time saturates at 7 days whenever the alert share is high. The last column is the share of all scored cell-days with a Watch+ day among the 7 days before and the day itself, i.e. what an event cell would show by luck; a lead or a 7-day detection is informative only against that rate.

Events (alert levels with hysteresis; lead = days from the first Watch+ day within the 7 days up to the event day, 0 = first alert on the day):

| cell | date | scored (operational) | operational: own cell | lead | operational: 3x3 | training-style: own cell | lead | training-style: 3x3 |
|---|---|---|---|---|---|---|---|---|
| 20405115 | 2018-08-05 | True | yes | 4 | yes | yes | 4 | yes |
| 19945134 | 2018-08-08 | True | yes | 7 | yes | yes | 7 | yes |
| 20035135 | 2018-08-08 | True | yes | 7 | yes | yes | 7 | yes |
| 20115127 | 2018-08-08 | True | yes | 7 | yes | yes | 7 | yes |
| 20345115 | 2018-08-08 | True | yes | 7 | yes | yes | 7 | yes |
| 20565111 | 2018-08-08 | True | yes | 7 | yes | yes | 7 | yes |
| 20305120 | 2018-08-09 | True | yes | 7 | yes | yes | 7 | yes |
| 20375119 | 2018-08-09 | True | yes | 7 | yes | yes | 7 | yes |
| 20385120 | 2018-08-09 | True | yes | 7 | yes | yes | 7 | yes |
| 19945137 | 2018-08-15 | True | yes | 7 | yes | yes | 7 | yes |
| 19965134 | 2018-08-15 | True | yes | 7 | yes | yes | 7 | yes |
| 20235117 | 2018-08-15 | True | yes | 7 | yes | yes | 7 | yes |
| 20495114 | 2018-08-15 | True | yes | 7 | yes | yes | 7 | yes |
| 19965138 | 2018-08-16 | True | yes | 7 | yes | yes | 7 | yes |
| 20065129 | 2018-08-16 | True | yes | 7 | yes | yes | 7 | yes |
| 20065137 | 2018-08-16 | True | yes | 7 | yes | yes | 7 | yes |
| 20375118 | 2018-08-16 | True | yes | 7 | yes | yes | 7 | yes |
| 20485114 | 2018-08-16 | True | yes | 7 | yes | yes | 7 | yes |
| 20025142 | 2018-08-17 | True | yes | 7 | yes | yes | 7 | yes |
| 20485114 | 2018-08-17 | True | yes | 7 | yes | yes | 7 | yes |
| 19955142 | 2018-08-18 | True | yes | 7 | yes | yes | 7 | yes |
| 20565112 | 2018-08-18 | True | yes | 7 | yes | yes | 7 | yes |
| 19925142 | 2018-08-19 | True | yes | 7 | yes | yes | 7 | yes |

### Share of scored cell-days at Watch or above (mean over days, bootstrap over days)

| rule | features | mean daily share [95% CI] | median | max | by region | levels |
|---|---|---|---|---|---|---|
| model Watch rule (raw score) | operational (live inputs) | 28.82% [25.03, 32.97] | 26.55% | 57.69% | western_ghats 28.82% | - |
| model Watch rule (raw score) | training-style (Late only) | 28.51% [24.94, 32.35] | 26.72% | 54.06% | western_ghats 28.51% | - |
| alert levels (risk, hysteresis) | operational (live inputs) | 44.27% [40.25, 48.39] | 41.31% | 67.81% | western_ghats 44.27% | Warning+ 22.65%, Emergency 12.75% |
| alert levels (risk, hysteresis) | training-style (Late only) | 43.13% [39.25, 47.23] | 39.36% | 65.69% | western_ghats 43.13% | Warning+ 21.54%, Emergency 12.25% |

### The train/live gap (operational minus training-style, same cells and days)

| rule | change in the daily alert share | Watch+ set overlap (Jaccard, mean over days) | events |
|---|---|---|---|
| model Watch rule (raw score) | +0.31 points [-0.55, +1.19] | 0.867 | both 22, only operational 0, only training-style 1, neither 0 |
| alert levels (risk, hysteresis) | +1.14 points [+0.32, +1.76] | 0.914 | both 23, only operational 0, only training-style 0, neither 0 |

Mean absolute difference of the features: 1-day rain 2.50 mm, 3-day rain 2.73 mm. Rank correlation of the raw scores of the two variants over the same cells: mean 0.9875, worst day 0.9699.

Alert levels with the pooled risk thresholds, as `live/run.py` applies them today (region-calibrated risk against the pooled card thresholds), against the region thresholds above: operational Watch+ share 44.26% (pooled) versus 44.27% (region).

Event detection, own cell: 100.0% [100.0, 100.0] (pooled) versus 100.0% [100.0, 100.0] (region).

## Wayanad 2024 case (15 Jul - 5 Aug), box cells

qualitative replay of the 30 July 2024 Mundakkai event; no NASA label exists. 140 cells (western_ghats 140), 22 days from 2024-07-15, 7 warm-up days scored before it for the hysteresis state; ran in 16 s.

Input products over 22 days: 00-03 UTC tail of IMD day D: gfs_00z_0_3h 22; UTC D-1: early 22. `persist_d1` share: 0.0% of days (0/22). Days with no operational score at all: 0; with no training-style score: 0.

### Focus-cell series (first Watch+ / Warning+ day; the landslide was on 30 July 2024)

| features | Watch+ focus | Watch+ within 10 km | Watch+ box | Warning+ focus | Warning+ within 10 km | peak risk within 10 km (per 100k) | peak date |
|---|---|---|---|---|---|---|---|
| operational (live inputs) | 2024-07-15 | 2024-07-15 | 2024-07-15 | 2024-07-15 | 2024-07-15 | 41.82 | 2024-07-30 |
| training-style (Late only) | 2024-07-15 | 2024-07-15 | 2024-07-15 | 2024-07-15 | 2024-07-15 | 41.82 | 2024-07-30 |

### Share of scored cell-days at Watch or above (mean over days, bootstrap over days)

| rule | features | mean daily share [95% CI] | median | max | by region | levels |
|---|---|---|---|---|---|---|
| model Watch rule (raw score) | operational (live inputs) | 78.44% [70.45, 86.53] | 80.71% | 100.00% | western_ghats 78.44% | - |
| model Watch rule (raw score) | training-style (Late only) | 86.59% [80.36, 91.92] | 89.64% | 100.00% | western_ghats 86.59% | - |
| alert levels (risk, hysteresis) | operational (live inputs) | 96.04% [92.79, 98.47] | 98.57% | 100.00% | western_ghats 96.04% | Warning+ 69.97%, Emergency 47.99% |
| alert levels (risk, hysteresis) | training-style (Late only) | 97.01% [93.83, 98.99] | 99.29% | 100.00% | western_ghats 97.01% | Warning+ 70.68%, Emergency 50.26% |

### The train/live gap (operational minus training-style, same cells and days)

| rule | change in the daily alert share | Watch+ set overlap (Jaccard, mean over days) | events |
|---|---|---|---|
| model Watch rule (raw score) | -8.15 points [-13.54, -3.28] | 0.890 | - |
| alert levels (risk, hysteresis) | -0.97 points [-2.40, +0.13] | 0.978 | - |

Mean absolute difference of the features: 1-day rain 11.88 mm, 3-day rain 13.33 mm. Rank correlation of the raw scores of the two variants over the same cells: mean 0.9763, worst day 0.9433.

Alert levels with the pooled risk thresholds, as `live/run.py` applies them today (region-calibrated risk against the pooled card thresholds), against the region thresholds above: operational Watch+ share 96.04% (pooled) versus 96.04% (region).

## Limits

- The GFS archive on disk covers 2021-2024 June-September 00Z cycles only. 2018 therefore has no GFS tail at all: every 2018 day uses `persist_d1` (the 00-03 UTC rain of day D taken as the rain of UTC D-1), the most pessimistic link of the live fallback chain. The 2023 and 2024 windows use the real 00Z 0-3 h accumulation. The 18Z and 12Z fall-back cycles are not in the local archive.
- The Early run is used as it is (identity map; the fitted map did not improve the held-out 2018 season). A day whose Early granule for UTC D-1 is not stored has no operational score.
- The candidate cells are the universe cells of the hazard evaluation (own terrain, slope at or above the frozen floor), not every scored cell of the live runner.
- Event counts are small (80 test_2018 positives; of them those inside the window), so every detection interval is wide, and the 2023 window and Kerala/Wayanad cases are qualitative. 2018 is the year v2 and v3-live were both tested on: this backtest is a further, descriptive view of the same frozen model on that test year, with nothing tuned on it.
- Labels are partial: alerts on cells without a recorded landslide are counted as alert share, not as errors.

## After re-derivation

The alert parameters were re-derived on the 2007-2017 development seasons for v3-live (`reports/phase6_alert_burden.md`, year-blocked out-of-fold scoring). No combination of `exit_factor`, `exit_days` and the `uncertain_high` bound reduces the Watch+ share without losing development events, so the parameters are unchanged (`data/processed/alerts/alert_config_v3.json` records the derivation). The tables above use the old parameters; the live runner now applies the thresholds of each region. Below, one scoring pass (operational features) is evaluated as the live runner published it before (pooled thresholds), with thresholds by region, and with the costed alternative. Nothing was chosen on these data.

### 2018 monsoon season (test year, 56 events)

36,792 cells, 122 days, operational features, one scoring pass. Descriptive only: nothing was chosen on these data.

| condition | Watch+ share [95% CI] | Warning+ | Emergency | detection, own cell [95% CI] | median lead (days) vs chance rate | flaps per 1000 cell-days |
|---|---|---|---|---|---|---|
| published by the live runner before (pooled thresholds, old parameters) | 50.9% [49.7, 52.1] | 22.48% | 7.29% | 91.1% [82.1, 98.2] | 7.0 (chance 62.22%) | 10.7 |
| thresholds by region, old = v3 parameters (unchanged by the re-derivation) | 56.4% [55.2, 57.6] | 22.65% | 8.71% | 91.1% [82.1, 98.2] | 7.0 (chance 68.37%) | 13.7 |
| thresholds by region, costed alternative (not adopted): exit factor 1, exit days 2, `uncertain_high` at the ensemble 60th percentile | 51.3% [50.1, 52.6] | 22.64% | 8.69% | 87.5% [78.6, 94.6] | 7.0 (chance 63.21%) | 13.5 |

### 2023 India window

4,093 cells, 46 days, operational features, one scoring pass. Descriptive only: nothing was chosen on these data.

| condition | Watch+ share [95% CI] | Warning+ | Emergency | window detection | control cells alerted | flaps per 1000 cell-days |
|---|---|---|---|---|---|---|
| published by the live runner before (pooled thresholds, old parameters) | 58.1% [56.4, 59.8] | 30.51% | 13.55% | 100.0% [100.0, 100.0] | 84.4% [83.2, 85.5] | 8.3 |
| thresholds by region, old = v3 parameters (unchanged by the re-derivation) | 64.7% [62.9, 66.3] | 30.47% | 13.24% | 100.0% [100.0, 100.0] | 89.7% [88.7, 90.6] | 11.7 |
| thresholds by region, costed alternative (not adopted): exit factor 1, exit days 2, `uncertain_high` at the ensemble 60th percentile | 59.7% [58.0, 61.3] | 30.46% | 13.17% | 100.0% [100.0, 100.0] | 85.9% [84.8, 87.0] | 11.0 |

### Kerala 2018 case

8,048 cells, 20 days, operational features, one scoring pass. Descriptive only: nothing was chosen on these data.

| condition | Watch+ share [95% CI] | Warning+ | Emergency | detection, own cell [95% CI] | median lead (days) vs chance rate | flaps per 1000 cell-days |
|---|---|---|---|---|---|---|
| published by the live runner before (pooled thresholds, old parameters) | 44.3% [40.2, 48.4] | 21.58% | 5.95% | 100.0% [100.0, 100.0] | 7.0 (chance 57.88%) | 13.6 |
| thresholds by region, old = v3 parameters (unchanged by the re-derivation) | 44.3% [40.3, 48.4] | 22.65% | 12.75% | 100.0% [100.0, 100.0] | 7.0 (chance 57.88%) | 13.5 |
| thresholds by region, costed alternative (not adopted): exit factor 1, exit days 2, `uncertain_high` at the ensemble 60th percentile | 39.4% [35.3, 43.7] | 22.65% | 12.75% | 100.0% [100.0, 100.0] | 7.0 (chance 52.53%) | 12.4 |
