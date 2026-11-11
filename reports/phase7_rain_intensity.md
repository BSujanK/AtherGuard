# Rain-intensity inputs: challenger v4-int (phase 7, W3)

**v4-int is adopted.** adopted: no independent-slide detection is lower than v3_ranked's and one is higher.

v4-int is the frozen v3-live configuration (same folds, seeds, hyper-parameters, 20-member ensemble, per-region isotonic calibration and monotone constraints) plus six rain-intensity inputs from the half-hourly IMERG Late run, each constrained non-decreasing: `iint_max1h_1`, `iint_max3h_1`, `iint_max6h_1`, `iint_max3h_max3d`, `iint_max6h_max3d`, `iint_wet_hours_1`. Nothing else differs. The intensity inputs lag the target day by 1 IMD day(s), as the train-serve gap study declared (development samples and season panels alike). The criterion was fixed before any result (`docs/superpowers/specs/2026-11-06-aetherguard-w3-rain-intensity.md` section 3 and its amendment).

## Stage 1: development (year-blocked CV 2007-2017)

The reference `C0` is the v3-live refit; it reproduces the frozen pooled OOF FA@90 to 0.0e+00 with the same tree count.

| model | inputs | trees | pooled OOF FA@90 (95% CI) |
|---|---|---|---|
| C0 | 26 | 315 | 0.1955 [0.1679, 0.2348] |
| v4_int | 32 | 355 | 0.1901 [0.1723, 0.2290] |

FA@90 is a false-alarm share, so lower is better. v4_int - C0 = -0.0054, 95% paired-bootstrap interval [-0.0145, +0.0149]. Rule: pooled OOF FA@90 is a false-alarm share (lower is better); passes when the paired bootstrap interval of v4_int - C0 has lower bound <= 0, i.e. v4-int is not significantly worse. Stage 1 **passed** (includes zero).

## Stage 2: held-out (pooled 2018-2025, the W1 assembly)

