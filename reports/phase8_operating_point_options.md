# Operating point options: how much detection for how much less alerting (phase 8, development only)

This document puts one decision in front of the user: how often AetherGuard may raise each alert level. Nothing here changes the live run, and no held-out number is in it. Every number comes from `data/processed/alerts/operating_options/` (development years 2007-2017, out of fold, every one of the 36,792 scored cells).

**Incomplete:** the January-May panels are not all scored yet, so the rest-of-year rows are missing.

## The three options at a glance (published levels, the whole live chain)

Share of cell-days at each level or above, and how many development events (landslide cell-days in the catalogues) the level caught: cell-exact = an alert on the event's own cell and day; tolerant = an alert within 10 km and 1 day.

**Himalaya, monsoon (Jun-Sep)** (557 development events)

| option | Watch+ share | Warning+ share | Emergency share | Warning+ caught (exact / tolerant) | Emergency caught (exact / tolerant) |
|---|---|---|---|---|---|
| A_detection_first | 51.8% | 19.5% | 6.21% | 85% / 98% | 62% / 90% |
| B_balanced | 30.6% | 8.8% | 2.81% | 68% / 93% | 46% / 78% |
| C_rare_emergency | 19.0% | 4.9% | 1.46% | 56% / 87% | 35% / 68% |

**Himalaya, post-monsoon (Oct-Dec)** (32 development events)

| option | Watch+ share | Warning+ share | Emergency share | Warning+ caught (exact / tolerant) | Emergency caught (exact / tolerant) |
|---|---|---|---|---|---|
| A_detection_first | 11.5% | 2.5% | 0.58% | 69% / 78% | 53% / 66% |
| B_balanced | 11.4% | 2.5% | 0.57% | 69% / 78% | 53% / 66% |
| C_rare_emergency | 8.2% | 2.5% | 0.57% | 69% / 78% | 53% / 66% |

**Western Ghats, monsoon (Jun-Sep)** (79 development events)

| option | Watch+ share | Warning+ share | Emergency share | Warning+ caught (exact / tolerant) | Emergency caught (exact / tolerant) |
|---|---|---|---|---|---|
| A_detection_first | 40.3% | 8.2% | 2.20% | 70% / 90% | 44% / 73% |
| B_balanced | 30.7% | 4.9% | 2.20% | 58% / 86% | 44% / 73% |
| C_rare_emergency | 19.0% | 4.6% | 1.31% | 58% / 86% | 35% / 71% |

**Western Ghats, post-monsoon (Oct-Dec)** (12 development events)

| option | Watch+ share | Warning+ share | Emergency share | Warning+ caught (exact / tolerant) | Emergency caught (exact / tolerant) |
|---|---|---|---|---|---|
| A_detection_first | 18.0% | 3.0% | 0.76% | 58% / 83% | 42% / 67% |
| B_balanced | 18.0% | 3.0% | 0.76% | 58% / 83% | 42% / 67% |
| C_rare_emergency | 13.1% | 3.0% | 0.76% | 58% / 83% | 42% / 67% |

## The price of each step, as a cost ratio

Moving from one option to the next saves published alert cell-days and loses some development events. The cost ratio is cell-days saved per event lost: the step is worth taking when one missed landslide is worth FEWER false-alarm cell-days than this number ('any': no event is lost).

| step | region and season | level | alert cell-days saved | events lost (exact / tolerant) | cost ratio (exact / tolerant) |
|---|---|---|---|---|---|
| A_detection_first->B_balanced | Himalaya, monsoon (Jun-Sep) | Watch+ | 8,192,754 (41%) | 35 / 6 | 234,079 / 1,365,459 |
| A_detection_first->B_balanced | Himalaya, monsoon (Jun-Sep) | Warning+ | 4,126,570 (55%) | 96 / 28 | 42,985 / 147,378 |
| A_detection_first->B_balanced | Himalaya, monsoon (Jun-Sep) | Emergency | 1,311,870 (55%) | 93 / 64 | 14,106 / 20,498 |
| A_detection_first->B_balanced | Himalaya, post-monsoon (Oct-Dec) | Watch+ | 11,193 (0%) | 0 / 0 | any / any |
| A_detection_first->B_balanced | Himalaya, post-monsoon (Oct-Dec) | Warning+ | 6,966 (1%) | 0 / 0 | any / any |
| A_detection_first->B_balanced | Himalaya, post-monsoon (Oct-Dec) | Emergency | 2,196 (1%) | 0 / 0 | any / any |
| A_detection_first->B_balanced | Western Ghats, monsoon (Jun-Sep) | Watch+ | 1,036,328 (24%) | 4 / 0 | 259,082 / any |
| A_detection_first->B_balanced | Western Ghats, monsoon (Jun-Sep) | Warning+ | 365,979 (41%) | 9 / 3 | 40,664 / 121,993 |
| A_detection_first->B_balanced | Western Ghats, monsoon (Jun-Sep) | Emergency | 0 (0%) | 0 / 0 | any / any |
| A_detection_first->B_balanced | Western Ghats, post-monsoon (Oct-Dec) | Watch+ | 1,366 (0%) | 0 / 0 | any / any |
| A_detection_first->B_balanced | Western Ghats, post-monsoon (Oct-Dec) | Warning+ | 565 (0%) | 0 / 0 | any / any |
| A_detection_first->B_balanced | Western Ghats, post-monsoon (Oct-Dec) | Emergency | 0 (0%) | 0 / 0 | any / any |
| B_balanced->C_rare_emergency | Himalaya, monsoon (Jun-Sep) | Watch+ | 4,454,914 (38%) | 36 / 6 | 123,748 / 742,486 |
| B_balanced->C_rare_emergency | Himalaya, monsoon (Jun-Sep) | Warning+ | 1,496,464 (44%) | 67 / 35 | 22,335 / 42,756 |
| B_balanced->C_rare_emergency | Himalaya, monsoon (Jun-Sep) | Emergency | 519,518 (48%) | 59 / 57 | 8,805 / 9,114 |
| B_balanced->C_rare_emergency | Himalaya, post-monsoon (Oct-Dec) | Watch+ | 945,460 (28%) | 1 / 0 | 945,460 / any |
| B_balanced->C_rare_emergency | Himalaya, post-monsoon (Oct-Dec) | Warning+ | 917 (0%) | 0 / 0 | any / any |
| B_balanced->C_rare_emergency | Himalaya, post-monsoon (Oct-Dec) | Emergency | 647 (0%) | 0 / 0 | any / any |
| B_balanced->C_rare_emergency | Western Ghats, monsoon (Jun-Sep) | Watch+ | 1,259,207 (38%) | 7 / 1 | 179,887 / 1,259,207 |
| B_balanced->C_rare_emergency | Western Ghats, monsoon (Jun-Sep) | Warning+ | 23,934 (5%) | 0 / 0 | any / any |
| B_balanced->C_rare_emergency | Western Ghats, monsoon (Jun-Sep) | Emergency | 95,687 (40%) | 7 / 2 | 13,670 / 47,844 |
| B_balanced->C_rare_emergency | Western Ghats, post-monsoon (Oct-Dec) | Watch+ | 401,325 (27%) | 0 / 0 | any / any |
| B_balanced->C_rare_emergency | Western Ghats, post-monsoon (Oct-Dec) | Warning+ | 250 (0%) | 0 / 0 | any / any |
| B_balanced->C_rare_emergency | Western Ghats, post-monsoon (Oct-Dec) | Emergency | 234 (0%) | 0 / 0 | any / any |

## Recommendation

Take **B_balanced** to its one confirming held-out look, and keep A (today) live until that look has passed and the wiring has been reviewed.

- Most alerts are raised in the Himalayan monsoon. There B cuts the published Emergency cell-days by 55% (share 6.21% -> 2.81%) and Warning+ by 55% (19.5% -> 8.8%). Emergency still catches 78% of the development events within 10 km and a day (46% on the exact cell), against 90% (62%) today. At B's 2% point cap the tolerant chance floor is 11%, so this detection is far above what scattered alerts would get.
- The price: A -> B is worth it when one missed Emergency event is worth fewer than 20,498 false-alarm Emergency cell-days (tolerant; 14,106 on the exact cell). Going on to C is worth it only below 9,114 (8,805). C leaves Emergency catching 68% tolerant and 35% exact. That is about one landslide in three on its own cell, too few for a level whose name promises the most danger. The ratio is the user's to set (roadmap section 5). If a missed landslide is worth more than the A -> B ratio, keep A.
- At the district level the burden stays high under every option. Under B the median Himalayan district would be at Emergency 0.7 days a week in the monsoon, and the busiest tenth 4.9 days (today: 0.9 and 5.2). A district holds many cells, so one cell at a level is enough on most days. Before districts are used for messages, a district-level frequency cap is needed (a share-of-cells rule chosen the way the cell caps were). That is the next piece of work, and it does not depend on this choice.
- Outside the monsoon the caps change little: on development data today's levels already fire below them. The high live burden outside June-September (phase8_season_validity) is not explained by the thresholds. It needs its own study and stays flagged outside the validated season.
- Any option changes published levels, so wiring it is a model change: it needs the look, a reviewed wiring step and the user's yes.

