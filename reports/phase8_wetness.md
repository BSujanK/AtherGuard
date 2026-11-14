# Antecedent wetness inputs and the combined model v5 (phase 8, W4): development

**Status: seasons scored: 0 of 8.** Next: `python -m aetherguard.hazard.v4_combined seasons --config configs/hazard_v5.yaml`.

Criteria fixed before any model result: `docs/superpowers/specs/2026-11-13-aetherguard-w4-wetness.md`. Development only (year-blocked CV 2007-2017, v3's folds and seeds); no 2018-2025 outcome was read for anything below.

## Source probe

Chosen: iwet: bucket water balance on the IMERG Late store, lag 2 IMD days (`reports/phase8_wetness_sources_probe.md`).

| candidate | verdict |
|---|---|
| SMAP L4 surface and root-zone soil moisture (SPL4SMGP / SPL4SMAU) | fails (a) |
| ERA5 volumetric soil water, ARCO-ERA5 public store (training) with ERA5T (live) | passes (a), (c), (d), (e); (b) only with a declared lag of at least 7 days, measured once |
| ERA5 (training) with ECMWF IFS open-data analysis `vsw` (live, 12 UTC of D-1) | fails (c) |
| ERA5 (training) with NOAA GFS analysis SOILW (live, 00 UTC of D) | fails (c) |
| GLDAS Noah 2.1 (main and Early Product), GLDAS CLSM 2.2, FLDAS | fails (b) |
| MERRA-2 land (NASA POWER GWETTOP / GWETROOT, already on disk for v2) | fails (b) |
| Bucket water balance on the IMERG Late store (this project's data), state at the end of IMD day D-2 | passes (a)-(e); identical in training and live by construction |
| Snow cover, MODIS MOD10C1 v061 (0.05 degree daily) | not pursued here |

## Inputs

`iwet_sat_l2` (bucket saturation at the end of IMD day D-2), `iwet_sat_anom_l2` (minus its 2007-2015 mean for the pixel and month), `iwet_satdays30_l2` (days at 95% or more in the 30 ending at D-2), each non-decreasing. IMERG Late days missing in the history the tables read: 0. NaN share per file (largest over the three inputs):

| file | rows | NaN share |
|---|---|---|
| train_samples_features.parquet | 6,501 | 0.0000% |
| universe_train_features.parquet | 200,000 | 0.0000% |
| validation_samples_features.parquet | 2,563 | 0.0000% |
| universe_validation_features.parquet | 200,000 | 0.0000% |
| test_2018_samples_features.parquet | 935 | 0.0000% |
| universe_test_2018_features.parquet | 200,000 | 0.0000% |
| window_2023_samples_features.parquet | 188,278 | 0.0000% |
| case_kerala_2018_samples_features.parquet | 160,960 | 0.0000% |
| case_wayanad_2024_samples_features.parquet | 3,080 | 0.0000% |
| season_2018_training.npz | 8,131,032 | 0.0000% |
| season_2019_training.npz | 8,131,032 | 0.0000% |
| season_2020_training.npz | 8,131,032 | 0.0000% |
| season_2021_training.npz | 8,131,032 | 0.0000% |
| season_2022_training.npz | 8,131,032 | 0.0000% |
| season_2023_training.npz | 8,131,032 | 0.0000% |
| season_2024_training.npz | 8,131,032 | 0.0000% |
| season_2025_training.npz | 8,131,032 | 0.0000% |

## Stage 1: the wetness group alone on v3

The reference C0 reproduces the frozen v3-live FA@90 to 0.0e+00 with the same tree count.

| model | inputs | trees | pooled OOF FA@90 (95% CI) |
|---|---|---|---|
| C0 | 26 | 315 | 0.1955 [0.1679, 0.2348] |
| w4_wet | 29 | 281 | 0.1959 [0.1689, 0.2228] |

FA@90 is a false-alarm share, lower is better. w4_wet - C0 = +0.0003, 95% paired-bootstrap interval [-0.0209, +0.0141]. Guard: lower bound at or below 0. Stage 1 **passed** (includes zero).

## Checks before the look (spec section 5) and the ablation

| check | numbers | rule | flag |
|---|---|---|---|
| C1 where, not when | v3 + iwet_sat_clim alone 0.1981; w4_wet 0.1959 | flag if FA@90 of v3 + iwet_sat_clim alone is at or below w4_wet's | no |
| C2 reporting bias by built-up share | low -0.0366; middle +0.0054; top -0.0051 | flag if the top lc_built tercile's w4_wet - C0 difference is negative while both others are at or above 0 | no |
| C3 missingness | iwet_sat_l2 0.00%; iwet_sat_anom_l2 0.00%; iwet_satdays30_l2 0.00% | flag if the NaN share of an input differs between positives and universe negatives by more than 1% | no |

Within the built-up terciles (w4_wet - C0, paired bootstrap; cells joined on `cell_id`):

| lc_built tercile | positives | universe rows | difference [95% CI] |
|---|---|---|---|
| low | 71 | 142,211 | -0.0366 [-0.0431, +0.0673] |
| middle | 220 | 123,216 | +0.0054 [-0.0228, +0.0276] |
| top | 487 | 133,845 | -0.0051 [-0.0269, +0.0059] |

Ablation (reported only, not used to choose inputs): v3 plus

| candidate | trees | pooled OOF FA@90 | difference to C0 [95% CI] |
|---|---|---|---|
| v3+iwet_sat_l2 | 311 | 0.1964 | +0.0009 [-0.0103, +0.0226] |
| v3+iwet_sat_anom_l2 | 232 | 0.2027 | +0.0072 [-0.0103, +0.0198] |
| v3+iwet_satdays30_l2 | 252 | 0.1913 | -0.0042 [-0.0197, +0.0131] |
| v3+iwet-iwet_sat_l2 | 246 | 0.1932 | -0.0023 [-0.0158, +0.0145] |
| v3+iwet-iwet_sat_anom_l2 | 367 | 0.1966 | +0.0010 [-0.0144, +0.0189] |
| v3+iwet-iwet_satdays30_l2 | 345 | 0.2004 | +0.0049 [-0.0117, +0.0179] |
| v3+iwet_sat_clim | 296 | 0.1981 | +0.0026 [-0.0156, +0.0133] |

## Stage 2: v5 = v4 plus the wetness group

C0 reproduces the frozen v3-live FA@90 to 0.0e+00.

| model | inputs | trees | pooled OOF FA@90 (95% CI) |
|---|---|---|---|
| C0 | 26 | 315 | 0.1955 [0.1679, 0.2348] |
| v5 | 44 | 449 | 0.1715 [0.1425, 0.2019] |
| v4 (stored OOF) | 41 | | 0.1773 [0.1467, 0.2014] |

v5 - C0 = -0.0241 [-0.0515, +0.0052]; v5 - v4 = -0.0058 [-0.0167, +0.0113]. Guards: both lower bounds at or below 0. Stage 2 **passed**.

## Seasons and preflight

v5 season panels scored: 0 of 8 (no outcome read).

## Caveats

- The held-out look is the only test that decides; development numbers are selection-free here but share the catalogue's reporting bias (C2 looks for it, it cannot remove it).
- Ground truth after 2018 is very incomplete, so held-out detection counts compare models at equal burden and are not absolute; tolerant matching has a high chance floor at Watch+ and Warning+.
- The bucket is a simple, unfitted water balance driven by satellite rain; it is not a measured soil moisture.
- The live adapter exists and is tested; it is not wired into the live run (a separate, reviewed step).
