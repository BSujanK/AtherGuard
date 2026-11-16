# Same-day SYNOP gauges for the integrity engine (phase 8, gauges-isd)

Research prototype, not validated for issuing real public warnings. Spec: `docs/superpowers/specs/2026-11-14-aetherguard-same-day-gauges.md`; sources: `reports/phase8_gauge_sources_probe.md`. Every number below is read from `phase8_same_day_gauges.json`.

## V1: SYNOP IMD-day totals against GHCN-Daily, July 2024 (the declared criterion)

Criterion (declared before measuring): within tolerance >= 0.95, r >= 0.95, wet-day hit rate >= 0.95, |bias| <= 0.5 mm.

| run | n | bias mm | r | wet hit | false wet | within tolerance |
|---|---|---|---|---|---|---|
| first run (decoder of 880bbbc) | 2767 | 1.18 | 0.919 | 0.988 | 0.089 | 0.972 |
| rerun (6RRR/7R24 rounding rule) | 2873 | 1.19 | 0.925 | 0.989 | 0.092 | 0.972 |
| post-hoc diagnostic: days whose 03 UTC report is in ISD | 2809 | 0.49 | 0.974 | 0.989 | 0.047 | 0.986 |

**V1 criterion met: NO** (first run: NO). Coverage of GHCN station-days: 0.995. How the totals were made: {'24h_group': 3007, 'ir3_zero': 1271, 'no_24h_amount': 7, 'no_03utc_report': 54, 'conflicting_24h_groups': 1}.

Diagnostic, not the criterion: GHCN 0.0 while SYNOP >= 1 mm on 47 station-days whose 03 UTC report is absent from ISD (GSOD wrote a zero for a missing report) and on 43 where it is present.

## V2: the replay period against GHCN-Daily 2026 and the IMD real-time grid (descriptive)

| reference | n | bias mm | r | wet hit | false wet | within tolerance |
|---|---|---|---|---|---|---|
| GHCN-Daily 2026, all values | 3020 | 4.60 | 0.018 | 0.500 | 0.279 | 0.800 |
| GHCN-Daily 2026, flag-H zeros removed | 4 | -0.25 | 0.999 | 0.500 | 0.000 | 1.000 |
| IMD real-time grid, nearest point | 4894 | 0.07 | 0.841 | 0.735 | 0.027 | 0.958 |

Period 2026-07-15 to 2026-11-15, 140 stations: SYNOP totals on 16954 of 17360 station-days ({'ir3_zero': 9561, '24h_group': 7391, 'no_03utc_report': 363, 'no_24h_amount': 42, 'partition': 2, 'conflicting_24h_groups': 1}). GHCN-Daily has 3067 flag-H zeros in the period, 843 of them on station-days where the station's own SYNOP has >= 1 mm. IMD real-time days compared: 39.

GHCN-Daily 2026 is source flag 2 (Synoptic Summary of the Day v2); its flag-H zeros are not measured zeros. The IMD real-time grid is gridded and includes these stations among its inputs: agreement with it is not independent evidence.

## Replayed days