## What a district officer would receive

A district is at a level on a day under the district rule chosen for the option (section 4 of the spec: the rule with the fewest Warning+ district-days that keeps at least 90% of the events the any-cell rule covers). Days per week at each level or above, for the median district and the busiest tenth of districts (90th percentile):

District boundaries: ODbL 1.0; contains information from geoBoundaries (gbOpen) and OpenStreetMap contributors.

| option | district rule | region and season | Watch+ days/week (median, p90) | Warning+ | Emergency |
|---|---|---|---|---|---|
| A_detection_first | 3 cells or 10% of cells | Himalaya, monsoon (Jun-Sep) | 6.8, 7.0 | 4.0, 6.8 | 0.9, 5.2 |
| A_detection_first | 3 cells or 10% of cells | Himalaya, post-monsoon (Oct-Dec) | 1.6, 3.7 | 0.4, 1.5 | 0.1, 0.5 |
| A_detection_first | 3 cells or 10% of cells | Western Ghats, monsoon (Jun-Sep) | 4.4, 6.8 | 0.3, 5.2 | 0.0, 2.6 |
| A_detection_first | 3 cells or 10% of cells | Western Ghats, post-monsoon (Oct-Dec) | 1.3, 5.1 | 0.1, 2.5 | 0.0, 1.1 |
| B_balanced | 1 cell | Himalaya, monsoon (Jun-Sep) | 6.3, 7.0 | 2.6, 6.6 | 0.7, 4.9 |
| B_balanced | 1 cell | Himalaya, post-monsoon (Oct-Dec) | 1.9, 4.6 | 0.6, 2.2 | 0.2, 0.9 |
| B_balanced | 1 cell | Western Ghats, monsoon (Jun-Sep) | 3.6, 6.8 | 0.2, 5.5 | 0.1, 4.2 |
| B_balanced | 1 cell | Western Ghats, post-monsoon (Oct-Dec) | 1.8, 5.5 | 0.2, 3.3 | 0.0, 1.8 |
| C_rare_emergency | 1 cell | Himalaya, monsoon (Jun-Sep) | 5.1, 7.0 | 1.4, 5.9 | 0.3, 3.8 |
| C_rare_emergency | 1 cell | Himalaya, post-monsoon (Oct-Dec) | 1.5, 4.2 | 0.6, 2.2 | 0.2, 0.9 |
| C_rare_emergency | 1 cell | Western Ghats, monsoon (Jun-Sep) | 1.7, 6.7 | 0.2, 5.5 | 0.0, 3.6 |
| C_rare_emergency | 1 cell | Western Ghats, post-monsoon (Oct-Dec) | 1.2, 5.4 | 0.2, 3.3 | 0.0, 1.8 |

## The options in full

### A_detection_first

Keep today's levels (detection first): the model card's thresholds, which caught about 90%, 75% and 50% of the development positives at Watch, Warning and Emergency.

Thresholds (calibrated risk, Watch / Warning / Emergency) are in `data/processed/alerts/operating_options/levels_A_detection_first.json`, in the card format (`alert_levels`, `risk_by_region`) once per season.

| region and season | level | threshold | point share | with uncertain_high | published share | hold inflation | caught cell-exact | caught tolerant | cell-days per event caught (tolerant) |
|---|---|---|---|---|---|---|---|---|---|
| Himalaya, monsoon (Jun-Sep) | Watch+ | 3.73e-06 | 39.59% | 52.04% | 51.81% | x1.31 | 543 / 557 (97% [96, 99]) | 556 / 557 (100% [99, 100]) | 35,945 |
| Himalaya, monsoon (Jun-Sep) | Warning+ | 1.7e-05 | 15.77% | 15.77% | 19.52% | x1.24 | 475 / 557 (85% [82, 88]) | 546 / 557 (98% [97, 99]) | 13,788 |
| Himalaya, monsoon (Jun-Sep) | Emergency | 7.45e-05 | 4.26% | 4.26% | 6.21% | x1.46 | 347 / 557 (62% [58, 67]) | 501 / 557 (90% [87, 92]) | 4,778 |
| Himalaya, post-monsoon (Oct-Dec) | Watch+ | 3.73e-06 | 10.23% | 20.54% | 11.46% | x1.12 | 27 / 32 (84% [70, 97]) | 29 / 32 (91% [78, 100]) | 114,997 |
| Himalaya, post-monsoon (Oct-Dec) | Warning+ | 1.7e-05 | 1.97% | 1.97% | 2.52% | x1.28 | 22 / 32 (69% [52, 84]) | 25 / 32 (78% [61, 91]) | 29,341 |
| Himalaya, post-monsoon (Oct-Dec) | Emergency | 7.45e-05 | 0.37% | 0.37% | 0.58% | x1.57 | 17 / 32 (53% [34, 71]) | 21 / 32 (66% [48, 81]) | 8,068 |
| Western Ghats, monsoon (Jun-Sep) | Watch+ | 4.14e-06 | 29.20% | 39.48% | 40.29% | x1.38 | 76 / 79 (96% [91, 100]) | 79 / 79 (100% [100, 100]) | 55,077 |
| Western Ghats, monsoon (Jun-Sep) | Warning+ | 2.59e-05 | 6.18% | 6.18% | 8.25% | x1.33 | 55 / 79 (70% [59, 79]) | 71 / 79 (90% [82, 96]) | 12,543 |
| Western Ghats, monsoon (Jun-Sep) | Emergency | 9.29e-05 | 1.42% | 1.42% | 2.20% | x1.55 | 35 / 79 (44% [33, 56]) | 58 / 79 (73% [63, 83]) | 4,091 |
| Western Ghats, post-monsoon (Oct-Dec) | Watch+ | 4.14e-06 | 13.17% | 20.84% | 18.02% | x1.37 | 10 / 12 (83% [58, 100]) | 10 / 12 (83% [58, 100]) | 146,779 |
| Western Ghats, post-monsoon (Oct-Dec) | Warning+ | 2.59e-05 | 2.20% | 2.20% | 3.00% | x1.36 | 7 / 12 (58% [33, 83]) | 10 / 12 (83% [58, 100]) | 24,453 |
| Western Ghats, post-monsoon (Oct-Dec) | Emergency | 9.29e-05 | 0.46% | 0.46% | 0.76% | x1.65 | 5 / 12 (42% [17, 67]) | 8 / 12 (67% [42, 92]) | 7,763 |

Districts (each candidate rule): district-days at the level or above, events inside a district at the level on the event day (and within 1 day), district-days per event:

