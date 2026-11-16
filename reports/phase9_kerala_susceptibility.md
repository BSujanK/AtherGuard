# Two-stage susceptibility from the Kerala 2018 mapped inventory: stage 1

**Stage 1 FAILED: the study ends here (spec section 3); no stage 2 was run and no held-out number exists.** Selected form `S_gbm`: pooled leave-one-district-out ROC AUC 0.817 against 0.831 for the mean slope alone (`B_slope`). The rule was fixed before any number (`docs/superpowers/specs/2026-11-17-aetherguard-kerala-susceptibility.md` section 3): the candidate with the higher pooled leave-one-district-out ROC AUC of its surface; stage 1 passes when that AUC is above B_slope's (stat_slope_mean alone).

## The inventory

Hao et al. 2020, ESSD 12, 2899-2918; van Westen 2020, DANS doi:10.17026/dans-x6c-y7x2; licence CC-BY-4.0. 4,728 points: 2,899 found by NRSC imagery, 1,395 by GSI field survey, 856 added by the authors from Google Earth; 973 are GSI-only. 1 point's coordinate attributes differ from its geometry (the geometry is used; no point changes cell). Dated only to 1 June - 26 August 2018, so it is used for where, never when. Raw rows stay under `data/` and are not committed.

Training cells: the 1,063 domain cells of the 14 Kerala districts, 351 holding at least one point (4,679 points). 49 points in 16 cells outside those districts were dropped. Inputs: v3's ten terrain statistics, the nine physical W5 columns and the IMERG Late rain of the window, held at its training median (1546 mm) when the surface is evaluated. Roads and built-up share are never inputs.

## Spatial-block evaluation (leave one district out; 95% intervals from 2,000 district resamples)

| score | ROC AUC | average precision |
|---|---|---|
| `S_lr` | 0.806 [0.771, 0.847] | 0.608 [0.496, 0.673] |
| `S_gbm` | 0.817 [0.778, 0.851] | 0.610 [0.486, 0.676] |
| `B_slope` | 0.831 [0.796, 0.870] | 0.649 [0.554, 0.722] |

| difference | ROC AUC | average precision |
|---|---|---|
| `S_lr-B_slope` | -0.025 [-0.041, -0.011] | -0.041 [-0.085, -0.010] |
| `S_gbm-B_slope` | -0.014 [-0.030, -0.003] | -0.039 [-0.087, -0.014] |
| `S_gbm-S_lr` | 0.011 [-0.009, 0.030] | 0.003 [-0.027, 0.026] |

Inside each district (diagnostic, decides nothing; districts with both classes):

| district | cells | with a point | `S_lr` | `S_gbm` | `B_slope` |
|---|---|---|---|---|---|
| Ernakulam | 72 | 19 | 0.779 | 0.736 | 0.775 |
| Idukki | 145 | 93 | 0.594 | 0.554 | 0.629 |
| Kannur | 86 | 17 | 0.893 | 0.860 | 0.896 |
| Kasaragod | 57 | 13 | 0.635 | 0.614 | 0.631 |
| Kollam | 68 | 4 | 0.902 | 0.887 | 0.922 |
| Kottayam | 60 | 7 | 0.973 | 0.970 | 0.984 |
| Kozhikode | 70 | 17 | 0.957 | 0.921 | 0.959 |
| Malappuram | 103 | 35 | 0.845 | 0.820 | 0.814 |
| Palakkad | 123 | 54 | 0.806 | 0.806 | 0.828 |
| Pathanamthitta | 82 | 24 | 0.767 | 0.741 | 0.784 |
| Thiruvananthapuram | 63 | 3 | 0.733 | 0.656 | 0.739 |
| Thrissur | 64 | 35 | 0.930 | 0.920 | 0.942 |
| Wayanad | 67 | 30 | 0.850 | 0.891 | 0.918 |
| median | | | 0.845 | 0.820 | 0.828 |

## Reporting-bias checks (decide nothing)

- A surface of the same form learned from reported development positives (557 of 36,792 scored cells; by region himalaya 485, western_ghats 72) ranks the Kerala mapped cells at ROC AUC 0.661 (average precision 0.449).
- Spearman correlation over the scored cells, with road density / built-up share: the mapped surface -0.115 / -0.257; the reported surface +0.137 / -0.023.
- Imagery-only label (1,030 cells, 318 positive, 33 GSI-only cells left out): ROC AUC 0.846; the mean slope alone on the same cells 0.857.
- The fitted models with each cell's own 2018 rain (not a surface; it carries the storm's footprint): `S_lr` 0.839, `S_gbm` 0.849.

## Caveats

- One storm in one state: a surface learned here would also have had to transfer to the Himalaya.
- The cells are 0.05 degree (about 5.5 km); slides are slope-scale, so a cell label is presence somewhere in it.
- No held-out event, case-study table or model output was read. Research prototype, not validated for issuing public warnings.
