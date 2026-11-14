# Post-model rules for model v4 (phase 8, development only)

The section 11 rule family (ensemble-agreement minimum, rain trigger, hold windows, blind-hold limit) chosen again, by the same pre-declared steps as v3's (`live.hardening_dev`), on v4's development out-of-fold risk. The live run still applies the v3 rules to v4; adopting the v4 rules needs the one held-out look of `docs/superpowers/specs/2026-11-13-aetherguard-post-rules-v4.md`.

Panels: `data/processed/alerts/accuracy_hardening_oof_v4`; models: the year-blocked cross-validation models of the v4 configuration (configs/hazard_v4.yaml, refitted with the folds, seeds and tree count of the model_v4_live card), each scoring the years it did not train on (out-of-fold, the setting the card's thresholds were set in). The refitted fold models give an out-of-fold recall at Watch of 0.917617 against the card's 0.917617 (789 positives). Hysteresis and `uncertain_high` from `data/processed/alerts/alert_config_v3.json`. Events in the panel cells: 636 (development positives of June-September 2007-2017).

## Parameters

| parameter | v3 rules (live today) | v4 rules (derived here) |
|---|---|---|
| `agreement_min` | 0.25 | 0.25 |
| `rain_minimum_mm` | {"7": 11.504499244689944} | {"7": 11.504499244689944} |
| `gated_levels` | ["Watch", "Warning", "Emergency"] | ["Watch", "Warning", "Emergency"] |
| `hold_window_days` | 3 | 3 |
| `hold_window_days_by_level` | {"Watch": 2, "Warning": 1, "Emergency": 1} | {"Watch": 2, "Warning": 1, "Emergency": 1} |
| `blind_hold_days` | 2 | 1 |
| `lead_uncertain_bound` | "unwidened" | "unwidened" |

`lead_uncertain_bound` is a forecast-lead parameter (the leads are scored by v3) and is copied, not re-derived.

## Development burden and detection

Share of universe-sample cell-days at the level or above (June-September) and development events at the level or above on their own cell and day (95% bootstrap interval of the detected share).

| model and rules | Watch+ share | Warning+ share | Emergency share | Watch+ events | Warning+ events | Emergency events | dry Watch / Warning / Emergency cell-days | median lead (days) |
|---|---|---|---|---|---|---|---|---|
| v4, no rules | 52.62% | 17.14% | 5.29% | 625 / 636 (97.17%-99.21%) | 534 / 636 (81.13%-86.79%) | 384 / 636 (56.60%-64.15%) | 159612 / 8094 / 341 | 7.0 |
| v4 with the v3 rules (live today) | 48.97% | 16.91% | 5.27% | 619 / 636 (96.07%-98.58%) | 530 / 636 (80.50%-86.32%) | 382 / 636 (56.45%-63.68%) | 86674 / 6288 / 235 | 7.0 |
| v4 with the v4 rules | 48.97% | 16.91% | 5.27% | 619 / 636 (96.07%-98.58%) | 530 / 636 (80.50%-86.32%) | 382 / 636 (56.45%-63.68%) | 86674 / 6288 / 235 | 7.0 |
| v3, no rules (reference) | 61.89% | 24.91% | 10.20% | 624 / 636 (96.86%-99.06%) | 543 / 636 (82.55%-88.21%) | 403 / 636 (59.59%-67.30%) | 180997 / 9190 / 399 | 7.0 |
| v3 with the v3 rules (reference) | 57.98% | 24.72% | 10.19% | 618 / 636 (95.75%-98.43%) | 539 / 636 (81.92%-87.58%) | 402 / 636 (59.43%-67.14%) | 101842 / 8010 / 320 | 7.0 |

## v4 rules against the v3 rules, both on v4

| level | share, v3 rules | share, v4 rules | change | events, v3 rules | events, v4 rules | change |
|---|---|---|---|---|---|---|
| Watch+ | 48.97% | 48.97% | +0.00 pp | 619 | 619 | +0 |
| Warning+ | 16.91% | 16.91% | +0.00 pp | 530 | 530 | +0 |
| Emergency+ | 5.27% | 5.27% | +0.00 pp | 382 | 382 | +0 |

## How the v4 rules were chosen

- Ensemble agreement: A = 0.25 (pre-declared) unless the disagreeing Warning+ alerts are at least as precise (events per alerted cell-day) as the agreeing ones; then the disagreement is reported as a flag only. At 0.25 the disagreeing Warning+ alerts give 0.03156604507082667 events per 1,000 alerted cell-days against 0.08031833948965374 for the agreeing ones -> `agreement_min` 0.25.
- Rain trigger: {"form": "acc_7", "percentile": 5.0, "minimum_mm": {"7": 11.504499244689944}, "gated_levels": ["Watch", "Warning", "Emergency"]} (candidates: 1st / 2nd / 5th percentiles of the development positives' 1-, 3-, 7-day IMERG rain; adopted per level when at most 1% of that level's development events is lost and the share falls).
- Hold windows: {"Watch": 2, "Warning": 1, "Emergency": 1}.
- Blind-hold limit: 1 day(s) (H = the largest k in [1, 2, 3] whose retention is at least 0.5 at every level, and at least 1 (pre-declared)).

## Caveats

- Development data only (2007-2017, June-September, out of fold); no held-out number is in this report.
- Detection is cell-exact on the event cell and day (development positives), so it counts what the catalogues recorded; the catalogues miss most landslides, so alert cell-days far from a recorded event are not all false alarms.
- Alert shares are on the 5,000 seeded universe cells of the study, not on every scored cell.
- The rules are chosen in sample on these seasons by pre-declared rules; the burden change here is not evidence of a held-out gain, which only the one look of the spec decides.
- The ensemble-agreement rule changes confidence, not the level, so it does not move any number of the level tables.