| region and season | level | rule | district-days | events in alerted district | within 1 day | district-days per event | cell-days per event (tolerant, beside) |
|---|---|---|---|---|---|---|---|
| Himalaya, monsoon (Jun-Sep) | Watch+ | 1 cell | 478,647 | 556 / 557 | 556 | 861 | 35,945 |
| Himalaya, monsoon (Jun-Sep) | Watch+ | 3 cells or 10% of cells | 452,835 | 556 / 557 | 556 | 814 | 35,945 |
| Himalaya, monsoon (Jun-Sep) | Watch+ | 5 cells or 25% of cells | 429,424 | 556 / 557 | 556 | 772 | 35,945 |
| Himalaya, monsoon (Jun-Sep) | Warning+ | 1 cell | 328,046 | 555 / 557 | 556 | 591 | 13,788 |
| Himalaya, monsoon (Jun-Sep) | Warning+ | 3 cells or 10% of cells | 289,727 | 552 / 557 | 553 | 525 | 13,788 |
| Himalaya, monsoon (Jun-Sep) | Warning+ | 5 cells or 25% of cells | 258,790 | 546 / 557 | 551 | 474 | 13,788 |
| Himalaya, monsoon (Jun-Sep) | Emergency | 1 cell | 204,637 | 528 / 557 | 543 | 388 | 4,778 |
| Himalaya, monsoon (Jun-Sep) | Emergency | 3 cells or 10% of cells | 153,202 | 486 / 557 | 524 | 315 | 4,778 |
| Himalaya, monsoon (Jun-Sep) | Emergency | 5 cells or 25% of cells | 121,780 | 466 / 557 | 508 | 261 | 4,778 |
| Himalaya, post-monsoon (Oct-Dec) | Watch+ | 1 cell | 135,498 | 29 / 32 | 30 | 4,672 | 114,997 |
| Himalaya, post-monsoon (Oct-Dec) | Watch+ | 3 cells or 10% of cells | 112,119 | 29 / 32 | 29 | 3,866 | 114,997 |
| Himalaya, post-monsoon (Oct-Dec) | Watch+ | 5 cells or 25% of cells | 97,950 | 29 / 32 | 29 | 3,378 | 114,997 |
| Himalaya, post-monsoon (Oct-Dec) | Warning+ | 1 cell | 56,903 | 25 / 32 | 27 | 2,276 | 29,341 |
| Himalaya, post-monsoon (Oct-Dec) | Warning+ | 3 cells or 10% of cells | 40,374 | 24 / 32 | 26 | 1,682 | 29,341 |
| Himalaya, post-monsoon (Oct-Dec) | Warning+ | 5 cells or 25% of cells | 31,891 | 24 / 32 | 25 | 1,329 | 29,341 |
| Himalaya, post-monsoon (Oct-Dec) | Emergency | 1 cell | 22,228 | 23 / 32 | 24 | 966 | 8,068 |
| Himalaya, post-monsoon (Oct-Dec) | Emergency | 3 cells or 10% of cells | 12,399 | 21 / 32 | 23 | 590 | 8,068 |
| Himalaya, post-monsoon (Oct-Dec) | Emergency | 5 cells or 25% of cells | 8,627 | 20 / 32 | 23 | 431 | 8,068 |
| Western Ghats, monsoon (Jun-Sep) | Watch+ | 1 cell | 101,917 | 79 / 79 | 79 | 1,290 | 55,077 |
| Western Ghats, monsoon (Jun-Sep) | Watch+ | 3 cells or 10% of cells | 90,262 | 79 / 79 | 79 | 1,143 | 55,077 |
| Western Ghats, monsoon (Jun-Sep) | Watch+ | 5 cells or 25% of cells | 81,968 | 79 / 79 | 79 | 1,038 | 55,077 |
| Western Ghats, monsoon (Jun-Sep) | Warning+ | 1 cell | 50,948 | 78 / 79 | 79 | 653 | 12,543 |
| Western Ghats, monsoon (Jun-Sep) | Warning+ | 3 cells or 10% of cells | 39,599 | 74 / 79 | 76 | 535 | 12,543 |
| Western Ghats, monsoon (Jun-Sep) | Warning+ | 5 cells or 25% of cells | 32,919 | 69 / 79 | 75 | 477 | 12,543 |
| Western Ghats, monsoon (Jun-Sep) | Emergency | 1 cell | 28,643 | 66 / 79 | 74 | 434 | 4,091 |
| Western Ghats, monsoon (Jun-Sep) | Emergency | 3 cells or 10% of cells | 17,075 | 57 / 79 | 61 | 300 | 4,091 |
| Western Ghats, monsoon (Jun-Sep) | Emergency | 5 cells or 25% of cells | 12,592 | 51 / 79 | 57 | 247 | 4,091 |
| Western Ghats, post-monsoon (Oct-Dec) | Watch+ | 1 cell | 43,424 | 12 / 12 | 12 | 3,619 | 146,779 |
| Western Ghats, post-monsoon (Oct-Dec) | Watch+ | 3 cells or 10% of cells | 37,688 | 12 / 12 | 12 | 3,141 | 146,779 |
| Western Ghats, post-monsoon (Oct-Dec) | Watch+ | 5 cells or 25% of cells | 34,441 | 11 / 12 | 11 | 3,131 | 146,779 |
| Western Ghats, post-monsoon (Oct-Dec) | Warning+ | 1 cell | 18,981 | 10 / 12 | 10 | 1,898 | 24,453 |
| Western Ghats, post-monsoon (Oct-Dec) | Warning+ | 3 cells or 10% of cells | 13,911 | 10 / 12 | 10 | 1,391 | 24,453 |
| Western Ghats, post-monsoon (Oct-Dec) | Warning+ | 5 cells or 25% of cells | 11,107 | 10 / 12 | 10 | 1,111 | 24,453 |
| Western Ghats, post-monsoon (Oct-Dec) | Emergency | 1 cell | 9,493 | 9 / 12 | 9 | 1,055 | 7,763 |
| Western Ghats, post-monsoon (Oct-Dec) | Emergency | 3 cells or 10% of cells | 5,312 | 8 / 12 | 8 | 664 | 7,763 |
| Western Ghats, post-monsoon (Oct-Dec) | Emergency | 5 cells or 25% of cells | 3,705 | 6 / 12 | 7 | 618 | 7,763 |

Chosen district rule: **3 cells or 10% of cells**.

### B_balanced

Balanced: in every region and season, Watch+ on at most 20%, Warning+ on at most 6% and Emergency on at most 2% of the cell-days (point level), never below today's thresholds.

Thresholds (calibrated risk, Watch / Warning / Emergency) are in `data/processed/alerts/operating_options/levels_B_balanced.json`, in the card format (`alert_levels`, `risk_by_region`) once per season.

| region and season | level | threshold | point share | with uncertain_high | published share | hold inflation | caught cell-exact | caught tolerant | cell-days per event caught (tolerant) |
|---|---|---|---|---|---|---|---|---|---|
| Himalaya, monsoon (Jun-Sep) | Watch+ | 9.82e-06 | 17.07% | 26.89% | 30.57% | x1.79 | 508 / 557 (91% [89, 93]) | 550 / 557 (99% [98, 100]) | 21,441 |
| Himalaya, monsoon (Jun-Sep) | Warning+ | 4.77e-05 | 5.75% | 5.75% | 8.82% | x1.53 | 379 / 557 (68% [64, 72]) | 518 / 557 (93% [91, 95]) | 6,567 |
| Himalaya, monsoon (Jun-Sep) | Emergency | 0.00011 | 1.65% | 1.65% | 2.81% | x1.70 | 254 / 557 (46% [41, 50]) | 437 / 557 (78% [75, 82]) | 2,476 |
| Himalaya, post-monsoon (Oct-Dec) | Watch+ | 3.73e-06 | 10.23% | 20.54% | 11.43% | x1.12 | 27 / 32 (84% [70, 97]) | 29 / 32 (91% [78, 100]) | 114,611 |
| Himalaya, post-monsoon (Oct-Dec) | Warning+ | 1.7e-05 | 1.97% | 1.97% | 2.50% | x1.27 | 22 / 32 (69% [52, 84]) | 25 / 32 (78% [61, 91]) | 29,062 |
| Himalaya, post-monsoon (Oct-Dec) | Emergency | 7.45e-05 | 0.37% | 0.37% | 0.57% | x1.55 | 17 / 32 (53% [34, 71]) | 21 / 32 (66% [48, 81]) | 7,963 |
| Western Ghats, monsoon (Jun-Sep) | Watch+ | 4.14e-06 | 17.15% | 26.46% | 30.69% | x1.79 | 72 / 79 (91% [84, 96]) | 79 / 79 (100% [100, 100]) | 41,959 |
| Western Ghats, monsoon (Jun-Sep) | Warning+ | 2.59e-05 | 2.38% | 2.38% | 4.86% | x2.04 | 46 / 79 (58% [47, 69]) | 68 / 79 (86% [78, 93]) | 7,714 |
| Western Ghats, monsoon (Jun-Sep) | Emergency | 9.29e-05 | 1.42% | 1.42% | 2.20% | x1.55 | 35 / 79 (44% [33, 56]) | 58 / 79 (73% [63, 83]) | 4,091 |
| Western Ghats, post-monsoon (Oct-Dec) | Watch+ | 4.14e-06 | 13.17% | 20.84% | 18.00% | x1.37 | 10 / 12 (83% [58, 100]) | 10 / 12 (83% [58, 100]) | 146,643 |
| Western Ghats, post-monsoon (Oct-Dec) | Warning+ | 2.59e-05 | 2.20% | 2.20% | 3.00% | x1.36 | 7 / 12 (58% [33, 83]) | 10 / 12 (83% [58, 100]) | 24,396 |
| Western Ghats, post-monsoon (Oct-Dec) | Emergency | 9.29e-05 | 0.46% | 0.46% | 0.76% | x1.65 | 5 / 12 (42% [17, 67]) | 8 / 12 (67% [42, 92]) | 7,763 |

Districts (each candidate rule): district-days at the level or above, events inside a district at the level on the event day (and within 1 day), district-days per event:

