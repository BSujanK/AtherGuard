# Phase 6: alert accuracy hardening

Generated 2026-10-24T00:03:08Z. Every threshold and choice below was made on the development years (2007-2017, out of fold) before 2018 or any live day was evaluated; 2018 and 2026-10-23 were evaluated once, descriptively. The frozen v3 model files, card and calibrators are unchanged; the scoring code's interval and the post-model rules are the protocol amendment of spec section 11.

## The reported alerts

Two user-confirmed false alarms of the 2026-10-23 run: cell 23965166 (Warning, a 1.8 per 100k point outside its own 0.014-0.15 range) and 24605098 at Katra (Emergency since 17 Oct, held through the 20-21 Oct outage). Both had 0 mm of IMERG rain over 1, 3 and 7 days.

| cell |  | level | risk per 100k | range per 100k | confidence | causes | codes | agreement |
|---|---|---|---|---|---|---|---|---|
| 23965166 (29.83N 78.32E, himalaya) | first publication | Warning | 1.79 | 0.0141 - 0.147 | High | - | risk_above_warning |  |
| 23965166 (29.83N 78.32E, himalaya) | after (re-run) | Watch | 1.79 | 0.733 - 4.92 | Degraded | ensemble_disagrees | risk_above_warning;no_recent_rain | 0.00 |
| 24605098 (Katra, Reasi, J&K; 33.03N 74.93E) | first publication | Emergency | 10.7 | 1.38 - 27.7 | High | - | risk_above_emergency |  |
| 24605098 (Katra, Reasi, J&K; 33.03N 74.93E) | after (re-run) | Watch | 10.7 | 2.3 - 38.8 | High | - | risk_above_emergency;no_recent_rain | 0.80 |

After the rules both are **Watch** with code `no_recent_rain` (7-day rain 0 mm, below the 11.5 mm minimum; the cap takes Warning and Emergency to Watch). 23965166 is also Degraded: none of the 20 members reaches Warning (`ensemble_disagrees`). Regression tests: `tests/test_live_false_alarms.py`.

## 1. Interval consistency

`risk_lo` / `risk_hi` were the 10th / 90th percentile of the calibrated members while `risk` is the point model. On the development seasons the point lay outside that interval on 215,355 of 6,710,000 universe cell-days (3.21%; 200,700 above it). The interval is now the members' logit spread re-centred on the point (`expit(logit(point) - (logit(median) - logit(p10)))`, `expit(logit(point) + (logit(p90) - logit(median)))`, clipped at 1e-12, calibrated like the point): 0 cell-days outside. `score` also returns `member_median_risk` and `ensemble_agreement`.

Effect on `uncertain_high` (development, full Task 6b levels):

| condition | Watch+ share | Warning+ share | Emergency share | events at Watch+ | at Warning+ | at Emergency | dry Watch cell-days | dry Warning | dry Emergency |
|---|---|---|---|---|---|---|---|---|---|
| old interval | 58.78% | 24.91% | 10.20% | 623/636 = 98.0% [96.9, 98.9] | 543/636 = 85.4% [82.5, 88.2] | 403/636 = 63.4% [59.6, 67.3] | 143,883 | 9,190 | 399 |
| re-centred interval | 61.89% | 24.91% | 10.20% | 624/636 = 98.1% [96.9, 99.1] | 543/636 = 85.4% [82.5, 88.2] | 403/636 = 63.4% [59.6, 67.3] | 180,997 | 9,190 | 399 |
| no uncertain_high | 52.26% | 24.91% | 10.20% | 617/636 = 97.0% [95.6, 98.3] | 543/636 = 85.4% [82.5, 88.2] | 403/636 = 63.4% [59.6, 67.3] | 103,192 | 9,190 | 399 |

The re-centred upper bound lies above the old one where the point is above the members, so `uncertain_high` raises more cell-days to Watch. The re-centring is the consistency fix and is the baseline below; whether `uncertain_high` should test a different bound is left open (not chosen here).

