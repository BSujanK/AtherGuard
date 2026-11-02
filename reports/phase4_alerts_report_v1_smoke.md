# Phase 4 alert report

> **PROVISIONAL: v1 hazard model smoke check (not the frozen protocol-v2 model).** Numbers below come from a model that is not the frozen one; they only demonstrate that the pipeline runs and must not be quoted as results.

Thresholds (v1_card_fallback (watch: recall=0.9, warning: fa_share=0.05, emergency: fa_share=0.01)): Watch 1.40e-05, Warning 3.68e-05, Emergency 1.09e-04 (calibrated risk per cell-day).
Model card sha256: `6a1fc4d4a21e990e4905a462151d5f75f143a8d12c7ea18b3613b359edc3dd07`.
Lead window: Watch+ on the event day or within 7 days before; a flap is a Watch+ alert off and on again within 3 days.

## test_2018 (universe + positives)

80 in-domain positive cell-days plus 5 out-of-domain (counted as misses); event base rate 0.000006 per cell-day.

| level | alerts / 1000 cell-days | recall (in domain) | recall (all, OOD = miss) |
|---|---|---|---|
| Watch | 250.29 | 0.850 | 0.800 |
| Warning | 63.55 | 0.562 | 0.529 |
| Emergency | 8.01 | 0.200 | 0.188 |

### Cost-loss

An alert is optimal when risk >= C/L, so each threshold is the cost ratio at which it is optimal. `relative expense` is expense / min(never alert, always alert); below 1 the rule beats both.

| rule | threshold | C/L | alerts / 1000 | recall | relative expense |
|---|---|---|---|---|---|
| watch threshold | 1.40e-05 | 1.40e-05 | 180.60 | 0.787 | 0.611 |
| warning threshold | 3.68e-05 | 3.68e-05 | 63.23 | 0.562 | 0.805 |
| emergency threshold | 1.09e-04 | 1.09e-04 | 7.93 | 0.200 | 0.936 |
| C/L = 1/10 | 0.100 | 0.100 | 2.19e-03 | 0.000 | 1.035 |
| C/L = 1/50 | 0.020 | 0.020 | 2.19e-03 | 0.000 | 1.007 |
| C/L = 1/200 | 0.005 | 0.005 | 2.19e-03 | 0.000 | 1.002 |

### Same-day event detection (sample positives)

| events | detected | rate | with history | median lead (d) | lead >= 1 d | Watch+ | Warning+ | Emergency |
|---|---|---|---|---|---|---|---|---|
| 80 | 68 | 0.850 | 2 | 0.0 | 2 | 68 | 45 | 16 |

### Level and confidence mix (universe, weighted)

| Normal | Watch | Warning | Emergency | High conf. | Degraded | Insufficient |
|---|---|---|---|---|---|---|
| 0.7487 | 0.1872 | 0.0559 | 0.0082 | 0.7666 | 0.2331 | 0.0003 |

### Blind escalations (universe)

| cell-days | blind-rule applies | level actually raised | cells raised | raised near an event | events covered |
|---|---|---|---|---|---|
| 200000 | 4997 | 1439 | 1144 | 0 | 0 |

Positives whose level was raised by the blind rule: 0.

the sample files hold the event day only, so lead time is 0 by construction; the universe rows are random cell-days (not consecutive), so flapping and area per day do not apply

## Window 2023 (2023-06-16 .. 2023-07-31)

| positive cells | detected (cell or 8 neighbours) | rate | other cells | other cells alerted any day | other cell-days alerted |
|---|---|---|---|---|---|
| 24 | 24 | 1.000 | 4069 | 0.899 | 0.5386 |

### Alerted area (sampled cells)

| days | cells/day | Watch+ share mean | Watch+ share max | Warning+ share mean | Watch+ km2 mean | Watch+ km2 max | peak day |
|---|---|---|---|---|---|---|---|
| 46 | 4093 | 0.5410 | 0.6609 | 0.2479 | 60383 | 73844 | 2023-06-27 |

### Flapping

| level used | cell-days | level changes | per 1000 | flaps | per 1000 |
|---|---|---|---|---|---|
| with hysteresis | 188278 | 31095 | 165.15 | 3132 | 16.63 |
| without hysteresis (raw level) | 188278 | 46166 | 245.20 | 5983 | 31.78 |

### Blind escalations

| cell-days | blind-rule applies | level actually raised | cells raised | raised near an event | events covered | raised in positive cells |
|---|---|---|---|---|---|---|
| 188278 | 10920 | 1913 | 827 | n/a | n/a | 1 |

### Level and confidence mix

| Normal | Watch | Warning | Emergency | High conf. | Degraded | Insufficient |
|---|---|---|---|---|---|---|
| 0.4590 | 0.2931 | 0.1940 | 0.0539 | 0.6830 | 0.3163 | 0.0007 |

window events have no dates, so detection is window-level; the table holds the sampled cells (positive cells and controls), so area is the sampled share, not a region total

## Kerala 2018 (2018-08-01 .. 2018-08-20, 8048 cells)

### Event detection with lead time

| events | detected | rate | with history | median lead (d) | lead >= 1 d | Watch+ | Warning+ | Emergency |
|---|---|---|---|---|---|---|---|---|
| 23 | 23 | 1.000 | 23 | 7.0 | 23 | 23 | 19 | 13 |

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
| 20385120 | 2018-08-09 | yes | 1 | 8 |
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
| 20 | 8048 | 0.4326 | 0.6485 | 0.1708 | 104027 | 155021 | 2018-08-17 |

### Flapping

| level used | cell-days | level changes | per 1000 | flaps | per 1000 |
|---|---|---|---|---|---|
| with hysteresis | 160960 | 18780 | 116.67 | 1955 | 12.15 |
| without hysteresis (raw level) | 160960 | 29387 | 182.57 | 4347 | 27.01 |

### Blind escalations

| cell-days | blind-rule applies | level actually raised | cells raised | raised near an event | events covered |
|---|---|---|---|---|---|
| 160960 | 18705 | 8584 | 1291 | 0 | 0 |

### Level and confidence mix

| Normal | Watch | Warning | Emergency | High conf. | Degraded | Insufficient |
|---|---|---|---|---|---|---|
| 0.5674 | 0.2617 | 0.1224 | 0.0484 | 0.7404 | 0.2595 | 0.0002 |

## Wayanad 2024 (2024-07-15 .. 2024-08-05, 140 cells)

### Alerted area per day

| days | cells/day | Watch+ share mean | Watch+ share max | Warning+ share mean | Watch+ km2 mean | Watch+ km2 max | peak day |
|---|---|---|---|---|---|---|---|
| 22 | 140 | 0.7432 | 0.9714 | 0.4653 | 3150 | 4117 | 2024-07-31 |

### Flapping

| level used | cell-days | level changes | per 1000 | flaps | per 1000 |
|---|---|---|---|---|---|
| with hysteresis | 3080 | 630 | 204.55 | 61 | 19.81 |
| without hysteresis (raw level) | 3080 | 914 | 296.75 | 99 | 32.14 |

### Blind escalations

| cell-days | blind-rule applies | level actually raised | cells raised | raised near an event | events covered |
|---|---|---|---|---|---|
| 3080 | 83 | 69 | 45 | n/a | n/a |

### Level and confidence mix

| Normal | Watch | Warning | Emergency | High conf. | Degraded | Insufficient |
|---|---|---|---|---|---|---|
| 0.2568 | 0.2779 | 0.2610 | 0.2042 | 0.9669 | 0.0331 | 0.0000 |

no landslide label exists for this case (no NASA record), so no detection statistics