| region and season | level | rule | district-days | events in alerted district | within 1 day | district-days per event | cell-days per event (tolerant, beside) |
|---|---|---|---|---|---|---|---|
| Himalaya, monsoon (Jun-Sep) | Watch+ | 1 cell | 395,166 | 556 / 557 | 556 | 711 | 21,441 |
| Himalaya, monsoon (Jun-Sep) | Watch+ | 3 cells or 10% of cells | 359,448 | 555 / 557 | 556 | 648 | 21,441 |
| Himalaya, monsoon (Jun-Sep) | Watch+ | 5 cells or 25% of cells | 329,649 | 554 / 557 | 555 | 595 | 21,441 |
| Himalaya, monsoon (Jun-Sep) | Warning+ | 1 cell | 241,879 | 540 / 557 | 550 | 448 | 6,567 |
| Himalaya, monsoon (Jun-Sep) | Warning+ | 3 cells or 10% of cells | 192,127 | 510 / 557 | 536 | 377 | 6,567 |
| Himalaya, monsoon (Jun-Sep) | Warning+ | 5 cells or 25% of cells | 158,767 | 483 / 557 | 520 | 329 | 6,567 |
| Himalaya, monsoon (Jun-Sep) | Emergency | 1 cell | 139,413 | 486 / 557 | 522 | 287 | 2,476 |
| Himalaya, monsoon (Jun-Sep) | Emergency | 3 cells or 10% of cells | 90,070 | 415 / 557 | 457 | 217 | 2,476 |
| Himalaya, monsoon (Jun-Sep) | Emergency | 5 cells or 25% of cells | 65,294 | 380 / 557 | 420 | 172 | 2,476 |
| Himalaya, post-monsoon (Oct-Dec) | Watch+ | 1 cell | 135,380 | 29 / 32 | 30 | 4,668 | 114,611 |
| Himalaya, post-monsoon (Oct-Dec) | Watch+ | 3 cells or 10% of cells | 111,968 | 29 / 32 | 29 | 3,861 | 114,611 |
| Himalaya, post-monsoon (Oct-Dec) | Watch+ | 5 cells or 25% of cells | 97,810 | 29 / 32 | 29 | 3,373 | 114,611 |
| Himalaya, post-monsoon (Oct-Dec) | Warning+ | 1 cell | 56,722 | 25 / 32 | 27 | 2,269 | 29,062 |
| Himalaya, post-monsoon (Oct-Dec) | Warning+ | 3 cells or 10% of cells | 40,163 | 24 / 32 | 26 | 1,673 | 29,062 |
| Himalaya, post-monsoon (Oct-Dec) | Warning+ | 5 cells or 25% of cells | 31,658 | 24 / 32 | 25 | 1,319 | 29,062 |
| Himalaya, post-monsoon (Oct-Dec) | Emergency | 1 cell | 22,040 | 23 / 32 | 24 | 958 | 7,963 |
| Himalaya, post-monsoon (Oct-Dec) | Emergency | 3 cells or 10% of cells | 12,234 | 21 / 32 | 23 | 583 | 7,963 |
| Himalaya, post-monsoon (Oct-Dec) | Emergency | 5 cells or 25% of cells | 8,520 | 20 / 32 | 23 | 426 | 7,963 |
| Western Ghats, monsoon (Jun-Sep) | Watch+ | 1 cell | 86,598 | 79 / 79 | 79 | 1,096 | 41,959 |
| Western Ghats, monsoon (Jun-Sep) | Watch+ | 3 cells or 10% of cells | 76,401 | 79 / 79 | 79 | 967 | 41,959 |
| Western Ghats, monsoon (Jun-Sep) | Watch+ | 5 cells or 25% of cells | 70,419 | 79 / 79 | 79 | 891 | 41,959 |
| Western Ghats, monsoon (Jun-Sep) | Warning+ | 1 cell | 42,377 | 71 / 79 | 78 | 597 | 7,714 |
| Western Ghats, monsoon (Jun-Sep) | Warning+ | 3 cells or 10% of cells | 30,026 | 65 / 79 | 74 | 462 | 7,714 |
| Western Ghats, monsoon (Jun-Sep) | Warning+ | 5 cells or 25% of cells | 23,481 | 62 / 79 | 70 | 379 | 7,714 |
| Western Ghats, monsoon (Jun-Sep) | Emergency | 1 cell | 28,630 | 66 / 79 | 74 | 434 | 4,091 |
| Western Ghats, monsoon (Jun-Sep) | Emergency | 3 cells or 10% of cells | 17,075 | 57 / 79 | 61 | 300 | 4,091 |
| Western Ghats, monsoon (Jun-Sep) | Emergency | 5 cells or 25% of cells | 12,592 | 51 / 79 | 57 | 247 | 4,091 |
| Western Ghats, post-monsoon (Oct-Dec) | Watch+ | 1 cell | 43,408 | 12 / 12 | 12 | 3,617 | 146,643 |
| Western Ghats, post-monsoon (Oct-Dec) | Watch+ | 3 cells or 10% of cells | 37,663 | 12 / 12 | 12 | 3,139 | 146,643 |
| Western Ghats, post-monsoon (Oct-Dec) | Watch+ | 5 cells or 25% of cells | 34,417 | 11 / 12 | 11 | 3,129 | 146,643 |
| Western Ghats, post-monsoon (Oct-Dec) | Warning+ | 1 cell | 18,960 | 10 / 12 | 10 | 1,896 | 24,396 |
| Western Ghats, post-monsoon (Oct-Dec) | Warning+ | 3 cells or 10% of cells | 13,891 | 10 / 12 | 10 | 1,389 | 24,396 |
| Western Ghats, post-monsoon (Oct-Dec) | Warning+ | 5 cells or 25% of cells | 11,092 | 10 / 12 | 10 | 1,109 | 24,396 |
| Western Ghats, post-monsoon (Oct-Dec) | Emergency | 1 cell | 9,493 | 9 / 12 | 9 | 1,055 | 7,763 |
| Western Ghats, post-monsoon (Oct-Dec) | Emergency | 3 cells or 10% of cells | 5,312 | 8 / 12 | 8 | 664 | 7,763 |
| Western Ghats, post-monsoon (Oct-Dec) | Emergency | 5 cells or 25% of cells | 3,705 | 6 / 12 | 7 | 618 | 7,763 |

Chosen district rule: **1 cell**.

### C_rare_emergency

Rare Emergency: Watch+ on at most 10%, Warning+ on at most 3% and Emergency on at most 1% of the cell-days (point level), never below today's thresholds.

Thresholds (calibrated risk, Watch / Warning / Emergency) are in `data/processed/alerts/operating_options/levels_C_rare_emergency.json`, in the card format (`alert_levels`, `risk_by_region`) once per season.

| region and season | level | threshold | point share | with uncertain_high | published share | hold inflation | caught cell-exact | caught tolerant | cell-days per event caught (tolerant) |
|---|---|---|---|---|---|---|---|---|---|
| Himalaya, monsoon (Jun-Sep) | Watch+ | 2.5e-05 | 8.74% | 15.25% | 19.02% | x2.18 | 472 / 557 (85% [82, 88]) | 544 / 557 (98% [96, 99]) | 13,489 |
| Himalaya, monsoon (Jun-Sep) | Warning+ | 7.83e-05 | 2.90% | 2.90% | 4.94% | x1.70 | 312 / 557 (56% [52, 61]) | 483 / 557 (87% [84, 90]) | 3,945 |
| Himalaya, monsoon (Jun-Sep) | Emergency | 0.000183 | 0.86% | 0.86% | 1.46% | x1.71 | 195 / 557 (35% [31, 39]) | 380 / 557 (68% [64, 72]) | 1,480 |
| Himalaya, post-monsoon (Oct-Dec) | Watch+ | 3.73e-06 | 4.22% | 9.49% | 8.18% | x1.94 | 26 / 32 (81% [66, 94]) | 29 / 32 (91% [78, 100]) | 82,009 |
| Himalaya, post-monsoon (Oct-Dec) | Warning+ | 1.7e-05 | 1.97% | 1.97% | 2.49% | x1.27 | 22 / 32 (69% [52, 84]) | 25 / 32 (78% [61, 91]) | 29,026 |
| Himalaya, post-monsoon (Oct-Dec) | Emergency | 7.45e-05 | 0.37% | 0.37% | 0.57% | x1.54 | 17 / 32 (53% [34, 71]) | 21 / 32 (66% [48, 81]) | 7,932 |
| Western Ghats, monsoon (Jun-Sep) | Watch+ | 9.17e-06 | 8.08% | 14.62% | 19.03% | x2.36 | 65 / 79 (82% [73, 90]) | 78 / 79 (99% [96, 100]) | 26,353 |
| Western Ghats, monsoon (Jun-Sep) | Warning+ | 2.59e-05 | 2.38% | 2.38% | 4.64% | x1.95 | 46 / 79 (58% [47, 69]) | 68 / 79 (86% [78, 93]) | 7,362 |
| Western Ghats, monsoon (Jun-Sep) | Emergency | 9.29e-05 | 0.69% | 0.69% | 1.31% | x1.89 | 28 / 79 (35% [26, 46]) | 56 / 79 (71% [60, 80]) | 2,528 |
| Western Ghats, post-monsoon (Oct-Dec) | Watch+ | 4.14e-06 | 6.81% | 11.96% | 13.08% | x1.92 | 10 / 12 (83% [58, 100]) | 10 / 12 (83% [58, 100]) | 106,510 |
| Western Ghats, post-monsoon (Oct-Dec) | Warning+ | 2.59e-05 | 2.20% | 2.20% | 2.99% | x1.36 | 7 / 12 (58% [33, 83]) | 10 / 12 (83% [58, 100]) | 24,371 |
| Western Ghats, post-monsoon (Oct-Dec) | Emergency | 9.29e-05 | 0.46% | 0.46% | 0.76% | x1.64 | 5 / 12 (42% [17, 67]) | 8 / 12 (67% [42, 92]) | 7,734 |

