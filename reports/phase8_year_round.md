# Year-round alerts: what a level means outside June-September (phase 8, development)

Development years 2007-2017 only, out of fold, every one of the 36,792 scored cells (`data/processed/alerts/year_round/summary.json`, from `python -m aetherguard.verify.year_round`). Nothing here is wired into the live run. A change of the out-of-season levels would be a model change.

## Answer

- Development (v4 out of fold, today's chain): outside June-September the levels fire less often but each alert cell-day verifies less often than in the monsoon, at every level and in both regions:
- Himalaya, post-monsoon (Oct-Dec) (32 development events): published Watch+ 11.46% and Emergency 0.58% (monsoon 51.81% and 6.21%); hits per 100k alert cell-days Watch+ 0.81 (monsoon 2.72), Warning+ 3.00 (monsoon 6.31), Emergency 10.03 (monsoon 14.50); E/O at Watch+ 6.39 (monsoon 2.62).
- Himalaya, rest of year (Jan-May) (90 development events): published Watch+ 20.01% and Emergency 1.15% (monsoon 51.81% and 6.21%); hits per 100k alert cell-days Watch+ 0.76 (monsoon 2.72), Warning+ 2.25 (monsoon 6.31), Emergency 5.81 (monsoon 14.50); E/O at Watch+ 7.28 (monsoon 2.62).
- Western Ghats, post-monsoon (Oct-Dec) (12 development events): published Watch+ 18.02% and Emergency 0.76% (monsoon 40.29% and 2.20%); hits per 100k alert cell-days Watch+ 0.68 (monsoon 1.75), Warning+ 2.86 (monsoon 6.18), Emergency 8.05 (monsoon 14.75); E/O at Watch+ 1.81 (monsoon 0.98).
- Western Ghats, rest of year (Jan-May) (5 development events): published Watch+ 7.85% and Emergency 0.18% (monsoon 40.29% and 2.20%); hits per 100k alert cell-days Watch+ 0.38 (monsoon 1.75), Warning+ 1.73 (monsoon 6.18), Emergency 8.26 (monsoon 14.75); E/O at Watch+ 2.21 (monsoon 0.98).
- Live: 32 of the 36 published days outside the monsoon were scored by v3 (Emergency on 2.37% of the cell-days). On the first v4 day (2026-11-13) 579 of the 686 Emergency cells were held by the hysteresis from the v3 day before. Replayed with v4 at lead 0, the days 2026-11-08, 2026-11-09, 2026-11-10, 2026-11-11, 2026-11-12, 2026-11-13 give 9, 9, 15, 102, 164, 179 Emergency cells against 96, 102, 137, 637, 985, 719 with v3.
- post-monsoon (Oct-Dec): the declared rule chose `m1.00_uoff`; leave one year out it cuts Watch+ / Warning+ / Emergency published cell-days by 26% / 0% / 0% and loses at most 1 slide(s) at any level and tolerance.
- rest of year (Jan-May): every candidate that cuts the burden loses more than the declared 2 slide(s) at some level and tolerance; today's levels stay.
- Held-out ground truth out of season (W1, licence-clean): 3 slide(s) in post-monsoon (Oct-Dec), 1 slide(s) in rest of year (Jan-May). No held-out test of detection can decide anything with these; the look below decides burden only and carries a detection veto.

## Today's chain by region and season

Published share = cell-days at the level or above after the whole chain (`uncertain_high`, rain cap, hold release, hysteresis). Hits = development events on their own cell and day at the level or above. Precision = hits per 100,000 alert cell-days. E/O = the summed risk of the alert cell-days over the hits (1 would be a calibrated tail; the model's risk is a probability of a catalogued slide per cell-day).

| region and season | events (slides) | level | published share | hits | hits per 100k alert cell-days | E/O |
|---|---|---|---|---|---|---|
| Himalaya, monsoon (Jun-Sep) | 557 (510) | Watch+ | 51.81% | 543 | 2.72 | 2.62 |
| Himalaya, monsoon (Jun-Sep) | 557 (510) | Warning+ | 19.52% | 475 | 6.31 | 2.89 |
| Himalaya, monsoon (Jun-Sep) | 557 (510) | Emergency | 6.21% | 347 | 14.50 | 3.64 |
| Himalaya, post-monsoon (Oct-Dec) | 32 (30) | Watch+ | 11.46% | 27 | 0.81 | 6.39 |
| Himalaya, post-monsoon (Oct-Dec) | 32 (30) | Warning+ | 2.52% | 22 | 3.00 | 7.36 |
| Himalaya, post-monsoon (Oct-Dec) | 32 (30) | Emergency | 0.58% | 17 | 10.03 | 8.90 |
| Himalaya, rest of year (Jan-May) | 90 (88) | Watch+ | 20.01% | 73 | 0.76 | 7.28 |
| Himalaya, rest of year (Jan-May) | 90 (88) | Warning+ | 5.02% | 54 | 2.25 | 9.33 |
| Himalaya, rest of year (Jan-May) | 90 (88) | Emergency | 1.15% | 32 | 5.81 | 14.61 |
| Western Ghats, monsoon (Jun-Sep) | 79 (75) | Watch+ | 40.29% | 76 | 1.75 | 0.98 |
| Western Ghats, monsoon (Jun-Sep) | 79 (75) | Warning+ | 8.25% | 55 | 6.18 | 1.06 |
| Western Ghats, monsoon (Jun-Sep) | 79 (75) | Emergency | 2.20% | 35 | 14.75 | 1.18 |
| Western Ghats, post-monsoon (Oct-Dec) | 12 (12) | Watch+ | 18.02% | 10 | 0.68 | 1.81 |
| Western Ghats, post-monsoon (Oct-Dec) | 12 (12) | Warning+ | 3.00% | 7 | 2.86 | 1.81 |
| Western Ghats, post-monsoon (Oct-Dec) | 12 (12) | Emergency | 0.76% | 5 | 8.05 | 1.63 |
| Western Ghats, rest of year (Jan-May) | 5 (5) | Watch+ | 7.85% | 4 | 0.38 | 2.21 |
| Western Ghats, rest of year (Jan-May) | 5 (5) | Warning+ | 0.86% | 2 | 1.73 | 2.52 |
| Western Ghats, rest of year (Jan-May) | 5 (5) | Emergency | 0.18% | 2 | 8.26 | 1.43 |

Where the published share comes from (share of cell-days):

| region and season | point Watch+ | `uncertain_high` adds (after the rain cap) | published Watch+ | point Emergency | published Emergency | hold inflation Warning+ / Emergency | 7-day rain at or above the rule's minimum | events under the rain minimum |
|---|---|---|---|---|---|---|---|---|
| Himalaya, monsoon (Jun-Sep) | 39.59% | 10.24% | 51.81% | 4.26% | 6.21% | 1.26 / 1.46 | 79.6% | 2.5% |
| Himalaya, post-monsoon (Oct-Dec) | 10.23% | 3.03% | 11.46% | 0.37% | 0.58% | 1.46 / 1.64 | 17.7% | 15.6% |
| Himalaya, rest of year (Jan-May) | 15.12% | 5.25% | 20.01% | 0.73% | 1.15% | 1.41 / 1.61 | 29.2% | 18.9% |
| Western Ghats, monsoon (Jun-Sep) | 29.20% | 8.68% | 40.29% | 1.42% | 2.20% | 1.34 / 1.55 | 77.4% | 1.3% |
| Western Ghats, post-monsoon (Oct-Dec) | 13.17% | 4.38% | 18.02% | 0.46% | 0.76% | 1.40 / 1.67 | 32.5% | 16.7% |
| Western Ghats, rest of year (Jan-May) | 5.31% | 2.34% | 7.85% | 0.11% | 0.18% | 1.47 / 1.70 | 17.1% | 20.0% |

Himalaya by elevation band (Watch+ published):

| season | band | share of cell-days | events | Watch+ share | hits per 100k Watch+ cell-days |
|---|---|---|---|---|---|
| monsoon (Jun-Sep) | below 1,000 m | 46.8% | 187 | 44.3% | 2.30 |
| monsoon (Jun-Sep) | 1,000-2,000 m | 17.4% | 270 | 86.6% | 4.62 |
| monsoon (Jun-Sep) | 2,000-3,000 m | 9.2% | 66 | 78.1% | 2.30 |
| monsoon (Jun-Sep) | 3,000-4,000 m | 8.2% | 25 | 63.2% | 0.95 |
| monsoon (Jun-Sep) | 4,000 m and above | 18.3% | 9 | 19.5% | 0.51 |
| post-monsoon (Oct-Dec) | below 1,000 m | 46.8% | 11 | 9.2% | 0.80 |
| post-monsoon (Oct-Dec) | 1,000-2,000 m | 17.4% | 17 | 21.0% | 1.50 |
| post-monsoon (Oct-Dec) | 2,000-3,000 m | 9.2% | 2 | 19.4% | 0.19 |
| post-monsoon (Oct-Dec) | 3,000-4,000 m | 8.2% | 1 | 14.0% | 0.00 |
| post-monsoon (Oct-Dec) | 4,000 m and above | 18.3% | 1 | 3.0% | 0.00 |
| rest of year (Jan-May) | below 1,000 m | 46.8% | 20 | 13.3% | 0.60 |
| rest of year (Jan-May) | 1,000-2,000 m | 17.4% | 53 | 38.6% | 1.31 |
| rest of year (Jan-May) | 2,000-3,000 m | 9.2% | 13 | 40.7% | 0.61 |
| rest of year (Jan-May) | 3,000-4,000 m | 8.2% | 4 | 28.6% | 0.18 |
| rest of year (Jan-May) | 4,000 m and above | 18.3% | 0 | 5.0% | 0.00 |

## The live days so far (lead 0, published)

| month | model | region | days | Watch+ | Warning+ | Emergency | Emergency held by the hysteresis (cells, summed) | 7-day rain at or above the rain minimum |
|---|---|---|---|---|---|---|---|---|
| 10 | `model_v3_live` | Himalaya | 20 | 22.28% | 5.65% | 1.86% | 3786 | 30.2% |
| 10 | `model_v3_live` | Western Ghats | 20 | 28.48% | 13.18% | 6.28% | 3713 | 50.6% |
| 11 | `model_v3_live` | Himalaya | 12 | 22.72% | 5.13% | 1.75% | 3991 | 32.8% |
| 11 | `model_v3_live` | Western Ghats | 12 | 18.28% | 4.09% | 1.06% | 366 | 38.2% |
| 11 | `model_v4_live` | Himalaya | 4 | 13.55% | 4.09% | 0.73% | 701 | 18.5% |
| 11 | `model_v4_live` | Western Ghats | 4 | 10.27% | 0.37% | 0.00% | 0 | 12.3% |

The same months in the development years (v4 out of fold, today's chain; lowest / median / highest year):

| month | region | Watch+ | Emergency | 7-day rain at or above the rain minimum |
|---|---|---|---|---|
| 10 | Himalaya | 16.20% / 22.82% / 34.05% | 0.33% / 1.39% / 1.97% | 24.9% / 36.2% / 55.6% |
| 10 | Western Ghats | 10.57% / 28.48% / 37.50% | 0.12% / 1.27% / 2.06% | 29.5% / 53.6% / 70.9% |
| 11 | Himalaya | 3.18% / 5.81% / 10.79% | 0.02% / 0.10% / 0.40% | 5.7% / 11.0% / 17.7% |
| 11 | Western Ghats | 5.98% / 17.06% / 42.76% | 0.01% / 0.36% / 3.19% | 11.6% / 25.7% / 73.0% |

The same live days replayed with v4 and with v3 at lead 0 (`reports/phase8_live_replays.json`), Emergency cells of 36,792:

| day | v4 | v3 |
|---|---|---|
| 2026-11-08 | 9 | 96 |
| 2026-11-09 | 9 | 102 |
| 2026-11-10 | 15 | 137 |
| 2026-11-11 | 102 | 637 |
| 2026-11-12 | 164 | 985 |
| 2026-11-13 | 179 | 719 |

## Candidates (out of season only; June-September is today's chain in every candidate)

`m` = the per-season risk scale (thresholds times m), `u` = `uncertain_high` out of season. Hits are independent slides (records within 10 km and a day merged), cell-exact / tolerant (10 km, 1 day).

### post-monsoon (Oct-Dec)

| candidate | Himalaya Watch+ / Warning+ / Emergency | Western Ghats Watch+ / Warning+ / Emergency | Watch+ hits | Warning+ hits | Emergency hits |
|---|---|---|---|---|---|
| `m1.00_uon` | 11.46% / 2.52% / 0.58% | 18.02% / 3.00% / 0.76% | 35 / 37 | 27 / 33 | 20 / 27 |
| `m1.00_uoff` (chosen) | 8.39% / 2.52% / 0.58% | 13.42% / 3.00% / 0.76% | 34 / 37 | 27 / 33 | 20 / 27 |
| `m1.25_uon` | 8.05% / 1.86% / 0.40% | 13.12% / 1.69% / 0.40% | 34 / 37 | 23 / 32 | 16 / 22 |
| `m1.25_uoff` | 6.69% / 1.86% / 0.40% | 10.90% / 1.69% / 0.40% | 33 / 36 | 23 / 32 | 16 / 22 |
| `m1.50_uon` | 7.53% / 1.39% / 0.26% | 12.37% / 1.25% / 0.32% | 32 / 37 | 22 / 30 | 15 / 22 |
| `m1.50_uoff` | 4.81% / 1.39% / 0.26% | 8.06% / 1.25% / 0.32% | 31 / 35 | 22 / 30 | 15 / 22 |
| `m2.00_uon` | 6.76% / 1.16% / 0.21% | 8.91% / 1.17% / 0.08% | 32 / 36 | 22 / 30 | 14 / 21 |
| `m2.00_uoff` | 4.23% / 1.16% / 0.21% | 6.53% / 1.17% / 0.08% | 29 / 33 | 22 / 30 | 14 / 21 |
| `m3.00_uon` | 5.04% / 0.83% / 0.15% | 6.26% / 1.06% / 0.08% | 29 / 36 | 22 / 28 | 13 / 21 |
| `m3.00_uoff` | 3.53% / 0.83% / 0.15% | 3.80% / 1.06% / 0.08% | 29 / 33 | 22 / 28 | 13 / 21 |

Declared rule: at most 1 slide(s) lost against today at every level and tolerance; then the fewest Emergency, Warning+, Watch+ cell-days. Chosen on all 11 years: `m1.00_uoff` (largest loss 1). Leave one year out (the rule re-chosen without the year, then applied to it): published cell-days reduced 26% / 0% / 0% (Watch+ / Warning+ / Emergency); slides lost: tolerant|1 0, tolerant|2 0, tolerant|3 0, cell_exact|1 1, cell_exact|2 0, cell_exact|3 0.

### rest of year (Jan-May)

| candidate | Himalaya Watch+ / Warning+ / Emergency | Western Ghats Watch+ / Warning+ / Emergency | Watch+ hits | Warning+ hits | Emergency hits |
|---|---|---|---|---|---|
| `m1.00_uon` (chosen) | 20.01% / 5.02% / 1.15% | 7.85% / 0.86% / 0.18% | 75 / 87 | 55 / 77 | 33 / 56 |
| `m1.00_uoff` | 14.86% / 5.02% / 1.15% | 5.30% / 0.86% / 0.18% | 72 / 87 | 55 / 77 | 33 / 56 |
| `m1.25_uon` | 14.23% / 3.60% / 0.74% | 5.17% / 0.40% / 0.09% | 73 / 86 | 50 / 71 | 33 / 52 |
| `m1.25_uoff` | 11.35% / 3.60% / 0.74% | 3.82% / 0.40% / 0.09% | 69 / 85 | 50 / 71 | 33 / 52 |
| `m1.50_uon` | 13.47% / 2.70% / 0.45% | 4.88% / 0.31% / 0.07% | 71 / 86 | 47 / 68 | 30 / 49 |
| `m1.50_uoff` | 8.71% / 2.70% / 0.45% | 2.78% / 0.31% / 0.07% | 66 / 85 | 47 / 68 | 30 / 49 |
| `m2.00_uon` | 12.14% / 2.20% / 0.35% | 3.21% / 0.29% / 0.02% | 71 / 86 | 42 / 67 | 26 / 43 |
| `m2.00_uoff` | 7.64% / 2.20% / 0.35% | 2.02% / 0.29% / 0.02% | 63 / 85 | 42 / 67 | 26 / 43 |
| `m3.00_uon` | 9.11% / 1.49% / 0.22% | 2.06% / 0.26% / 0.02% | 64 / 84 | 35 / 61 | 26 / 38 |
| `m3.00_uoff` | 6.11% / 1.49% / 0.22% | 1.04% / 0.26% / 0.02% | 60 / 82 | 35 / 61 | 26 / 38 |

Declared rule: at most 2 slide(s) lost against today at every level and tolerance; then the fewest Emergency, Warning+, Watch+ cell-days. Chosen on all 11 years: `m1.00_uon` (largest loss 0). Leave one year out (the rule re-chosen without the year, then applied to it): published cell-days reduced 5% / 0% / 0% (Watch+ / Warning+ / Emergency); slides lost: tolerant|1 0, tolerant|2 0, tolerant|3 0, cell_exact|1 2, cell_exact|2 0, cell_exact|3 0.

## Ground truth outside the monsoon (independent slides)

| set | Himalaya monsoon (Jun-Sep) | Himalaya post-monsoon (Oct-Dec) | Himalaya rest of year (Jan-May) | Western Ghats monsoon (Jun-Sep) | Western Ghats post-monsoon (Oct-Dec) | Western Ghats rest of year (Jan-May) |
|---|---|---|---|---|---|---|
| development 2007-2017 | 510 | 30 | 88 | 75 | 12 | 5 |
| held-out W1 2018-2025 (deciding) | 46 | 1 | 1 | 37 | 2 | 0 |
| held-out v2 without BIPAD | 46 | 1 | 1 | 37 | 2 | 0 |
| held-out v2 with BIPAD (unlicensed, local only, not deciding) | 1145 | 81 | 86 | 37 | 2 | 0 |

What a held-out look could decide:

- post-monsoon (Oct-Dec): 3 W1 slide(s). If none were lost, the loss could still be up to 63% of slides (one-sided 95%). A treatment losing 10% of slides would lose at least one of them with chance 27%. With BIPAD (83 slides) the bound would be 3.5%. Held-out panels: yes (alerts/v4_seasons).
- rest of year (Jan-May): 1 W1 slide(s). If none were lost, the loss could still be up to 95% of slides (one-sided 95%). A treatment losing 10% of slides would lose at least one of them with chance 10%. With BIPAD (86 slides) the bound would be 3.4%. Held-out panels: none (IMERG half-hourly files for January-May 2018-2025 are not on disk).

## The held-out look (declared before any held-out number; the lead's, once)

Command: `python -m aetherguard.verify.year_round heldout`. Season: post-monsoon (Oct-Dec) 2018-2025 on `alerts/v4_seasons`. Treatment `m1.00_uoff` (`levels_year_round.json`, sha256 `efe08fe42e3cc9c0...`).

1. Burden (decides): in every region and level below, the held-out published share falls by at least 50% of the development reduction, paired with today's levels on the same days:

| region and level | development today | development treatment | development reduction | required held-out reduction |
|---|---|---|---|---|
| Himalaya Watch+ | 11.46% | 8.39% | 27% | 13% |
| Western Ghats Watch+ | 18.02% | 13.42% | 26% | 13% |

2. June-September published levels identical cell-day by cell-day (a check of the construction).
3. Detection veto, W1 (3 slide(s)): every W1 slide of the season that today's levels detect at a level and tolerance is detected by the treatment at that level and tolerance (no slide lost). It cannot show that detection is not worse (section above); it only stops adoption if a slide is lost.
4. Beside, not deciding: the same paired detection on assembly v2 with and without BIPAD.

Adopt only if 1-3 pass. Adoption still changes published levels (a model change): it needs a reviewed wiring step and the user's yes. January-May has no held-out panels and stays development-only.

## The held-out look: ADOPT by the declared rule

| condition | held-out | required | passed |
|---|---|---|---|
| burden himalaya|Watch+ | 26% | 13% | True |
| burden western_ghats|Watch+ | 25% | 13% | True |
| June-September identical | 0 differing | 0 | True |
| detection veto (W1) | lost {'tolerant|1': 0, 'tolerant|2': 0, 'tolerant|3': 0, 'cell_exact|1': 0, 'cell_exact|2': 0, 'cell_exact|3': 0} | none lost | True |

heldout_w1: 3 slide(s); today {'tolerant|1': 3, 'tolerant|2': 3, 'tolerant|3': 2, 'cell_exact|1': 3, 'cell_exact|2': 2, 'cell_exact|3': 0}, treatment {'tolerant|1': 3, 'tolerant|2': 3, 'tolerant|3': 2, 'cell_exact|1': 3, 'cell_exact|2': 2, 'cell_exact|3': 0}.

heldout_v2_all_unlicensed_included: 83 slide(s); today {'tolerant|1': 73, 'tolerant|2': 71, 'tolerant|3': 66, 'cell_exact|1': 71, 'cell_exact|2': 67, 'cell_exact|3': 61}, treatment {'tolerant|1': 73, 'tolerant|2': 71, 'tolerant|3': 66, 'cell_exact|1': 71, 'cell_exact|2': 67, 'cell_exact|3': 61}.

heldout_v2_licence_clean: 3 slide(s); today {'tolerant|1': 3, 'tolerant|2': 3, 'tolerant|3': 2, 'cell_exact|1': 3, 'cell_exact|2': 2, 'cell_exact|3': 0}, treatment {'tolerant|1': 3, 'tolerant|2': 3, 'tolerant|3': 2, 'cell_exact|1': 3, 'cell_exact|2': 2, 'cell_exact|3': 0}.

## Caveats

- Detection counts what the catalogues recorded. They miss most landslides and report them where people live and when people look; out-of-season slides may be reported less often than monsoon slides, which would make the out-of-season precision and E/O look worse than they are. The catalogues cannot separate this from a model that over-predicts out of season.
- Out of the monsoon the development events are few (counts in the tables), so every out-of-season detection number has a wide interval; the leave-one-year-out estimate is the honest one for the selected rule.
- Tolerant matching (10 km, 1 day) has a high chance floor at Watch+.
- The development panels have no blind-escalation rule (it needs the live IMD comparison); January-May starts each year cold (no hysteresis carried over New Year).
- The live days so far are 2026-10-09 onwards, mostly scored by v3; one month of live weather cannot separate weather from a train/serve gap.
