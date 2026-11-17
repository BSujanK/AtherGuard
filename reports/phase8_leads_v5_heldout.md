# Forecast leads on v4-static (leads v5): the held-out look

**v4-static forecast leads (candidate s): ADOPTED** by the rule of spec amendment 2, declared before the look: the development gate passed, and the 2025 no-harm veto was not triggered (NET_ALL = -2 against the threshold 13, NET_CE = 0 against 4; a negative net means the candidate caught more slides than the incumbent). The deciding 2025 set holds only 3 independent W1 slide(s) per lead, so the look could only have stopped a gross loss; it is no evidence of a gain.

Taken once (2026-11-17T02:43:00+00:00). Spec docs/superpowers/specs/2026-11-17-aetherguard-leads-v5.md, amendment 2; preflight reports/phase8_leads_v5_preflight.md. Research prototype, not validated for issuing real public warnings.

## Deciding: licence-clean W1 assembly, June-September 2025 (fresh)

Each lead's candidate levels are burden-matched to the incumbent lead's realised 2025 shares.

| lead | tolerance | level | slides detected, incumbent (v3) | slides detected, candidate | slides | alert cell-days, incumbent | alert cell-days, candidate |
|---|---|---|---|---|---|---|---|
| 1 | tolerant | Watch+ | 3 | 3 | 3 | 2,596,664 | 2,596,664 |
| 1 | tolerant | Warning+ | 3 | 3 | 3 | 1,023,993 | 1,023,993 |
| 1 | tolerant | Emergency | 3 | 3 | 3 | 371,793 | 371,793 |
| 1 | cell_exact | Watch+ | 3 | 3 | 3 | 2,596,664 | 2,596,664 |
| 1 | cell_exact | Warning+ | 2 | 2 | 3 | 1,023,993 | 1,023,993 |
| 1 | cell_exact | Emergency | 2 | 2 | 3 | 371,793 | 371,793 |
| 2 | tolerant | Watch+ | 3 | 3 | 3 | 2,678,660 | 2,678,660 |
| 2 | tolerant | Warning+ | 3 | 3 | 3 | 1,083,845 | 1,083,845 |
| 2 | tolerant | Emergency | 2 | 3 | 3 | 373,745 | 373,745 |
| 2 | cell_exact | Watch+ | 3 | 3 | 3 | 2,678,660 | 2,678,660 |
| 2 | cell_exact | Warning+ | 2 | 2 | 3 | 1,083,845 | 1,083,845 |
| 2 | cell_exact | Emergency | 2 | 2 | 3 | 373,745 | 373,745 |
| 3 | tolerant | Watch+ | 3 | 3 | 3 | 2,430,063 | 2,430,063 |
| 3 | tolerant | Warning+ | 3 | 3 | 3 | 923,494 | 923,494 |
| 3 | tolerant | Emergency | 2 | 3 | 3 | 369,238 | 369,238 |
| 3 | cell_exact | Watch+ | 3 | 3 | 3 | 2,430,063 | 2,430,063 |
| 3 | cell_exact | Warning+ | 2 | 2 | 3 | 923,494 | 923,494 |
| 3 | cell_exact | Emergency | 2 | 2 | 3 | 369,238 | 369,238 |

### The no-harm veto (amendment 2 b)

| lead | tolerance | level | incumbent | candidate | net loss (incumbent - candidate) |
|---|---|---|---|---|---|
| 1 | tolerant | Warning+ | 3 | 3 | 0 |
| 1 | tolerant | Emergency | 3 | 3 | 0 |
| 1 | cell_exact | Warning+ | 2 | 2 | 0 |
| 1 | cell_exact | Emergency | 2 | 2 | 0 |
| 2 | tolerant | Warning+ | 3 | 3 | 0 |
| 2 | tolerant | Emergency | 2 | 3 | -1 |
| 2 | cell_exact | Warning+ | 2 | 2 | 0 |
| 2 | cell_exact | Emergency | 2 | 2 | 0 |
| 3 | tolerant | Warning+ | 3 | 3 | 0 |
| 3 | tolerant | Emergency | 2 | 3 | -1 |
| 3 | cell_exact | Warning+ | 2 | 2 | 0 |
| 3 | cell_exact | Emergency | 2 | 2 | 0 |

NET_ALL = -2 (veto at >= 13); NET_CE = 0 (veto at >= 4). Veto triggered: no.

## Development gate (amendment 2 a, no event read)

Gate PASSED. Rule: every lead: burden within 20% of the reference at Watch, Warning, Emergency; Warning+ recall >= incumbent's.
Gate file sha256 `597057e713fe172b9beca287d945f8c87bb9f00d64005dd75d6f001263687376` (reports/phase8_leads_v5_e1.json), frozen by the preflight.

Decision: adopt = true (gate passed = True, veto triggered = False).

## Beside it, NOT deciding

### W1 2021-2024: ALREADY LOOKED AT by the v4-leads look (second look on the same events; decides nothing)