## 2. Ensemble disagreement

| A | group | development events with a Warning+ point | Warning+ point cell-days (universe sample) | events per 1,000 alerted cell-days |
|---|---|---|---|---|
| 0.1 | agreeing | 518 (81.4% of all events) | 1,309,304 (99.3%) | 0.0538 |
| 0.1 | disagreeing | 2 (0.3% of all events) | 9,733 (0.7%) | 0.0279 |
| 0.25 | agreeing | 512 (80.5% of all events) | 1,259,438 (95.5%) | 0.0552 |
| 0.25 | disagreeing | 8 (1.3% of all events) | 59,599 (4.5%) | 0.0182 |
| 0.5 | agreeing | 466 (73.3% of all events) | 1,070,064 (81.1%) | 0.0592 |
| 0.5 | disagreeing | 54 (8.5% of all events) | 248,973 (18.9%) | 0.0295 |

The disagreeing Warning+ alerts are less precise than the agreeing ones at every A, so the pre-declared default holds: **A = 0.25**. A point at Warning or above with fewer than A of the members at its level is capped at Degraded with cause `ensemble_disagrees` ("most of the 20 ensemble models put this cell lower"); the level is not changed.

## 3. Rain trigger

Minima: low percentiles of the IMERG rain of the 789 in-domain development positives (every month). Each candidate gated at one level at a time on the full levels (re-centred interval, hold released after a dry hold window of 3 days); adoption needs at most 1% of that level's events lost and a lower share at that level.

| form | percentile | minimum | gate at Watch | gate at Warning | gate at Emergency | adoptable at |
|---|---|---|---|---|---|---|
| acc_3 | p1 | 3-day 0 mm | vacuous (a 0 mm minimum admits every cell-day) |  |  |  |
| acc_3 | p2 | 3-day 0.588 mm | 0 lost of 624 (0.00%); share 61.89% -> 60.85%; adopt | 0 lost of 543 (0.00%); share 24.91% -> 24.90%; adopt | 0 lost of 403 (0.00%); share 10.20% -> 10.20%; adopt | Watch, Warning, Emergency |
| acc_3 | p5 | 3-day 2.7 mm | 2 lost of 624 (0.32%); share 61.89% -> 58.68%; adopt | 2 lost of 543 (0.37%); share 24.91% -> 24.83%; adopt | 0 lost of 403 (0.00%); share 10.20% -> 10.19%; adopt | Watch, Warning, Emergency |
| acc_7 | p1 | 7-day 0.345 mm | 0 lost of 624 (0.00%); share 61.89% -> 61.77%; adopt | 0 lost of 543 (0.00%); share 24.91% -> 24.91%; adopt | 0 lost of 403 (0.00%); share 10.20% -> 10.20%; adopt | Watch, Warning, Emergency |
| acc_7 | p2 | 7-day 4 mm | 0 lost of 624 (0.00%); share 61.89% -> 60.93%; adopt | 1 lost of 543 (0.18%); share 24.91% -> 24.90%; adopt | 0 lost of 403 (0.00%); share 10.20% -> 10.20%; adopt | Watch, Warning, Emergency |
| acc_7 | p5 | 7-day 11.5 mm | 4 lost of 624 (0.64%); share 61.89% -> 58.42%; adopt | 2 lost of 543 (0.37%); share 24.91% -> 24.79%; adopt | 0 lost of 403 (0.00%); share 10.20% -> 10.19%; adopt | Watch, Warning, Emergency |
| acc_3_or_acc_7 | p1 | 3-day 0 mm, 7-day 0.345 mm | vacuous (a 0 mm minimum admits every cell-day) |  |  |  |
| acc_3_or_acc_7 | p2 | 3-day 0.588 mm, 7-day 4 mm | 0 lost of 624 (0.00%); share 61.89% -> 61.50%; adopt | 0 lost of 543 (0.00%); share 24.91% -> 24.91%; adopt | 0 lost of 403 (0.00%); share 10.20% -> 10.20%; adopt | Watch, Warning, Emergency |
| acc_3_or_acc_7 | p5 | 3-day 2.7 mm, 7-day 11.5 mm | 1 lost of 624 (0.16%); share 61.89% -> 60.16%; adopt | 1 lost of 543 (0.18%); share 24.91% -> 24.89%; adopt | 0 lost of 403 (0.00%); share 10.20% -> 10.20%; adopt | Watch, Warning, Emergency |
| acc_1_or_acc_3_or_acc_7 | p1 | 1-day 0 mm, 3-day 0 mm, 7-day 0.345 mm | vacuous (a 0 mm minimum admits every cell-day) |  |  |  |
| acc_1_or_acc_3_or_acc_7 | p2 | 1-day 0 mm, 3-day 0.588 mm, 7-day 4 mm | vacuous (a 0 mm minimum admits every cell-day) |  |  |  |
| acc_1_or_acc_3_or_acc_7 | p5 | 1-day 0.345 mm, 3-day 2.7 mm, 7-day 11.5 mm | 0 lost of 624 (0.00%); share 61.89% -> 61.09%; adopt | 0 lost of 543 (0.00%); share 24.91% -> 24.91%; adopt | 0 lost of 403 (0.00%); share 10.20% -> 10.20%; adopt | Watch, Warning, Emergency |

