# Scratch replays of real live days (phase 8)

Backtest mode (inputs issued before 11:00 IST of each day), scratch live_dir; never data/live. The first day starts the hysteresis without history.

## Confidence of lead 0

| day | set | High | Degraded | Insufficient | causes | check day | audit |
|---|---|---|---|---|---|---|---|
| 2026-11-08 | before (dc93f98) | 0 | 36792 | 0 | imd_missing 36792, ensemble_disagrees 80 | - | 0 |
| 2026-11-08 | after, v4, alert_config_v3 | 30425 | 6367 | 0 | imd_missing 5461, sources_disagree 843, ensemble_disagrees 80 | 2026-11-07 | 0 |
| 2026-11-08 | after, lead 0 by v3 | 30437 | 6355 | 0 | imd_missing 5461, sources_disagree 843, ensemble_disagrees 56 | 2026-11-07 | 0 |
| 2026-11-08 | after, v4, alert_config_v4 | 30302 | 6490 | 0 | imd_missing 5461, sources_disagree 966, ensemble_disagrees 80 | 2026-11-07 | 0 |
| 2026-11-09 | before (dc93f98) | 0 | 36792 | 0 | imd_missing 36792, ensemble_disagrees 70 | - | 0 |
| 2026-11-09 | after, v4, alert_config_v3 | 30600 | 6192 | 0 | imd_missing 5461, sources_disagree 679, ensemble_disagrees 70 | 2026-11-08 | 0 |
| 2026-11-09 | after, lead 0 by v3 | 30611 | 6181 | 0 | imd_missing 5461, sources_disagree 679, ensemble_disagrees 46 | 2026-11-08 | 0 |
| 2026-11-09 | after, v4, alert_config_v4 | 30440 | 6352 | 0 | imd_missing 5461, sources_disagree 839, ensemble_disagrees 70 | 2026-11-08 | 0 |
| 2026-11-10 | before (dc93f98) | 0 | 36792 | 0 | imd_missing 36792, ensemble_disagrees 64 | - | 0 |
| 2026-11-10 | after, v4, alert_config_v3 | 31119 | 5673 | 0 | imd_missing 5461, sources_disagree 160, ensemble_disagrees 64 | 2026-11-09 | 0 |
| 2026-11-10 | after, lead 0 by v3 | 31112 | 5680 | 0 | imd_missing 5461, sources_disagree 160, ensemble_disagrees 71 | 2026-11-09 | 0 |
| 2026-11-10 | after, v4, alert_config_v4 | 30999 | 5793 | 0 | imd_missing 5461, sources_disagree 280, ensemble_disagrees 64 | 2026-11-09 | 0 |
| 2026-11-11 | before (dc93f98) | 0 | 36792 | 0 | imd_missing 36792, ensemble_disagrees 61 | - | 0 |
| 2026-11-11 | after, v4, alert_config_v3 | 30310 | 6482 | 0 | imd_missing 5461, sources_disagree 977, ensemble_disagrees 61 | 2026-11-10 | 0 |
| 2026-11-11 | after, lead 0 by v3 | 30297 | 6495 | 0 | imd_missing 5461, sources_disagree 977, ensemble_disagrees 63 | 2026-11-10 | 0 |
| 2026-11-11 | after, v4, alert_config_v4 | 30013 | 6779 | 0 | imd_missing 5461, sources_disagree 1280, ensemble_disagrees 61 | 2026-11-10 | 0 |
| 2026-11-12 | before (dc93f98) | 0 | 36792 | 0 | imd_missing 36792, ensemble_disagrees 49 | - | 0 |
| 2026-11-12 | after, v4, alert_config_v3 | 29445 | 7347 | 0 | imd_missing 5461, sources_disagree 1864, ensemble_disagrees 49 | 2026-11-11 | 0 |
| 2026-11-12 | after, lead 0 by v3 | 29415 | 7377 | 0 | imd_missing 5461, sources_disagree 1864, ensemble_disagrees 99 | 2026-11-11 | 0 |
| 2026-11-12 | after, v4, alert_config_v4 | 28977 | 7815 | 0 | imd_missing 5461, sources_disagree 2334, ensemble_disagrees 49 | 2026-11-11 | 0 |
| 2026-11-13 | before (dc93f98) | 0 | 36792 | 0 | imd_missing 36792, ensemble_disagrees 54 | - | 0 |
| 2026-11-13 | after, v4, alert_config_v3 | 28990 | 7802 | 0 | imd_missing 5461, sources_disagree 2298, ensemble_disagrees 54 | 2026-11-12 | 0 |
| 2026-11-13 | after, lead 0 by v3 | 28995 | 7797 | 0 | imd_missing 5461, sources_disagree 2298, ensemble_disagrees 59 | 2026-11-12 | 0 |
| 2026-11-13 | after, v4, alert_config_v4 | 28548 | 8244 | 0 | imd_missing 5461, sources_disagree 2740, ensemble_disagrees 54 | 2026-11-12 | 0 |

