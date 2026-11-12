# Static susceptibility inputs and the combined model v4 (phase 7, W5 and W6)

**v4 is adopted.** adopted: no independent-slide detection is lower than v4_int_ranked's and one is higher.

v4 is the frozen v3-live configuration plus the six rain-intensity inputs of W3 (non-decreasing, lagged 1 IMD day(s)) and nine static inputs, unconstrained: `lc_tree`, `lc_shrub_grass`, `lc_crop`, `lc_bare`, `soil_clay`, `soil_sand`, `soil_coarse`, `ter_steep25`, `ter_steep35`. The criteria were fixed before any result (`docs/superpowers/specs/2026-11-10-aetherguard-w5-static-susceptibility.md` sections 3-4); section 6 is an amendment made after the development result and before any held-out look.

## W5 stage 1: the static group alone (development, year-blocked CV 2007-2017)

| v3 plus | inputs | pooled OOF FA@90 | difference to v3 (95% paired bootstrap) | stage 1 |
|---|---|---|---|---|
| all eleven columns, as first declared | 37 | 0.1062 | -0.0894 [-0.1233, -0.0619] | passed |
| the nine physical columns (amendment) | 35 | 0.1674 | -0.0282 [-0.0572, -0.0007] | passed |

FA@90 is a false-alarm share, so lower is better; v3's is 0.1955. Nearly all of the eleven-column gain came from the built-up share (v3 plus roads and built-up alone: 0.1138). The catalogues place a slide where it was reported, which is where people and roads are, so those two columns predict that a slide gets recorded at least as much as that the ground fails, and the held-out events carry the same bias. They were left out of the hazard model before any held-out look; the cost is that the real effect of road cuts goes with them.

## W6: v4 on development

The reference `C0` reproduces the frozen v3-live FA@90 to 0.0e+00.

| model | inputs | trees | pooled OOF FA@90 (95% CI) |
|---|---|---|---|
| C0 | 26 | 315 | 0.1955 [0.1679, 0.2348] |
| v4 | 41 | 438 | 0.1773 [0.1467, 0.2014] |

v4 - C0 = -0.0182, 95% paired-bootstrap interval [-0.0478, +0.0088] (passed the not-significantly-worse guard).

## The held-out look (pooled 2018-2025, the W1 assembly, taken once)

92 events in 87 independent slides. The deciding comparison is v4 against `v4_int_ranked`, the incumbent v4-int: in each season both rank the scored cell-days by their own calibrated risk and are cut to the Watch+ / Warning+ / Emergency shares v3 realised with the section 11 rules, so the comparison is at equal burden and isolates the nine static inputs. Detection is the number of independent slides with an alert at the level within tolerance (`tolerant`: 10 km, 1 day; `cell_exact`: the same cell and day).

| tolerance | level | v4_int_ranked slides detected | v4 slides detected | difference | not lower | higher |
|---|---|---|---|---|---|---|
| tolerant | Warning+ | 81 | 83 | +2 | yes | yes |
| tolerant | Emergency | 72 | 78 | +6 | yes | yes |
| cell_exact | Warning+ | 63 | 74 | +11 | yes | yes |
| cell_exact | Emergency | 47 | 58 | +11 | yes | yes |

Adoption needs every row "not lower" and at least one "higher".

All levels (v4_int_ranked against v4):

| tolerance | level | v4_int_ranked | v4 | difference |
|---|---|---|---|---|
| tolerant | Watch+ | 84 | 87 | +3 |
| tolerant | Warning+ | 81 | 83 | +2 |
| tolerant | Emergency | 72 | 78 | +6 |
| cell_exact | Watch+ | 81 | 83 | +2 |
| cell_exact | Warning+ | 63 | 74 | +11 |
| cell_exact | Emergency | 47 | 58 | +11 |

Beside it, not deciding: v3 with the section 11 rules and the hysteresis against v4:

| tolerance | level | v3 with rules | v4 | difference |
|---|---|---|---|---|
| tolerant | Watch+ | 85 | 87 | +2 |
| tolerant | Warning+ | 79 | 83 | +4 |
| tolerant | Emergency | 73 | 78 | +5 |
| cell_exact | Watch+ | 79 | 83 | +4 |
| cell_exact | Warning+ | 65 | 74 | +9 |
| cell_exact | Emergency | 48 | 58 | +10 |

Alert cell-days at the matched burden, pooled, on the same scored cell-days (Watch+ / Warning+ / Emergency):

| levels | alert cell-days |
|---|---|
| v3_rules | 25,582,037 / 10,356,868 / 4,275,304 |
| v4_int_ranked | 25,582,037 / 10,356,868 / 4,275,304 |
| v4 | 25,582,037 / 10,356,868 / 4,275,304 |

Burden matching per season (target, then the realised shares; ties at the cuts with the cell-days a straddled tie leaves out in brackets):

| season | target | v4_int_ranked realised | v4 realised | v4_int_ranked ties | v4 ties |
|---|---|---|---|---|---|
| 2018 | 36.18% / 13.48% / 5.11% | 36.18% / 13.48% / 5.11% | 36.18% / 13.48% / 5.11% | 2 (0) ; 1 (0) ; 2 (1) | 1 (0) ; 1 (0) ; 1 (0) |
| 2019 | 44.10% / 17.91% / 7.46% | 44.10% / 17.91% / 7.46% | 44.10% / 17.91% / 7.46% | 2 (0) ; 1 (0) ; 1 (0) | 1 (0) ; 1 (0) ; 1 (0) |
| 2020 | 40.85% / 16.68% / 6.88% | 40.85% / 16.68% / 6.88% | 40.85% / 16.68% / 6.88% | 1 (0) ; 1 (0) ; 1 (0) | 1 (0) ; 1 (0) ; 1 (0) |
| 2021 | 41.68% / 16.92% / 6.90% | 41.68% / 16.92% / 6.90% | 41.68% / 16.92% / 6.90% | 1 (0) ; 2 (0) ; 1 (0) | 1 (0) ; 1 (0) ; 1 (0) |
| 2022 | 40.15% / 16.39% / 6.85% | 40.15% / 16.39% / 6.85% | 40.15% / 16.39% / 6.85% | 1 (0) ; 2 (1) ; 1 (0) | 1 (0) ; 1 (0) ; 1 (0) |
| 2023 | 37.72% / 14.85% / 5.89% | 37.72% / 14.85% / 5.89% | 37.72% / 14.85% / 5.89% | 1 (0) ; 1 (0) ; 1 (0) | 2 (1) ; 1 (0) ; 1 (0) |
| 2024 | 41.26% / 18.06% / 8.23% | 41.26% / 18.06% / 8.23% | 41.26% / 18.06% / 8.23% | 1 (0) ; 1 (0) ; 1 (0) | 1 (0) ; 1 (0) ; 1 (0) |
| 2025 | 42.96% / 17.25% / 6.97% | 42.96% / 17.25% / 6.97% | 42.96% / 17.25% / 6.97% | 2 (0) ; 1 (0) ; 1 (0) | 1 (0) ; 1 (0) ; 1 (0) |

Ground truth after 2018 is very incomplete, so detection counts are relative (between models at equal burden), not absolute. Adoption into the live run is a separate, reviewed step.