Independent slides on the target days: lead 1 22, lead 2 22, lead 3 22.

| lead | tolerance | level | slides detected, incumbent (v3) | slides detected, candidate | slides | alert cell-days, incumbent | alert cell-days, candidate |
|---|---|---|---|---|---|---|---|
| 1 | tolerant | Watch+ | 22 | 22 | 22 | 9,879,332 | 9,879,332 |
| 1 | tolerant | Warning+ | 22 | 22 | 22 | 3,980,404 | 3,980,404 |
| 1 | tolerant | Emergency | 19 | 21 | 22 | 1,519,172 | 1,519,172 |
| 1 | cell_exact | Watch+ | 20 | 21 | 22 | 9,879,332 | 9,879,332 |
| 1 | cell_exact | Warning+ | 16 | 20 | 22 | 3,980,404 | 3,980,404 |
| 1 | cell_exact | Emergency | 13 | 15 | 22 | 1,519,172 | 1,519,172 |
| 2 | tolerant | Watch+ | 22 | 22 | 22 | 9,979,959 | 9,979,959 |
| 2 | tolerant | Warning+ | 22 | 21 | 22 | 3,973,793 | 3,973,793 |
| 2 | tolerant | Emergency | 18 | 20 | 22 | 1,468,339 | 1,468,339 |
| 2 | cell_exact | Watch+ | 21 | 21 | 22 | 9,979,959 | 9,979,959 |
| 2 | cell_exact | Warning+ | 15 | 19 | 22 | 3,973,793 | 3,973,793 |
| 2 | cell_exact | Emergency | 8 | 13 | 22 | 1,468,339 | 1,468,339 |
| 3 | tolerant | Watch+ | 22 | 22 | 22 | 9,606,050 | 9,606,050 |
| 3 | tolerant | Warning+ | 22 | 22 | 22 | 3,743,287 | 3,743,287 |
| 3 | tolerant | Emergency | 18 | 21 | 22 | 1,464,847 | 1,464,847 |
| 3 | cell_exact | Watch+ | 21 | 21 | 22 | 9,606,050 | 9,606,050 |
| 3 | cell_exact | Warning+ | 17 | 19 | 22 | 3,743,287 | 3,743,287 |
| 3 | cell_exact | Emergency | 11 | 17 | 22 | 1,464,847 | 1,464,847 |

### assembly v2 2025, all records (includes the BIPAD Nepal register: no stated licence, rows local only; decides nothing)

Independent slides on the target days: lead 1 142, lead 2 142, lead 3 141.

| lead | tolerance | level | slides detected, incumbent (v3) | slides detected, candidate | slides | alert cell-days, incumbent | alert cell-days, candidate |
|---|---|---|---|---|---|---|---|
| 1 | tolerant | Watch+ | 142 | 142 | 142 | 2,596,664 | 2,596,664 |
| 1 | tolerant | Warning+ | 141 | 141 | 142 | 1,023,993 | 1,023,993 |
| 1 | tolerant | Emergency | 132 | 139 | 142 | 371,793 | 371,793 |
| 1 | cell_exact | Watch+ | 142 | 142 | 142 | 2,596,664 | 2,596,664 |
| 1 | cell_exact | Warning+ | 116 | 129 | 142 | 1,023,993 | 1,023,993 |
| 1 | cell_exact | Emergency | 59 | 101 | 142 | 371,793 | 371,793 |
| 2 | tolerant | Watch+ | 142 | 142 | 142 | 2,678,660 | 2,678,660 |
| 2 | tolerant | Warning+ | 141 | 142 | 142 | 1,083,845 | 1,083,845 |
| 2 | tolerant | Emergency | 131 | 139 | 142 | 373,745 | 373,745 |
| 2 | cell_exact | Watch+ | 141 | 142 | 142 | 2,678,660 | 2,678,660 |
| 2 | cell_exact | Warning+ | 127 | 132 | 142 | 1,083,845 | 1,083,845 |
| 2 | cell_exact | Emergency | 63 | 106 | 142 | 373,745 | 373,745 |
| 3 | tolerant | Watch+ | 140 | 141 | 141 | 2,430,063 | 2,430,063 |
| 3 | tolerant | Warning+ | 137 | 140 | 141 | 923,494 | 923,494 |
| 3 | tolerant | Emergency | 121 | 138 | 141 | 369,238 | 369,238 |
| 3 | cell_exact | Watch+ | 139 | 141 | 141 | 2,430,063 | 2,430,063 |
| 3 | cell_exact | Warning+ | 114 | 127 | 141 | 923,494 | 923,494 |
| 3 | cell_exact | Emergency | 55 | 90 | 141 | 369,238 | 369,238 |

### assembly v2 2025 without the BIPAD register (decides nothing)

Independent slides on the target days: lead 1 3, lead 2 3, lead 3 3.