| day | set | stations on D | SYNOP how on D | flagged on D | mean trust | High / Degraded / Insufficient | Normal / Watch / Warning / Emergency | blind-escalated | audit |
|---|---|---|---|---|---|---|---|---|---|
| 2026-11-10 | before (GHCN-Daily only) | 0 | - | 0 | - | 31135 / 5657 / 0 | 34259 / 2358 / 165 / 10 | 0 | 0 |
| 2026-11-10 | after (SYNOP merged) | 139 | {'ir3_zero': 127, '24h_group': 12, 'no_03utc_report': 1} | 83 | 0.452 | 10176 / 26580 / 36 | 34246 / 2371 / 165 / 10 | 13 | 0 |
| 2026-11-10 | after, GHCN flag-H zeros missing | 139 | {'ir3_zero': 127, '24h_group': 12, 'no_03utc_report': 1} | 83 | 0.451 | 10176 / 26580 / 36 | 34246 / 2371 / 165 / 10 | 13 | 0 |
| 2026-11-11 | before (GHCN-Daily only) | 0 | - | 0 | - | 30310 / 6482 / 0 | 32797 / 3236 / 657 / 102 | 18 | 0 |
| 2026-11-11 | after (SYNOP merged) | 139 | {'ir3_zero': 122, '24h_group': 17, 'no_03utc_report': 1} | 84 | 0.447 | 9859 / 26621 / 312 | 32772 / 3261 / 657 / 102 | 30 | 0 |
| 2026-11-11 | after, GHCN flag-H zeros missing | 139 | {'ir3_zero': 122, '24h_group': 17, 'no_03utc_report': 1} | 84 | 0.447 | 9859 / 26621 / 312 | 32772 / 3261 / 657 / 102 | 30 | 0 |
| 2026-11-12 | before (GHCN-Daily only) | 0 | - | 0 | - | 29445 / 7347 / 0 | 31653 / 4012 / 963 / 164 | 17 | 0 |
| 2026-11-12 | after (SYNOP merged) | 139 | {'ir3_zero': 119, '24h_group': 20, 'no_03utc_report': 1} | 80 | 0.471 | 9652 / 26521 / 619 | 30631 / 5004 / 993 / 164 | 631 | 0 |
| 2026-11-12 | after, GHCN flag-H zeros missing | 139 | {'ir3_zero': 119, '24h_group': 20, 'no_03utc_report': 1} | 80 | 0.469 | 9652 / 26521 / 619 | 30631 / 5004 / 993 / 164 | 631 | 0 |
| 2026-11-13 | before (GHCN-Daily only) | 0 | - | 0 | - | 28990 / 7802 / 0 | 31121 / 4467 / 1025 / 179 | 8 | 0 |
| 2026-11-13 | after (SYNOP merged) | 137 | {'ir3_zero': 125, '24h_group': 12, 'no_03utc_report': 3} | 79 | 0.456 | 9375 / 26920 / 497 | 30928 / 4654 / 1031 / 179 | 11 | 0 |
| 2026-11-13 | after, GHCN flag-H zeros missing | 137 | {'ir3_zero': 125, '24h_group': 12, 'no_03utc_report': 3} | 79 | 0.456 | 9375 / 26920 / 497 | 30928 / 4654 / 1031 / 179 | 11 | 0 |
| 2026-11-14 | before (GHCN-Daily only) | 0 | - | 0 | - | 29528 / 7264 / 0 | 32759 / 3295 / 625 / 113 | 0 | 0 |
| 2026-11-14 | after (SYNOP merged) | 139 | {'ir3_zero': 129, '24h_group': 10, 'no_03utc_report': 1} | 81 | 0.451 | 9507 / 26868 / 417 | 32756 / 3298 / 625 / 113 | 0 | 0 |
| 2026-11-14 | after, GHCN flag-H zeros missing | 139 | {'ir3_zero': 129, '24h_group': 10, 'no_03utc_report': 1} | 81 | 0.450 | 9507 / 26868 / 417 | 32756 / 3298 / 625 / 113 | 0 | 0 |
| 2026-11-15 | before (GHCN-Daily only) | 0 | - | 0 | - | 29930 / 6862 / 0 | 33432 / 3050 / 284 / 26 | 0 | 0 |
| 2026-11-15 | after (SYNOP merged) | 137 | {'ir3_zero': 118, '24h_group': 19, 'no_03utc_report': 3} | 77 | 0.459 | 9756 / 26763 / 273 | 33432 / 3050 / 284 / 26 | 0 | 0 |
| 2026-11-15 | after, GHCN flag-H zeros missing | 137 | {'ir3_zero': 118, '24h_group': 19, 'no_03utc_report': 3} | 77 | 0.459 | 9756 / 26763 / 273 | 33432 / 3050 / 284 / 26 | 0 | 0 |