92 events in 87 independent slides (records within 10 km and a day are one slide). The deciding comparison is v4-int against `v3_ranked`: in each season both rank the scored cell-days by their own calibrated risk (ties by the panel's raw score) and are cut to the Watch+ / Warning+ / Emergency shares v3 realised in that season with the section 11 rules, so the comparison is at equal burden and isolates the six features. Detection is the number of independent slides with an alert at the level within tolerance (`tolerant`: 10 km, 1 day; `cell_exact`: the same cell and day).

| tolerance | level | v3_ranked slides detected | v4-int slides detected | difference | not lower | higher |
|---|---|---|---|---|---|---|
| tolerant | Warning+ | 80 | 81 | +1 | yes | yes |
| tolerant | Emergency | 72 | 72 | +0 | yes | no |
| cell_exact | Warning+ | 61 | 63 | +2 | yes | yes |
| cell_exact | Emergency | 46 | 47 | +1 | yes | yes |

Adoption needs every row "not lower" and at least one "higher".

All levels, independent slides detected (v3_ranked against v4-int):

| tolerance | level | v3_ranked | v4-int | difference |
|---|---|---|---|---|
| tolerant | Watch+ | 85 | 84 | -1 |
| tolerant | Warning+ | 80 | 81 | +1 |
| tolerant | Emergency | 72 | 72 | +0 |
| cell_exact | Watch+ | 79 | 81 | +2 |
| cell_exact | Warning+ | 61 | 63 | +2 |
| cell_exact | Emergency | 46 | 47 | +1 |

Beside it, not deciding: v3 with the section 11 rules and the hysteresis (its own, rule-based levels at the same burden) against v4-int:

| tolerance | level | v3 with rules | v4-int | difference |
|---|---|---|---|---|
| tolerant | Watch+ | 85 | 84 | -1 |
| tolerant | Warning+ | 79 | 81 | +2 |
| tolerant | Emergency | 73 | 72 | -1 |
| cell_exact | Watch+ | 79 | 81 | +2 |
| cell_exact | Warning+ | 65 | 63 | -2 |
| cell_exact | Emergency | 48 | 47 | -1 |

Alert cell-days at the matched burden, pooled, all three on the same scored cell-days (Watch+ / Warning+ / Emergency):

| levels | alert cell-days |
|---|---|
| v3_rules | 25,582,037 / 10,356,868 / 4,275,304 |
| v3_ranked | 25,582,037 / 10,356,868 / 4,275,304 |
| v4_int | 25,582,037 / 10,356,868 / 4,275,304 |
| v3_rules, counted as the W1 report counts them (held levels included) | 25,582,037 / 10,356,868 / 4,275,304 |

Burden matching per season: target (v3 with rules realised) and the realised shares of v3_ranked and v4-int, Watch+ / Warning+ / Emergency. Cell-days tied on both calibrated risk and raw score are ordered by a seeded key of (cell, day); the last two columns give, at each cut, the cell-days tied with the last one taken, and in brackets how many of them the cut leaves out (a straddled tie):

| season | target | v3_ranked realised | v4-int realised | v3_ranked ties at the cuts | v4-int ties at the cuts |
|---|---|---|---|---|---|
| 2018 | 36.18% / 13.48% / 5.11% | 36.18% / 13.48% / 5.11% | 36.18% / 13.48% / 5.11% | 1 (0) ; 2 (0) ; 1 (0) | 2 (0) ; 1 (0) ; 2 (1) |
| 2019 | 44.10% / 17.91% / 7.46% | 44.10% / 17.91% / 7.46% | 44.10% / 17.91% / 7.46% | 2 (0) ; 1 (0) ; 1 (0) | 2 (0) ; 1 (0) ; 1 (0) |
| 2020 | 40.85% / 16.68% / 6.88% | 40.85% / 16.68% / 6.88% | 40.85% / 16.68% / 6.88% | 1 (0) ; 1 (0) ; 1 (0) | 1 (0) ; 1 (0) ; 1 (0) |
| 2021 | 41.68% / 16.92% / 6.90% | 41.68% / 16.92% / 6.90% | 41.68% / 16.92% / 6.90% | 7 (3) ; 1 (0) ; 1 (0) | 1 (0) ; 2 (0) ; 1 (0) |
| 2022 | 40.15% / 16.39% / 6.85% | 40.15% / 16.39% / 6.85% | 40.15% / 16.39% / 6.85% | 1 (0) ; 1 (0) ; 1 (0) | 1 (0) ; 2 (1) ; 1 (0) |
| 2023 | 37.72% / 14.85% / 5.89% | 37.72% / 14.85% / 5.89% | 37.72% / 14.85% / 5.89% | 1 (0) ; 1 (0) ; 1 (0) | 1 (0) ; 1 (0) ; 1 (0) |
| 2024 | 41.26% / 18.06% / 8.23% | 41.26% / 18.06% / 8.23% | 41.26% / 18.06% / 8.23% | 1 (0) ; 1 (0) ; 1 (0) | 1 (0) ; 1 (0) ; 1 (0) |
| 2025 | 42.96% / 17.25% / 6.97% | 42.96% / 17.25% / 6.97% | 42.96% / 17.25% / 6.97% | 1 (0) ; 2 (1) ; 1 (0) | 2 (0) ; 1 (0) ; 1 (0) |

Share of scored held-out cell-days with a NaN intensity input, per season (a NaN is learned as missing, never zero):

| season | iint_max1h_1 | iint_max3h_1 | iint_max6h_1 | iint_max3h_max3d | iint_max6h_max3d | iint_wet_hours_1 |
|---|---|---|---|---|---|---|
| 2018 | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% |
| 2019 | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% |
| 2020 | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% |
| 2021 | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% |
| 2022 | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% |
| 2023 | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% |
| 2024 | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% |
| 2025 | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% |

Ground truth after 2018 is very incomplete, so detection counts are relative (between models at equal burden), not absolute.
