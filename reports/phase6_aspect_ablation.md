# Challenger experiments (Task 5)

Protocol: protocol v2: year-blocked CV over 2007-2017, pooled OOF FA@90 on the weighted universe, bootstrap of positives as events and universe rows iid within year-region strata. Bootstrap n=2000, seed 31337, level 0.95. Config `configs/hazard_v3_aspect_ablation.yaml`.

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
| lgb_no_aspect | lightgbm | 24 | 362 | 0.1992 [0.1745, 0.2276] | 0.0037 [-0.0165, 0.0184] | 0.3080 [0.2763, 0.3422] | 0.6261 [0.5932, 0.6603] | 0.2161 |

## Descriptions

- `v3_selected`: selected v3-live configuration (reproduced)
- `v2_selected`: frozen v2 configuration (reproduced from configs/hazard.yaml)
- `lgb_no_aspect`: LightGBM, imerg_core without the aspect inputs stat_aspect_sin and stat_aspect_cos

## Adoption

a challenger replaces the selected v3 configuration only if its pooled OOF FA@90 is lower by MORE than the bootstrap SE of the paired difference.

| challenger | adoptable | gain over v3 | paired SE | gain / SE | replaces v3 |
|---|---|---|---|---|---|
| lgb_no_aspect | yes | -0.0037 | 0.0090 | -0.41 | no |

Adopted: none. The selected v3-live configuration is unchanged.

## Caveat on multiple comparisons

1 challenger candidates were compared with the same development rows; the chance that the best of them looks better than it is grows with that number. The single look at test_2018 is the check.

Runtime 21 s.
