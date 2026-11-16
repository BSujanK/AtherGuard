# Forecast leads on v4: the held-out look (W7)

**v4 forecast leads (candidate a): NOT ADOPTED** under the rule declared before the look (12 rows: leads 1-3, tolerant and cell-exact, Warning+ and Emergency independent-slide detection not lower than the incumbent's in any row and higher in at least one). 9 of 12 rows are higher and 2 are lower (lead 2 tolerant Warning+ 22 -> 21; lead 3 tolerant Warning+ 22 -> 21). The rule was not changed after the look; the incumbent (v3 on forecast rain) stays. Independent W1 slides on the target days: lead 1 22, lead 2 22, lead 3 22, so one slide moves a row.

Taken once (2026-11-16T16:58:01+00:00); spec docs/superpowers/specs/2026-11-14-aetherguard-leads-v4.md section 5, amendments 1-2; preflight reports/phase8_leads_v4_preflight.md. Research prototype, not validated for issuing real public warnings.

## Deciding: licence-clean W1 assembly, June-September 2021-2024

Each lead's candidate levels are burden-matched per season to the incumbent lead's realised Watch+ / Warning+ / Emergency shares. Lead L detects a slide of day X when the forecast issued on X-L puts a cell within tolerance at the level.

| lead | tolerance | level | slides detected, incumbent (v3) | slides detected, candidate | slides | alert cell-days, incumbent | alert cell-days, candidate |
|---|---|---|---|---|---|---|---|
| 1 | tolerant | Watch+ | 22 | 22 | 22 | 9,879,332 | 9,879,332 |
| 1 | tolerant | Warning+ | 22 | 22 | 22 | 3,980,404 | 3,980,404 |
| 1 | tolerant | Emergency | 19 | 21 | 22 | 1,519,172 | 1,519,172 |
| 1 | cell_exact | Watch+ | 20 | 21 | 22 | 9,879,332 | 9,879,332 |
| 1 | cell_exact | Warning+ | 16 | 20 | 22 | 3,980,404 | 3,980,404 |
| 1 | cell_exact | Emergency | 13 | 14 | 22 | 1,519,172 | 1,519,172 |
| 2 | tolerant | Watch+ | 22 | 22 | 22 | 9,979,959 | 9,979,959 |
| 2 | tolerant | Warning+ | 22 | 21 | 22 | 3,973,793 | 3,973,793 |
| 2 | tolerant | Emergency | 18 | 21 | 22 | 1,468,339 | 1,468,339 |
| 2 | cell_exact | Watch+ | 21 | 21 | 22 | 9,979,959 | 9,979,959 |
| 2 | cell_exact | Warning+ | 15 | 18 | 22 | 3,973,793 | 3,973,793 |
| 2 | cell_exact | Emergency | 8 | 13 | 22 | 1,468,339 | 1,468,339 |
| 3 | tolerant | Watch+ | 22 | 22 | 22 | 9,606,050 | 9,606,050 |
| 3 | tolerant | Warning+ | 22 | 21 | 22 | 3,743,287 | 3,743,287 |
| 3 | tolerant | Emergency | 18 | 21 | 22 | 1,464,847 | 1,464,847 |
| 3 | cell_exact | Watch+ | 21 | 21 | 22 | 9,606,050 | 9,606,050 |
| 3 | cell_exact | Warning+ | 17 | 19 | 22 | 3,743,287 | 3,743,287 |
| 3 | cell_exact | Emergency | 11 | 15 | 22 | 1,464,847 | 1,464,847 |

### The 12 deciding rows

| lead | tolerance | level | incumbent | candidate | not lower | higher |
|---|---|---|---|---|---|---|
| 1 | tolerant | Warning+ | 22 | 22 | yes | no |
| 1 | tolerant | Emergency | 19 | 21 | yes | yes |
| 1 | cell_exact | Warning+ | 16 | 20 | yes | yes |
| 1 | cell_exact | Emergency | 13 | 14 | yes | yes |
| 2 | tolerant | Warning+ | 22 | 21 | NO | no |
| 2 | tolerant | Emergency | 18 | 21 | yes | yes |
| 2 | cell_exact | Warning+ | 15 | 18 | yes | yes |
| 2 | cell_exact | Emergency | 8 | 13 | yes | yes |
| 3 | tolerant | Warning+ | 22 | 21 | NO | no |
| 3 | tolerant | Emergency | 18 | 21 | yes | yes |
| 3 | cell_exact | Warning+ | 17 | 19 | yes | yes |
| 3 | cell_exact | Emergency | 11 | 15 | yes | yes |

Decision: adopt = false.

## Beside it, NOT deciding: held-out assembly v2

Reported as the spec declares; it decides nothing. The BIPAD Nepal register has no stated licence: its rows stay local and only these derived numbers are shown.

### assembly v2, all records (includes the BIPAD Nepal register: no stated licence, rows local only)

Independent slides on the target days: lead 1 517, lead 2 517, lead 3 518.

| lead | tolerance | level | slides detected, incumbent (v3) | slides detected, candidate | slides | alert cell-days, incumbent | alert cell-days, candidate |
|---|---|---|---|---|---|---|---|
| 1 | tolerant | Watch+ | 516 | 517 | 517 | 9,879,332 | 9,879,332 |
| 1 | tolerant | Warning+ | 512 | 515 | 517 | 3,980,404 | 3,980,404 |
| 1 | tolerant | Emergency | 488 | 506 | 517 | 1,519,172 | 1,519,172 |
| 1 | cell_exact | Watch+ | 512 | 514 | 517 | 9,879,332 | 9,879,332 |
| 1 | cell_exact | Warning+ | 438 | 484 | 517 | 3,980,404 | 3,980,404 |
| 1 | cell_exact | Emergency | 277 | 382 | 517 | 1,519,172 | 1,519,172 |
| 2 | tolerant | Watch+ | 515 | 517 | 517 | 9,979,959 | 9,979,959 |
| 2 | tolerant | Warning+ | 511 | 513 | 517 | 3,973,793 | 3,973,793 |
| 2 | tolerant | Emergency | 485 | 506 | 517 | 1,468,339 | 1,468,339 |
| 2 | cell_exact | Watch+ | 511 | 515 | 517 | 9,979,959 | 9,979,959 |
| 2 | cell_exact | Warning+ | 451 | 486 | 517 | 3,973,793 | 3,973,793 |
| 2 | cell_exact | Emergency | 270 | 394 | 517 | 1,468,339 | 1,468,339 |
| 3 | tolerant | Watch+ | 514 | 518 | 518 | 9,606,050 | 9,606,050 |
| 3 | tolerant | Warning+ | 509 | 511 | 518 | 3,743,287 | 3,743,287 |
| 3 | tolerant | Emergency | 477 | 504 | 518 | 1,464,847 | 1,464,847 |
| 3 | cell_exact | Watch+ | 510 | 513 | 518 | 9,606,050 | 9,606,050 |
| 3 | cell_exact | Warning+ | 439 | 484 | 518 | 3,743,287 | 3,743,287 |
| 3 | cell_exact | Emergency | 269 | 379 | 518 | 1,464,847 | 1,464,847 |

### assembly v2 without the BIPAD register

Independent slides on the target days: lead 1 22, lead 2 22, lead 3 22.

| lead | tolerance | level | slides detected, incumbent (v3) | slides detected, candidate | slides | alert cell-days, incumbent | alert cell-days, candidate |
|---|---|---|---|---|---|---|---|
| 1 | tolerant | Watch+ | 22 | 22 | 22 | 9,879,332 | 9,879,332 |
| 1 | tolerant | Warning+ | 22 | 22 | 22 | 3,980,404 | 3,980,404 |
| 1 | tolerant | Emergency | 19 | 21 | 22 | 1,519,172 | 1,519,172 |
| 1 | cell_exact | Watch+ | 20 | 21 | 22 | 9,879,332 | 9,879,332 |
| 1 | cell_exact | Warning+ | 16 | 20 | 22 | 3,980,404 | 3,980,404 |
| 1 | cell_exact | Emergency | 13 | 14 | 22 | 1,519,172 | 1,519,172 |
| 2 | tolerant | Watch+ | 22 | 22 | 22 | 9,979,959 | 9,979,959 |
| 2 | tolerant | Warning+ | 22 | 21 | 22 | 3,973,793 | 3,973,793 |
| 2 | tolerant | Emergency | 18 | 21 | 22 | 1,468,339 | 1,468,339 |
| 2 | cell_exact | Watch+ | 21 | 21 | 22 | 9,979,959 | 9,979,959 |
| 2 | cell_exact | Warning+ | 15 | 18 | 22 | 3,973,793 | 3,973,793 |
| 2 | cell_exact | Emergency | 8 | 13 | 22 | 1,468,339 | 1,468,339 |
| 3 | tolerant | Watch+ | 22 | 22 | 22 | 9,606,050 | 9,606,050 |
| 3 | tolerant | Warning+ | 22 | 21 | 22 | 3,743,287 | 3,743,287 |
| 3 | tolerant | Emergency | 18 | 21 | 22 | 1,464,847 | 1,464,847 |
| 3 | cell_exact | Watch+ | 21 | 21 | 22 | 9,606,050 | 9,606,050 |
| 3 | cell_exact | Warning+ | 17 | 19 | 22 | 3,743,287 | 3,743,287 |
| 3 | cell_exact | Emergency | 11 | 15 | 22 | 1,464,847 | 1,464,847 |

### assembly v2, India only

Independent slides on the target days: lead 1 22, lead 2 22, lead 3 22.

| lead | tolerance | level | slides detected, incumbent (v3) | slides detected, candidate | slides | alert cell-days, incumbent | alert cell-days, candidate |
|---|---|---|---|---|---|---|---|
| 1 | tolerant | Watch+ | 22 | 22 | 22 | 9,879,332 | 9,879,332 |
| 1 | tolerant | Warning+ | 22 | 22 | 22 | 3,980,404 | 3,980,404 |
| 1 | tolerant | Emergency | 20 | 22 | 22 | 1,519,172 | 1,519,172 |
| 1 | cell_exact | Watch+ | 21 | 22 | 22 | 9,879,332 | 9,879,332 |
| 1 | cell_exact | Warning+ | 17 | 21 | 22 | 3,980,404 | 3,980,404 |
| 1 | cell_exact | Emergency | 14 | 15 | 22 | 1,519,172 | 1,519,172 |
| 2 | tolerant | Watch+ | 22 | 22 | 22 | 9,979,959 | 9,979,959 |
| 2 | tolerant | Warning+ | 22 | 22 | 22 | 3,973,793 | 3,973,793 |
| 2 | tolerant | Emergency | 19 | 22 | 22 | 1,468,339 | 1,468,339 |
| 2 | cell_exact | Watch+ | 22 | 22 | 22 | 9,979,959 | 9,979,959 |
| 2 | cell_exact | Warning+ | 16 | 19 | 22 | 3,973,793 | 3,973,793 |
| 2 | cell_exact | Emergency | 9 | 14 | 22 | 1,468,339 | 1,468,339 |
| 3 | tolerant | Watch+ | 22 | 22 | 22 | 9,606,050 | 9,606,050 |
| 3 | tolerant | Warning+ | 22 | 22 | 22 | 3,743,287 | 3,743,287 |
| 3 | tolerant | Emergency | 19 | 22 | 22 | 1,464,847 | 1,464,847 |
| 3 | cell_exact | Watch+ | 22 | 22 | 22 | 9,606,050 | 9,606,050 |
| 3 | cell_exact | Warning+ | 18 | 20 | 22 | 3,743,287 | 3,743,287 |
| 3 | cell_exact | Emergency | 12 | 16 | 22 | 1,464,847 | 1,464,847 |

## Caveats

- Low power: 22, 22, 22 independent W1 slides (leads 1, 2, 3), 22, 22, 22 records, 2, 2, 2 outside the target days. A single slide decides a row, in either direction.
- The incumbent leads' burden is high (Watch+ about half of the scored cell-days), so tolerant matching has a high chance floor; the cell-exact rows are the stronger test.
- Only 2021-2024 have archived forecasts; 2018-2020 (most of the held-out slides) could not be used. 2021 is the fit season of the GFS intensity maps (rain only). Leads 2-3 use the GFS fallback where ECMWF has no archive (2021-2022, part of 2023).
- Ground truth after 2018 is very incomplete; precision is relative.