| lead | tolerance | level | slides detected, incumbent (v3) | slides detected, candidate | slides | alert cell-days, incumbent | alert cell-days, candidate |
|---|---|---|---|---|---|---|---|
| 1 | tolerant | Watch+ | 3 | 3 | 3 | 2,596,664 | 2,596,664 |
| 1 | tolerant | Warning+ | 3 | 3 | 3 | 1,023,993 | 1,023,993 |
| 1 | tolerant | Emergency | 3 | 3 | 3 | 371,793 | 371,793 |
| 1 | cell_exact | Watch+ | 3 | 3 | 3 | 2,596,664 | 2,596,664 |
| 1 | cell_exact | Warning+ | 2 | 2 | 3 | 1,023,993 | 1,023,993 |
| 1 | cell_exact | Emergency | 2 | 2 | 3 | 371,793 | 371,793 |
| 2 | tolerant | Watch+ | 3 | 3 | 3 | 2,678,660 | 2,678,660 |
| 2 | tolerant | Warning+ | 3 | 3 | 3 | 1,083,845 | 1,083,845 |
| 2 | tolerant | Emergency | 2 | 3 | 3 | 373,745 | 373,745 |
| 2 | cell_exact | Watch+ | 3 | 3 | 3 | 2,678,660 | 2,678,660 |
| 2 | cell_exact | Warning+ | 2 | 2 | 3 | 1,083,845 | 1,083,845 |
| 2 | cell_exact | Emergency | 2 | 2 | 3 | 373,745 | 373,745 |
| 3 | tolerant | Watch+ | 3 | 3 | 3 | 2,430,063 | 2,430,063 |
| 3 | tolerant | Warning+ | 3 | 3 | 3 | 923,494 | 923,494 |
| 3 | tolerant | Emergency | 2 | 3 | 3 | 369,238 | 369,238 |
| 3 | cell_exact | Watch+ | 3 | 3 | 3 | 2,430,063 | 2,430,063 |
| 3 | cell_exact | Warning+ | 2 | 2 | 3 | 923,494 | 923,494 |
| 3 | cell_exact | Emergency | 2 | 2 | 3 | 369,238 | 369,238 |

### assembly v2 2025, India only (decides nothing)

Independent slides on the target days: lead 1 3, lead 2 3, lead 3 3.

| lead | tolerance | level | slides detected, incumbent (v3) | slides detected, candidate | slides | alert cell-days, incumbent | alert cell-days, candidate |
|---|---|---|---|---|---|---|---|
| 1 | tolerant | Watch+ | 3 | 3 | 3 | 2,596,664 | 2,596,664 |
| 1 | tolerant | Warning+ | 3 | 3 | 3 | 1,023,993 | 1,023,993 |
| 1 | tolerant | Emergency | 3 | 3 | 3 | 371,793 | 371,793 |
| 1 | cell_exact | Watch+ | 3 | 3 | 3 | 2,596,664 | 2,596,664 |
| 1 | cell_exact | Warning+ | 2 | 2 | 3 | 1,023,993 | 1,023,993 |
| 1 | cell_exact | Emergency | 2 | 2 | 3 | 371,793 | 371,793 |
| 2 | tolerant | Watch+ | 3 | 3 | 3 | 2,678,660 | 2,678,660 |
| 2 | tolerant | Warning+ | 3 | 3 | 3 | 1,083,845 | 1,083,845 |
| 2 | tolerant | Emergency | 2 | 3 | 3 | 373,745 | 373,745 |
| 2 | cell_exact | Watch+ | 3 | 3 | 3 | 2,678,660 | 2,678,660 |
| 2 | cell_exact | Warning+ | 2 | 2 | 3 | 1,083,845 | 1,083,845 |
| 2 | cell_exact | Emergency | 2 | 2 | 3 | 373,745 | 373,745 |
| 3 | tolerant | Watch+ | 3 | 3 | 3 | 2,430,063 | 2,430,063 |
| 3 | tolerant | Warning+ | 3 | 3 | 3 | 923,494 | 923,494 |
| 3 | tolerant | Emergency | 2 | 3 | 3 | 369,238 | 369,238 |
| 3 | cell_exact | Watch+ | 3 | 3 | 3 | 2,430,063 | 2,430,063 |
| 3 | cell_exact | Warning+ | 2 | 2 | 3 | 923,494 | 923,494 |
| 3 | cell_exact | Emergency | 2 | 2 | 3 | 369,238 | 369,238 |

## Caveats

- Low power: the deciding set has 3, 3, 3 independent W1 slides (leads 1, 2, 3) and 3, 3, 3 records. The veto can stop a gross loss only; adoption rests on the development evidence (spec sections 2 and 7).
- GFS fallback: in the development gate, leads 2 and 3 used the GFS fallback on the issue days without an ECMWF archive (2022 and part of 2023; counts in reports/phase8_leads_v5_e1.json).
- The idea came partly from the pattern of the spent v4-leads look (spec section 1); 2021-2024 is therefore beside only, as a second look.
- Ground truth after 2018 is very incomplete; precision is relative.
