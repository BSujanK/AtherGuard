# A district level an officer can act on: frequency-capped district rule (phase 8, development only)

Today a district would take the highest level of any of its cells (R0). A district holds a median of 49 scored cells, so that puts districts on alert most days. This report caps how often a district may be at each level and shows what the cap costs in covered slides. Every number comes from `data/processed/alerts/district_cap/fit.json`: development years 2007-2017, out of fold, today's published cell levels (option A), district shares fitted leave-one-year-out. Nothing is wired.

## The rules side by side

| rule | Watch+ cap | Warning+ cap | Emergency cap |
|---|---|---|---|
| R0 any cell | none (any cell) | none (any cell) | none (any cell) |
| declared (F1_stratum) | 50.0% | none (any cell) | none (any cell) |
| alternative (F1_stratum) | 50.0% | 25.0% | 10.0% |

Share of district-days at the level or above, days per week for the median district and the busiest tenth (p90), and the development events inside a district at the level within one day:

| region and season | level | rule | district-days | days/week median | p90 | covered within 1 day | covered same day | chance floor |
|---|---|---|---|---|---|---|---|---|
| Himalaya, rest of year (Jan-May) (90 events) | Watch+ | R0 any cell | 40.8% | 3.05 | 5.96 | 87 (97% [93, 100]) | 86 (96% [91, 99]) | 44.6% |
| Himalaya, rest of year (Jan-May) (90 events) | Watch+ | declared (F1_stratum) | 40.8% | 3.05 | 5.96 | 87 (97% [93, 100]) | 86 (96% [91, 99]) | 44.6% |
| Himalaya, rest of year (Jan-May) (90 events) | Watch+ | alternative (F1_stratum) | 40.8% | 3.05 | 5.96 | 87 (97% [93, 100]) | 86 (96% [91, 99]) | 44.6% |
| Himalaya, rest of year (Jan-May) (90 events) | Warning+ | R0 any cell | 22.4% | 1.20 | 3.99 | 81 (90% [84, 96]) | 79 (88% [81, 94]) | 26.7% |
| Himalaya, rest of year (Jan-May) (90 events) | Warning+ | declared (F1_stratum) | 22.4% | 1.20 | 3.99 | 81 (90% [84, 96]) | 79 (88% [81, 94]) | 26.7% |
| Himalaya, rest of year (Jan-May) (90 events) | Warning+ | alternative (F1_stratum) | 22.4% | 1.20 | 3.99 | 81 (90% [84, 96]) | 79 (88% [81, 94]) | 26.7% |
| Himalaya, rest of year (Jan-May) (90 events) | Emergency | R0 any cell | 10.3% | 0.30 | 1.94 | 74 (82% [74, 90]) | 66 (73% [64, 82]) | 13.8% |
| Himalaya, rest of year (Jan-May) (90 events) | Emergency | declared (F1_stratum) | 10.3% | 0.30 | 1.94 | 74 (82% [74, 90]) | 66 (73% [64, 82]) | 13.8% |
| Himalaya, rest of year (Jan-May) (90 events) | Emergency | alternative (F1_stratum) | 10.0% | 0.30 | 1.92 | 73 (81% [73, 89]) | 65 (72% [63, 81]) | 13.5% |
| Himalaya, monsoon (Jun-Sep) (557 events) | Watch+ | R0 any cell | 82.8% | 6.86 | 7.00 | 556 (100% [99, 100]) | 556 (100% [99, 100]) | 86.0% |
| Himalaya, monsoon (Jun-Sep) (557 events) | Watch+ | declared (F1_stratum) | 61.7% | 5.83 | 6.95 | 556 (100% [99, 100]) | 555 (100% [99, 100]) | 66.6% |
| Himalaya, monsoon (Jun-Sep) (557 events) | Watch+ | alternative (F1_stratum) | 50.1% | 3.95 | 6.78 | 521 (94% [91, 96]) | 506 (91% [88, 93]) | 55.4% |
| Himalaya, monsoon (Jun-Sep) (557 events) | Warning+ | R0 any cell | 56.7% | 4.92 | 6.94 | 556 (100% [99, 100]) | 555 (100% [99, 100]) | 61.8% |
| Himalaya, monsoon (Jun-Sep) (557 events) | Warning+ | declared (F1_stratum) | 56.7% | 4.92 | 6.94 | 556 (100% [99, 100]) | 555 (100% [99, 100]) | 61.8% |
| Himalaya, monsoon (Jun-Sep) (557 events) | Warning+ | alternative (F1_stratum) | 25.0% | 0.67 | 5.01 | 478 (86% [83, 89]) | 435 (78% [74, 82]) | 30.9% |
| Himalaya, monsoon (Jun-Sep) (557 events) | Emergency | R0 any cell | 35.4% | 1.80 | 6.05 | 543 (97% [96, 99]) | 528 (95% [93, 97]) | 41.6% |
| Himalaya, monsoon (Jun-Sep) (557 events) | Emergency | declared (F1_stratum) | 35.4% | 1.80 | 6.05 | 543 (97% [96, 99]) | 528 (95% [93, 97]) | 41.6% |
| Himalaya, monsoon (Jun-Sep) (557 events) | Emergency | alternative (F1_stratum) | 10.0% | 0.08 | 2.53 | 354 (64% [59, 68]) | 289 (52% [47, 56]) | 13.8% |
| Himalaya, post-monsoon (Oct-Dec) (32 events) | Watch+ | R0 any cell | 31.1% | 1.89 | 4.61 | 30 (94% [84, 100]) | 29 (91% [78, 100]) | 35.0% |
| Himalaya, post-monsoon (Oct-Dec) (32 events) | Watch+ | declared (F1_stratum) | 31.1% | 1.89 | 4.61 | 30 (94% [84, 100]) | 29 (91% [78, 100]) | 35.0% |
| Himalaya, post-monsoon (Oct-Dec) (32 events) | Watch+ | alternative (F1_stratum) | 31.1% | 1.89 | 4.61 | 30 (94% [84, 100]) | 29 (91% [78, 100]) | 35.0% |
| Himalaya, post-monsoon (Oct-Dec) (32 events) | Warning+ | R0 any cell | 13.0% | 0.62 | 2.20 | 27 (84% [71, 97]) | 25 (78% [63, 91]) | 16.3% |
| Himalaya, post-monsoon (Oct-Dec) (32 events) | Warning+ | declared (F1_stratum) | 13.0% | 0.62 | 2.20 | 27 (84% [71, 97]) | 25 (78% [63, 91]) | 16.3% |
| Himalaya, post-monsoon (Oct-Dec) (32 events) | Warning+ | alternative (F1_stratum) | 13.0% | 0.62 | 2.20 | 27 (84% [71, 97]) | 25 (78% [63, 91]) | 16.2% |
| Himalaya, post-monsoon (Oct-Dec) (32 events) | Emergency | R0 any cell | 5.1% | 0.17 | 0.95 | 24 (75% [59, 90]) | 23 (72% [56, 86]) | 7.1% |
| Himalaya, post-monsoon (Oct-Dec) (32 events) | Emergency | declared (F1_stratum) | 5.1% | 0.17 | 0.95 | 24 (75% [59, 90]) | 23 (72% [56, 86]) | 7.1% |
| Himalaya, post-monsoon (Oct-Dec) (32 events) | Emergency | alternative (F1_stratum) | 5.1% | 0.17 | 0.95 | 24 (75% [59, 90]) | 23 (72% [56, 86]) | 7.1% |
| Western Ghats, rest of year (Jan-May) (5 events) | Watch+ | R0 any cell | 20.1% | 0.98 | 3.64 | 4 (80% [40, 100]) | 4 (80% [40, 100]) | 22.9% |
| Western Ghats, rest of year (Jan-May) (5 events) | Watch+ | declared (F1_stratum) | 20.1% | 0.98 | 3.64 | 4 (80% [40, 100]) | 4 (80% [40, 100]) | 22.9% |
| Western Ghats, rest of year (Jan-May) (5 events) | Watch+ | alternative (F1_stratum) | 20.1% | 0.98 | 3.64 | 4 (80% [40, 100]) | 4 (80% [40, 100]) | 22.9% |
| Western Ghats, rest of year (Jan-May) (5 events) | Warning+ | R0 any cell | 6.5% | 0.03 | 1.52 | 4 (80% [40, 100]) | 4 (80% [40, 100]) | 8.3% |
| Western Ghats, rest of year (Jan-May) (5 events) | Warning+ | declared (F1_stratum) | 6.5% | 0.03 | 1.52 | 4 (80% [40, 100]) | 4 (80% [40, 100]) | 8.3% |
| Western Ghats, rest of year (Jan-May) (5 events) | Warning+ | alternative (F1_stratum) | 6.5% | 0.03 | 1.52 | 4 (80% [40, 100]) | 4 (80% [40, 100]) | 8.3% |
| Western Ghats, rest of year (Jan-May) (5 events) | Emergency | R0 any cell | 2.5% | 0.00 | 0.65 | 3 (60% [20, 100]) | 2 (40% [0, 80]) | 3.4% |
| Western Ghats, rest of year (Jan-May) (5 events) | Emergency | declared (F1_stratum) | 2.5% | 0.00 | 0.65 | 3 (60% [20, 100]) | 2 (40% [0, 80]) | 3.4% |
| Western Ghats, rest of year (Jan-May) (5 events) | Emergency | alternative (F1_stratum) | 2.5% | 0.00 | 0.65 | 3 (60% [20, 100]) | 2 (40% [0, 80]) | 3.4% |
| Western Ghats, monsoon (Jun-Sep) (79 events) | Watch+ | R0 any cell | 61.2% | 4.93 | 6.90 | 79 (100% [100, 100]) | 79 (100% [100, 100]) | 66.3% |
| Western Ghats, monsoon (Jun-Sep) (79 events) | Watch+ | declared (F1_stratum) | 50.3% | 3.59 | 6.70 | 79 (100% [100, 100]) | 79 (100% [100, 100]) | 55.4% |
| Western Ghats, monsoon (Jun-Sep) (79 events) | Watch+ | alternative (F1_stratum) | 50.0% | 3.53 | 6.70 | 79 (100% [100, 100]) | 79 (100% [100, 100]) | 55.1% |
| Western Ghats, monsoon (Jun-Sep) (79 events) | Warning+ | R0 any cell | 30.6% | 0.47 | 5.95 | 79 (100% [100, 100]) | 78 (99% [96, 100]) | 34.8% |
| Western Ghats, monsoon (Jun-Sep) (79 events) | Warning+ | declared (F1_stratum) | 30.6% | 0.47 | 5.95 | 79 (100% [100, 100]) | 78 (99% [96, 100]) | 34.8% |
| Western Ghats, monsoon (Jun-Sep) (79 events) | Warning+ | alternative (F1_stratum) | 25.0% | 0.40 | 5.25 | 77 (97% [94, 100]) | 72 (91% [84, 96]) | 29.4% |
| Western Ghats, monsoon (Jun-Sep) (79 events) | Emergency | R0 any cell | 17.2% | 0.08 | 4.16 | 74 (94% [87, 99]) | 66 (84% [74, 91]) | 20.6% |
| Western Ghats, monsoon (Jun-Sep) (79 events) | Emergency | declared (F1_stratum) | 17.2% | 0.08 | 4.16 | 74 (94% [87, 99]) | 66 (84% [74, 91]) | 20.6% |
| Western Ghats, monsoon (Jun-Sep) (79 events) | Emergency | alternative (F1_stratum) | 10.0% | 0.06 | 2.43 | 60 (76% [66, 85]) | 53 (67% [56, 77]) | 12.9% |
| Western Ghats, post-monsoon (Oct-Dec) (12 events) | Watch+ | R0 any cell | 34.6% | 1.76 | 5.53 | 12 (100% [100, 100]) | 12 (100% [100, 100]) | 38.3% |
| Western Ghats, post-monsoon (Oct-Dec) (12 events) | Watch+ | declared (F1_stratum) | 34.6% | 1.76 | 5.53 | 12 (100% [100, 100]) | 12 (100% [100, 100]) | 38.3% |
| Western Ghats, post-monsoon (Oct-Dec) (12 events) | Watch+ | alternative (F1_stratum) | 34.6% | 1.76 | 5.53 | 12 (100% [100, 100]) | 12 (100% [100, 100]) | 38.3% |
| Western Ghats, post-monsoon (Oct-Dec) (12 events) | Warning+ | R0 any cell | 15.1% | 0.22 | 3.29 | 10 (83% [58, 100]) | 10 (83% [58, 100]) | 18.1% |
| Western Ghats, post-monsoon (Oct-Dec) (12 events) | Warning+ | declared (F1_stratum) | 15.1% | 0.22 | 3.29 | 10 (83% [58, 100]) | 10 (83% [58, 100]) | 18.1% |
| Western Ghats, post-monsoon (Oct-Dec) (12 events) | Warning+ | alternative (F1_stratum) | 15.1% | 0.22 | 3.29 | 10 (83% [58, 100]) | 10 (83% [58, 100]) | 18.1% |
| Western Ghats, post-monsoon (Oct-Dec) (12 events) | Emergency | R0 any cell | 7.6% | 0.03 | 1.81 | 9 (75% [50, 92]) | 9 (75% [50, 92]) | 9.5% |
| Western Ghats, post-monsoon (Oct-Dec) (12 events) | Emergency | declared (F1_stratum) | 7.6% | 0.03 | 1.81 | 9 (75% [50, 92]) | 9 (75% [50, 92]) | 9.5% |
| Western Ghats, post-monsoon (Oct-Dec) (12 events) | Emergency | alternative (F1_stratum) | 7.6% | 0.03 | 1.81 | 9 (75% [50, 92]) | 9 (75% [50, 92]) | 9.5% |

