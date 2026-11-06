# W2: precision-optimal operating point (phase 7)

**Do not adopt candidate C1** (failed: cell_exact: warning_detection). Spec section 3, pre-declared before any result: the selected candidate is adopted only if, on POOLED 2018-2025 (87 independent slides), tolerant and cell-exact, independent-slide detection is not lower than v3's by more than 1 slide at Warning+ and at Emergency and 2 at Watch+, and Warning+ alert cell-days fall with the paired-bootstrap 95% CI of the reduction (days resampled) excluding 0. Otherwise it is reported and not adopted; nothing is tuned after the look.

## Reading this report

- Candidates: C1 = region x month thresholds (June-September; October-December and strata without events keep v3's); C2 = C1 and an Emergency confirmation (Emergency is published only if the raw level of the cell the day before was at least Warning, else Warning). Section 11 post-model rules and hysteresis apply unchanged on top of both. Selected on development only.
- Thresholds per level and stratum: the exact fewest alerts that keep v3's point-level hits (development, own cell, event day) over the strata that can be hit, from v3's risk quantiles 50% to 99.9% in 200 steps, then made non-decreasing across levels.
- Development numbers are in-sample for the thresholds (fitted on those seasons), so the burden reduction there is optimistic and is not evidence; only the held-out look decides. Development detection is cell-exact (a tolerant development figure would be a lower bound) and development alert cell-days are counted on the universe-sample cells.
- Ground truth after 2018 is very incomplete (the reported and catalog events are a small fraction of the slides that happened), so held-out precision is relative: for comparing v3 with the candidate at the burdens each raises, not an absolute false-alarm rate.
- Tolerant detection has a high chance floor at Watch+ and Warning+: the 10 km / 1 day window covers about 30-40 cell-days, so scattered alerts would also hit often. Read tolerant detection only as a comparison at similar burden; the cell-exact rows do not reward scattered alerts.
- 87 independent slides (92 records) is a small sample: one slide is 1.1 points of detection.
- The candidate is not read by the live run; adopting it needs a separate, reviewed wiring step.

## Thresholds by region and month (v3 -> candidate; v3 = the stratum keeps v3's)

Risk thresholds; the three levels are shared by C1 and C2.

| region | month | Watch | Warning | Emergency |
|---|---|---|---|---|
| Himalaya | 6 | 2.78e-06 -> 6e-06 | 1.38e-05 -> 1.38e-05 | 4.92e-05 -> 3.93e-05 |
| Himalaya | 7 | 2.78e-06 -> 2.78e-06 | 1.38e-05 -> 1.54e-05 | 4.92e-05 -> 4.92e-05 |
| Himalaya | 8 | 2.78e-06 -> 1.32e-06 | 1.38e-05 -> 7.33e-06 | 4.92e-05 -> 3.93e-05 |
| Himalaya | 9 | 2.78e-06 -> 6e-06 | 1.38e-05 -> 2.51e-05 | 4.92e-05 -> 4.92e-05 |
| Western Ghats | 6 | 3.81e-06 -> 2.09e-06 | 1.37e-05 -> 1.37e-05 | 2.56e-05 -> 4.81e-05 |
| Western Ghats | 7 | 3.81e-06 -> 2.09e-06 | 1.37e-05 -> 7.08e-05 | 2.56e-05 -> 0.000119 |
| Western Ghats | 8 | 3.81e-06 -> 3.81e-06 | 1.37e-05 -> 2.56e-05 | 2.56e-05 -> 2.56e-05 |
| Western Ghats | 9 | 3.81e-06 -> 3.81e-06 | 1.37e-05 -> 4.81e-05 | 2.56e-05 -> 7.08e-05 |

## Fit on the development seasons

Point level (risk against the thresholds, no rules), over the strata that can be hit. The allocation keeps at least the target hits with the fewest alert cell-days.

| level | target hits (v3) | hits allocated | v3 alert cell-days | allocated alert cell-days |
|---|---|---|---|---|
| Watch+ | 613 | 613 | 3,227,158 | 2,977,642 |
| Warning+ | 520 | 520 | 1,319,037 | 1,250,642 |
| Emergency | 363 | 363 | 497,212 | 449,616 |

## Development, full chain (cell-exact detection, universe-sample alert cell-days)

C2 would be selected only with fewer Warning+ alert cell-days than C1 at equal or higher detection at every level; otherwise C1 (ties go to C1). Selected: **C1**.

| model | level | events | hits | detection | alert cell-days | hits per 1000 alert cell-days | change against v3: hits / alert cell-days |
|---|---|---|---|---|---|---|---|
| v3 | Watch+ | 636 | 618 | 97.2% | 3,890,709 | 0.16 |  |
| v3 | Warning+ | 636 | 539 | 84.7% | 1,658,817 | 0.32 |  |
| v3 | Emergency | 636 | 402 | 63.2% | 683,446 | 0.59 |  |
| C1 | Watch+ | 636 | 618 | 97.2% | 3,737,048 | 0.17 | +0 / -153,661 (-3.9%) |
| C1 | Warning+ | 636 | 538 | 84.6% | 1,618,522 | 0.33 | -1 / -40,295 (-2.4%) |
| C1 | Emergency | 636 | 397 | 62.4% | 623,940 | 0.64 | -5 / -59,506 (-8.7%) |
| C2 | Watch+ | 636 | 618 | 97.2% | 3,736,207 | 0.17 | +0 / -154,502 (-4.0%) |
| C2 | Warning+ | 636 | 538 | 84.6% | 1,599,803 | 0.34 | -1 / -59,014 (-3.6%) |
| C2 | Emergency | 636 | 367 | 57.7% | 565,473 | 0.65 | -35 / -117,973 (-17.3%) |

## Held-out look, POOLED (92 records, 87 independent slides; 1 further event dated outside the panel days)

v3 against C1. Detection is in independent slides (a slide is detected when any record is); `events hit` counts records. The change is candidate minus v3 with a paired-bootstrap 95% interval (days resampled).

| tolerance | level | v3 slides | candidate slides | of | v3 events hit | candidate events hit | v3 alert cell-days | candidate alert cell-days | change [95% CI] | v3 precision | candidate precision | precision change [95% CI] |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| tolerant | Watch+ | 85 | 85 | 87 | 90 | 90 | 25,582,037 | 24,722,060 | -859,977 [-1,003,595, -731,775] | 0.0090% | 0.0092% | +0.0002 pp [0.0000, 0.0003] |
| tolerant | Warning+ | 79 | 78 | 87 | 84 | 83 | 10,356,868 | 10,041,684 | -315,184 [-471,841, -160,537] | 0.0171% | 0.0173% | +0.0001 pp [-0.0005, 0.0007] |
| tolerant | Emergency | 73 | 72 | 87 | 78 | 77 | 4,275,304 | 3,850,098 | -425,206 [-468,110, -383,385] | 0.0295% | 0.0319% | +0.0024 pp [0.0012, 0.0036] |
| cell_exact | Watch+ | 79 | 77 | 87 | 84 | 82 | 25,582,037 | 24,722,060 | -859,977 [-1,003,595, -731,775] | 0.0003% | 0.0003% | +0.0000 pp [-0.0000, 0.0000] |
| cell_exact | Warning+ | 65 | 62 | 87 | 69 | 66 | 10,356,868 | 10,041,684 | -315,184 [-471,841, -160,537] | 0.0007% | 0.0007% | -0.0000 pp [-0.0001, 0.0000] |
| cell_exact | Emergency | 48 | 48 | 87 | 52 | 52 | 4,275,304 | 3,850,098 | -425,206 [-468,110, -383,385] | 0.0012% | 0.0014% | +0.0001 pp [0.0001, 0.0002] |

## Decision

**Do not adopt C1.**

| tolerance | condition | numbers | result |
|---|---|---|---|
| tolerant | watch_detection | v3 85, candidate 85, lost 0, allowed 2 | pass |
| tolerant | warning_detection | v3 79, candidate 78, lost 1, allowed 1 | pass |
| tolerant | emergency_detection | v3 73, candidate 72, lost 1, allowed 1 | pass |
| tolerant | warning_burden | Warning+ alert cell-days change -315,184, 95% CI [-471,841, -160,537]; must fall with the interval below 0 | pass |
| cell_exact | watch_detection | v3 79, candidate 77, lost 2, allowed 2 | pass |
| cell_exact | warning_detection | v3 65, candidate 62, lost 3, allowed 1 | FAIL |
| cell_exact | emergency_detection | v3 48, candidate 48, lost 0, allowed 1 | pass |
| cell_exact | warning_burden | Warning+ alert cell-days change -315,184, 95% CI [-471,841, -160,537]; must fall with the interval below 0 | pass |