Districts (each candidate rule): district-days at the level or above, events inside a district at the level on the event day (and within 1 day), district-days per event:

| region and season | level | rule | district-days | events in alerted district | within 1 day | district-days per event | cell-days per event (tolerant, beside) |
|---|---|---|---|---|---|---|---|
| Himalaya, monsoon (Jun-Sep) | Watch+ | 1 cell | 335,603 | 554 / 557 | 556 | 606 | 13,489 |
| Himalaya, monsoon (Jun-Sep) | Watch+ | 3 cells or 10% of cells | 293,403 | 552 / 557 | 554 | 532 | 13,489 |
| Himalaya, monsoon (Jun-Sep) | Watch+ | 5 cells or 25% of cells | 260,139 | 551 / 557 | 552 | 472 | 13,489 |
| Himalaya, monsoon (Jun-Sep) | Warning+ | 1 cell | 186,563 | 516 / 557 | 533 | 362 | 3,945 |
| Himalaya, monsoon (Jun-Sep) | Warning+ | 3 cells or 10% of cells | 134,215 | 466 / 557 | 505 | 288 | 3,945 |
| Himalaya, monsoon (Jun-Sep) | Warning+ | 5 cells or 25% of cells | 103,745 | 432 / 557 | 477 | 240 | 3,945 |
| Himalaya, monsoon (Jun-Sep) | Emergency | 1 cell | 97,076 | 442 / 557 | 481 | 220 | 1,480 |
| Himalaya, monsoon (Jun-Sep) | Emergency | 3 cells or 10% of cells | 54,662 | 351 / 557 | 394 | 156 | 1,480 |
| Himalaya, monsoon (Jun-Sep) | Emergency | 5 cells or 25% of cells | 36,262 | 287 / 557 | 345 | 126 | 1,480 |
| Himalaya, post-monsoon (Oct-Dec) | Watch+ | 1 cell | 118,235 | 29 / 32 | 30 | 4,077 | 82,009 |
| Himalaya, post-monsoon (Oct-Dec) | Watch+ | 3 cells or 10% of cells | 93,055 | 29 / 32 | 29 | 3,209 | 82,009 |
| Himalaya, post-monsoon (Oct-Dec) | Watch+ | 5 cells or 25% of cells | 78,989 | 29 / 32 | 29 | 2,724 | 82,009 |
| Himalaya, post-monsoon (Oct-Dec) | Warning+ | 1 cell | 56,691 | 25 / 32 | 27 | 2,268 | 29,026 |
| Himalaya, post-monsoon (Oct-Dec) | Warning+ | 3 cells or 10% of cells | 40,137 | 24 / 32 | 26 | 1,672 | 29,026 |
| Himalaya, post-monsoon (Oct-Dec) | Warning+ | 5 cells or 25% of cells | 31,632 | 24 / 32 | 25 | 1,318 | 29,026 |
| Himalaya, post-monsoon (Oct-Dec) | Emergency | 1 cell | 21,983 | 23 / 32 | 24 | 956 | 7,932 |
| Himalaya, post-monsoon (Oct-Dec) | Emergency | 3 cells or 10% of cells | 12,196 | 21 / 32 | 23 | 581 | 7,932 |
| Himalaya, post-monsoon (Oct-Dec) | Emergency | 5 cells or 25% of cells | 8,490 | 20 / 32 | 23 | 424 | 7,932 |
| Western Ghats, monsoon (Jun-Sep) | Watch+ | 1 cell | 71,591 | 79 / 79 | 79 | 906 | 26,353 |
| Western Ghats, monsoon (Jun-Sep) | Watch+ | 3 cells or 10% of cells | 61,905 | 79 / 79 | 79 | 784 | 26,353 |
| Western Ghats, monsoon (Jun-Sep) | Watch+ | 5 cells or 25% of cells | 55,751 | 79 / 79 | 79 | 706 | 26,353 |
| Western Ghats, monsoon (Jun-Sep) | Warning+ | 1 cell | 41,701 | 71 / 79 | 78 | 587 | 7,362 |
| Western Ghats, monsoon (Jun-Sep) | Warning+ | 3 cells or 10% of cells | 29,303 | 65 / 79 | 74 | 451 | 7,362 |
| Western Ghats, monsoon (Jun-Sep) | Warning+ | 5 cells or 25% of cells | 22,853 | 61 / 79 | 70 | 375 | 7,362 |
| Western Ghats, monsoon (Jun-Sep) | Emergency | 1 cell | 22,936 | 63 / 79 | 71 | 364 | 2,528 |
| Western Ghats, monsoon (Jun-Sep) | Emergency | 3 cells or 10% of cells | 12,327 | 49 / 79 | 54 | 252 | 2,528 |
| Western Ghats, monsoon (Jun-Sep) | Emergency | 5 cells or 25% of cells | 8,825 | 45 / 79 | 49 | 196 | 2,528 |
| Western Ghats, post-monsoon (Oct-Dec) | Watch+ | 1 cell | 38,253 | 12 / 12 | 12 | 3,188 | 106,510 |
| Western Ghats, post-monsoon (Oct-Dec) | Watch+ | 3 cells or 10% of cells | 32,383 | 11 / 12 | 11 | 2,944 | 106,510 |
| Western Ghats, post-monsoon (Oct-Dec) | Watch+ | 5 cells or 25% of cells | 29,462 | 11 / 12 | 11 | 2,678 | 106,510 |
| Western Ghats, post-monsoon (Oct-Dec) | Warning+ | 1 cell | 18,956 | 10 / 12 | 10 | 1,896 | 24,371 |
| Western Ghats, post-monsoon (Oct-Dec) | Warning+ | 3 cells or 10% of cells | 13,882 | 10 / 12 | 10 | 1,388 | 24,371 |
| Western Ghats, post-monsoon (Oct-Dec) | Warning+ | 5 cells or 25% of cells | 11,083 | 10 / 12 | 10 | 1,108 | 24,371 |
| Western Ghats, post-monsoon (Oct-Dec) | Emergency | 1 cell | 9,486 | 9 / 12 | 9 | 1,054 | 7,734 |
| Western Ghats, post-monsoon (Oct-Dec) | Emergency | 3 cells or 10% of cells | 5,297 | 8 / 12 | 8 | 662 | 7,734 |
| Western Ghats, post-monsoon (Oct-Dec) | Emergency | 5 cells or 25% of cells | 3,698 | 6 / 12 | 7 | 616 | 7,734 |

Chosen district rule: **1 cell**.

## The trade-off curve (point level, no rules, no hysteresis)

Each row caps the level at a share of the cell-days of the region and season. Cost ratio: the alert cell-days the step saves per event it loses against the row above; the step is the better choice when one missed event is worth FEWER false-alarm cell-days than that ('any': the step loses no event). Chance floor: the share of all cell-days with an alert within 10 km and 1 day, i.e. the tolerant detection of an event placed at random.

### Himalaya, monsoon (Jun-Sep): 557 events (510 independent slides), 38,574,448 cell-days