Chosen by the pre-declared order (most adoptable levels, then the lowest Warning+ share): **acc_7 p5, irain_acc_7 >= 11.50 mm, gated at Watch, Warning, Emergency**; caps Watch -> Normal, Warning -> Watch, Emergency -> Watch; blind-escalated cells are exempt.

| condition | Watch+ share | Warning+ share | Emergency share | events at Watch+ | at Warning+ | at Emergency | dry Watch cell-days | dry Warning | dry Emergency |
|---|---|---|---|---|---|---|---|---|---|
| baseline (re-centred interval) | 61.89% | 24.91% | 10.20% | 624/636 = 98.1% [96.9, 99.1] | 543/636 = 85.4% [82.5, 88.2] | 403/636 = 63.4% [59.6, 67.3] | 180,997 | 9,190 | 399 |
| chosen rules | 57.98% | 24.72% | 10.19% | 618/636 = 97.2% [95.8, 98.4] | 539/636 = 84.7% [81.9, 87.6] | 402/636 = 63.2% [59.4, 67.1] | 101,842 | 8,010 | 320 |
| chosen rules, holds not released | 59.52% | 24.80% | 10.19% | 622/636 = 97.8% [96.5, 98.9] | 541/636 = 85.1% [82.2, 87.9] | 403/636 = 63.4% [59.6, 67.3] | 134,611 | 9,026 | 389 |

