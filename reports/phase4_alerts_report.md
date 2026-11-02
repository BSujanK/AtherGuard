# Phase 4 alert report

Thresholds (card.alert_levels): Watch 4.13e-06, Warning 1.58e-05, Emergency 3.70e-05 (calibrated risk per cell-day).
Model card sha256: `b14a60c317889e69983190206dfffdfd0997b037f93e2f17618f4f43bff830ef`; frozen 2026-10-03T11:39:44Z (freeze record verified before the replay was built).
Lead window: Watch+ on the event day or within 7 days before; a flap is a Watch+ alert off and on again within 3 days.

## test_2018 (universe + positives)

80 in-domain positive cell-days plus 5 out-of-domain (counted as misses); event base rate 0.000006 per cell-day.

| level | alerts / 1000 cell-days | recall (in domain) | recall (all, OOD = miss) |
|---|---|---|---|
| Watch | 271.59 | 0.912 | 0.859 |
| Warning | 91.70 | 0.700 | 0.659 |
| Emergency | 35.39 | 0.388 | 0.365 |

### Cost-loss

An alert is optimal when risk >= C/L, so each threshold is the cost ratio at which it is optimal. `relative expense` is expense / min(never alert, always alert); below 1 the rule beats both.

| rule | threshold | C/L | alerts / 1000 | recall | relative expense |
|---|---|---|---|---|---|
| watch threshold | 4.13e-06 | 4.13e-06 | 218.03 | 0.863 | 0.429 |
| warning threshold | 1.58e-05 | 1.58e-05 | 91.40 | 0.688 | 0.541 |
| emergency threshold | 3.70e-05 | 3.70e-05 | 35.17 | 0.388 | 0.818 |
| C/L = 1/10 | 0.100 | 0.100 | 0.00 | 0.000 | 1.000 |
| C/L = 1/50 | 0.020 | 0.020 | 0.00 | 0.000 | 1.000 |
| C/L = 1/200 | 0.005 | 0.005 | 4.39e-03 | 0.000 | 1.003 |


**What this implies.** The event base rate is 0.000006 per cell-day, so calibrated risks are tiny (the largest risk in the test_2018 universe is 0.01). Alerting is cost-justified when risk >= C/L, so the Watch, Warning and Emergency thresholds are optimal only if acting costs at most 4.13e-06, 1.58e-05 and 3.70e-05 of the loss it avoids (relative expense 0.43, 0.54, 0.82; below 1 beats both never and always alerting). At C/L = 1/10, 1/50 and 1/200 the cost-optimal rule is effectively never to alert on these data (0.000, 0.000, 0.004 alerts per 1000 cell-days, recall 0, relative expense about 1): almost no cell-day reaches a risk that high, so at those ratios this model supports no alert at all. The alert levels are defensible only where acting is very cheap relative to the loss avoided.

### What each layer adds (test_2018 universe, alerts per 1000 cell-days / recall)

Layers in order: calibrated point risk against the card thresholds; plus the `uncertain_high` rule (upper interval bound reaches Watch); plus the blind-escalation rule; after hysteresis (the published level; the universe rows are random cell-days, mostly not on consecutive days, so hysteresis has little to hold here and its row is a small effect).

**Watch+**

| layer | alerts / 1000 cell-days | recall (in domain) | recall (all, OOD = miss) |
|---|---|---|---|
| point_risk | 218.03 | 0.863 | 0.812 |
| plus_uncertain_high | 266.51 | 0.912 | 0.859 |
| plus_blind_rule | 271.09 | 0.912 | 0.859 |
| after_hysteresis | 271.59 | 0.912 | 0.859 |

**Warning+**

| layer | alerts / 1000 cell-days | recall (in domain) | recall (all, OOD = miss) |
|---|---|---|---|
| point_risk | 91.40 | 0.688 | 0.647 |
| plus_uncertain_high | 91.40 | 0.688 | 0.647 |
| plus_blind_rule | 91.40 | 0.688 | 0.647 |
| after_hysteresis | 91.70 | 0.700 | 0.659 |

