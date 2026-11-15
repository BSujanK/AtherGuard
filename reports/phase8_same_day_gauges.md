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

## Level and confidence changes against `before`

| day | set | cells | level changed (up / down) | level pairs | confidence changed | confidence pairs |
|---|---|---|---|---|---|---|

## Totals

| set | days | stations on D (sum) | High | Degraded | Insufficient | Watch | Warning | Emergency | blind-escalated | audit violations |
|---|---|---|---|---|---|---|---|---|---|---|

Published alert levels do not change on these days; confidence may.

## Caveats

- The replayed days are November, outside the validated June-September season, and mostly dry: they show the plumbing (stations seen on D, engine verdicts, confidence) far more than rain-day behaviour.
- Only the newest replayed day has reports with measured arrival times (the NWS ring); earlier days use OGIMET archive reports, treated as arriving `synop.latency_h` after observation.
- The integrity engine runs with the live substitutes for its references (IMD real-time grid, IMERG), as every live run does; that substitution is not validated.
- V1 compares two summaries of the same reports; it tests the decoding and the day rule, not the gauges.
