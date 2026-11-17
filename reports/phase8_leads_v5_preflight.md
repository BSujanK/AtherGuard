# Forecast leads on v4-static (leads v5): preflight of the held-out look (no outcome computed)

Spec: docs/superpowers/specs/2026-11-17-aetherguard-leads-v5.md (written before any held-out number). Research prototype, not validated for issuing real public warnings. The preflight joins no event with a level.

Candidate **s** (v4-static at leads 1-3). Deciding season: 2025 June-September (fresh). Beside only: 2021, 2022, 2023, 2024. Generated 2026-11-17T02:35:45+00:00.

## Frozen inputs

| file | sha256 |
|---|---|
| panel 2025 | `101c79ec0a7b812732136f8fe0d46ffdb670433c07f14742d3b4328a79066037` |
| panel 2021 | `470be4dda2e8990c6afb61ad3485b33a3de9b2958a6a869b6069b41fdfb76a96` |
| panel 2022 | `cf01cca9e0aa45b76b2a4b9e5c089bec66c8ccc8f4d0c28994934965d4e2dbea` |
| panel 2023 | `6a3e1857faa8de2d66b987400b7ed80ea58cbcbc58fe82d898531481bf3301ce` |
| panel 2024 | `86779ba15d1858c405dadd9fdba719c4f28a9502be735ed5b52782adb6bcb41d` |
| v4-static model.txt | `d2344a1d1df28077e5d57b9721ef711e84626ab7e85987a769968375eb697817` |
| v4-static card.json | `536230304ada22fdb2608b21198b792e91fc0f164f33d5e5e7da9bb5b9161db6` |
| v4-static calibrator.json | `0e9016c7e0fb0d7e2c8e6bfcf8afee7618de942289107d6717eb1afc7287cb31` |
| v4-static calibrator_regions.json | `8a67b526a251184e804496b001c9e9910405c39a66e867a0b58dec778ce9c5fb` |

## Development gate: E1 (amendment 2 a; no event read)

Years 2022, 2023, 2024, 2536 cells (seed 20261115). Reference: published v4 lead-0 level of the target day from observed features (Late lag-1 intensity, static).

| lead | candidate | days | agreement | Warning+ recall | Emergency recall | Watch / Warning / Emergency share | reference shares |
|---|---|---|---|---|---|---|---|
| 1 | c | 366 | 0.6555 | 0.7529 | 0.5688 | 32.68% / 13.02% / 8.47% | 29.77% / 9.62% / 3.94% |
| 1 | s | 366 | 0.8026 | 0.7699 | 0.5701 | 30.53% / 11.07% / 4.05% | 29.77% / 9.62% / 3.94% |
| 2 | c | 366 | 0.6425 | 0.7436 | 0.5477 | 33.24% / 13.41% / 8.33% | 29.84% / 9.63% / 3.94% |
| 2 | s | 366 | 0.7881 | 0.7582 | 0.5493 | 31.35% / 11.17% / 3.95% | 29.84% / 9.63% / 3.94% |
| 3 | c | 366 | 0.6455 | 0.6778 | 0.5056 | 32.05% / 11.68% / 8.30% | 29.91% / 9.65% / 3.94% |
| 3 | s | 366 | 0.7739 | 0.6949 | 0.5086 | 29.84% / 10.06% / 4.01% | 29.91% / 9.65% / 3.94% |

Gate: **PASSED**. Rule: every lead: burden within 20% of the reference at Watch, Warning, Emergency; Warning+ recall >= incumbent's.

Preflight froze the gate verdict (passed = True) and the gate file (sha256 `597057e713fe172b9beca287d945f8c87bb9f00d64005dd75d6f001263687376`). Decision rule: amendment 2: adoption = development gate passed AND 2025 veto not triggered (NET_ALL >= 13 or NET_CE >= 4 over the 12 W1 rows, incumbent minus candidate slides).

## Deciding season: burden matching and events (W1)

| lead | target days | scored cell-days | issue days scored | target W+ / Wa+ / E | realised W+ / Wa+ / E | straddle | W1 events on days | outside | independent slides |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 122 | 4,488,557 | 122 | 57.8508% / 22.8134% / 8.2831% | 57.8508% / 22.8134% / 8.2831% | 0, 0, 1 | 3 | 0 | 3 |
| 2 | 122 | 4,488,624 | 122 | 59.6766% / 24.1465% / 8.3265% | 59.6766% / 24.1465% / 8.3265% | 0, 0, 1 | 3 | 0 | 3 |
| 3 | 122 | 4,488,624 | 122 | 54.1383% / 20.5741% / 8.2261% | 54.1383% / 20.5741% / 8.2261% | 0, 0, 0 | 3 | 0 | 3 |

## Beside, deciding nothing (dates only)

| set | lead | events on days | outside | independent slides |
|---|---|---|---|---|
| W1 2021-2024 (ALREADY LOOKED AT by the v4-leads look: a second look, beside only) | 1 | 22 | 2 | 22 |
| W1 2021-2024 (ALREADY LOOKED AT by the v4-leads look: a second look, beside only) | 2 | 22 | 2 | 22 |
| W1 2021-2024 (ALREADY LOOKED AT by the v4-leads look: a second look, beside only) | 3 | 22 | 2 | 22 |
| assembly v2 2025, all records (includes the BIPAD Nepal register: no stated licence, rows local only) | 1 | 154 | 62 | 142 |
| assembly v2 2025, all records (includes the BIPAD Nepal register: no stated licence, rows local only) | 2 | 154 | 62 | 142 |
| assembly v2 2025, all records (includes the BIPAD Nepal register: no stated licence, rows local only) | 3 | 153 | 63 | 141 |
| assembly v2 2025 without the BIPAD register | 1 | 3 | 0 | 3 |
| assembly v2 2025 without the BIPAD register | 2 | 3 | 0 | 3 |
| assembly v2 2025 without the BIPAD register | 3 | 3 | 0 | 3 |
| assembly v2 2025, India only | 1 | 3 | 0 | 3 |
| assembly v2 2025, India only | 2 | 3 | 0 | 3 |
| assembly v2 2025, India only | 3 | 3 | 0 | 3 |

## Checks

- lead 1: burden matched within tolerance every season: passed
- lead 2: burden matched within tolerance every season: passed
- lead 3: burden matched within tolerance every season: passed
- every panel scored with the v4-static files on disk: passed

## Power

The deciding season holds 3 independent W1 slide(s) per lead, so the 2025 look can only veto a gross loss (spec amendment 2: reports/phase8_leads_v5_veto.json gives the pass and block probabilities).