**Emergency+**

| layer | alerts / 1000 cell-days | recall (in domain) | recall (all, OOD = miss) |
|---|---|---|---|
| point_risk | 35.17 | 0.388 | 0.365 |
| plus_uncertain_high | 35.17 | 0.388 | 0.365 |
| plus_blind_rule | 35.17 | 0.388 | 0.365 |
| after_hysteresis | 35.39 | 0.388 | 0.365 |

### Same-day event detection (sample positives)

| events | detected | rate | with history | median lead (d) | lead >= 1 d | Watch+ | Warning+ | Emergency |
|---|---|---|---|---|---|---|---|---|
| 80 | 73 | 0.912 | 2 | 0.0 | 2 | 73 | 56 | 31 |

### Level and confidence mix (universe, weighted)

| Normal | Watch | Warning | Emergency | High conf. | Degraded | Insufficient |
|---|---|---|---|---|---|---|
| 0.7274 | 0.1803 | 0.0566 | 0.0358 | 0.7666 | 0.2331 | 0.0003 |

Confidence limited by (cell-days): imd_missing 19236, sources_disagree 17069, station_out_of_distribution 8892, stations_flagged_nearby 5741, all_nearby_stations_untrusted 1255.

### Blind escalations (universe)

| cell-days | blind-rule applies | level actually raised | cells raised | raised near an event | events covered |
|---|---|---|---|---|---|
| 200000 | 4997 | 1300 | 1069 | 0 | 0 |

Positives whose level was raised by the blind rule: 0.

the sample files hold the event day only, so lead time is 0 by construction; the universe rows are random cell-days (not consecutive), so flapping and area per day do not apply

## Window 2023 (2023-06-16 .. 2023-07-31)

| positive cells | detected (cell or 8 neighbours) | rate | other cells | other cells alerted any day | other cell-days alerted |
|---|---|---|---|---|---|
| 24 | 24 | 1.000 | 4069 | 0.909 | 0.6008 |

### Alerted area (sampled cells)

| days | cells/day | Watch+ share mean | Watch+ share max | Warning+ share mean | Watch+ km2 mean | Watch+ km2 max | peak day |
|---|---|---|---|---|---|---|---|
| 46 | 4093 | 0.6030 | 0.6968 | 0.3317 | 67348 | 78075 | 2023-06-28 |

### Flapping

| level used | cell-days | level changes | per 1000 | flaps | per 1000 |
|---|---|---|---|---|---|
| with hysteresis | 188278 | 29748 | 158.00 | 2390 | 12.69 |
| without hysteresis (raw level) | 188278 | 47613 | 252.89 | 4363 | 23.17 |

### Blind escalations

| cell-days | blind-rule applies | level actually raised | cells raised | raised near an event | events covered | raised in positive cells |
|---|---|---|---|---|---|---|
| 188278 | 10920 | 1565 | 717 | n/a | n/a | 1 |

### Level and confidence mix

| Normal | Watch | Warning | Emergency | High conf. | Degraded | Insufficient |
|---|---|---|---|---|---|---|
| 0.3970 | 0.2714 | 0.1445 | 0.1872 | 0.6830 | 0.3163 | 0.0007 |

Confidence limited by (cell-days): imd_missing 35788, sources_disagree 26975, station_out_of_distribution 12260, stations_flagged_nearby 7334, all_nearby_stations_untrusted 1579.

### Share of cell-days at each level after each layer

| level | point_risk | plus_uncertain_high | plus_blind_rule | after_hysteresis |
|---|---|---|---|---|
| Watch | 0.4827 | 0.5485 | 0.5568 | 0.6030 |
| Warning | 0.2611 | 0.2611 | 0.2611 | 0.3317 |
| Emergency | 0.1184 | 0.1184 | 0.1184 | 0.1872 |

window events have no dates, so detection is window-level; the table holds the sampled cells (positive cells and controls), so area is the sampled share, not a region total

## Kerala 2018 (2018-08-01 .. 2018-08-20, 8048 cells)

