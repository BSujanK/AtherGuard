# Phase 6 alert burden and the v3 alert parameters

Generated 2026-10-16T04:32:18Z. Chosen on development years only; test_2018, the 2023 window and the case sets are not read.

## What was fixed in the live runner

`live/run.py` compared the region-calibrated risk with the POOLED card thresholds. It now uses the card's `risk_by_region` thresholds of each cell's region for a model calibrated per region (pooled thresholds for any other region and for a pooled model), in the engine, in the hysteresis over the previous days and in the forecast leads; `run.json` keeps `model.thresholds` (pooled) and adds `model.thresholds_by_region`.

## Protocol

- Development seasons: 06-01 to 09-30 of 2007-2017 (train + validation years); every day, with a 7-day warm-up before 1 June for the hysteresis state. Shares are over 6,710,000 scored cell-days of a seeded sample of 5,000 universe cells in the out-of-fold analysis, and over all 36,792 cells in the frozen-model analysis (49,374,864 cell-days).
- Events: 636 in-domain train and validation positives of those seasons (of 647; the rest lie in cells the live runner does not score).
- Model for the choice: the year-blocked cross-validation models of the v3-live configuration, each scoring the years it did not train on (out-of-fold, the setting the card's thresholds were set in); training-style features (Late IMERG), thresholds of the card per region.
- Why not the frozen model: it was fitted on every one of these positives, so it detects them almost whatever the rule (raw-score Watch rule 629/636, against 598/636 out of fold) and a no-loss constraint measured on it is nearly empty. The year-blocked refits reproduce the card's out-of-fold recall at Watch exactly (0.917617), so the choice is made on them; the frozen-model analysis, as the brief specified it, is reported below.
- Grid: 24 combinations (limit 30), seeded; bootstrap SE: 2000 event resamples, seed 20261016 (reported, not used to choose).
- Objective: minimise the development Watch+ cell-day share; constraints: own-cell detection of the development events (point estimate) not below that of the current parameters, median lead not shorter.

## Where the burden comes from (development seasons, out of fold)

| rule | Watch+ share | Warning+ | Emergency | own cell on the event day | Watch+ within 7 days up to it | median lead (days) | flaps per 1000 cell-days |
|---|---|---|---|---|---|---|---|
| 0. frozen Watch rule on the raw score (the model's own rule) | 41.77% | 0.00% | 0.00% | 598/636 = 94.0% (SE 0.9) | 617/636 = 97.0% (SE 0.7) | 7.0 | 22.7 |
| a. raw point-risk rule | 48.09% | 19.66% | 7.41% | 613/636 = 96.4% (SE 0.7) | 622/636 = 97.8% (SE 0.6) | 7.0 | 21.2 |
| b. a + uncertain_high | 54.90% | 19.66% | 7.41% | 621/636 = 97.6% (SE 0.6) | 628/636 = 98.7% (SE 0.5) | 7.0 | 20.6 |
| c. b + hysteresis (day count only, exit factor 1) | 58.78% | 24.91% | 10.17% | 623/636 = 98.0% (SE 0.6) | 630/636 = 99.1% (SE 0.4) | 7.0 | 12.0 |
| d. c + exit rule = the full alert levels | 58.78% | 24.91% | 10.20% | 623/636 = 98.0% (SE 0.6) | 630/636 = 99.1% (SE 0.4) | 7.0 | 12.0 |
| side: point risk + full hysteresis, no uncertain_high | 52.26% | 24.91% | 10.20% | 617/636 = 97.0% (SE 0.7) | 625/636 = 98.3% (SE 0.5) | 7.0 | 11.9 |

Rows a to d add one rule at a time. (c) is hysteresis with the day count only (exit factor 1: a level steps down after `exit_days` consecutive days below it); (d) adds the exit factor and is the full alert levels. The side row keeps hysteresis but drops `uncertain_high`. Detection is the own cell on the event day; the 7-day column counts a Watch+ day in the 7 days up to and including it.

The calibrated-risk rule (a) is more permissive than the model's own raw-score rule (0): 6.32% of cell-days are at Watch by the risk threshold of the region but below the frozen raw threshold, against 0.00% the other way round. The isotonic calibration is flat over stretches of the raw score, so the risk threshold admits every raw score on the plateau at the threshold's risk. This is the largest piece of the burden that is not a tunable parameter: the card defines its operating points on the raw score, and comparing the raw score with the card's raw thresholds would remove it together with the recall that comes with it (row 0 against row a). It was not changed.

The same decomposition for the frozen model on all universe cells (in-sample detection):

| rule | Watch+ share | Warning+ | Emergency | own cell on the event day | Watch+ within 7 days up to it | median lead (days) | flaps per 1000 cell-days |
|---|---|---|---|---|---|---|---|
| 0. frozen Watch rule on the raw score (the model's own rule) | 42.09% | 0.00% | 0.00% | 629/636 = 98.9% (SE 0.4) | 632/636 = 99.4% (SE 0.3) | 7.0 | 24.0 |
| a. raw point-risk rule | 48.58% | 19.52% | 7.34% | 632/636 = 99.4% (SE 0.3) | 633/636 = 99.5% (SE 0.3) | 7.0 | 21.6 |
| b. a + uncertain_high | 55.22% | 19.52% | 7.34% | 636/636 = 100.0% (SE 0.0) | 636/636 = 100.0% (SE 0.0) | 7.0 | 20.7 |
| c. b + hysteresis (day count only, exit factor 1) | 59.09% | 24.99% | 10.15% | 636/636 = 100.0% (SE 0.0) | 636/636 = 100.0% (SE 0.0) | 7.0 | 12.3 |
| d. c + exit rule = the full alert levels | 59.09% | 25.00% | 10.18% | 636/636 = 100.0% (SE 0.0) | 636/636 = 100.0% (SE 0.0) | 7.0 | 12.3 |
| side: point risk + full hysteresis, no uncertain_high | 52.81% | 25.00% | 10.18% | 632/636 = 99.4% (SE 0.3) | 634/636 = 99.7% (SE 0.2) | 7.0 | 11.9 |

## The grid (development seasons, out of fold)

| combination | Watch+ share | Warning+ | Emergency | own cell on the event day | Watch+ within 7 days up to it | median lead (days) | flaps per 1000 cell-days | events vs old |
|---|---|---|---|---|---|---|---|---|
| ensemble p90, exit factor 0.8, exit days 2 (old) (chosen) | 58.78% | 24.91% | 10.20% | 623/636 = 98.0% (SE 0.6) | 630/636 = 99.1% (SE 0.4) | 7.0 | 12.0 | +0 |
| ensemble p90, exit factor 0.8, exit days 1 | 54.91% | 20.16% | 7.44% | 621/636 = 97.6% (SE 0.6) | 628/636 = 98.7% (SE 0.5) | 7.0 | 20.6 | -2 |
| ensemble p90, exit factor 0.9, exit days 1 | 54.91% | 20.16% | 7.43% | 621/636 = 97.6% (SE 0.6) | 628/636 = 98.7% (SE 0.5) | 7.0 | 20.6 | -2 |
| ensemble p90, exit factor 0.9, exit days 2 | 58.78% | 24.91% | 10.20% | 623/636 = 98.0% (SE 0.6) | 630/636 = 99.1% (SE 0.4) | 7.0 | 12.0 | +0 |
| ensemble p90, exit factor 1, exit days 1 | 54.91% | 20.15% | 7.41% | 621/636 = 97.6% (SE 0.6) | 628/636 = 98.7% (SE 0.5) | 7.0 | 20.6 | -2 |
| ensemble p90, exit factor 1, exit days 2 | 58.78% | 24.91% | 10.17% | 623/636 = 98.0% (SE 0.6) | 630/636 = 99.1% (SE 0.4) | 7.0 | 12.0 | +0 |
| ensemble p75, exit factor 0.8, exit days 1 | 51.26% | 20.16% | 7.44% | 617/636 = 97.0% (SE 0.7) | 625/636 = 98.3% (SE 0.5) | 7.0 | 20.7 | -6 |
| ensemble p75, exit factor 0.8, exit days 2 | 55.21% | 24.91% | 10.20% | 621/636 = 97.6% (SE 0.6) | 627/636 = 98.6% (SE 0.5) | 7.0 | 12.0 | -2 |
| ensemble p75, exit factor 0.9, exit days 1 | 51.26% | 20.16% | 7.43% | 617/636 = 97.0% (SE 0.7) | 625/636 = 98.3% (SE 0.5) | 7.0 | 20.7 | -6 |
| ensemble p75, exit factor 0.9, exit days 2 | 55.21% | 24.91% | 10.20% | 621/636 = 97.6% (SE 0.6) | 627/636 = 98.6% (SE 0.5) | 7.0 | 12.0 | -2 |
| ensemble p75, exit factor 1, exit days 1 | 51.26% | 20.15% | 7.41% | 617/636 = 97.0% (SE 0.7) | 625/636 = 98.3% (SE 0.5) | 7.0 | 20.7 | -6 |
| ensemble p75, exit factor 1, exit days 2 | 55.21% | 24.91% | 10.17% | 621/636 = 97.6% (SE 0.6) | 627/636 = 98.6% (SE 0.5) | 7.0 | 12.0 | -2 |
| ensemble p60, exit factor 0.8, exit days 1 | 49.48% | 20.16% | 7.44% | 616/636 = 96.9% (SE 0.7) | 624/636 = 98.1% (SE 0.6) | 7.0 | 20.8 | -7 |
| ensemble p60, exit factor 0.8, exit days 2 | 53.49% | 24.91% | 10.20% | 620/636 = 97.5% (SE 0.6) | 626/636 = 98.4% (SE 0.5) | 7.0 | 11.9 | -3 |
| ensemble p60, exit factor 0.9, exit days 1 | 49.48% | 20.16% | 7.43% | 616/636 = 96.9% (SE 0.7) | 624/636 = 98.1% (SE 0.6) | 7.0 | 20.8 | -7 |
| ensemble p60, exit factor 0.9, exit days 2 | 53.49% | 24.91% | 10.20% | 620/636 = 97.5% (SE 0.6) | 626/636 = 98.4% (SE 0.5) | 7.0 | 11.9 | -3 |
| ensemble p60, exit factor 1, exit days 1 | 49.48% | 20.15% | 7.41% | 616/636 = 96.9% (SE 0.7) | 624/636 = 98.1% (SE 0.6) | 7.0 | 20.8 | -7 |
| ensemble p60, exit factor 1, exit days 2 (alternative) | 53.49% | 24.91% | 10.17% | 620/636 = 97.5% (SE 0.6) | 626/636 = 98.4% (SE 0.5) | 7.0 | 11.9 | -3 |
| off, exit factor 0.8, exit days 1 | 48.18% | 20.16% | 7.44% | 613/636 = 96.4% (SE 0.7) | 622/636 = 97.8% (SE 0.6) | 7.0 | 21.0 | -10 |
| off, exit factor 0.8, exit days 2 | 52.26% | 24.91% | 10.20% | 617/636 = 97.0% (SE 0.7) | 625/636 = 98.3% (SE 0.5) | 7.0 | 11.9 | -6 |
| off, exit factor 0.9, exit days 1 | 48.18% | 20.16% | 7.43% | 613/636 = 96.4% (SE 0.7) | 622/636 = 97.8% (SE 0.6) | 7.0 | 21.0 | -10 |
| off, exit factor 0.9, exit days 2 | 52.26% | 24.91% | 10.20% | 617/636 = 97.0% (SE 0.7) | 625/636 = 98.3% (SE 0.5) | 7.0 | 11.9 | -6 |
| off, exit factor 1, exit days 1 | 48.18% | 20.15% | 7.41% | 613/636 = 96.4% (SE 0.7) | 622/636 = 97.8% (SE 0.6) | 7.0 | 21.0 | -10 |
| off, exit factor 1, exit days 2 | 52.26% | 24.91% | 10.17% | 617/636 = 97.0% (SE 0.7) | 625/636 = 98.3% (SE 0.5) | 7.0 | 11.9 | -6 |

## Result

No combination reduces the Watch+ share without losing development events, so the old parameters stay: exit factor 0.8, exit days 2, `uncertain_high` at the ensemble 90th percentile. The exit factor changes nothing on this grid (the risk of a cell that has dropped is almost always far below the held level's threshold); a shorter hold and a narrower or removed `uncertain_high` bound each cost events.

Costed alternative, not adopted: the smallest burden that loses at most 3 events (0.5% of 636) is exit factor 1, exit days 2, `uncertain_high` at the ensemble 60th percentile: Watch+ 53.49% against 58.78%, own-cell detection 620/636 against 623/636, flaps per 1000 cell-days 11.9 against 12.0.

## Parameters

| parameter | old (v2 development) | v3 (chosen) | costed alternative (not adopted) | chosen differs from old |
|---|---|---|---|---|
| exit_factor | 0.8 | 0.8 | 1.0 | no |
| exit_days | 2 | 2 | 2 | no |
| uncertain_percentile | 90.0 | 90.0 | 60.0 | no |

The data-derived values (source-disagreement range, heavy-rain amounts, station agreement) come from `aetherguard.alerts.derive`, which reads the development feature tables and no model: re-running it for v3 returns the v2 values unchanged. `alert_config_v3.json` records this and the grid.

## Development before and after (out of fold)

| rule | Watch+ share | Warning+ | Emergency | own cell on the event day | Watch+ within 7 days up to it | median lead (days) | flaps per 1000 cell-days |
|---|---|---|---|---|---|---|---|
| old parameters | 58.78% | 24.91% | 10.20% | 623/636 = 98.0% (SE 0.6) | 630/636 = 99.1% (SE 0.4) | 7.0 | 12.0 |
| v3 parameters | 58.78% | 24.91% | 10.20% | 623/636 = 98.0% (SE 0.6) | 630/636 = 99.1% (SE 0.4) | 7.0 | 12.0 |
| costed alternative (not adopted) | 53.49% | 24.91% | 10.17% | 620/636 = 97.5% (SE 0.6) | 626/636 = 98.4% (SE 0.5) | 7.0 | 11.9 |

## 2018, 2023 and Kerala (descriptive, one scoring pass)

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

## Limits

- The out-of-fold models are refits of the v3-live configuration with the cross-validation's own seeds; their ensembles (the `uncertain_high` bounds) use seeds of this study, so they are not the cross-validation's models member for member. The burden of that analysis is measured on a seeded sample of 5,000 of the 36,792 universe cells; the frozen-model analysis on all of them gives the same table to within a point.
- The frozen-model analysis detects the development events in-sample (the model was fitted on them), so its detection is near 100% under every rule.
- Training-style features (Late IMERG for every UTC day) were used: Early IMERG does not exist for 2007-2017, so the train/live gap of the operational inputs is not in the development numbers.
- The source-agreement, gauge and blind-escalation rules of the alert engine are not applied (no IMD real-time archive or gauge history on disk), neither in the development analysis nor in the backtest; the live alert share can be higher by the cells they raise to Watch.
- The data-derived values (source-disagreement range, heavy-rain amounts, station agreement) are percentiles of the development feature tables and do not depend on the model, so there was nothing to re-derive for v3.
- Lead time is capped at 7 days and saturates when the alert share is high; it is informative only against the chance rate. The labels are partial: alerts on cells without a recorded landslide count as alert share, not as errors.
- The Watch threshold itself (the card's recall-first operating point) was not touched; it fixes the floor of the burden.
