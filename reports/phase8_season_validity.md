# Season of validity of the live alert chain (phase 8, a measurement)

**Recommendation:** declare June-September the season of validity of the published alert chain and publish a visible flag on every lead whose date falls outside it (no suppression). Flag: `outside_validated_season`. Alternative: a year-round study: post-model rules and alert parameters chosen on twelve-month development panels, a per-month calibration check, and a held-out look that includes January-May; it needs the out-of-season events listed here, which are few.

## Which months each part of the chain was built and tested on

- Model training and cross-validation: every calendar day of 2007-2017 (positives, matched negatives and universe negatives year-round; configs/splits.yaml day_splits).
- Post-model rules (section 11) and alert-engine parameters: panels of months 6-9 only.
- Held-out look (v4 adoption): season panels of months 6-12 of 2018-2025.
- Live run: every day of the year.

## Development positives (2007-2017) by month

| region | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | outside June-September |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| himalaya (cell-days) | 6 | 12 | 12 | 43 | 24 | 110 | 202 | 169 | 89 | 30 | 2 | 0 | 129 |
| western_ghats (cell-days) | 0 | 0 | 0 | 3 | 3 | 36 | 24 | 30 | 11 | 8 | 8 | 2 | 24 |
| himalaya (catalogue events) | 6 | 12 | 12 | 45 | 25 | 113 | 212 | 174 | 95 | 30 | 2 | 0 | 132 |
| western_ghats (catalogue events) | 0 | 0 | 0 | 3 | 3 | 37 | 26 | 33 | 11 | 9 | 8 | 2 | 25 |

Development sample rows by kind (the negatives cover every month):

| kind | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| negative | 54 | 127 | 135 | 455 | 263 | 1461 | 2253 | 1967 | 985 | 394 | 128 | 18 |
| positive | 6 | 12 | 12 | 46 | 27 | 146 | 226 | 199 | 100 | 38 | 10 | 2 |
| universe | 32040 | 30822 | 34143 | 33031 | 33918 | 33297 | 34091 | 34194 | 32935 | 34167 | 33152 | 34210 |

## v4 out of fold on development, by month (card raw thresholds)

| quantity | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| positives | 6 | 11 | 11 | 45 | 24 | 139 | 220 | 191 | 97 | 35 | 8 | 2 |
| watch+ detected | 4 | 9 | 6 | 36 | 20 | 124 | 215 | 181 | 93 | 30 | 4 | 2 |
| warning+ detected | 3 | 7 | 4 | 26 | 14 | 105 | 185 | 140 | 81 | 23 | 3 | 1 |
| emergency+ detected | 3 | 4 | 2 | 16 | 6 | 74 | 135 | 78 | 55 | 19 | 3 | 0 |
| watch+ universe share | 5.94% | 8.29% | 9.59% | 16.95% | 22.27% | 32.16% | 39.86% | 37.56% | 31.25% | 18.85% | 7.11% | 4.29% |
| warning+ universe share | 1.14% | 1.58% | 1.79% | 3.46% | 5.17% | 10.24% | 15.07% | 13.36% | 9.18% | 3.83% | 0.94% | 0.66% |
| emergency+ universe share | 0.24% | 0.35% | 0.40% | 0.68% | 0.90% | 2.61% | 4.29% | 3.82% | 2.33% | 0.78% | 0.19% | 0.14% |

| level | June-September: detected / positives, universe share | other months: detected / positives, universe share |
|---|---|---|
| watch+ | 613 / 647, 35.27% | 111 / 142, 11.74% |
| warning+ | 511 / 647, 12.00% | 81 / 142, 2.34% |
| emergency+ | 342 / 647, 3.28% | 53 / 142, 0.46% |

## v4 point-level shares of the held-out season panels by month (2018-2025, risks only)

| month | cell-days | Watch+ | Warning+ | Emergency |
|---|---|---|---|---|
| 6 | 8,830,080 | 32.24% | 10.87% | 2.89% |
| 7 | 9,124,416 | 41.35% | 17.24% | 5.27% |
| 8 | 9,124,416 | 39.15% | 15.10% | 4.21% |
| 9 | 8,830,080 | 33.53% | 11.09% | 2.94% |
| 10 | 9,124,416 | 22.04% | 5.01% | 1.12% |
| 11 | 8,830,080 | 9.20% | 1.57% | 0.26% |
| 12 | 9,124,416 | 5.89% | 0.83% | 0.14% |

## Published live days, lead 0, by month and model

| month | model | days | Watch+ | Warning+ | Emergency |
|---|---|---|---|---|---|
| 10 | `data/processed/hazard/model_v3_live` | 20 | 23.64% | 7.30% | 2.83% |
| 11 | `data/processed/hazard/model_v3_live` | 12 | 21.75% | 4.90% | 1.60% |
| 11 | `data/processed/hazard/model_v4_live` | 1 | 18.11% | 6.17% | 1.86% |

## Reading

- The model is not extrapolating in the strict sense: it was trained on every month. But outside June-September the development positives are few (himalaya 129, western_ghats 24 cell-days, against himalaya 570, western_ghats 101 inside).
- The rest of the published chain (rain trigger, hold windows, ensemble agreement, blind-hold limit, hysteresis and `uncertain_high` parameters) was chosen on June-September panels only, and the held-out look never covered January-May. A level published outside June-September is therefore a level of a chain that was not developed or tested there.
- Live Emergency share in month 11: `data/processed/hazard/model_v3_live` 1.60% over 12 day(s); `data/processed/hazard/model_v4_live` 1.86% over 1 day(s); the same month in development (v4 out of fold, universe): 0.19%; in the held-out season panels (v4 point level): 0.26%. On 2026-11-13, 579 of the 686 Emergency cells were held by the hysteresis from the day before, not at Emergency on the day's own risk. The live days of one month with a rain event are too few to separate weather from a train/serve gap; the size of the difference is on record, not explained.
- Hence the flag `outside_validated_season` on every lead dated outside months 6-9 (run.json `season_of_validity` and each lead's `outside_validated_season`, and the bulletin), and no suppression: the alert stands, the reader is told it is outside the validated season.

## Caveats

- Development numbers are out of fold (year-blocked CV 2007-2017) but every month has few events outside June-September, so the monthly detection there has wide uncertainty (the counts are given).
- Detection counts what the catalogues recorded; the catalogues miss most landslides and report them where people live.
- Held-out season shares are point levels of the model (risk against the card's thresholds of the region), without the post-model rules or the hysteresis the live run adds; they read risks only, never an event.
- Live shares come from the published run.json of each day; the days before 2026-11-13 were scored by v3, from 2026-11-13 by v4.