Hold window per level (the chosen rule; one level's window shortened at a time, the others at 3 days; then all together):

| level | hold window (days) | events lost at the level | share at the level |  |
|---|---|---|---|---|
| Watch | 1 | 7 of 624 (1.12%) | 57.18% | no |
| Watch | 2 | 6 of 624 (0.96%) | 57.99% | adopt |
| Watch | 3 | 5 of 624 (0.80%) | 58.39% | adopt |
| Warning | 1 | 3 of 543 (0.55%) | 24.73% | adopt |
| Warning | 2 | 2 of 543 (0.37%) | 24.76% | adopt |
| Warning | 3 | 2 of 543 (0.37%) | 24.78% | adopt |
| Emergency | 1 | 1 of 403 (0.25%) | 10.19% | adopt |
| Emergency | 2 | 1 of 403 (0.25%) | 10.19% | adopt |
| Emergency | 3 | 0 of 403 (0.00%) | 10.19% | adopt |
| Watch | chosen, all together | 6 of 624 (0.96%) | 57.98% | adopt |
| Warning | chosen, all together | 4 of 543 (0.74%) | 24.72% | adopt |
| Emergency | chosen, all together | 1 of 403 (0.25%) | 10.19% | adopt |

Chosen (shortest window meeting the adoption rule at its level): **Watch 2 days, Warning 1 day, Emergency 1 day**. A hold at a level needs the rain rule to have passed on one of that many days ending on the day; this was refined after the continuous re-run of the live days showed longer windows letting a 7-day total from up to 9 days back justify a hold, and chosen on development data only.

Post-rain cost: 73 of the 789 development positives occurred 7 days or more after the last 10 mm day; 40 of them (5.07% of all positives) had a 7-day rain under 11.50 mm and fail the rule on their own day (every positive below the minimum is such a post-rain case: 40). On the June-September alert levels the gate loses 6 Watch+ detections of the 636 in-season events.

## 4. Blind-hold limit

| level | retained after 1 day(s) | retained after 2 day(s) | retained after 3 day(s) |
|---|---|---|---|
| Watch | 91.9% | 89.1% | 87.7% |
| Warning | 77.9% | 70.6% | 66.9% |
| Emergency | 62.9% | 50.9% | 44.8% |

Pre-declared: H = the largest lag whose retention is at least 50% at every level, at least 1. **H = 2** (Emergency retains 50.9% after 2 days). A level is held over at most H consecutive days without a score, then lowered one level per further day; the cell stays Insufficient with code `held_while_blind`; the blind-escalation rule still applies.

## 5. Forecast leads

`uncertain_high` on the forecast leads, on the forecast-skill pairs (488 GFS issue days of June-September 2021-2024, 2,536 cells, seed 20261015), each side with the chosen rain cap; observed level = the level the target day is published at from observed features:

| lead | uncertain_high bound | cell-day pairs | exact level agreement | forecast Watch+ share | observed Watch+ share |
|---|---|---|---|---|---|
| D+1 | widened | 1,237,568 | 73.58% | 49.70% | 33.35% |
| D+1 | unwidened | 1,237,568 | 82.85% | 34.89% | 33.35% |
| D+1 | none | 1,237,568 | 81.15% | 25.96% | 33.35% |
| D+2 | widened | 1,237,568 | 71.56% | 50.32% | 33.44% |
| D+2 | unwidened | 1,237,568 | 81.06% | 34.58% | 33.44% |
| D+2 | none | 1,237,568 | 79.72% | 25.88% | 33.44% |
| D+3 | widened | 1,237,568 | 69.94% | 50.65% | 33.53% |
| D+3 | unwidened | 1,237,568 | 79.15% | 34.85% | 33.53% |
| D+3 | none | 1,237,568 | 78.42% | 26.05% | 33.53% |
| all | widened |  | 71.69% | 50.22% |  |
| all | unwidened |  | 81.02% | 34.77% |  |
| all | none |  | 79.76% | 25.96% |  |

Pre-declared (higher pooled agreement, ties to three decimals to the lower Watch+ share): **unwidened**. A forecast day has no observation, so a lead's confidence is never High: a scored lead is Degraded with causes `forecast_day`, `observed_through_d_<D0 state>` and `forecast_widened`; the audit flags a High forecast row.

## 6. Terrain-only diagnostic

Development (out of fold, levels of the re-centred baseline; dry = 3-day rain under 1 mm):

| published level, rain | cell-days | explained | median log-odds aspect / TWI | share of the positive contribution | top 3 all aspect/TWI | point level drops without them |
|---|---|---|---|---|---|---|
| Watch dry | 180,997 | 180,997 | +0.032 / +0.017 | 11.3% | 0.07% | 13.7% |
| Watch wet | 2,300,544 | 1,475,091 | +0.001 / +0.003 | 7.0% | 0.00% | 7.1% |
| Warning dry | 9,190 | 9,190 | +0.077 / +0.071 | 9.9% | 0.00% | 18.9% |
| Warning wet | 977,846 | 969,750 | +0.012 / +0.035 | 5.9% | 0.00% | 9.9% |
| Emergency dry | 399 | 399 | +0.233 / +0.228 | 16.3% | 0.00% | 57.4% |
| Emergency wet | 684,157 | 684,008 | +0.037 / +0.065 | 5.2% | 0.00% | 11.8% |

2026-10-23 (published levels before the rules):

| published level, rain | cell-days | explained | median log-odds aspect / TWI | share of the positive contribution | top 3 all aspect/TWI | point level drops without them |
|---|---|---|---|---|---|---|
| Watch dry | 7,217 | 7,217 | +0.090 / -0.130 | 8.8% | 0.32% | 11.2% |
| Watch wet | 1,893 | 1,223 | -0.013 / +0.073 | 8.9% | 0.00% | 12.3% |
| Warning dry | 51 | 51 | +0.245 / +0.138 | 20.5% | 7.84% | 40.8% |
| Warning wet | 598 | 590 | +0.009 / +0.078 | 5.9% | 0.00% | 13.9% |
| Emergency dry | 1 | 1 | +1.044 / +0.044 | 19.9% | 0.00% | 100.0% |
| Emergency wet | 1,143 | 1,140 | +0.046 / +0.111 | 5.4% | 0.00% | 9.4% |

Aspect ablation (challenger harness, `--only lgb_no_aspect`, imerg_core without stat_aspect_sin/cos): pooled OOF FA@90 0.1992 against 0.1955 for v3; paired difference +0.0037 (SE 0.0090, 95% CI [-0.0165, +0.0184]); not adopted by the harness rule. Details: `reports/phase6_aspect_ablation.md`.

## 7. Evaluation (once, after the choice)

### 2018 operational backtest (36,792 cells, 122 days, 56 test events)

| condition | Watch+ share | Warning+ share | Emergency share | events at Watch+ | at Warning+ | at Emergency | dry Watch cell-days | dry Warning | dry Emergency |
|---|---|---|---|---|---|---|---|---|---|
| before: old interval, no post-model rules | 56.37% | 22.65% | 8.71% | 51/56 = 91.1% [82.1, 98.2] | 40/56 = 71.4% [58.9, 82.1] | 30/56 = 53.6% [41.1, 66.1] | 119,068 | 7,674 | 251 |
| re-centred interval, no post-model rules | 59.67% | 22.65% | 8.71% | 51/56 = 91.1% [82.1, 98.2] | 40/56 = 71.4% [58.9, 82.1] | 30/56 = 53.6% [41.1, 66.1] | 142,608 | 7,674 | 251 |
| re-centred interval + chosen rules | 55.46% | 22.38% | 8.69% | 48/56 = 85.7% [75.0, 94.6] | 40/56 = 71.4% [58.9, 82.1] | 30/56 = 53.6% [41.1, 66.1] | 79,946 | 6,624 | 182 |

Point outside the old interval: 141,009 of 4,451,832 cell-days; none with the re-centred one. `ensemble_disagrees` would mark 40,053 of 752,828 Warning+ point cell-days.

### 2026-10-23, recomputed offline from its stored features

| 23 Oct, lead 0 | Normal | Watch | Warning | Emergency | dry Watch | dry Warning | dry Emergency | risk outside [lo, hi] |
|---|---|---|---|---|---|---|---|---|
| first publication (old interval, no rules; inputs of the first run, no history) | 26,233 | 8,972 | 690 | 897 | 6,965 of 8,972 | 30 of 690 | 1 of 897 | 1,043 |
| re-run inputs, old interval, no rules, re-run history | 25,889 | 9,110 | 649 | 1,144 | 7,217 of 9,110 | 51 of 649 | 1 of 1,144 | 1,043 |
| re-run inputs, re-centred interval + chosen rules (= the re-run's published table) | 33,194 | 1,852 | 603 | 1,143 | 565 of 1,852 | 11 of 603 | 0 of 1,143 | 0 |

The first row is the alert engine re-run offline on the inputs of the first 23 Oct run (it reproduces the user-reported counts); the 23 Oct folder has since been re-run (inputs fetched on 24 Oct, the previous days re-run with the rules, 14 previous days of history), the source of the other rows. After: 9,175 cells capped by `no_recent_rain`, 60 marked `ensemble_disagrees`; the audit of the recomputed table finds 0 violations.

## 8. Audit of the published live days

As first published, audited with the rules of that time (one 3-day hold window, before the forecast checks; 2026-10-23T14:26:57Z):

| day | rows | interval | level | rain_rule | blind_hold | confidence | per_100k | lead0_table |
|---|---|---|---|---|---|---|---|---|
| 2026-10-09 | 183,960 | 946 | 0 | 3,351 | 0 | 0 | 0 | 0 |
| 2026-10-10 | 183,960 | 999 | 0 | 2,896 | 0 | 0 | 0 | 0 |
| 2026-10-11 | 183,960 | 1,034 | 0 | 2,556 | 3 | 0 | 0 | 0 |
| 2026-10-12 | 183,960 | 1,004 | 0 | 2,303 | 0 | 0 | 0 | 0 |
| 2026-10-13 | 183,960 | 946 | 0 | 2,865 | 0 | 0 | 0 | 0 |
| 2026-10-14 | 183,960 | 871 | 0 | 3,147 | 0 | 0 | 0 | 0 |
| 2026-10-15 | 183,960 | 884 | 0 | 3,986 | 0 | 0 | 0 | 0 |
| 2026-10-16 | 183,960 | 933 | 0 | 4,575 | 0 | 0 | 0 | 0 |
| 2026-10-17 | 183,960 | 1,005 | 0 | 6,890 | 0 | 0 | 0 | 0 |
| 2026-10-18 | 183,960 | 1,116 | 0 | 7,837 | 0 | 0 | 0 | 0 |
| 2026-10-19 | 183,960 | 1,042 | 0 | 8,291 | 0 | 0 | 0 | 0 |
| 2026-10-20 | 73,584 | 0 | 0 | 0 | 13,643 | 0 | 0 | 0 |
| 2026-10-21 | 73,584 | 0 | 0 | 0 | 13,643 | 0 | 0 | 0 |
| 2026-10-23 | 183,960 | 0 | 0 | 56,755 | 0 | 0 | 0 | 0 |

`interval` is the old interval; `rain_rule` the cell-days of lead 0 and of the leads with stored features that the rule caps; `blind_hold` the holds over days without a score that lack `held_while_blind` (none is held beyond H = 2 days).

After the re-run with the integrated runner (2026-10-24T00:01:23Z): 0 violations in total.

| day | rows | interval | level | rain_rule | blind_hold | confidence | forecast_confidence | per_100k | lead0_table |
|---|---|---|---|---|---|---|---|---|---|
| 2026-10-09 | 183,960 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 2026-10-10 | 183,960 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 2026-10-11 | 183,960 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 2026-10-12 | 183,960 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 2026-10-13 | 183,960 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 2026-10-14 | 183,960 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 2026-10-15 | 183,960 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 2026-10-16 | 183,960 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 2026-10-17 | 183,960 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 2026-10-18 | 183,960 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 2026-10-19 | 183,960 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 2026-10-20 | 183,960 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 2026-10-21 | 183,960 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 2026-10-22 | 183,960 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 2026-10-23 | 183,960 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## Limits

- The development seasons are June-September; the live days are October, when far more cells are dry (79.2% of the 23 Oct Watch cells against 7.3% of the development Watch cell-days). The rule's cost on in-domain positives of every month is the post-rain count above.
- The 1% adoption rule was met on development; on 2018 the gate costs 3 of 56 Watch+ detections (descriptive, not used to choose).
- The live days 2026-10-09..23 were re-run oldest first with the integrated runner (09-15 `--backtest --force`, 16-23 `--force`, 22 Oct included so the hysteresis is continuous); the re-runs of 16-23 used the inputs available on 24 Oct, not those of each day's 11:00 IST run.
- The hold windows were refined after the first continuous re-run (from one 3-day window to per-level windows); the choice was made on development data only, and 2018 was evaluated again with the final rules.