| level | cap | realised share | alert cell-days | caught cell-exact [95% CI] | caught tolerant [95% CI] | chance floor | events per 1,000 alert cell-days (exact / tolerant) | cost ratio (exact / tolerant) |
|---|---|---|---|---|---|---|---|---|
| Watch+ today | card | 39.59% | 15,270,824 | 535 / 557 (96% [94, 98]) | 555 / 557 (100% [99, 100]) | 68.3% | 0.04 / 0.04 | |
| Warning+ today | card | 15.77% | 6,081,561 | 464 / 557 (83% [80, 86]) | 547 / 557 (98% [97, 99]) | 44.3% | 0.08 / 0.09 | |
| Emergency today | card | 4.26% | 1,644,068 | 317 / 557 (57% [53, 61]) | 494 / 557 (89% [86, 91]) | 20.9% | 0.19 / 0.30 | |
| Watch+ | 45.0% | 42.53% | 16,403,822 | 538 / 557 (97% [95, 98]) | 555 / 557 (100% [99, 100]) | 70.5% | 0.03 / 0.03 | any / any |
| Watch+ | 35.0% | 25.24% | 9,735,436 | 503 / 557 (90% [88, 93]) | 550 / 557 (99% [98, 100]) | 56.2% | 0.05 / 0.06 | 190,525 / 1,333,677 |
| Watch+ | 25.0% | 22.53% | 8,691,301 | 496 / 557 (89% [86, 92]) | 550 / 557 (99% [98, 100]) | 53.2% | 0.06 / 0.06 | 149,162 / any |
| Watch+ | 15.0% | 13.48% | 5,201,666 | 447 / 557 (80% [77, 84]) | 542 / 557 (97% [96, 99]) | 41.1% | 0.09 / 0.10 | 71,217 / 436,204 |
| Watch+ | 10.0% | 8.74% | 3,372,802 | 401 / 557 (72% [68, 76]) | 525 / 557 (94% [92, 96]) | 32.3% | 0.12 / 0.16 | 39,758 / 107,580 |
| Watch+ | 6.0% | 5.75% | 2,219,288 | 352 / 557 (63% [59, 68]) | 512 / 557 (92% [90, 94]) | 25.3% | 0.16 / 0.23 | 23,541 / 88,732 |
| Watch+ | 3.0% | 2.90% | 1,117,875 | 270 / 557 (48% [44, 53]) | 472 / 557 (85% [82, 88]) | 16.5% | 0.24 / 0.42 | 13,432 / 27,535 |
| Warning+ | 20.0% | 17.07% | 6,583,534 | 470 / 557 (84% [81, 87]) | 548 / 557 (98% [97, 99]) | 46.4% | 0.07 / 0.08 | any / any |
| Warning+ | 15.0% | 13.48% | 5,201,666 | 447 / 557 (80% [77, 84]) | 542 / 557 (97% [96, 99]) | 41.1% | 0.09 / 0.10 | 60,081 / 230,311 |
| Warning+ | 10.0% | 8.74% | 3,372,802 | 401 / 557 (72% [68, 76]) | 525 / 557 (94% [92, 96]) | 32.3% | 0.12 / 0.16 | 39,758 / 107,580 |
| Warning+ | 6.0% | 5.75% | 2,219,288 | 352 / 557 (63% [59, 68]) | 512 / 557 (92% [90, 94]) | 25.3% | 0.16 / 0.23 | 23,541 / 88,732 |
| Warning+ | 4.0% | 3.23% | 1,245,590 | 281 / 557 (50% [46, 55]) | 478 / 557 (86% [83, 89]) | 17.7% | 0.23 / 0.38 | 13,714 / 28,638 |
| Warning+ | 2.0% | 1.65% | 638,059 | 215 / 557 (39% [34, 43]) | 422 / 557 (76% [72, 79]) | 11.4% | 0.34 / 0.66 | 9,205 / 10,849 |
| Warning+ | 1.0% | 0.86% | 329,918 | 162 / 557 (29% [25, 33]) | 362 / 557 (65% [60, 69]) | 7.2% | 0.49 / 1.10 | 5,814 / 5,136 |
| Emergency | 8.0% | 7.25% | 2,797,717 | 380 / 557 (68% [64, 72]) | 517 / 557 (93% [90, 95]) | 29.0% | 0.14 / 0.18 | any / any |
| Emergency | 5.0% | 4.33% | 1,669,816 | 318 / 557 (57% [53, 62]) | 494 / 557 (89% [86, 91]) | 21.3% | 0.19 / 0.30 | 18,192 / 49,039 |
| Emergency | 3.0% | 2.90% | 1,117,875 | 270 / 557 (48% [44, 53]) | 472 / 557 (85% [82, 88]) | 16.5% | 0.24 / 0.42 | 11,499 / 25,088 |
| Emergency | 2.0% | 1.65% | 638,059 | 215 / 557 (39% [34, 43]) | 422 / 557 (76% [72, 79]) | 11.4% | 0.34 / 0.66 | 8,724 / 9,596 |
| Emergency | 1.0% | 0.86% | 329,918 | 162 / 557 (29% [25, 33]) | 362 / 557 (65% [60, 69]) | 7.2% | 0.49 / 1.10 | 5,814 / 5,136 |
| Emergency | 0.5% | 0.30% | 116,800 | 92 / 557 (17% [13, 20]) | 236 / 557 (42% [38, 47]) | 3.3% | 0.79 / 2.02 | 3,045 / 1,691 |
| Emergency | 0.2% | 0.09% | 36,193 | 61 / 557 (11% [8, 14]) | 153 / 557 (27% [23, 32]) | 1.3% | 1.69 / 4.23 | 2,600 / 971 |

### Himalaya, post-monsoon (Oct-Dec): 32 events (30 independent slides), 29,088,928 cell-days

| level | cap | realised share | alert cell-days | caught cell-exact [95% CI] | caught tolerant [95% CI] | chance floor | events per 1,000 alert cell-days (exact / tolerant) | cost ratio (exact / tolerant) |
|---|---|---|---|---|---|---|---|---|
| Watch+ today | card | 10.23% | 2,975,463 | 25 / 32 (78% [62, 91]) | 32 / 32 (100% [100, 100]) | 31.3% | 0.01 / 0.01 | |
| Warning+ today | card | 1.97% | 573,533 | 22 / 32 (69% [52, 84]) | 25 / 32 (78% [62, 91]) | 9.7% | 0.04 / 0.04 | |
| Emergency today | card | 0.37% | 107,840 | 16 / 32 (50% [30, 68]) | 21 / 32 (66% [48, 81]) | 2.6% | 0.15 / 0.19 | |
| Watch+ | 45.0% | 30.94% | 9,000,282 | 32 / 32 (100% [100, 100]) | 32 / 32 (100% [100, 100]) | 60.1% | 0.00 / 0.00 | any / any |
| Watch+ | 35.0% | 30.94% | 9,000,282 | 32 / 32 (100% [100, 100]) | 32 / 32 (100% [100, 100]) | 60.1% | 0.00 / 0.00 | any / any |
| Watch+ | 25.0% | 18.29% | 5,319,626 | 30 / 32 (94% [84, 100]) | 32 / 32 (100% [100, 100]) | 45.3% | 0.01 / 0.01 | 1,840,328 / any |
| Watch+ | 15.0% | 12.04% | 3,500,853 | 27 / 32 (84% [70, 97]) | 32 / 32 (100% [100, 100]) | 34.8% | 0.01 / 0.01 | 606,258 / any |
| Watch+ | 10.0% | 4.22% | 1,228,249 | 24 / 32 (75% [59, 88]) | 27 / 32 (84% [70, 94]) | 16.9% | 0.02 / 0.02 | 757,535 / 454,521 |
| Watch+ | 6.0% | 4.22% | 1,228,249 | 24 / 32 (75% [59, 88]) | 27 / 32 (84% [70, 94]) | 16.9% | 0.02 / 0.02 | any / any |
| Watch+ | 3.0% | 2.22% | 647,104 | 23 / 32 (72% [55, 87]) | 25 / 32 (78% [62, 91]) | 10.6% | 0.04 / 0.04 | 581,145 / 290,572 |
| Warning+ | 20.0% | 18.29% | 5,319,626 | 30 / 32 (94% [84, 100]) | 32 / 32 (100% [100, 100]) | 45.3% | 0.01 / 0.01 | any / any |
| Warning+ | 15.0% | 12.04% | 3,500,853 | 27 / 32 (84% [70, 97]) | 32 / 32 (100% [100, 100]) | 34.8% | 0.01 / 0.01 | 606,258 / any |
| Warning+ | 10.0% | 4.22% | 1,228,249 | 24 / 32 (75% [59, 88]) | 27 / 32 (84% [70, 94]) | 16.9% | 0.02 / 0.02 | 757,535 / 454,521 |
| Warning+ | 6.0% | 4.22% | 1,228,249 | 24 / 32 (75% [59, 88]) | 27 / 32 (84% [70, 94]) | 16.9% | 0.02 / 0.02 | any / any |
| Warning+ | 4.0% | 3.48% | 1,011,241 | 23 / 32 (72% [55, 87]) | 27 / 32 (84% [70, 94]) | 14.7% | 0.02 / 0.03 | 217,008 / any |
| Warning+ | 2.0% | 1.97% | 573,566 | 22 / 32 (69% [52, 84]) | 25 / 32 (78% [62, 91]) | 9.7% | 0.04 / 0.04 | 437,675 / 218,838 |
| Warning+ | 1.0% | 0.87% | 253,302 | 16 / 32 (50% [30, 68]) | 23 / 32 (72% [56, 87]) | 5.2% | 0.06 / 0.09 | 53,377 / 160,132 |
| Emergency | 8.0% | 4.22% | 1,228,249 | 24 / 32 (75% [59, 88]) | 27 / 32 (84% [70, 94]) | 16.9% | 0.02 / 0.02 | any / any |
| Emergency | 5.0% | 4.22% | 1,228,249 | 24 / 32 (75% [59, 88]) | 27 / 32 (84% [70, 94]) | 16.9% | 0.02 / 0.02 | any / any |
| Emergency | 3.0% | 2.22% | 647,104 | 23 / 32 (72% [55, 87]) | 25 / 32 (78% [62, 91]) | 10.6% | 0.04 / 0.04 | 581,145 / 290,572 |
| Emergency | 2.0% | 1.97% | 573,566 | 22 / 32 (69% [52, 84]) | 25 / 32 (78% [62, 91]) | 9.7% | 0.04 / 0.04 | 73,538 / any |
| Emergency | 1.0% | 0.87% | 253,302 | 16 / 32 (50% [30, 68]) | 23 / 32 (72% [56, 87]) | 5.2% | 0.06 / 0.09 | 53,377 / 160,132 |
| Emergency | 0.5% | 0.45% | 131,338 | 16 / 32 (50% [30, 68]) | 21 / 32 (66% [48, 81]) | 3.0% | 0.12 / 0.16 | any / 60,982 |
| Emergency | 0.2% | 0.14% | 41,561 | 13 / 32 (41% [23, 58]) | 19 / 32 (59% [41, 76]) | 1.1% | 0.31 / 0.46 | 29,926 / 44,888 |