### Event detection with lead time

| events | detected | rate | with history | median lead (d) | lead >= 1 d | Watch+ | Warning+ | Emergency |
|---|---|---|---|---|---|---|---|---|
| 23 | 23 | 1.000 | 23 | 7.0 | 23 | 23 | 20 | 14 |

| cell | event day | detected | lead (d) | days available |
|---|---|---|---|---|
| 20405115 | 2018-08-05 | yes | 4 | 5 |
| 19945134 | 2018-08-08 | yes | 7 | 8 |
| 20035135 | 2018-08-08 | yes | 7 | 8 |
| 20115127 | 2018-08-08 | yes | 7 | 8 |
| 20345115 | 2018-08-08 | yes | 7 | 8 |
| 20565111 | 2018-08-08 | yes | 7 | 8 |
| 20305120 | 2018-08-09 | yes | 7 | 8 |
| 20375119 | 2018-08-09 | yes | 7 | 8 |
| 20385120 | 2018-08-09 | yes | 7 | 8 |
| 19945137 | 2018-08-15 | yes | 7 | 8 |
| 19965134 | 2018-08-15 | yes | 7 | 8 |
| 20235117 | 2018-08-15 | yes | 7 | 8 |
| 20495114 | 2018-08-15 | yes | 7 | 8 |
| 19965138 | 2018-08-16 | yes | 7 | 8 |
| 20065129 | 2018-08-16 | yes | 7 | 8 |
| 20065137 | 2018-08-16 | yes | 7 | 8 |
| 20375118 | 2018-08-16 | yes | 7 | 8 |
| 20485114 | 2018-08-16 | yes | 7 | 8 |
| 20025142 | 2018-08-17 | yes | 7 | 8 |
| 20485114 | 2018-08-17 | yes | 7 | 8 |
| 19955142 | 2018-08-18 | yes | 7 | 8 |
| 20565112 | 2018-08-18 | yes | 7 | 8 |
| 19925142 | 2018-08-19 | yes | 7 | 8 |

Lead time is limited by the days the case table holds before each event (`days available`).

### Alerted area per day

| days | cells/day | Watch+ share mean | Watch+ share max | Warning+ share mean | Watch+ km2 mean | Watch+ km2 max | peak day |
|---|---|---|---|---|---|---|---|
| 20 | 8048 | 0.4531 | 0.6667 | 0.2009 | 108790 | 159327 | 2018-08-17 |

### Flapping

| level used | cell-days | level changes | per 1000 | flaps | per 1000 |
|---|---|---|---|---|---|
| with hysteresis | 160960 | 19602 | 121.78 | 1659 | 10.31 |
| without hysteresis (raw level) | 160960 | 29921 | 185.89 | 3568 | 22.17 |

### Blind escalations

| cell-days | blind-rule applies | level actually raised | cells raised | raised near an event | events covered |
|---|---|---|---|---|---|
| 160960 | 18705 | 6485 | 1183 | 0 | 0 |

### Level and confidence mix

| Normal | Watch | Warning | Emergency | High conf. | Degraded | Insufficient |
|---|---|---|---|---|---|---|
| 0.5469 | 0.2522 | 0.0982 | 0.1027 | 0.7404 | 0.2595 | 0.0002 |

Confidence limited by (cell-days): sources_disagree 32087, station_out_of_distribution 26553, stations_flagged_nearby 9721, all_nearby_stations_untrusted 89.

### Share of cell-days at each level after each layer

| level | point_risk | plus_uncertain_high | plus_blind_rule | after_hysteresis |
|---|---|---|---|---|
| Watch | 0.3186 | 0.3686 | 0.4089 | 0.4531 |
| Warning | 0.1570 | 0.1570 | 0.1570 | 0.2009 |
| Emergency | 0.0698 | 0.0698 | 0.0698 | 0.1027 |

## Wayanad 2024 (2024-07-15 .. 2024-08-05, 140 cells)

### Alerted area per day