## What the development data say, and the recommendation

- With R0, a Himalayan district in the monsoon is at Emergency on 35% of days (median district 1.8 days a week, busiest tenth 6.1). It covers 97% of the development events within a day.
- Coverage falls nearly in step with frequency. A district's coverage is 2.3 x its chance floor under R0, and 4.6 x with a 10% Emergency cap: capping makes each alert more informative, but every district-day removed also removes slides. Going from R0 to the alternative's Emergency cap saves 147,071 Himalayan monsoon district-days and leaves 189 covered events uncovered: 778 district-days per event (the cost ratio; the curve below gives it for every step).
- The rule declared before the curve (keep 90% of R0's within-1-day coverage) finds no Warning+ or Emergency cap on the declared ladder that meets it. It caps only Watch+ (50.0%), which leaves the Emergency frequency where it is (p90 6.1 days a week). So no district frequency an officer can act on comes without losing covered slides.
- The alternative (spec section 7: the gentlest cap of each ladder, Warning+ 25.0%, Emergency 10.0%) brings Emergency to 10% of district-days (median 0.08, busiest tenth 2.5 days a week) and Warning+ to 25% (from 57%). The price: within-1-day Emergency coverage 97% -> 64%, Warning+ 100% -> 86%.
- Recommendation: the choice is the user's cost ratio, not a statistical one. If an uncovered recorded slide is worth more than about 778 false-alarm district-days, keep R0 for Warning+ and Emergency (the declared rule) and use districts only to route the cell alerts. If the user wants a district Emergency that fires on about one monsoon day in 10 instead, take the alternative to the one look, knowing it gives up 35% of the Emergency events R0 covers in the Himalayan monsoon on development data. I recommend the alternative for the look only if the user accepts that price, and the declared rule otherwise. The declared rule's look tells little, because it changes only Watch+.

## The choice of each family (spec section 4)

| family | Watch+ cap | Warning+ cap | Emergency cap | Himalaya monsoon Emergency p90 days/week |
|---|---|---|---|---|
| F1_stratum | 50.0% | none (any cell) | none (any cell) | 6.05 |
| F2_district | none (any cell) | none (any cell) | none (any cell) | 6.05 |

Chosen: **F1_stratum**.

## The trade-off curve (each level alone, leave-one-year-out)

Cost ratio: district-days saved per covered event lost against the row above (the first cap against R0); the step is worth taking when one uncovered recorded landslide is worth FEWER false-alarm district-days than that ('any': none lost). Chance floor: the share of district-days at the level within one day.

### F1_stratum, Watch+, Himalaya, rest of year (Jan-May) (90 events)

| cap | district-days | days/week median / p90 | chance floor | covered within 1 day | covered same day | district-days per event covered | cost ratio (within 1 day / same day) |
|---|---|---|---|---|---|---|---|
| R0 any cell | 40.8% | 3.05 / 5.96 | 44.6% | 87 (97% [93, 100]) | 86 (96% [91, 99]) | 3,361 | |
| 50.0% | 40.8% | 3.05 / 5.96 | 44.6% | 87 (97% [93, 100]) | 86 (96% [91, 99]) | 3,361 | any / any |
| 40.0% | 40.0% | 3.03 / 5.76 | 43.9% | 87 (97% [93, 100]) | 85 (94% [90, 99]) | 3,296 | any / 5,697 |
| 30.0% | 30.0% | 2.40 / 4.28 | 33.7% | 81 (90% [83, 96]) | 79 (88% [80, 94]) | 2,653 | 11,968 / 11,968 |
| 20.0% | 20.0% | 1.37 / 3.00 | 23.5% | 77 (86% [78, 92]) | 72 (80% [72, 88]) | 1,863 | 17,876 / 10,215 |
| 15.0% | 15.0% | 0.72 / 2.51 | 18.3% | 70 (78% [69, 86]) | 65 (72% [63, 81]) | 1,539 | 5,102 / 5,102 |
| 10.0% | 10.0% | 0.24 / 1.94 | 12.8% | 64 (71% [62, 81]) | 56 (62% [52, 73]) | 1,122 | 5,979 / 3,986 |
| 5.0% | 5.0% | 0.05 / 1.21 | 6.9% | 46 (51% [40, 62]) | 39 (43% [33, 54]) | 782 | 1,991 / 2,108 |

### F1_stratum, Watch+, Himalaya, monsoon (Jun-Sep) (557 events)

| cap | district-days | days/week median / p90 | chance floor | covered within 1 day | covered same day | district-days per event covered | cost ratio (within 1 day / same day) |
|---|---|---|---|---|---|---|---|
| R0 any cell | 82.8% | 6.86 / 7.00 | 86.0% | 556 (100% [99, 100]) | 556 (100% [99, 100]) | 861 | |
| 50.0% | 50.0% | 3.95 / 6.78 | 55.3% | 518 (93% [91, 95]) | 499 (90% [87, 92]) | 558 | 4,987 / 3,325 |
| 40.0% | 39.8% | 2.34 / 6.54 | 45.5% | 454 (82% [78, 85]) | 439 (79% [75, 82]) | 507 | 920 / 982 |
| 30.0% | 30.0% | 1.08 / 6.01 | 35.6% | 407 (73% [69, 77]) | 385 (69% [65, 73]) | 426 | 1,212 / 1,055 |
| 20.0% | 20.0% | 0.39 / 4.72 | 25.1% | 303 (54% [50, 59]) | 261 (47% [43, 51]) | 382 | 554 / 465 |
| 15.0% | 0.0% | 0.00 / 0.00 | 0.4% | 1 (0% [0, 1]) | 0 (0% [0, 0]) | 0 | 383 / 443 |
| 10.0% | 0.0% | 0.00 / 0.00 | 0.3% | 1 (0% [0, 1]) | 0 (0% [0, 0]) | 0 | any / any |
| 5.0% | 0.0% | 0.00 / 0.00 | 0.1% | 1 (0% [0, 1]) | 0 (0% [0, 0]) | 0 | any / any |

### F1_stratum, Watch+, Himalaya, post-monsoon (Oct-Dec) (32 events)

| cap | district-days | days/week median / p90 | chance floor | covered within 1 day | covered same day | district-days per event covered | cost ratio (within 1 day / same day) |
|---|---|---|---|---|---|---|---|
| R0 any cell | 31.1% | 1.89 / 4.61 | 35.0% | 30 (94% [84, 100]) | 29 (91% [78, 100]) | 4,517 | |
| 50.0% | 31.1% | 1.89 / 4.61 | 35.0% | 30 (94% [84, 100]) | 29 (91% [78, 100]) | 4,517 | any / any |
| 40.0% | 31.1% | 1.89 / 4.61 | 35.0% | 30 (94% [84, 100]) | 29 (91% [78, 100]) | 4,517 | any / any |
| 30.0% | 30.0% | 1.85 / 4.35 | 33.9% | 29 (91% [78, 100]) | 29 (91% [78, 100]) | 4,506 | 4,838 / any |
| 20.0% | 19.9% | 1.36 / 2.87 | 23.2% | 28 (88% [74, 97]) | 28 (88% [74, 97]) | 3,107 | 43,666 / 43,666 |
| 15.0% | 15.0% | 1.00 / 2.35 | 17.8% | 28 (88% [74, 97]) | 28 (88% [74, 97]) | 2,334 | any / any |
| 10.0% | 10.0% | 0.59 / 1.66 | 12.2% | 27 (84% [70, 97]) | 26 (81% [66, 94]) | 1,616 | 21,716 / 10,858 |
| 5.0% | 5.0% | 0.13 / 0.98 | 6.5% | 24 (75% [58, 88]) | 21 (66% [48, 81]) | 913 | 7,241 / 4,345 |

### F1_stratum, Watch+, Western Ghats, rest of year (Jan-May) (5 events)

| cap | district-days | days/week median / p90 | chance floor | covered within 1 day | covered same day | district-days per event covered | cost ratio (within 1 day / same day) |
|---|---|---|---|---|---|---|---|
| R0 any cell | 20.1% | 0.98 / 3.64 | 22.9% | 4 (80% [40, 100]) | 4 (80% [40, 100]) | 10,381 | |
| 50.0% | 20.1% | 0.98 / 3.64 | 22.9% | 4 (80% [40, 100]) | 4 (80% [40, 100]) | 10,381 | any / any |
| 40.0% | 20.1% | 0.98 / 3.64 | 22.9% | 4 (80% [40, 100]) | 4 (80% [40, 100]) | 10,381 | any / any |
| 30.0% | 20.1% | 0.98 / 3.64 | 22.9% | 4 (80% [40, 100]) | 4 (80% [40, 100]) | 10,381 | any / any |
| 20.0% | 20.0% | 0.94 / 3.62 | 22.7% | 4 (80% [40, 100]) | 4 (80% [40, 100]) | 10,295 | any / any |
| 15.0% | 15.0% | 0.45 / 3.16 | 17.4% | 4 (80% [40, 100]) | 4 (80% [40, 100]) | 7,744 | any / any |
| 10.0% | 10.0% | 0.09 / 2.41 | 11.7% | 4 (80% [40, 100]) | 4 (80% [40, 100]) | 5,136 | any / any |
| 5.0% | 5.0% | 0.01 / 1.42 | 6.1% | 3 (60% [20, 100]) | 3 (60% [20, 100]) | 3,430 | 10,251 / 10,251 |

### F1_stratum, Watch+, Western Ghats, monsoon (Jun-Sep) (79 events)

| cap | district-days | days/week median / p90 | chance floor | covered within 1 day | covered same day | district-days per event covered | cost ratio (within 1 day / same day) |
|---|---|---|---|---|---|---|---|
| R0 any cell | 61.2% | 4.93 / 6.90 | 66.3% | 79 (100% [100, 100]) | 79 (100% [100, 100]) | 1,290 | |
| 50.0% | 50.0% | 3.53 / 6.70 | 55.1% | 79 (100% [100, 100]) | 79 (100% [100, 100]) | 1,052 | any / any |
| 40.0% | 40.0% | 1.52 / 6.53 | 44.4% | 78 (99% [96, 100]) | 77 (97% [94, 100]) | 854 | 16,546 / 8,273 |
| 30.0% | 29.7% | 0.37 / 6.17 | 33.5% | 74 (94% [88, 99]) | 70 (89% [81, 95]) | 668 | 4,288 / 2,450 |
| 20.0% | 20.0% | 0.08 / 5.41 | 23.2% | 63 (80% [70, 88]) | 58 (73% [63, 82]) | 528 | 1,471 / 1,348 |
| 15.0% | 15.0% | 0.03 / 4.36 | 17.9% | 49 (62% [51, 72]) | 44 (56% [44, 67]) | 510 | 589 / 589 |
| 10.0% | 10.0% | 0.01 / 2.62 | 12.5% | 40 (51% [39, 62]) | 37 (47% [35, 58]) | 414 | 939 / 1,207 |
| 5.0% | 0.0% | 0.00 / 0.00 | 0.1% | 0 (0% [0, 0]) | 0 (0% [0, 0]) | 0 | 414 / 448 |

### F1_stratum, Watch+, Western Ghats, post-monsoon (Oct-Dec) (12 events)

| cap | district-days | days/week median / p90 | chance floor | covered within 1 day | covered same day | district-days per event covered | cost ratio (within 1 day / same day) |
|---|---|---|---|---|---|---|---|
| R0 any cell | 34.6% | 1.76 / 5.53 | 38.3% | 12 (100% [100, 100]) | 12 (100% [100, 100]) | 3,619 | |
| 50.0% | 34.6% | 1.76 / 5.53 | 38.3% | 12 (100% [100, 100]) | 12 (100% [100, 100]) | 3,619 | any / any |
| 40.0% | 34.6% | 1.76 / 5.53 | 38.3% | 12 (100% [100, 100]) | 12 (100% [100, 100]) | 3,619 | any / any |
| 30.0% | 30.0% | 1.26 / 5.18 | 33.6% | 11 (92% [75, 100]) | 11 (92% [75, 100]) | 3,423 | 5,766 / 5,766 |
| 20.0% | 20.1% | 0.39 / 4.33 | 22.8% | 10 (83% [58, 100]) | 10 (83% [58, 100]) | 2,517 | 12,491 / 12,491 |
| 15.0% | 15.1% | 0.10 / 3.75 | 17.4% | 10 (83% [58, 100]) | 10 (83% [58, 100]) | 1,889 | any / any |
| 10.0% | 10.1% | 0.04 / 2.76 | 12.0% | 9 (75% [50, 92]) | 9 (75% [50, 92]) | 1,408 | 6,221 / 6,221 |
| 5.0% | 5.1% | 0.02 / 1.52 | 6.4% | 4 (33% [8, 58]) | 4 (33% [8, 58]) | 1,590 | 1,262 / 1,262 |

### F1_stratum, Warning+, Himalaya, rest of year (Jan-May) (90 events)

| cap | district-days | days/week median / p90 | chance floor | covered within 1 day | covered same day | district-days per event covered | cost ratio (within 1 day / same day) |
|---|---|---|---|---|---|---|---|
| R0 any cell | 22.4% | 1.20 / 3.99 | 26.7% | 81 (90% [84, 96]) | 79 (88% [81, 94]) | 1,987 | |
| 25.0% | 22.4% | 1.20 / 3.99 | 26.7% | 81 (90% [84, 96]) | 79 (88% [81, 94]) | 1,987 | any / any |
| 18.0% | 18.0% | 0.95 / 3.04 | 22.2% | 76 (84% [77, 91]) | 72 (80% [72, 88]) | 1,698 | 6,382 / 4,559 |
| 12.0% | 12.0% | 0.44 / 2.20 | 15.7% | 71 (79% [70, 87]) | 66 (73% [64, 82]) | 1,210 | 8,615 / 7,179 |
| 8.0% | 8.0% | 0.19 / 1.51 | 11.1% | 68 (76% [66, 84]) | 56 (62% [52, 72]) | 845 | 9,491 / 2,847 |
| 6.0% | 6.0% | 0.11 / 1.20 | 8.6% | 61 (68% [58, 77]) | 51 (57% [47, 67]) | 708 | 2,041 / 2,858 |
| 4.0% | 4.0% | 0.04 / 0.84 | 5.9% | 55 (61% [51, 71]) | 45 (50% [40, 61]) | 524 | 2,393 / 2,393 |
| 2.0% | 2.0% | 0.01 / 0.45 | 3.1% | 43 (48% [38, 58]) | 36 (40% [30, 51]) | 336 | 1,196 / 1,594 |

### F1_stratum, Warning+, Himalaya, monsoon (Jun-Sep) (557 events)

| cap | district-days | days/week median / p90 | chance floor | covered within 1 day | covered same day | district-days per event covered | cost ratio (within 1 day / same day) |
|---|---|---|---|---|---|---|---|
| R0 any cell | 56.7% | 4.92 / 6.94 | 61.8% | 556 (100% [99, 100]) | 555 (100% [99, 100]) | 590 | |
| 25.0% | 25.0% | 0.67 / 5.01 | 30.9% | 478 (86% [83, 89]) | 435 (78% [74, 82]) | 302 | 2,352 / 1,529 |
| 18.0% | 17.7% | 0.27 / 4.02 | 22.9% | 402 (72% [68, 76]) | 364 (65% [61, 70]) | 255 | 554 / 593 |
| 12.0% | 11.9% | 0.10 / 2.90 | 16.0% | 313 (56% [52, 60]) | 268 (48% [44, 53]) | 220 | 378 / 350 |
| 8.0% | 8.0% | 0.04 / 1.94 | 11.2% | 242 (43% [39, 48]) | 191 (34% [30, 39]) | 192 | 317 / 292 |
| 6.0% | 6.0% | 0.02 / 1.40 | 8.6% | 199 (36% [31, 40]) | 159 (29% [25, 33]) | 174 | 273 / 367 |
| 4.0% | 4.0% | 0.01 / 0.94 | 5.9% | 147 (26% [22, 31]) | 109 (20% [16, 24]) | 158 | 220 / 229 |
| 2.0% | 2.0% | 0.00 / 0.31 | 3.1% | 68 (12% [9, 16]) | 51 (9% [6, 13]) | 170 | 147 / 200 |

### F1_stratum, Warning+, Himalaya, post-monsoon (Oct-Dec) (32 events)

| cap | district-days | days/week median / p90 | chance floor | covered within 1 day | covered same day | district-days per event covered | cost ratio (within 1 day / same day) |
|---|---|---|---|---|---|---|---|
| R0 any cell | 13.0% | 0.62 / 2.20 | 16.3% | 27 (84% [71, 97]) | 25 (78% [63, 91]) | 2,108 | |
| 25.0% | 13.0% | 0.62 / 2.20 | 16.2% | 27 (84% [71, 97]) | 25 (78% [63, 91]) | 2,108 | any / any |
| 18.0% | 13.0% | 0.62 / 2.20 | 16.2% | 27 (84% [71, 97]) | 25 (78% [63, 91]) | 2,108 | any / any |
| 12.0% | 12.0% | 0.56 / 2.06 | 15.0% | 27 (84% [71, 97]) | 25 (78% [63, 91]) | 1,937 | any / any |
| 8.0% | 8.0% | 0.42 / 1.43 | 10.5% | 25 (78% [63, 91]) | 23 (72% [55, 87]) | 1,399 | 8,666 / 8,666 |
| 6.0% | 6.0% | 0.28 / 1.11 | 8.1% | 25 (78% [63, 91]) | 23 (72% [55, 87]) | 1,053 | any / any |
| 4.0% | 4.0% | 0.15 / 0.82 | 5.6% | 24 (75% [58, 88]) | 23 (72% [55, 87]) | 732 | 8,777 / any |
| 2.0% | 2.0% | 0.04 / 0.46 | 3.0% | 21 (66% [48, 81]) | 16 (50% [32, 68]) | 420 | 2,915 / 1,249 |

### F1_stratum, Warning+, Western Ghats, rest of year (Jan-May) (5 events)

| cap | district-days | days/week median / p90 | chance floor | covered within 1 day | covered same day | district-days per event covered | cost ratio (within 1 day / same day) |
|---|---|---|---|---|---|---|---|
| R0 any cell | 6.5% | 0.03 / 1.52 | 8.3% | 4 (80% [40, 100]) | 4 (80% [40, 100]) | 3,356 | |
| 25.0% | 6.5% | 0.03 / 1.52 | 8.3% | 4 (80% [40, 100]) | 4 (80% [40, 100]) | 3,356 | any / any |
| 18.0% | 6.5% | 0.03 / 1.52 | 8.3% | 4 (80% [40, 100]) | 4 (80% [40, 100]) | 3,356 | any / any |
| 12.0% | 6.5% | 0.03 / 1.52 | 8.3% | 4 (80% [40, 100]) | 4 (80% [40, 100]) | 3,356 | any / any |
| 8.0% | 6.5% | 0.03 / 1.52 | 8.3% | 4 (80% [40, 100]) | 4 (80% [40, 100]) | 3,356 | any / any |
| 6.0% | 6.0% | 0.03 / 1.47 | 7.7% | 4 (80% [40, 100]) | 4 (80% [40, 100]) | 3,102 | any / any |
| 4.0% | 4.0% | 0.01 / 1.09 | 5.4% | 4 (80% [40, 100]) | 2 (40% [0, 80]) | 2,074 | any / 2,056 |
| 2.0% | 2.0% | 0.00 / 0.63 | 2.8% | 1 (20% [0, 60]) | 0 (0% [0, 0]) | 4,128 | 1,389 / 2,084 |

### F1_stratum, Warning+, Western Ghats, monsoon (Jun-Sep) (79 events)

| cap | district-days | days/week median / p90 | chance floor | covered within 1 day | covered same day | district-days per event covered | cost ratio (within 1 day / same day) |
|---|---|---|---|---|---|---|---|
| R0 any cell | 30.6% | 0.47 / 5.95 | 34.8% | 79 (100% [100, 100]) | 78 (99% [96, 100]) | 645 | |
| 25.0% | 25.0% | 0.40 / 5.25 | 29.4% | 77 (97% [94, 100]) | 72 (91% [84, 96]) | 540 | 4,690 / 1,563 |
| 18.0% | 18.0% | 0.21 / 4.10 | 22.3% | 69 (87% [79, 94]) | 61 (77% [67, 86]) | 434 | 1,453 / 1,056 |
| 12.0% | 12.0% | 0.06 / 2.80 | 15.7% | 61 (77% [68, 86]) | 53 (67% [56, 77]) | 329 | 1,238 / 1,238 |
| 8.0% | 8.0% | 0.02 / 1.90 | 10.9% | 52 (66% [55, 76]) | 40 (51% [39, 62]) | 257 | 740 / 512 |
| 6.0% | 6.1% | 0.01 / 1.47 | 8.4% | 45 (57% [46, 68]) | 34 (43% [31, 54]) | 224 | 472 / 551 |
| 4.0% | 4.0% | 0.00 / 0.84 | 5.6% | 28 (35% [24, 47]) | 25 (32% [21, 43]) | 239 | 200 / 377 |
| 2.0% | 2.0% | 0.00 / 0.26 | 2.8% | 21 (27% [16, 38]) | 19 (24% [14, 35]) | 159 | 478 / 557 |

### F1_stratum, Warning+, Western Ghats, post-monsoon (Oct-Dec) (12 events)

| cap | district-days | days/week median / p90 | chance floor | covered within 1 day | covered same day | district-days per event covered | cost ratio (within 1 day / same day) |
|---|---|---|---|---|---|---|---|
| R0 any cell | 15.1% | 0.22 / 3.29 | 18.1% | 10 (83% [58, 100]) | 10 (83% [58, 100]) | 1,898 | |
| 25.0% | 15.1% | 0.22 / 3.29 | 18.1% | 10 (83% [58, 100]) | 10 (83% [58, 100]) | 1,898 | any / any |
| 18.0% | 15.1% | 0.22 / 3.29 | 18.1% | 10 (83% [58, 100]) | 10 (83% [58, 100]) | 1,898 | any / any |
| 12.0% | 12.1% | 0.12 / 2.85 | 14.8% | 10 (83% [58, 100]) | 10 (83% [58, 100]) | 1,517 | any / any |
| 8.0% | 8.1% | 0.06 / 2.09 | 10.3% | 10 (83% [58, 100]) | 10 (83% [58, 100]) | 1,014 | any / any |
| 6.0% | 6.1% | 0.03 / 1.44 | 8.0% | 9 (75% [50, 92]) | 9 (75% [50, 92]) | 850 | 2,490 / 2,490 |
| 4.0% | 4.1% | 0.01 / 1.09 | 5.5% | 5 (42% [17, 67]) | 5 (42% [17, 67]) | 1,028 | 628 / 628 |
| 2.0% | 2.0% | 0.00 / 0.56 | 2.8% | 4 (33% [8, 58]) | 4 (33% [8, 58]) | 626 | 2,638 / 2,638 |

### F1_stratum, Emergency, Himalaya, rest of year (Jan-May) (90 events)

| cap | district-days | days/week median / p90 | chance floor | covered within 1 day | covered same day | district-days per event covered | cost ratio (within 1 day / same day) |
|---|---|---|---|---|---|---|---|
| R0 any cell | 10.3% | 0.30 / 1.94 | 13.8% | 74 (82% [74, 90]) | 66 (73% [64, 82]) | 995 | |
| 10.0% | 10.0% | 0.30 / 1.92 | 13.5% | 73 (81% [73, 89]) | 65 (72% [63, 81]) | 982 | 1,956 / 1,956 |
| 6.0% | 6.0% | 0.16 / 1.19 | 8.8% | 67 (74% [66, 84]) | 54 (60% [51, 71]) | 644 | 4,749 / 2,590 |
| 4.0% | 4.0% | 0.08 / 0.77 | 6.1% | 59 (66% [56, 75]) | 47 (52% [42, 63]) | 487 | 1,807 / 2,066 |
| 3.0% | 3.0% | 0.03 / 0.61 | 4.7% | 49 (54% [44, 65]) | 44 (49% [39, 59]) | 441 | 709 / 2,362 |
| 2.0% | 2.0% | 0.02 / 0.40 | 3.2% | 42 (47% [36, 57]) | 35 (39% [29, 49]) | 343 | 1,031 / 802 |
| 1.0% | 1.0% | 0.00 / 0.22 | 1.7% | 36 (40% [30, 51]) | 31 (34% [25, 44]) | 202 | 1,192 / 1,788 |
| 0.5% | 0.5% | 0.00 / 0.11 | 0.9% | 27 (30% [21, 40]) | 24 (27% [18, 37]) | 136 | 399 / 513 |

### F1_stratum, Emergency, Himalaya, monsoon (Jun-Sep) (557 events)

| cap | district-days | days/week median / p90 | chance floor | covered within 1 day | covered same day | district-days per event covered | cost ratio (within 1 day / same day) |
|---|---|---|---|---|---|---|---|
| R0 any cell | 35.4% | 1.80 / 6.05 | 41.6% | 543 (97% [96, 99]) | 528 (95% [93, 97]) | 377 | |
| 10.0% | 10.0% | 0.08 / 2.53 | 13.8% | 354 (64% [59, 68]) | 289 (52% [47, 56]) | 163 | 778 / 615 |
| 6.0% | 6.0% | 0.03 / 1.62 | 8.7% | 241 (43% [39, 48]) | 186 (33% [29, 38]) | 144 | 202 / 222 |
| 4.0% | 4.0% | 0.01 / 0.89 | 6.0% | 176 (32% [27, 36]) | 131 (24% [20, 28]) | 132 | 178 / 210 |
| 3.0% | 3.0% | 0.00 / 0.70 | 4.5% | 143 (26% [22, 30]) | 108 (19% [16, 23]) | 121 | 178 / 256 |
| 2.0% | 2.0% | 0.00 / 0.35 | 3.1% | 106 (19% [15, 23]) | 78 (14% [11, 18]) | 108 | 158 / 195 |
| 1.0% | 1.0% | 0.00 / 0.15 | 1.6% | 54 (10% [7, 13]) | 44 (8% [5, 11]) | 108 | 108 / 165 |
| 0.5% | 0.5% | 0.00 / 0.06 | 0.8% | 39 (7% [4, 10]) | 29 (5% [3, 8]) | 73 | 198 / 198 |

### F1_stratum, Emergency, Himalaya, post-monsoon (Oct-Dec) (32 events)

| cap | district-days | days/week median / p90 | chance floor | covered within 1 day | covered same day | district-days per event covered | cost ratio (within 1 day / same day) |
|---|---|---|---|---|---|---|---|
| R0 any cell | 5.1% | 0.17 / 0.95 | 7.1% | 24 (75% [59, 90]) | 23 (72% [56, 86]) | 926 | |
| 10.0% | 5.1% | 0.17 / 0.95 | 7.1% | 24 (75% [59, 90]) | 23 (72% [56, 86]) | 926 | any / any |
| 6.0% | 5.1% | 0.17 / 0.95 | 7.1% | 24 (75% [59, 90]) | 23 (72% [56, 86]) | 926 | any / any |
| 4.0% | 4.0% | 0.14 / 0.75 | 5.8% | 24 (75% [59, 90]) | 22 (69% [52, 84]) | 731 | any / 4,682 |
| 3.0% | 3.0% | 0.11 / 0.56 | 4.5% | 23 (72% [56, 86]) | 22 (69% [52, 84]) | 571 | 4,422 / any |
| 2.0% | 2.0% | 0.06 / 0.39 | 3.1% | 21 (66% [48, 81]) | 19 (59% [42, 76]) | 418 | 2,170 / 1,447 |
| 1.0% | 1.0% | 0.03 / 0.21 | 1.6% | 17 (53% [35, 71]) | 17 (53% [35, 71]) | 258 | 1,100 / 2,200 |
| 0.5% | 0.5% | 0.01 / 0.10 | 0.9% | 15 (47% [29, 65]) | 11 (34% [16, 53]) | 147 | 1,092 / 364 |

### F1_stratum, Emergency, Western Ghats, rest of year (Jan-May) (5 events)

| cap | district-days | days/week median / p90 | chance floor | covered within 1 day | covered same day | district-days per event covered | cost ratio (within 1 day / same day) |
|---|---|---|---|---|---|---|---|
| R0 any cell | 2.5% | 0.00 / 0.65 | 3.4% | 3 (60% [20, 100]) | 2 (40% [0, 80]) | 1,714 | |
| 10.0% | 2.5% | 0.00 / 0.65 | 3.4% | 3 (60% [20, 100]) | 2 (40% [0, 80]) | 1,714 | any / any |
| 6.0% | 2.5% | 0.00 / 0.65 | 3.4% | 3 (60% [20, 100]) | 2 (40% [0, 80]) | 1,714 | any / any |
| 4.0% | 2.5% | 0.00 / 0.65 | 3.4% | 3 (60% [20, 100]) | 2 (40% [0, 80]) | 1,714 | any / any |
| 3.0% | 2.5% | 0.00 / 0.65 | 3.4% | 3 (60% [20, 100]) | 2 (40% [0, 80]) | 1,714 | any / any |
| 2.0% | 2.0% | 0.00 / 0.56 | 2.8% | 3 (60% [20, 100]) | 2 (40% [0, 80]) | 1,363 | any / any |
| 1.0% | 1.0% | 0.00 / 0.29 | 1.5% | 0 (0% [0, 0]) | 0 (0% [0, 0]) | 0 | 666 / 999 |
| 0.5% | 0.5% | 0.00 / 0.15 | 0.8% | 0 (0% [0, 0]) | 0 (0% [0, 0]) | 0 | any / any |

### F1_stratum, Emergency, Western Ghats, monsoon (Jun-Sep) (79 events)

| cap | district-days | days/week median / p90 | chance floor | covered within 1 day | covered same day | district-days per event covered | cost ratio (within 1 day / same day) |
|---|---|---|---|---|---|---|---|
| R0 any cell | 17.2% | 0.08 / 4.16 | 20.6% | 74 (94% [87, 99]) | 66 (84% [74, 91]) | 387 | |
| 10.0% | 10.0% | 0.06 / 2.43 | 12.9% | 60 (76% [66, 85]) | 53 (67% [56, 77]) | 279 | 852 / 917 |
| 6.0% | 6.0% | 0.03 / 1.26 | 8.1% | 47 (59% [48, 71]) | 39 (49% [38, 60]) | 214 | 514 / 477 |
| 4.0% | 4.0% | 0.01 / 0.68 | 5.5% | 34 (43% [32, 54]) | 31 (39% [28, 50]) | 196 | 259 / 421 |
| 3.0% | 3.0% | 0.00 / 0.47 | 4.2% | 32 (41% [29, 51]) | 26 (33% [22, 44]) | 157 | 818 / 327 |
| 2.0% | 2.0% | 0.00 / 0.26 | 2.8% | 22 (28% [17, 39]) | 21 (27% [16, 38]) | 152 | 168 / 337 |
| 1.0% | 1.0% | 0.00 / 0.05 | 1.2% | 9 (11% [4, 20]) | 9 (11% [4, 20]) | 177 | 136 / 147 |
| 0.5% | 0.0% | 0.00 / 0.00 | 0.0% | 0 (0% [0, 0]) | 0 (0% [0, 0]) | 0 | 177 / 177 |

### F1_stratum, Emergency, Western Ghats, post-monsoon (Oct-Dec) (12 events)

| cap | district-days | days/week median / p90 | chance floor | covered within 1 day | covered same day | district-days per event covered | cost ratio (within 1 day / same day) |
|---|---|---|---|---|---|---|---|
| R0 any cell | 7.6% | 0.03 / 1.81 | 9.5% | 9 (75% [50, 92]) | 9 (75% [50, 92]) | 1,055 | |
| 10.0% | 7.6% | 0.03 / 1.81 | 9.5% | 9 (75% [50, 92]) | 9 (75% [50, 92]) | 1,055 | any / any |
| 6.0% | 6.1% | 0.03 / 1.47 | 7.7% | 8 (67% [42, 92]) | 8 (67% [42, 92]) | 952 | 1,878 / 1,878 |
| 4.0% | 4.1% | 0.01 / 1.00 | 5.4% | 8 (67% [42, 92]) | 7 (58% [33, 83]) | 637 | any / 2,520 |
| 3.0% | 3.0% | 0.00 / 0.78 | 4.2% | 7 (58% [25, 83]) | 6 (50% [25, 75]) | 544 | 1,286 / 1,286 |
| 2.0% | 2.1% | 0.00 / 0.57 | 2.9% | 4 (33% [8, 58]) | 4 (33% [8, 58]) | 649 | 405 / 607 |
| 1.0% | 1.1% | 0.00 / 0.28 | 1.5% | 3 (25% [0, 50]) | 3 (25% [0, 50]) | 446 | 1,256 / 1,256 |
| 0.5% | 0.5% | 0.00 / 0.11 | 0.7% | 2 (17% [0, 42]) | 2 (17% [0, 42]) | 287 | 765 / 765 |

### F2_district, Watch+, Himalaya, rest of year (Jan-May) (90 events)

| cap | district-days | days/week median / p90 | chance floor | covered within 1 day | covered same day | district-days per event covered | cost ratio (within 1 day / same day) |
|---|---|---|---|---|---|---|---|
| R0 any cell | 40.8% | 3.05 / 5.96 | 44.6% | 87 (97% [93, 100]) | 86 (96% [91, 99]) | 3,361 | |
| 50.0% | 31.4% | 3.02 / 3.48 | 35.8% | 82 (91% [85, 97]) | 74 (82% [73, 90]) | 2,744 | 13,480 / 5,617 |
| 40.0% | 26.4% | 2.66 / 2.79 | 30.9% | 78 (87% [80, 93]) | 71 (79% [69, 87]) | 2,424 | 8,994 / 11,993 |
| 30.0% | 20.3% | 1.97 / 2.09 | 25.0% | 65 (72% [62, 81]) | 58 (64% [54, 74]) | 2,245 | 3,316 / 3,316 |
| 20.0% | 13.6% | 1.28 / 1.39 | 17.9% | 50 (56% [45, 66]) | 46 (51% [41, 61]) | 1,945 | 3,248 / 4,060 |
| 15.0% | 9.7% | 0.92 / 1.04 | 13.4% | 43 (48% [37, 58]) | 37 (41% [31, 51]) | 1,620 | 3,938 / 3,063 |
| 10.0% | 6.2% | 0.58 / 0.70 | 9.1% | 33 (37% [26, 47]) | 27 (30% [20, 40]) | 1,357 | 2,488 / 2,488 |
| 5.0% | 2.9% | 0.26 / 0.36 | 4.5% | 23 (26% [16, 35]) | 21 (23% [14, 33]) | 895 | 2,419 / 4,032 |

### F2_district, Watch+, Himalaya, monsoon (Jun-Sep) (557 events)

| cap | district-days | days/week median / p90 | chance floor | covered within 1 day | covered same day | district-days per event covered | cost ratio (within 1 day / same day) |
|---|---|---|---|---|---|---|---|
| R0 any cell | 82.8% | 6.86 / 7.00 | 86.0% | 556 (100% [99, 100]) | 556 (100% [99, 100]) | 861 | |
| 50.0% | 35.9% | 3.20 / 3.45 | 45.8% | 306 (55% [51, 59]) | 273 (49% [45, 53]) | 679 | 1,084 / 957 |
| 40.0% | 28.0% | 2.52 / 2.76 | 37.5% | 255 (46% [41, 50]) | 213 (38% [34, 43]) | 636 | 895 / 760 |
| 30.0% | 19.8% | 1.84 / 2.07 | 28.0% | 198 (36% [31, 40]) | 157 (28% [24, 32]) | 578 | 837 / 852 |
| 20.0% | 11.9% | 1.19 / 1.39 | 17.9% | 137 (25% [21, 28]) | 104 (19% [15, 22]) | 504 | 742 / 854 |
| 15.0% | 8.6% | 0.90 / 1.05 | 13.4% | 105 (19% [15, 23]) | 82 (15% [11, 18]) | 472 | 611 / 889 |
| 10.0% | 5.5% | 0.56 / 0.71 | 8.9% | 69 (12% [9, 15]) | 53 (10% [7, 12]) | 459 | 495 / 615 |
| 5.0% | 2.4% | 0.18 / 0.37 | 4.1% | 42 (8% [5, 10]) | 29 (5% [3, 8]) | 331 | 659 / 741 |

### F2_district, Watch+, Himalaya, post-monsoon (Oct-Dec) (32 events)

| cap | district-days | days/week median / p90 | chance floor | covered within 1 day | covered same day | district-days per event covered | cost ratio (within 1 day / same day) |
|---|---|---|---|---|---|---|---|
| R0 any cell | 31.1% | 1.89 / 4.61 | 35.0% | 30 (94% [84, 100]) | 29 (91% [78, 100]) | 4,517 | |
| 50.0% | 26.8% | 1.86 / 3.43 | 30.8% | 29 (91% [78, 100]) | 29 (91% [78, 100]) | 4,028 | 18,682 / any |
| 40.0% | 24.1% | 1.86 / 2.78 | 28.0% | 29 (91% [78, 100]) | 29 (91% [78, 100]) | 3,625 | any / any |
| 30.0% | 20.2% | 1.78 / 2.09 | 23.9% | 29 (91% [78, 100]) | 28 (88% [74, 97]) | 3,042 | any / 16,922 |
| 20.0% | 14.6% | 1.32 / 1.41 | 17.8% | 28 (88% [74, 97]) | 27 (84% [70, 97]) | 2,278 | 24,412 / 24,412 |
| 15.0% | 11.2% | 1.00 / 1.07 | 14.1% | 20 (62% [43, 79]) | 16 (50% [31, 67]) | 2,450 | 1,850 / 1,345 |
| 10.0% | 7.7% | 0.66 / 0.73 | 10.1% | 11 (34% [18, 52]) | 9 (28% [12, 45]) | 3,039 | 1,730 / 2,224 |
| 5.0% | 3.8% | 0.33 / 0.38 | 5.5% | 5 (16% [3, 29]) | 5 (16% [3, 29]) | 3,344 | 2,785 / 4,178 |

### F2_district, Watch+, Western Ghats, rest of year (Jan-May) (5 events)

| cap | district-days | days/week median / p90 | chance floor | covered within 1 day | covered same day | district-days per event covered | cost ratio (within 1 day / same day) |
|---|---|---|---|---|---|---|---|
| R0 any cell | 20.1% | 0.98 / 3.64 | 22.9% | 4 (80% [40, 100]) | 4 (80% [40, 100]) | 10,381 | |
| 50.0% | 18.5% | 0.98 / 3.42 | 21.3% | 4 (80% [40, 100]) | 4 (80% [40, 100]) | 9,535 | any / any |
| 40.0% | 16.8% | 0.98 / 2.76 | 19.6% | 4 (80% [40, 100]) | 4 (80% [40, 100]) | 8,670 | any / any |
| 30.0% | 14.3% | 0.98 / 2.07 | 17.1% | 3 (60% [20, 100]) | 2 (40% [0, 80]) | 9,857 | 5,108 / 2,554 |
| 20.0% | 10.8% | 0.89 / 1.39 | 13.4% | 2 (40% [0, 80]) | 1 (20% [0, 60]) | 11,112 | 7,345 / 7,345 |
| 15.0% | 8.5% | 0.76 / 1.04 | 11.0% | 2 (40% [0, 80]) | 1 (20% [0, 60]) | 8,722 | any / any |
| 10.0% | 5.7% | 0.51 / 0.70 | 7.9% | 1 (20% [0, 60]) | 1 (20% [0, 60]) | 11,762 | 5,682 / any |
| 5.0% | 3.0% | 0.29 / 0.35 | 4.4% | 1 (20% [0, 60]) | 1 (20% [0, 60]) | 6,099 | any / any |

### F2_district, Watch+, Western Ghats, monsoon (Jun-Sep) (79 events)

| cap | district-days | days/week median / p90 | chance floor | covered within 1 day | covered same day | district-days per event covered | cost ratio (within 1 day / same day) |
|---|---|---|---|---|---|---|---|
| R0 any cell | 61.2% | 4.93 / 6.90 | 66.3% | 79 (100% [100, 100]) | 79 (100% [100, 100]) | 1,290 | |
| 50.0% | 33.9% | 3.17 / 3.47 | 42.3% | 57 (72% [62, 81]) | 52 (66% [55, 76]) | 990 | 2,068 / 1,685 |
| 40.0% | 27.1% | 2.50 / 2.77 | 35.5% | 44 (56% [44, 67]) | 38 (48% [37, 59]) | 1,026 | 868 / 806 |
| 30.0% | 20.5% | 1.89 / 2.07 | 28.4% | 41 (52% [40, 63]) | 34 (43% [32, 54]) | 832 | 3,678 / 2,758 |
| 20.0% | 13.6% | 1.22 / 1.39 | 20.0% | 27 (34% [23, 46]) | 20 (25% [15, 36]) | 841 | 814 / 814 |
| 15.0% | 9.8% | 0.91 / 1.04 | 15.0% | 23 (29% [19, 40]) | 16 (20% [11, 30]) | 707 | 1,613 / 1,613 |
| 10.0% | 6.5% | 0.61 / 0.70 | 10.4% | 15 (19% [11, 28]) | 11 (14% [6, 23]) | 718 | 686 / 1,097 |
| 5.0% | 3.2% | 0.30 / 0.36 | 5.5% | 8 (10% [4, 18]) | 7 (9% [4, 16]) | 672 | 772 / 1,350 |

### F2_district, Watch+, Western Ghats, post-monsoon (Oct-Dec) (12 events)

| cap | district-days | days/week median / p90 | chance floor | covered within 1 day | covered same day | district-days per event covered | cost ratio (within 1 day / same day) |
|---|---|---|---|---|---|---|---|
| R0 any cell | 34.6% | 1.76 / 5.53 | 38.3% | 12 (100% [100, 100]) | 12 (100% [100, 100]) | 3,619 | |
| 50.0% | 26.1% | 1.59 / 3.48 | 30.0% | 10 (83% [58, 100]) | 10 (83% [58, 100]) | 3,269 | 5,367 / 5,367 |
| 40.0% | 21.9% | 1.56 / 2.79 | 25.9% | 10 (83% [58, 100]) | 10 (83% [58, 100]) | 2,753 | any / any |
| 30.0% | 17.5% | 1.45 / 2.11 | 21.2% | 8 (67% [42, 92]) | 8 (67% [42, 92]) | 2,739 | 2,810 / 2,810 |
| 20.0% | 11.7% | 1.03 / 1.41 | 15.0% | 5 (42% [17, 67]) | 5 (42% [17, 67]) | 2,934 | 2,413 / 2,413 |
| 15.0% | 8.8% | 0.77 / 1.07 | 11.7% | 4 (33% [8, 58]) | 4 (33% [8, 58]) | 2,765 | 3,613 / 3,613 |
| 10.0% | 6.2% | 0.57 / 0.73 | 8.6% | 3 (25% [0, 50]) | 3 (25% [0, 50]) | 2,580 | 3,318 / 3,318 |
| 5.0% | 3.4% | 0.31 / 0.38 | 5.1% | 2 (17% [0, 42]) | 1 (8% [0, 25]) | 2,141 | 3,459 / 1,730 |

### F2_district, Warning+, Himalaya, rest of year (Jan-May) (90 events)

| cap | district-days | days/week median / p90 | chance floor | covered within 1 day | covered same day | district-days per event covered | cost ratio (within 1 day / same day) |
|---|---|---|---|---|---|---|---|
| R0 any cell | 22.4% | 1.20 / 3.99 | 26.7% | 81 (90% [84, 96]) | 79 (88% [81, 94]) | 1,987 | |
| 25.0% | 13.0% | 1.16 / 1.72 | 17.4% | 65 (72% [62, 82]) | 56 (62% [52, 73]) | 1,437 | 4,218 / 2,934 |
| 18.0% | 9.8% | 1.01 / 1.25 | 13.8% | 62 (69% [59, 79]) | 53 (59% [49, 70]) | 1,138 | 7,629 / 7,629 |
| 12.0% | 6.8% | 0.72 / 0.84 | 10.1% | 55 (61% [50, 71]) | 47 (52% [43, 63]) | 886 | 3,116 / 3,635 |
| 8.0% | 4.7% | 0.50 / 0.57 | 7.2% | 48 (53% [43, 63]) | 39 (43% [33, 54]) | 700 | 2,164 / 1,894 |
| 6.0% | 3.6% | 0.37 / 0.43 | 5.7% | 44 (49% [39, 59]) | 34 (38% [28, 48]) | 586 | 1,948 / 1,558 |
| 4.0% | 2.5% | 0.24 / 0.29 | 4.0% | 38 (42% [32, 53]) | 29 (32% [23, 42]) | 468 | 1,334 / 1,600 |
| 2.0% | 1.3% | 0.13 / 0.16 | 2.2% | 29 (32% [22, 42]) | 26 (29% [20, 38]) | 329 | 918 / 2,753 |

### F2_district, Warning+, Himalaya, monsoon (Jun-Sep) (557 events)

| cap | district-days | days/week median / p90 | chance floor | covered within 1 day | covered same day | district-days per event covered | cost ratio (within 1 day / same day) |
|---|---|---|---|---|---|---|---|
| R0 any cell | 56.7% | 4.92 / 6.94 | 61.8% | 556 (100% [99, 100]) | 555 (100% [99, 100]) | 590 | |
| 25.0% | 17.3% | 1.56 / 1.73 | 25.6% | 361 (65% [61, 69]) | 264 (47% [43, 52]) | 277 | 1,170 / 784 |
| 18.0% | 12.6% | 1.12 / 1.24 | 19.5% | 290 (52% [47, 57]) | 211 (38% [33, 42]) | 252 | 379 / 507 |
| 12.0% | 8.4% | 0.73 / 0.84 | 13.6% | 232 (42% [37, 46]) | 167 (30% [26, 34]) | 210 | 417 / 550 |
| 8.0% | 5.7% | 0.50 / 0.56 | 9.6% | 182 (33% [28, 37]) | 129 (23% [19, 27]) | 182 | 314 / 413 |
| 6.0% | 4.4% | 0.38 / 0.43 | 7.4% | 146 (26% [22, 30]) | 99 (18% [14, 22]) | 173 | 217 / 260 |
| 4.0% | 2.9% | 0.26 / 0.29 | 5.1% | 112 (20% [16, 24]) | 75 (13% [10, 17]) | 152 | 245 / 347 |
| 2.0% | 1.5% | 0.13 / 0.15 | 2.7% | 65 (12% [8, 15]) | 48 (9% [6, 12]) | 135 | 175 / 304 |

### F2_district, Warning+, Himalaya, post-monsoon (Oct-Dec) (32 events)

| cap | district-days | days/week median / p90 | chance floor | covered within 1 day | covered same day | district-days per event covered | cost ratio (within 1 day / same day) |
|---|---|---|---|---|---|---|---|
| R0 any cell | 13.0% | 0.62 / 2.20 | 16.3% | 27 (84% [71, 97]) | 25 (78% [63, 91]) | 2,108 | |
| 25.0% | 10.8% | 0.62 / 1.67 | 13.8% | 27 (84% [71, 97]) | 25 (78% [63, 91]) | 1,746 | any / any |
| 18.0% | 8.9% | 0.62 / 1.23 | 11.7% | 27 (84% [71, 97]) | 24 (75% [58, 89]) | 1,442 | any / 8,204 |
| 12.0% | 6.7% | 0.57 / 0.84 | 9.2% | 25 (78% [63, 91]) | 22 (69% [52, 84]) | 1,171 | 4,830 / 4,830 |
| 8.0% | 4.9% | 0.48 / 0.57 | 7.0% | 22 (69% [52, 84]) | 20 (62% [45, 78]) | 974 | 2,618 / 3,927 |
| 6.0% | 3.9% | 0.38 / 0.44 | 5.8% | 21 (66% [48, 81]) | 17 (53% [35, 71]) | 812 | 4,375 / 1,458 |
| 4.0% | 2.7% | 0.26 / 0.30 | 4.2% | 15 (47% [29, 65]) | 13 (41% [23, 59]) | 795 | 852 / 1,278 |
| 2.0% | 1.5% | 0.13 / 0.16 | 2.4% | 12 (38% [19, 56]) | 11 (34% [16, 53]) | 546 | 1,793 / 2,690 |

### F2_district, Warning+, Western Ghats, rest of year (Jan-May) (5 events)

| cap | district-days | days/week median / p90 | chance floor | covered within 1 day | covered same day | district-days per event covered | cost ratio (within 1 day / same day) |
|---|---|---|---|---|---|---|---|
| R0 any cell | 6.5% | 0.03 / 1.52 | 8.3% | 4 (80% [40, 100]) | 4 (80% [40, 100]) | 3,356 | |
| 25.0% | 5.5% | 0.03 / 1.47 | 7.2% | 4 (80% [40, 100]) | 2 (40% [0, 80]) | 2,840 | any / 1,032 |
| 18.0% | 4.5% | 0.03 / 1.14 | 6.2% | 2 (40% [0, 80]) | 1 (20% [0, 60]) | 4,687 | 992 / 1,985 |
| 12.0% | 3.6% | 0.03 / 0.79 | 5.0% | 2 (40% [0, 80]) | 1 (20% [0, 60]) | 3,692 | any / any |
| 8.0% | 2.7% | 0.03 / 0.54 | 4.0% | 1 (20% [0, 60]) | 1 (20% [0, 60]) | 5,645 | 1,738 / any |
| 6.0% | 2.2% | 0.03 / 0.40 | 3.2% | 1 (20% [0, 60]) | 1 (20% [0, 60]) | 4,482 | any / any |
| 4.0% | 1.6% | 0.03 / 0.28 | 2.4% | 0 (0% [0, 0]) | 0 (0% [0, 0]) | 0 | 1,168 / 1,168 |
| 2.0% | 0.9% | 0.03 / 0.15 | 1.4% | 0 (0% [0, 0]) | 0 (0% [0, 0]) | 0 | any / any |

### F2_district, Warning+, Western Ghats, monsoon (Jun-Sep) (79 events)

| cap | district-days | days/week median / p90 | chance floor | covered within 1 day | covered same day | district-days per event covered | cost ratio (within 1 day / same day) |
|---|---|---|---|---|---|---|---|
| R0 any cell | 30.6% | 0.47 / 5.95 | 34.8% | 79 (100% [100, 100]) | 78 (99% [96, 100]) | 645 | |
| 25.0% | 11.8% | 0.40 / 1.75 | 16.7% | 50 (63% [52, 74]) | 37 (47% [35, 58]) | 392 | 1,081 / 764 |
| 18.0% | 8.9% | 0.40 / 1.26 | 13.2% | 47 (59% [47, 70]) | 30 (38% [26, 49]) | 316 | 1,587 / 680 |
| 12.0% | 6.3% | 0.38 / 0.85 | 9.7% | 35 (44% [32, 56]) | 26 (33% [22, 44]) | 298 | 369 / 1,107 |
| 8.0% | 4.5% | 0.37 / 0.57 | 7.2% | 29 (37% [25, 49]) | 23 (29% [18, 41]) | 257 | 492 / 985 |
| 6.0% | 3.5% | 0.33 / 0.43 | 5.8% | 28 (35% [24, 47]) | 23 (29% [18, 41]) | 209 | 1,600 / any |
| 4.0% | 2.5% | 0.23 / 0.29 | 4.1% | 23 (29% [18, 41]) | 20 (25% [15, 36]) | 179 | 351 / 585 |
| 2.0% | 1.3% | 0.13 / 0.16 | 2.3% | 14 (18% [9, 28]) | 11 (14% [6, 23]) | 160 | 207 / 207 |

### F2_district, Warning+, Western Ghats, post-monsoon (Oct-Dec) (12 events)

| cap | district-days | days/week median / p90 | chance floor | covered within 1 day | covered same day | district-days per event covered | cost ratio (within 1 day / same day) |
|---|---|---|---|---|---|---|---|
| R0 any cell | 15.1% | 0.22 / 3.29 | 18.1% | 10 (83% [58, 100]) | 10 (83% [58, 100]) | 1,898 | |
| 25.0% | 9.7% | 0.22 / 1.71 | 12.4% | 8 (67% [42, 92]) | 8 (67% [42, 92]) | 1,523 | 3,399 / 3,399 |
| 18.0% | 7.7% | 0.22 / 1.25 | 10.2% | 7 (58% [33, 83]) | 7 (58% [33, 83]) | 1,373 | 2,569 / 2,569 |
| 12.0% | 5.5% | 0.20 / 0.85 | 7.6% | 6 (50% [25, 75]) | 6 (50% [25, 75]) | 1,151 | 2,710 / 2,710 |
| 8.0% | 3.9% | 0.16 / 0.58 | 5.5% | 6 (50% [25, 75]) | 6 (50% [25, 75]) | 808 | any / any |
| 6.0% | 3.1% | 0.15 / 0.45 | 4.6% | 6 (50% [25, 75]) | 3 (25% [0, 50]) | 646 | any / 324 |
| 4.0% | 2.1% | 0.11 / 0.30 | 3.2% | 3 (25% [0, 50]) | 2 (17% [0, 42]) | 878 | 414 / 1,243 |
| 2.0% | 1.2% | 0.09 / 0.17 | 2.0% | 3 (25% [0, 50]) | 2 (17% [0, 42]) | 518 | any / any |

### F2_district, Emergency, Himalaya, rest of year (Jan-May) (90 events)

| cap | district-days | days/week median / p90 | chance floor | covered within 1 day | covered same day | district-days per event covered | cost ratio (within 1 day / same day) |
|---|---|---|---|---|---|---|---|
| R0 any cell | 10.3% | 0.30 / 1.94 | 13.8% | 74 (82% [74, 90]) | 66 (73% [64, 82]) | 995 | |
| 10.0% | 4.5% | 0.29 / 0.67 | 7.0% | 52 (58% [47, 67]) | 43 (48% [38, 58]) | 618 | 1,885 / 1,803 |
| 6.0% | 3.0% | 0.27 / 0.42 | 4.8% | 43 (48% [37, 58]) | 36 (40% [30, 50]) | 497 | 1,201 / 1,544 |
| 4.0% | 2.1% | 0.20 / 0.29 | 3.5% | 36 (40% [30, 51]) | 28 (31% [21, 41]) | 419 | 893 / 781 |
| 3.0% | 1.7% | 0.16 / 0.22 | 2.8% | 35 (39% [29, 49]) | 27 (30% [20, 40]) | 338 | 3,264 / 3,264 |
| 2.0% | 1.1% | 0.11 / 0.16 | 1.9% | 28 (31% [22, 41]) | 22 (24% [16, 34]) | 293 | 518 / 726 |
| 1.0% | 0.6% | 0.06 / 0.09 | 1.1% | 17 (19% [11, 28]) | 15 (17% [9, 25]) | 268 | 332 / 521 |
| 0.5% | 0.4% | 0.03 / 0.05 | 0.6% | 16 (18% [10, 26]) | 13 (14% [7, 22]) | 160 | 1,993 / 996 |

### F2_district, Emergency, Himalaya, monsoon (Jun-Sep) (557 events)

| cap | district-days | days/week median / p90 | chance floor | covered within 1 day | covered same day | district-days per event covered | cost ratio (within 1 day / same day) |
|---|---|---|---|---|---|---|---|
| R0 any cell | 35.4% | 1.80 / 6.05 | 41.6% | 543 (97% [96, 99]) | 528 (95% [93, 97]) | 377 | |
| 10.0% | 6.1% | 0.58 / 0.71 | 9.9% | 221 (40% [35, 44]) | 162 (29% [25, 34]) | 160 | 526 / 463 |
| 6.0% | 3.9% | 0.35 / 0.43 | 6.5% | 168 (30% [26, 35]) | 120 (22% [17, 26]) | 133 | 244 / 308 |
| 4.0% | 2.7% | 0.25 / 0.29 | 4.7% | 123 (22% [18, 26]) | 87 (16% [12, 19]) | 127 | 150 / 205 |
| 3.0% | 2.1% | 0.18 / 0.22 | 3.6% | 101 (18% [14, 22]) | 72 (13% [9, 17]) | 118 | 170 / 249 |
| 2.0% | 1.5% | 0.13 / 0.16 | 2.6% | 81 (15% [11, 18]) | 61 (11% [8, 15]) | 104 | 175 / 318 |
| 1.0% | 0.8% | 0.07 / 0.09 | 1.5% | 59 (11% [7, 14]) | 46 (8% [5, 12]) | 79 | 171 / 250 |
| 0.5% | 0.5% | 0.04 / 0.05 | 0.9% | 39 (7% [4, 10]) | 27 (5% [2, 8]) | 70 | 97 / 102 |

### F2_district, Emergency, Himalaya, post-monsoon (Oct-Dec) (32 events)

| cap | district-days | days/week median / p90 | chance floor | covered within 1 day | covered same day | district-days per event covered | cost ratio (within 1 day / same day) |
|---|---|---|---|---|---|---|---|
| R0 any cell | 5.1% | 0.17 / 0.95 | 7.1% | 24 (75% [59, 90]) | 23 (72% [56, 86]) | 926 | |
| 10.0% | 3.7% | 0.17 / 0.64 | 5.5% | 24 (75% [59, 90]) | 21 (66% [48, 81]) | 668 | any / 3,093 |
| 6.0% | 2.8% | 0.17 / 0.42 | 4.3% | 21 (66% [48, 81]) | 19 (59% [42, 76]) | 575 | 1,322 / 1,983 |
| 4.0% | 2.0% | 0.15 / 0.28 | 3.2% | 18 (56% [39, 74]) | 17 (53% [35, 71]) | 489 | 1,092 / 1,638 |
| 3.0% | 1.6% | 0.14 / 0.22 | 2.7% | 18 (56% [39, 74]) | 12 (38% [19, 56]) | 395 | any / 338 |
| 2.0% | 1.2% | 0.11 / 0.15 | 2.0% | 16 (50% [31, 68]) | 11 (34% [16, 53]) | 327 | 942 / 1,884 |
| 1.0% | 0.7% | 0.07 / 0.09 | 1.2% | 12 (38% [19, 56]) | 11 (34% [16, 53]) | 258 | 532 / any |
| 0.5% | 0.4% | 0.03 / 0.05 | 0.7% | 8 (25% [7, 43]) | 7 (22% [6, 40]) | 212 | 350 / 350 |

### F2_district, Emergency, Western Ghats, rest of year (Jan-May) (5 events)

| cap | district-days | days/week median / p90 | chance floor | covered within 1 day | covered same day | district-days per event covered | cost ratio (within 1 day / same day) |
|---|---|---|---|---|---|---|---|
| R0 any cell | 2.5% | 0.00 / 0.65 | 3.4% | 3 (60% [20, 100]) | 2 (40% [0, 80]) | 1,714 | |
| 10.0% | 1.8% | 0.00 / 0.53 | 2.5% | 1 (20% [0, 60]) | 1 (20% [0, 60]) | 3,616 | 763 / 1,526 |
| 6.0% | 1.3% | 0.00 / 0.36 | 2.0% | 1 (20% [0, 60]) | 1 (20% [0, 60]) | 2,703 | any / any |
| 4.0% | 1.0% | 0.00 / 0.25 | 1.6% | 0 (0% [0, 0]) | 0 (0% [0, 0]) | 0 | 598 / 598 |
| 3.0% | 0.8% | 0.00 / 0.20 | 1.3% | 0 (0% [0, 0]) | 0 (0% [0, 0]) | 0 | any / any |
| 2.0% | 0.6% | 0.00 / 0.13 | 1.0% | 0 (0% [0, 0]) | 0 (0% [0, 0]) | 0 | any / any |
| 1.0% | 0.4% | 0.00 / 0.08 | 0.6% | 0 (0% [0, 0]) | 0 (0% [0, 0]) | 0 | any / any |
| 0.5% | 0.2% | 0.00 / 0.04 | 0.4% | 0 (0% [0, 0]) | 0 (0% [0, 0]) | 0 | any / any |

### F2_district, Emergency, Western Ghats, monsoon (Jun-Sep) (79 events)

| cap | district-days | days/week median / p90 | chance floor | covered within 1 day | covered same day | district-days per event covered | cost ratio (within 1 day / same day) |
|---|---|---|---|---|---|---|---|
| R0 any cell | 17.2% | 0.08 / 4.16 | 20.6% | 74 (94% [87, 99]) | 66 (84% [74, 91]) | 387 | |
| 10.0% | 3.9% | 0.07 / 0.69 | 6.0% | 31 (39% [28, 51]) | 25 (32% [21, 43]) | 210 | 514 / 540 |
| 6.0% | 2.6% | 0.07 / 0.43 | 4.2% | 24 (30% [20, 42]) | 22 (28% [18, 40]) | 179 | 318 / 742 |
| 4.0% | 1.8% | 0.07 / 0.29 | 3.0% | 19 (24% [14, 35]) | 17 (22% [12, 32]) | 159 | 255 / 255 |
| 3.0% | 1.5% | 0.07 / 0.22 | 2.4% | 17 (22% [12, 32]) | 14 (18% [9, 28]) | 143 | 297 / 198 |
| 2.0% | 1.1% | 0.06 / 0.16 | 1.8% | 13 (16% [8, 27]) | 12 (15% [6, 25]) | 137 | 161 / 322 |
| 1.0% | 0.6% | 0.05 / 0.09 | 1.1% | 10 (13% [5, 22]) | 6 (8% [1, 16]) | 104 | 248 / 124 |
| 0.5% | 0.4% | 0.03 / 0.05 | 0.7% | 7 (9% [1, 17]) | 5 (6% [0, 14]) | 91 | 132 / 397 |

### F2_district, Emergency, Western Ghats, post-monsoon (Oct-Dec) (12 events)

| cap | district-days | days/week median / p90 | chance floor | covered within 1 day | covered same day | district-days per event covered | cost ratio (within 1 day / same day) |
|---|---|---|---|---|---|---|---|
| R0 any cell | 7.6% | 0.03 / 1.81 | 9.5% | 9 (75% [50, 92]) | 9 (75% [50, 92]) | 1,055 | |
| 10.0% | 3.5% | 0.03 / 0.68 | 5.0% | 5 (42% [17, 67]) | 4 (33% [8, 58]) | 889 | 1,262 / 1,010 |
| 6.0% | 2.4% | 0.03 / 0.43 | 3.5% | 4 (33% [8, 58]) | 3 (25% [0, 50]) | 741 | 1,480 / 1,480 |
| 4.0% | 1.7% | 0.03 / 0.30 | 2.6% | 4 (33% [8, 58]) | 3 (25% [0, 50]) | 548 | any / any |
| 3.0% | 1.4% | 0.03 / 0.24 | 2.2% | 4 (33% [8, 58]) | 3 (25% [0, 50]) | 448 | any / any |
| 2.0% | 1.0% | 0.03 / 0.17 | 1.7% | 4 (33% [8, 58]) | 3 (25% [0, 50]) | 324 | any / any |
| 1.0% | 0.6% | 0.01 / 0.09 | 0.9% | 2 (17% [0, 42]) | 2 (17% [0, 42]) | 346 | 302 / 604 |
| 0.5% | 0.3% | 0.01 / 0.06 | 0.6% | 2 (17% [0, 42]) | 2 (17% [0, 42]) | 206 | any / any |

## The one held-out look (pre-declared, one look for this study; the lead's)

### declared

Command (in this worktree, PYTHONPATH=src): `python -m aetherguard.verify.district_cap heldout --rule declared`. confirmed when every held-out share of district-days at a level (region x season x level, June-December 2018-2025) is at most 1.5 x its development value, and at every level and reading the independent slides the rule leaves uncovered compared with R0 on the same days are at most q x 87 + 2.0 x sqrt(87 q (1 - q)).

| condition | development value | allowed |
|---|---|---|
| burden himalaya / monsoon / 1 | 61.66% | at most 92.48% |
| burden himalaya / monsoon / 2 | 56.72% | at most 85.07% |
| burden himalaya / monsoon / 3 | 35.38% | at most 53.07% |
| burden himalaya / post_monsoon / 1 | 31.07% | at most 46.60% |
| burden himalaya / post_monsoon / 2 | 13.05% | at most 19.57% |
| burden himalaya / post_monsoon / 3 | 5.10% | at most 7.64% |
| burden western_ghats / monsoon / 1 | 50.26% | at most 75.39% |
| burden western_ghats / monsoon / 2 | 30.62% | at most 45.92% |
| burden western_ghats / monsoon / 3 | 17.21% | at most 25.82% |
| burden western_ghats / post_monsoon / 1 | 34.60% | at most 51.91% |
| burden western_ghats / post_monsoon / 2 | 15.13% | at most 22.69% |
| burden western_ghats / post_monsoon / 3 | 7.56% | at most 11.35% |
| coverage lost against R0 same_day / 1 | 0.1% of events | 0.1 + 0.7 slides |
| coverage lost against R0 same_day / 2 | 0.0% of events | 0.0 + 0.0 slides |
| coverage lost against R0 same_day / 3 | 0.0% of events | 0.0 + 0.0 slides |
| coverage lost against R0 within_1_day / 1 | 0.0% of events | 0.0 + 0.0 slides |
| coverage lost against R0 within_1_day / 2 | 0.0% of events | 0.0 + 0.0 slides |
| coverage lost against R0 within_1_day / 3 | 0.0% of events | 0.0 + 0.0 slides |

### alternative

Command (in this worktree, PYTHONPATH=src): `python -m aetherguard.verify.district_cap heldout --rule alternative`. confirmed when every held-out share of district-days at a level (region x season x level, June-December 2018-2025) is at most 1.5 x its development value, and at every level and reading the independent slides the rule leaves uncovered compared with R0 on the same days are at most q x 87 + 2.0 x sqrt(87 q (1 - q)).

| condition | development value | allowed |
|---|---|---|
| burden himalaya / monsoon / 1 | 50.08% | at most 75.12% |
| burden himalaya / monsoon / 2 | 25.03% | at most 37.55% |
| burden himalaya / monsoon / 3 | 9.95% | at most 14.93% |
| burden himalaya / post_monsoon / 1 | 31.07% | at most 46.60% |
| burden himalaya / post_monsoon / 2 | 13.05% | at most 19.57% |
| burden himalaya / post_monsoon / 3 | 5.10% | at most 7.64% |
| burden western_ghats / monsoon / 1 | 50.00% | at most 75.00% |
| burden western_ghats / monsoon / 2 | 24.98% | at most 37.47% |
| burden western_ghats / monsoon / 3 | 10.05% | at most 15.07% |
| burden western_ghats / post_monsoon / 1 | 34.60% | at most 51.91% |
| burden western_ghats / post_monsoon / 2 | 15.13% | at most 22.69% |
| burden western_ghats / post_monsoon / 3 | 7.56% | at most 11.35% |
| coverage lost against R0 same_day / 1 | 7.4% of events | 6.4 + 4.9 slides |
| coverage lost against R0 same_day / 2 | 18.5% of events | 16.1 + 7.2 slides |
| coverage lost against R0 same_day / 3 | 37.1% of events | 32.2 + 9.0 slides |
| coverage lost against R0 within_1_day / 1 | 5.1% of events | 4.5 + 4.1 slides |
| coverage lost against R0 within_1_day / 2 | 11.8% of events | 10.2 + 6.0 slides |
| coverage lost against R0 within_1_day / 3 | 29.9% of events | 26.0 + 8.5 slides |

## The held-out look (alternative): CONFIRMED

| condition | held-out | limit | result |
|---|---|---|---|
| burden himalaya / monsoon / 1 | 48.34% | 75.12% | pass |
| burden himalaya / monsoon / 2 | 24.32% | 37.55% | pass |
| burden himalaya / monsoon / 3 | 10.01% | 14.93% | pass |
| burden himalaya / post_monsoon / 1 | 33.29% | 46.60% | pass |
| burden himalaya / post_monsoon / 2 | 14.55% | 19.57% | pass |
| burden himalaya / post_monsoon / 3 | 6.01% | 7.64% | pass |
| burden western_ghats / monsoon / 1 | 51.08% | 75.00% | pass |
| burden western_ghats / monsoon / 2 | 26.37% | 37.47% | pass |
| burden western_ghats / monsoon / 3 | 11.55% | 15.07% | pass |
| burden western_ghats / post_monsoon / 1 | 38.38% | 51.91% | pass |
| burden western_ghats / post_monsoon / 2 | 17.82% | 22.69% | pass |
| burden western_ghats / post_monsoon / 3 | 9.00% | 11.35% | pass |
| coverage lost against R0 same_day / 1 | 10 slides lost | 11.3 | pass |
| coverage lost against R0 same_day / 2 | 16 slides lost | 23.4 | pass |
| coverage lost against R0 same_day / 3 | 27 slides lost | 41.3 | pass |
| coverage lost against R0 within_1_day / 1 | 8 slides lost | 8.6 | pass |
| coverage lost against R0 within_1_day / 2 | 12 slides lost | 16.2 | pass |
| coverage lost against R0 within_1_day / 3 | 22 slides lost | 34.5 | pass |

## Caveats

- Development data only (2007-2017, out of fold, every scored cell); the curve's shares are fitted leave-one-year-out. No held-out number is in the development tables.
- The district levels aggregate today's published cell levels (option A: the card's thresholds and the whole live chain except the blind-escalation rule).
- Catalogue events are recorded where people and roads are, and most landslides are never recorded; coverage counts recorded events only.
- The chance floor is the share of district-days at the level within one day: the coverage an event placed in a random district on a random day would get. Read coverage against it.
- A cost ratio counts every alerted district-day without a recorded event as a false alarm.
- January-May has no held-out panels, so its rows can only ever be development numbers.
- District boundaries: ODbL 1.0; contains information from geoBoundaries (gbOpen) and OpenStreetMap contributors. Nepal uses the 75 districts of 2006, Bhutan its 20 dzongkhags.