### Western Ghats, monsoon (Jun-Sep): 79 events (75 independent slides), 10,800,416 cell-days

| level | cap | realised share | alert cell-days | caught cell-exact [95% CI] | caught tolerant [95% CI] | chance floor | events per 1,000 alert cell-days (exact / tolerant) | cost ratio (exact / tolerant) |
|---|---|---|---|---|---|---|---|---|
| Watch+ today | card | 29.20% | 3,153,866 | 72 / 79 (91% [85, 96]) | 79 / 79 (100% [100, 100]) | 52.4% | 0.02 / 0.03 | |
| Warning+ today | card | 6.18% | 667,205 | 53 / 79 (67% [56, 77]) | 70 / 79 (89% [81, 95]) | 23.0% | 0.08 / 0.10 | |
| Emergency today | card | 1.42% | 153,147 | 30 / 79 (38% [27, 50]) | 56 / 79 (71% [60, 81]) | 8.2% | 0.20 / 0.37 | |
| Watch+ | 45.0% | 41.88% | 4,523,459 | 77 / 79 (97% [94, 100]) | 79 / 79 (100% [100, 100]) | 62.7% | 0.02 / 0.02 | any / any |
| Watch+ | 35.0% | 29.20% | 3,153,935 | 72 / 79 (91% [85, 96]) | 79 / 79 (100% [100, 100]) | 52.5% | 0.02 / 0.03 | 273,905 / any |
| Watch+ | 25.0% | 17.15% | 1,852,135 | 65 / 79 (82% [73, 90]) | 78 / 79 (99% [96, 100]) | 40.7% | 0.04 / 0.04 | 185,971 / 1,301,800 |
| Watch+ | 15.0% | 10.78% | 1,164,106 | 60 / 79 (76% [66, 85]) | 76 / 79 (96% [91, 100]) | 32.0% | 0.05 / 0.07 | 137,606 / 344,014 |
| Watch+ | 10.0% | 8.08% | 872,651 | 56 / 79 (71% [61, 80]) | 74 / 79 (94% [88, 99]) | 27.1% | 0.06 / 0.08 | 72,864 / 145,728 |
| Watch+ | 6.0% | 2.38% | 257,213 | 40 / 79 (51% [40, 62]) | 67 / 79 (85% [76, 92]) | 12.2% | 0.16 / 0.26 | 38,465 / 87,920 |
| Watch+ | 3.0% | 2.38% | 257,213 | 40 / 79 (51% [40, 62]) | 67 / 79 (85% [76, 92]) | 12.2% | 0.16 / 0.26 | any / any |
| Warning+ | 20.0% | 17.15% | 1,852,135 | 65 / 79 (82% [73, 90]) | 78 / 79 (99% [96, 100]) | 40.7% | 0.04 / 0.04 | any / any |
| Warning+ | 15.0% | 10.78% | 1,164,106 | 60 / 79 (76% [66, 85]) | 76 / 79 (96% [91, 100]) | 32.0% | 0.05 / 0.07 | 137,606 / 344,014 |
| Warning+ | 10.0% | 8.08% | 872,651 | 56 / 79 (71% [61, 80]) | 74 / 79 (94% [88, 99]) | 27.1% | 0.06 / 0.08 | 72,864 / 145,728 |
| Warning+ | 6.0% | 2.38% | 257,213 | 40 / 79 (51% [40, 62]) | 67 / 79 (85% [76, 92]) | 12.2% | 0.16 / 0.26 | 38,465 / 87,920 |
| Warning+ | 4.0% | 2.38% | 257,213 | 40 / 79 (51% [40, 62]) | 67 / 79 (85% [76, 92]) | 12.2% | 0.16 / 0.26 | any / any |
| Warning+ | 2.0% | 1.95% | 210,707 | 36 / 79 (46% [35, 57]) | 63 / 79 (80% [70, 88]) | 10.5% | 0.17 / 0.30 | 11,626 / 11,626 |
| Warning+ | 1.0% | 0.69% | 75,033 | 24 / 79 (30% [21, 41]) | 50 / 79 (63% [52, 74]) | 4.6% | 0.32 / 0.67 | 11,306 / 10,436 |
| Emergency | 8.0% | 6.84% | 739,094 | 54 / 79 (68% [58, 78]) | 71 / 79 (90% [82, 96]) | 24.6% | 0.07 / 0.10 | any / any |
| Emergency | 5.0% | 2.38% | 257,213 | 40 / 79 (51% [40, 62]) | 67 / 79 (85% [76, 92]) | 12.2% | 0.16 / 0.26 | 34,420 / 120,470 |
| Emergency | 3.0% | 2.38% | 257,213 | 40 / 79 (51% [40, 62]) | 67 / 79 (85% [76, 92]) | 12.2% | 0.16 / 0.26 | any / any |
| Emergency | 2.0% | 1.95% | 210,707 | 36 / 79 (46% [35, 57]) | 63 / 79 (80% [70, 88]) | 10.5% | 0.17 / 0.30 | 11,626 / 11,626 |
| Emergency | 1.0% | 0.69% | 75,033 | 24 / 79 (30% [21, 41]) | 50 / 79 (63% [52, 74]) | 4.6% | 0.32 / 0.67 | 11,306 / 10,436 |
| Emergency | 0.5% | 0.19% | 20,567 | 18 / 79 (23% [14, 32]) | 31 / 79 (39% [29, 51]) | 1.4% | 0.88 / 1.51 | 9,078 / 2,867 |
| Emergency | 0.2% | 0.19% | 20,567 | 18 / 79 (23% [14, 32]) | 31 / 79 (39% [29, 51]) | 1.3% | 0.88 / 1.51 | any / any |

### Western Ghats, post-monsoon (Oct-Dec): 12 events (12 independent slides), 8,144,576 cell-days