| days | cells/day | Watch+ share mean | Watch+ share max | Warning+ share mean | Watch+ km2 mean | Watch+ km2 max | peak day |
|---|---|---|---|---|---|---|---|
| 22 | 140 | 0.7461 | 0.9714 | 0.4795 | 3163 | 4117 | 2024-07-31 |

### Flapping

| level used | cell-days | level changes | per 1000 | flaps | per 1000 |
|---|---|---|---|---|---|
| with hysteresis | 3080 | 554 | 179.87 | 44 | 14.29 |
| without hysteresis (raw level) | 3080 | 797 | 258.77 | 68 | 22.08 |

### Blind escalations

| cell-days | blind-rule applies | level actually raised | cells raised | raised near an event | events covered |
|---|---|---|---|---|---|
| 3080 | 83 | 60 | 40 | n/a | n/a |

### Level and confidence mix

| Normal | Watch | Warning | Emergency | High conf. | Degraded | Insufficient |
|---|---|---|---|---|---|---|
| 0.2539 | 0.2666 | 0.1331 | 0.3464 | 0.9669 | 0.0331 | 0.0000 |

Confidence limited by (cell-days): sources_disagree 179.

### Share of cell-days at each level after each layer

| level | point_risk | plus_uncertain_high | plus_blind_rule | after_hysteresis |
|---|---|---|---|---|
| Watch | 0.6058 | 0.6675 | 0.6870 | 0.7461 |
| Warning | 0.3987 | 0.3987 | 0.3987 | 0.4795 |
| Emergency | 0.2510 | 0.2510 | 0.2510 | 0.3464 |

### Limitation: the alert levels saturate

Focus cell 20295122 (nearest the Mundakkai point, 0.8 km away) is at Emergency on every one of the 22 days. Over all cells the share at Emergency per day averages 0.346 (range 0.164 to 0.500). The calibrated risk takes 10 distinct values over the 22 days and its maximum (4.52e-04) is reached on 2024-07-17, 2024-07-30 (tied). The landslide struck on 2024-07-30: that day shares the maximum with 2024-07-17 (rank 1).

So the level cannot rank the days of this event, and the risk ordering gives no unique top day. This is a reported limitation of the model and the alert levels, not something tuned away: Wayanad is a never-tuned case study with no label, and no threshold or rule was changed after seeing it.

| date | level | risk | risk rank (1 = highest) |
|---|---|---|---|
| 2024-07-15 | Emergency | 2.27e-04 | 3 |
| 2024-07-16 | Emergency | 2.27e-04 | 3 |
| 2024-07-17 | Emergency | 4.52e-04 | 1 |
| 2024-07-18 | Emergency | 2.27e-04 | 3 |
| 2024-07-19 | Emergency | 2.27e-04 | 3 |
| 2024-07-20 | Emergency | 2.27e-04 | 3 |
| 2024-07-21 | Emergency | 8.14e-05 | 16 |
| 2024-07-22 | Emergency | 1.06e-04 | 15 |
| 2024-07-23 | Emergency | 1.23e-04 | 12 |
| 2024-07-24 | Emergency | 8.14e-05 | 16 |
| 2024-07-25 | Emergency | 1.23e-04 | 12 |
| 2024-07-26 | Emergency | 2.27e-04 | 3 |
| 2024-07-27 | Emergency | 2.27e-04 | 3 |
| 2024-07-28 | Emergency | 7.47e-05 | 18 |
| 2024-07-29 | Emergency | 4.26e-05 | 21 |
| 2024-07-30 | Emergency | 4.52e-04 | 1 |
| 2024-07-31 | Emergency | 1.83e-04 | 11 |
| 2024-08-01 | Emergency | 2.27e-04 | 3 |
| 2024-08-02 | Emergency | 1.23e-04 | 12 |
| 2024-08-03 | Emergency | 7.47e-05 | 18 |
| 2024-08-04 | Emergency | 6.43e-05 | 20 |
| 2024-08-05 | Emergency | 3.74e-05 | 22 |

no landslide label exists for this case (no NASA record), so no detection statistics
