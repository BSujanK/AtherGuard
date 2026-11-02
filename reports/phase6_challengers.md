# Challenger experiments (Task 5)

Protocol: protocol v2: year-blocked CV over 2007-2017, pooled OOF FA@90 on the weighted universe, bootstrap of positives as events and universe rows iid within year-region strata. Bootstrap n=2000, seed 31337, level 0.95. Config `configs/hazard_v3.yaml`.

## Reproduction check

| scorer | selected group | reported FA@90 | recomputed FA@90 | abs difference | trees (reported / recomputed) |
|---|---|---|---|---|---|
| v3_selected | imerg_core | 0.195541 | 0.195541 | 0.000000 | 315 / 315 |
| v2_selected | drop_src | 0.188405 | 0.188405 | 0.000000 | 118 / 118 |

Development rows (identical for v2 and v3, checked key by key): 789 positives, 399,272 universe negatives, 8240 matched negatives.

## Selected v3-live versus frozen v2 (paired)

FA@90 v3 0.1955 versus v2 0.1884: point difference 0.0071, bootstrap mean 0.0059, SE 0.0149, 95% CI [-0.0203, 0.0384]; the interval does not exclude zero in favour of v3-live. Share of resamples with v3 better: 0.374.

## All candidates (pooled OOF)

Difference = FA@90(candidate) - FA@90(selected v3), one shared resample; `*` = the interval excludes 0; negative favours the candidate.

| candidate | family | inputs | trees | FA@90 [95% CI] | difference vs v3 [95% CI] | recall @ FA 1% | recall @ FA 5% | design log-loss |
|---|---|---|---|---|---|---|---|---|
| v3_selected | lightgbm | 26 | 315 | 0.1955 [0.1679, 0.2348] |  | 0.3004 [0.2700, 0.3359] | 0.6261 [0.5919, 0.6616] | 0.2146 |
| v2_selected | frozen_v2 | 30 | 118 | 0.1884 [0.1726, 0.2128] |  | 0.2763 [0.2446, 0.3080] | 0.5881 [0.5526, 0.6223] | 0.2225 |
| lgb_iclim_add | lightgbm | 32 | 332 | 0.1898 [0.1704, 0.2208] | -0.0057 [-0.0196, 0.0127] | 0.3232 [0.2864, 0.3574] | 0.6362 [0.6008, 0.6680] | 0.2152 |
| lgb_iclim_swap | lightgbm | 29 | 352 | 0.1883 [0.1663, 0.2281] | -0.0072 [-0.0219, 0.0103] | 0.3371 [0.3042, 0.3726] | 0.6401 [0.6046, 0.6717] | 0.2169 |
| cb_d4_l2_3 | catboost | 26 | 329 | 0.2003 [0.1769, 0.2329] | 0.0048 [-0.0210, 0.0268] | 0.3371 [0.3029, 0.3701] | 0.6337 [0.6008, 0.6679] | 0.2134 |
| cb_d4_l2_10 | catboost | 26 | 583 | 0.2003 [0.1747, 0.2435] | 0.0047 [-0.0154, 0.0284] | 0.3308 [0.2978, 0.3650] | 0.6489 [0.6147, 0.6819] | 0.2124 |
| cb_d6_l2_3 | catboost | 26 | 254 | 0.2077 [0.1811, 0.2310] | 0.0122 [-0.0137, 0.0339] | 0.3283 [0.2953, 0.3625] | 0.6515 [0.6172, 0.6831] | 0.2154 |
| cb_d6_l2_10 | catboost | 26 | 259 | 0.2007 [0.1736, 0.2248] | 0.0051 [-0.0197, 0.0274] | 0.3321 [0.3003, 0.3676] | 0.6464 [0.6134, 0.6794] | 0.2123 |
| blend_rank | blend | n/a | n/a | 0.1896 [0.1608, 0.2105] | -0.0059 [-0.0272, 0.0081] | 0.3549 [0.3207, 0.3904] | 0.6603 [0.6261, 0.6933] | n/a |

## Descriptions

- `v3_selected`: selected v3-live configuration (reproduced)
- `v2_selected`: frozen v2 configuration (reproduced from configs/hazard.yaml)
- `lgb_iclim_add`: LightGBM, imerg_core plus the climatology-normalised rain group iclim
- `lgb_iclim_swap`: LightGBM, imerg_core with irain_acc*_vs_clim replaced by iclim
- `cb_d4_l2_3`: CatBoost {'depth': 4, 'l2_leaf_reg': 3, 'learning_rate': 0.1}
- `cb_d4_l2_10`: CatBoost {'depth': 4, 'l2_leaf_reg': 10, 'learning_rate': 0.1}
- `cb_d6_l2_3`: CatBoost {'depth': 6, 'l2_leaf_reg': 3, 'learning_rate': 0.1}
- `cb_d6_l2_10`: CatBoost {'depth': 6, 'l2_leaf_reg': 10, 'learning_rate': 0.1}
- `blend_rank`: within-fold rank average of lgb_iclim_swap and cb_d4_l2_10; a ranking score, so it needs a reference distribution and cannot be scored on a single live day

## Adoption

a challenger replaces the selected v3 configuration only if its pooled OOF FA@90 is lower by MORE than the bootstrap SE of the paired difference.

| challenger | adoptable | gain over v3 | paired SE | gain / SE | replaces v3 |
|---|---|---|---|---|---|
| lgb_iclim_add | yes | 0.0057 | 0.0085 | 0.68 | no |
| lgb_iclim_swap | yes | 0.0072 | 0.0083 | 0.87 | no |
| cb_d4_l2_3 | yes | -0.0048 | 0.0119 | -0.40 | no |
| cb_d4_l2_10 | yes | -0.0047 | 0.0113 | -0.42 | no |
| cb_d6_l2_3 | yes | -0.0122 | 0.0121 | -1.01 | no |
| cb_d6_l2_10 | yes | -0.0051 | 0.0121 | -0.43 | no |
| blend_rank | no | 0.0059 | 0.0090 | 0.66 | no |

Adopted: none. The selected v3-live configuration is unchanged.

## Caveat on multiple comparisons

7 challenger candidates were compared with the same development rows; the chance that the best of them looks better than it is grows with that number. The single look at test_2018 is the check.

## Static susceptibility prior (probe)

Obtainable without login (direct GeoTIFF, 33.5 MB, https://gpm.nasa.gov/sites/default/files/downloads/global-landslide-susceptibility-map-2-27-23.tif) but NOT used: NASA LHASA susceptibility is derived from the NASA Global Landslide Catalog / COOLR inventory, the same catalogs that supply this project's positive labels (leakage). Candidate imerg_core+susc was therefore not run; nothing was downloaded.

Runtime 758 s.