| level | cap | realised share | alert cell-days | caught cell-exact [95% CI] | caught tolerant [95% CI] | chance floor | events per 1,000 alert cell-days (exact / tolerant) | cost ratio (exact / tolerant) |
|---|---|---|---|---|---|---|---|---|
| Watch+ today | card | 13.17% | 1,072,409 | 11 / 12 (92% [75, 100]) | 12 / 12 (100% [100, 100]) | 28.2% | 0.01 / 0.01 | |
| Warning+ today | card | 2.20% | 179,458 | 7 / 12 (58% [33, 83]) | 10 / 12 (83% [58, 100]) | 9.0% | 0.04 / 0.06 | |
| Emergency today | card | 0.46% | 37,655 | 5 / 12 (42% [17, 67]) | 8 / 12 (67% [42, 92]) | 2.9% | 0.13 / 0.21 | |
| Watch+ | 45.0% | 36.16% | 2,945,396 | 11 / 12 (92% [75, 100]) | 12 / 12 (100% [100, 100]) | 55.4% | 0.00 / 0.00 | any / any |
| Watch+ | 35.0% | 25.45% | 2,073,167 | 11 / 12 (92% [75, 100]) | 12 / 12 (100% [100, 100]) | 43.5% | 0.01 / 0.01 | any / any |
| Watch+ | 25.0% | 22.25% | 1,812,323 | 11 / 12 (92% [75, 100]) | 12 / 12 (100% [100, 100]) | 39.7% | 0.01 / 0.01 | any / any |
| Watch+ | 15.0% | 13.17% | 1,072,433 | 11 / 12 (92% [75, 100]) | 12 / 12 (100% [100, 100]) | 28.2% | 0.01 / 0.01 | any / any |
| Watch+ | 10.0% | 6.81% | 554,512 | 10 / 12 (83% [58, 100]) | 11 / 12 (92% [75, 100]) | 18.6% | 0.02 / 0.02 | 517,921 / 517,921 |
| Watch+ | 6.0% | 4.04% | 329,004 | 8 / 12 (67% [42, 92]) | 10 / 12 (83% [58, 100]) | 13.3% | 0.02 / 0.03 | 112,754 / 225,508 |
| Watch+ | 3.0% | 2.95% | 240,529 | 8 / 12 (67% [42, 92]) | 10 / 12 (83% [58, 100]) | 10.9% | 0.03 / 0.04 | any / any |
| Warning+ | 20.0% | 17.00% | 1,384,780 | 11 / 12 (92% [75, 100]) | 12 / 12 (100% [100, 100]) | 33.2% | 0.01 / 0.01 | any / any |
| Warning+ | 15.0% | 13.17% | 1,072,433 | 11 / 12 (92% [75, 100]) | 12 / 12 (100% [100, 100]) | 28.2% | 0.01 / 0.01 | any / any |
| Warning+ | 10.0% | 6.81% | 554,512 | 10 / 12 (83% [58, 100]) | 11 / 12 (92% [75, 100]) | 18.6% | 0.02 / 0.02 | 517,921 / 517,921 |
| Warning+ | 6.0% | 4.04% | 329,004 | 8 / 12 (67% [42, 92]) | 10 / 12 (83% [58, 100]) | 13.3% | 0.02 / 0.03 | 112,754 / 225,508 |
| Warning+ | 4.0% | 2.95% | 240,529 | 8 / 12 (67% [42, 92]) | 10 / 12 (83% [58, 100]) | 10.9% | 0.03 / 0.04 | any / any |
| Warning+ | 2.0% | 0.80% | 65,418 | 5 / 12 (42% [17, 67]) | 9 / 12 (75% [50, 92]) | 4.4% | 0.08 / 0.14 | 58,370 / 175,111 |
| Warning+ | 1.0% | 0.80% | 65,418 | 5 / 12 (42% [17, 67]) | 9 / 12 (75% [50, 92]) | 4.4% | 0.08 / 0.14 | any / any |
| Emergency | 8.0% | 6.81% | 554,512 | 10 / 12 (83% [58, 100]) | 11 / 12 (92% [75, 100]) | 18.6% | 0.02 / 0.02 | any / any |
| Emergency | 5.0% | 4.04% | 329,004 | 8 / 12 (67% [42, 92]) | 10 / 12 (83% [58, 100]) | 13.3% | 0.02 / 0.03 | 112,754 / 225,508 |
| Emergency | 3.0% | 2.95% | 240,529 | 8 / 12 (67% [42, 92]) | 10 / 12 (83% [58, 100]) | 10.9% | 0.03 / 0.04 | any / any |
| Emergency | 2.0% | 0.80% | 65,418 | 5 / 12 (42% [17, 67]) | 9 / 12 (75% [50, 92]) | 4.4% | 0.08 / 0.14 | 58,370 / 175,111 |
| Emergency | 1.0% | 0.80% | 65,418 | 5 / 12 (42% [17, 67]) | 9 / 12 (75% [50, 92]) | 4.4% | 0.08 / 0.14 | any / any |
| Emergency | 0.5% | 0.46% | 37,687 | 5 / 12 (42% [17, 67]) | 8 / 12 (67% [42, 92]) | 2.9% | 0.13 / 0.21 | any / 27,731 |
| Emergency | 0.2% | 0.04% | 3,608 | 2 / 12 (17% [0, 42]) | 4 / 12 (33% [8, 58]) | 0.4% | 0.55 / 1.11 | 11,360 / 8,520 |

## The one held-out look per option (pre-declared; the lead's, after the user chooses)

- **A_detection_first**: `python -m aetherguard.verify.operating_options heldout --option A_detection_first`. confirmed when every held-out published share (region x season x level, June-December 2018-2025) is at most 1.5 x its development value, and at every tolerance and level the independent slides detected are at least the development detection share x the slides less 2.0 binomial standard deviations. Development values it is held to: tolerant|1 99% (allowed shortfall 1.7 slides); tolerant|2 96% (allowed shortfall 3.7 slides); tolerant|3 86% (allowed shortfall 6.4 slides); cell_exact|1 96% (allowed shortfall 3.4 slides); cell_exact|2 82% (allowed shortfall 7.1 slides); cell_exact|3 59% (allowed shortfall 9.2 slides).
- **B_balanced**: `python -m aetherguard.verify.operating_options heldout --option B_balanced`. confirmed when every held-out published share (region x season x level, June-December 2018-2025) is at most 1.5 x its development value, and at every tolerance and level the independent slides it detects fewer than A_detection_first on the same held-out days are at most the development share of events lost x the slides plus 2.0 binomial standard deviations. Development values it is held to: tolerant|1 lost 0.9% of the events (allowance 1.7 slides); tolerant|2 lost 4.6% of the events (allowance 3.9 slides); tolerant|3 lost 9.4% of the events (allowance 5.4 slides); cell_exact|1 lost 5.7% of the events (allowance 4.3 slides); cell_exact|2 lost 15.4% of the events (allowance 6.7 slides); cell_exact|3 lost 13.7% of the events (allowance 6.4 slides).
- **C_rare_emergency**: `python -m aetherguard.verify.operating_options heldout --option C_rare_emergency`. confirmed when every held-out published share (region x season x level, June-December 2018-2025) is at most 1.5 x its development value, and at every tolerance and level the independent slides it detects fewer than A_detection_first on the same held-out days are at most the development share of events lost x the slides plus 2.0 binomial standard deviations. Development values it is held to: tolerant|1 lost 1.9% of the events (allowance 2.6 slides); tolerant|2 lost 9.7% of the events (allowance 5.5 slides); tolerant|3 lost 18.1% of the events (allowance 7.2 slides); cell_exact|1 lost 12.2% of the events (allowance 6.1 slides); cell_exact|2 lost 25.3% of the events (allowance 8.1 slides); cell_exact|3 lost 23.4% of the events (allowance 7.9 slides).

## Caveats

- Development data only (2007-2017, out of fold, every scored cell). No held-out number is in this report; each option's realised detection and burden on 2018-2025 is confirmed by one look, after the choice.
- The catalogues miss most landslides and record them where people and roads are, so an alert far from a recorded event is not necessarily a false alarm, and detection counts what was recorded.
- Tolerant matching (10 km, 1 day) has a high chance floor at high burden: the floor column is the detection an event placed at random would get. Read tolerant detection against it; the cell-exact rows do not reward scattered alerts.
- The calibrated risk takes few distinct values in its upper tail (the monotone calibrator is a step function), so a threshold can only sit between two steps; a cap is met as 'at most', and the realised share is often well below it.
- The caps are met on the point level. The published level also raises to Watch where the ensemble's upper bound reaches it (uncertain_high) and holds levels (hysteresis, rain-capped hold release), which raises the realised share; the published columns measure it on the same panels.
- The live run outside June-September has published far more alerts than these panels show (reports/phase8_season_validity.md); thresholds set on development data do not remove that difference.
- January-May panels start on 1 January without a warm-up (no hysteresis state carried over New Year).
- District numbers use geoBoundaries district polygons (India ADM2, Nepal ADM2 = the 75 districts of 2006, Bhutan ADM1 = the 20 dzongkhags); a few cells at coasts and borders take the nearest district of their country within 5 km. District data: ODbL 1.0; contains information from geoBoundaries (gbOpen) and OpenStreetMap contributors.
- A cost ratio counts every alert cell-day as a false alarm and every catalogue event as the only landslide; the catalogues hold a small fraction of the slides that happened, so the real number of misses behind each lost event is larger than one.
- The blind-escalation rule of the live run (raise to Watch when the rain sources disagree and confidence is not High) needs the live IMD comparison and is not in the development chain.