**after (SYNOP merged): the engine flags 484 of 830 station readings on the run days (0.58); 825 station-days are out of distribution ('uncertain').** The readings are mostly dry-day zeros that agree with the IMD real-time grid (V2), so the flags point at the engine under its live substitute references, not at the SYNOP values (not verified).

**after, GHCN flag-H zeros missing: the engine flags 484 of 830 station readings on the run days (0.58); 825 station-days are out of distribution ('uncertain').** The readings are mostly dry-day zeros that agree with the IMD real-time grid (V2), so the flags point at the engine under its live substitute references, not at the SYNOP values (not verified).

Integrity-engine verdicts on D (station states of the alert engine and the engine's fault types):

- before (GHCN-Daily only), 2026-11-10: states {'missing': 140}, fault types -, lowest trust -
- before (GHCN-Daily only), 2026-11-11: states {'missing': 140}, fault types -, lowest trust -
- before (GHCN-Daily only), 2026-11-12: states {'missing': 140}, fault types -, lowest trust -
- before (GHCN-Daily only), 2026-11-13: states {'missing': 140}, fault types -, lowest trust -
- before (GHCN-Daily only), 2026-11-14: states {'missing': 140}, fault types -, lowest trust -
- before (GHCN-Daily only), 2026-11-15: states {'missing': 140}, fault types -, lowest trust -
- after (SYNOP merged), 2026-11-10: states {'uncertain': 138, 'missing': 1, 'trusted': 1}, fault types {'zero_fault': 83}, lowest trust 0.013
- after (SYNOP merged), 2026-11-11: states {'uncertain': 138, 'missing': 1, 'trusted': 1}, fault types {'zero_fault': 84}, lowest trust 0.013
- after (SYNOP merged), 2026-11-12: states {'uncertain': 138, 'missing': 1, 'trusted': 1}, fault types {'zero_fault': 80}, lowest trust 0.004
- after (SYNOP merged), 2026-11-13: states {'uncertain': 136, 'missing': 3, 'trusted': 1}, fault types {'zero_fault': 79}, lowest trust 0.004
- after (SYNOP merged), 2026-11-14: states {'uncertain': 138, 'missing': 1, 'trusted': 1}, fault types {'zero_fault': 81}, lowest trust 0.004
- after (SYNOP merged), 2026-11-15: states {'uncertain': 137, 'missing': 3}, fault types {'zero_fault': 76, 'scale_drift': 1}, lowest trust 0.004
- after, GHCN flag-H zeros missing, 2026-11-10: states {'uncertain': 138, 'missing': 1, 'trusted': 1}, fault types {'zero_fault': 83}, lowest trust 0.013
- after, GHCN flag-H zeros missing, 2026-11-11: states {'uncertain': 138, 'missing': 1, 'trusted': 1}, fault types {'zero_fault': 84}, lowest trust 0.013
- after, GHCN flag-H zeros missing, 2026-11-12: states {'uncertain': 138, 'missing': 1, 'trusted': 1}, fault types {'zero_fault': 80}, lowest trust 0.004
- after, GHCN flag-H zeros missing, 2026-11-13: states {'uncertain': 136, 'missing': 3, 'trusted': 1}, fault types {'zero_fault': 79}, lowest trust 0.004
- after, GHCN flag-H zeros missing, 2026-11-14: states {'uncertain': 138, 'missing': 1, 'trusted': 1}, fault types {'zero_fault': 81}, lowest trust 0.004
- after, GHCN flag-H zeros missing, 2026-11-15: states {'uncertain': 137, 'missing': 3}, fault types {'zero_fault': 76, 'scale_drift': 1}, lowest trust 0.004

## Level and confidence changes against `before`

| day | set | cells | level changed (up / down) | level pairs | confidence changed | confidence pairs |
|---|---|---|---|---|---|---|
| 2026-11-10 | after (SYNOP merged) | 36792 | 13 (13 / 0) | {'Normal->Watch': 13} | 20995 | {'High->Degraded': 20959, 'Degraded->Insufficient': 36} |
| 2026-11-10 | after, GHCN flag-H zeros missing | 36792 | 13 (13 / 0) | {'Normal->Watch': 13} | 20995 | {'High->Degraded': 20959, 'Degraded->Insufficient': 36} |
| 2026-11-11 | after (SYNOP merged) | 36792 | 25 (25 / 0) | {'Normal->Watch': 25} | 20763 | {'High->Degraded': 20451, 'Degraded->Insufficient': 312} |
| 2026-11-11 | after, GHCN flag-H zeros missing | 36792 | 25 (25 / 0) | {'Normal->Watch': 25} | 20763 | {'High->Degraded': 20451, 'Degraded->Insufficient': 312} |
| 2026-11-12 | after (SYNOP merged) | 36792 | 1052 (1052 / 0) | {'Normal->Watch': 1022, 'Watch->Warning': 30} | 20412 | {'High->Degraded': 19793, 'Degraded->Insufficient': 619} |
| 2026-11-12 | after, GHCN flag-H zeros missing | 36792 | 1052 (1052 / 0) | {'Normal->Watch': 1022, 'Watch->Warning': 30} | 20412 | {'High->Degraded': 19793, 'Degraded->Insufficient': 619} |
| 2026-11-13 | after (SYNOP merged) | 36792 | 199 (199 / 0) | {'Normal->Watch': 193, 'Watch->Warning': 6} | 20112 | {'High->Degraded': 19615, 'Degraded->Insufficient': 497} |
| 2026-11-13 | after, GHCN flag-H zeros missing | 36792 | 199 (199 / 0) | {'Normal->Watch': 193, 'Watch->Warning': 6} | 20112 | {'High->Degraded': 19615, 'Degraded->Insufficient': 497} |
| 2026-11-14 | after (SYNOP merged) | 36792 | 3 (3 / 0) | {'Normal->Watch': 3} | 20438 | {'High->Degraded': 20021, 'Degraded->Insufficient': 417} |
| 2026-11-14 | after, GHCN flag-H zeros missing | 36792 | 3 (3 / 0) | {'Normal->Watch': 3} | 20438 | {'High->Degraded': 20021, 'Degraded->Insufficient': 417} |
| 2026-11-15 | after (SYNOP merged) | 36792 | 0 (0 / 0) | - | 20447 | {'High->Degraded': 20174, 'Degraded->Insufficient': 273} |
| 2026-11-15 | after, GHCN flag-H zeros missing | 36792 | 0 (0 / 0) | - | 20447 | {'High->Degraded': 20174, 'Degraded->Insufficient': 273} |

## Totals

| set | days | stations on D (sum) | High | Degraded | Insufficient | Watch | Warning | Emergency | blind-escalated | audit violations |
|---|---|---|---|---|---|---|---|---|---|---|
| before (GHCN-Daily only) | 6 | 0 | 179338 | 41414 | 0 | 20418 | 3719 | 594 | 43 | 0 |
| after (SYNOP merged) | 6 | 830 | 58325 | 160273 | 2154 | 21638 | 3755 | 594 | 685 | 0 |
| after, GHCN flag-H zeros missing | 6 | 830 | 58325 | 160273 | 2154 | 21638 | 3755 | 594 | 685 | 0 |

**Published alert levels change in these replays: wiring the SYNOP gauges is a MODEL CHANGE.** The lead decides.

## Caveats

- The replayed days are November, outside the validated June-September season, and mostly dry: they show the plumbing (stations seen on D, engine verdicts, confidence) far more than rain-day behaviour.
- Only the newest replayed day has reports with measured arrival times (the NWS ring); earlier days use OGIMET archive reports, treated as arriving `synop.latency_h` after observation.
- The integrity engine runs with the live substitutes for its references (IMD real-time grid, IMERG), as every live run does; that substitution is not validated.
- V1 compares two summaries of the same reports; it tests the decoding and the day rule, not the gauges.
- The `after, GHCN flag-H zeros missing` run of 15 Nov was repeated: its first attempt hit a DNS failure (GHCN failed, IMD real-time late); the failed run.json is kept in the scratch replay directory.