## Levels of lead 0 and lead 1

| day | set | lead 0 Normal / Watch / Warning / Emergency | blind-escalated | lead 1 Normal / Watch / Warning / Emergency |
|---|---|---|---|---|
| 2026-11-08 | before (dc93f98) | 34467 / 2174 / 142 / 9 | 0 | 33706 / 2505 / 418 / 163 |
| 2026-11-08 | after, v4, alert_config_v3 | 34467 / 2174 / 142 / 9 | 0 | 33706 / 2505 / 418 / 163 |
| 2026-11-08 | after, lead 0 by v3 | 33993 / 2313 / 390 / 96 | 0 | 33706 / 2505 / 418 / 163 |
| 2026-11-08 | after, v4, alert_config_v4 | 34467 / 2174 / 142 / 9 | 0 | 33706 / 2505 / 418 / 163 |
| 2026-11-09 | before (dc93f98) | 34346 / 2288 / 149 / 9 | 0 | 34335 / 1859 / 468 / 130 |
| 2026-11-09 | after, v4, alert_config_v3 | 34346 / 2288 / 149 / 9 | 0 | 34335 / 1859 / 468 / 130 |
| 2026-11-09 | after, lead 0 by v3 | 33873 / 2390 / 427 / 102 | 0 | 34335 / 1859 / 468 / 130 |
| 2026-11-09 | after, v4, alert_config_v4 | 34346 / 2288 / 149 / 9 | 0 | 34335 / 1859 / 468 / 130 |
| 2026-11-10 | before (dc93f98) | 33943 / 2631 / 203 / 15 | 10 | 33478 / 2811 / 435 / 68 |
| 2026-11-10 | after, v4, alert_config_v3 | 33953 / 2621 / 203 / 15 | 0 | 33478 / 2811 / 435 / 68 |
| 2026-11-10 | after, lead 0 by v3 | 33265 / 2871 / 519 / 137 | 0 | 33478 / 2811 / 435 / 68 |
| 2026-11-10 | after, v4, alert_config_v4 | 33953 / 2621 / 203 / 15 | 0 | 33478 / 2811 / 435 / 68 |
| 2026-11-11 | before (dc93f98) | 32769 / 3262 / 659 / 102 | 37 | 31311 / 4328 / 897 / 256 |
| 2026-11-11 | after, v4, alert_config_v3 | 32797 / 3234 / 659 / 102 | 18 | 31311 / 4328 / 897 / 256 |
| 2026-11-11 | after, lead 0 by v3 | 32257 / 2976 / 922 / 637 | 1 | 31311 / 4328 / 897 / 256 |
| 2026-11-11 | after, v4, alert_config_v4 | 32786 / 3245 / 659 / 102 | 29 | 31311 / 4328 / 897 / 256 |
| 2026-11-12 | before (dc93f98) | 31637 / 4025 / 966 / 164 | 19 | 31406 / 4352 / 799 / 235 |
| 2026-11-12 | after, v4, alert_config_v3 | 31653 / 4009 / 966 / 164 | 17 | 31406 / 4352 / 799 / 235 |
| 2026-11-12 | after, lead 0 by v3 | 30887 / 3612 / 1308 / 985 | 1 | 31406 / 4352 / 799 / 235 |
| 2026-11-12 | after, v4, alert_config_v4 | 31637 / 4025 / 966 / 164 | 27 | 31406 / 4352 / 799 / 235 |
| 2026-11-13 | before (dc93f98) | 31118 / 4470 / 1025 / 179 | 11 | 32569 / 3874 / 321 / 28 |
| 2026-11-13 | after, v4, alert_config_v3 | 31121 / 4467 / 1025 / 179 | 8 | 32569 / 3874 / 321 / 28 |
| 2026-11-13 | after, lead 0 by v3 | 30253 / 4311 / 1509 / 719 | 0 | 32569 / 3874 / 321 / 28 |
| 2026-11-13 | after, v4, alert_config_v4 | 31111 / 4477 / 1025 / 179 | 8 | 32569 / 3874 / 321 / 28 |

## Totals over the replayed days

| set | days | High | Degraded | Insufficient | Watch | Warning | Emergency | blind-escalated | audit violations |
|---|---|---|---|---|---|---|---|---|---|
| before (dc93f98) | 6 | 0 | 220752 | 0 | 18850 | 3144 | 478 | 77 | 0 |
| after, v4, alert_config_v3 | 6 | 180889 | 39863 | 0 | 18793 | 3144 | 478 | 43 | 0 |
| after, lead 0 by v3 | 6 | 180867 | 39885 | 0 | 18473 | 5075 | 2676 | 2 | 0 |
| after, v4, alert_config_v4 | 6 | 179279 | 41473 | 0 | 18830 | 3144 | 478 | 64 | 0 |

Lead 1 is scored by v3 in every set (forecast rain); lead 0 by v4 except in `after_v3lead0`.
