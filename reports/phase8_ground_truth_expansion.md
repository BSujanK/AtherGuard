# Ground-truth expansion W1b: held-out assembly v2 (phase 8)

**Gate (storm clusters, all sources, deciding): 701 storm clusters of 1,266 independent slides (1,422 records) against the 150-event gate: MET, 551 over.** **Without BIPAD Nepal (no licence stated; its raw rows stay local and are never committed): 72 storm clusters of 87 slides (91 records): NOT MET, 78 short.** India only: 71 storm clusters, NOT MET, 79 short. No model was scored on any v2 event; this report only counts.

Rules (pre-declared in `docs/superpowers/specs/2026-11-13-aetherguard-w1b-ground-truth.md`): new records are dated to the day (no window record qualified), located to 5 km or better, in a scored cell, rain-triggered or cause unknown, deduplicated within and across sources (one day and 5 km, or the same cell and day). Independent slides merge records within 10 km and a day; storm clusters merge slides of one 1-degree tile within a fixed 5-day episode.

## Reading this report

- Every record in v2 was found by people reporting a slide (police, agencies, news, NASA catalogs built from news). None was mapped from imagery, so the set follows roads and settlements; an alert in an empty valley that verifies nothing is not shown to be false.
- BIPAD Nepal dominates the new records. Its location is the reporting ward (the incident point is a per-ward point), bounded by the ward's box; the 5 km bound keeps the small wards of hills and towns, which strengthens the settlement bias. Its register states no licence; the view without BIPAD is printed for that decision.
- A pass carried by Nepal records says nothing about skill in India. The India-only view is printed beside it, and any G1-G4 claim must be broken down by country.
- Ground truth stays very incomplete: precision on these records is relative (between models at matched burden), never an absolute false-alarm rate. Tolerant matching has a high chance floor at Watch+ and Warning+.

## Gate views (held-out records on panel days, June-December 2018-2025)

| view | what | records | slides | storm clusters | storm clusters (2-degree tiles) | verdict |
|---|---|---|---|---|---|---|
| all_sources | every source (deciding) | 1,422 | 1,266 | 701 | 539 | MET, 551 over |
| without_bipad | without BIPAD Nepal (its register states no licence: a user decision) | 91 | 87 | 72 | 66 | NOT MET, 78 short |
| india_only | records in Indian cells only | 90 | 86 | 71 | 65 | NOT MET, 79 short |
| nepal_bhutan_only | records in Nepal and Bhutan cells only | 1,331 | 1,180 | 631 | 476 | MET, 481 over |

The W1 part alone (2018 catalog, W1 reported, test_sparse) on panel days: 91 records, 87 slides, 72 storm clusters. 87 held-out records fall outside the panel days (January-May) and are counted, not scored.

## Held-out records on panel days

| source | records | slides | storm clusters |
|---|---|---|---|
| bipad_nepal | 1,331 | 1,179 | 630 |
| catalog_2018 | 55 | 52 | 39 |
| catalog_sparse | 6 | 6 | 6 |
| reported | 30 | 30 | 28 |

| year | records | slides | storm clusters |
|---|---|---|---|
| 2018 | 189 | 171 | 110 |
| 2019 | 174 | 152 | 85 |
| 2020 | 237 | 207 | 100 |
| 2021 | 165 | 142 | 73 |
| 2022 | 161 | 150 | 86 |
| 2023 | 132 | 121 | 66 |
| 2024 | 176 | 157 | 82 |
| 2025 | 188 | 166 | 99 |

| region | records | slides | storm clusters |
|---|---|---|---|
| himalaya | 1,379 | 1,226 | 672 |
| out_of_scope | 1 | 1 | 1 |
| western_ghats | 42 | 39 | 28 |

| country | records | slides | storm clusters |
|---|---|---|---|
| BD | 1 | 1 | 1 |
| IN | 90 | 86 | 71 |
| NP | 1,331 | 1,180 | 631 |

| how found | records | slides | storm clusters |
|---|---|---|---|
| reported | 1,422 | 1,266 | 701 |

| date precision | records |
|---|---|
| day | 1,422 |
| window (<= 7 days) | 0 |

Location bound of the new records (km): p25 3.06, p50 3.81, p75 4.32, p100 5.00.

Cross-source duplicates dropped: 8 (bipad_nepal -> bipad_nepal 2, bipad_nepal -> catalog_2018 1, bipad_nepal -> gfld 2, catalog_2018 -> catalog_2018 1, catalog_sparse -> reported 2). New records outside the scored cells: 120.

## Development labels added (2007-2017)

506 records not repeating an existing development positive (103 dropped as repeats or duplicates). By source: bipad_nepal 142, gfld 364; by country: BT 3, IN 139, NP 364; by year: 2007 43, 2008 40, 2009 45, 2010 28, 2011 55, 2012 53, 2013 47, 2014 36, 2015 34, 2016 83, 2017 42. Nothing was retrained; using them is a separate, declared step.

## Frozen files

- `processed/heldout_v2`: manifest sha256 `146a30c7a4e8c6c20a44015099f7813250c3ffcb4f1fd141536651cb822932a2`; `events.parquet` `8dbef353f1a8499b`, `window_events.parquet` `d570eb598312c32c`
- `processed/labels_dev_v2`: manifest sha256 `fb5c6f6871b968d5247609e59a88632cbc552034fd1e7cbb4376e613aadca871`; `added_positives.parquet` `2c254d683573ce88`

## Next step (the lead's)

READY FOR HELD-OUT LOOK. The verdict rests on BIPAD Nepal: from sources with a known open licence the gate is not met, and until the register's terms are known a G1-G4 claim must be stated both ways. The W1 held-out report re-run on assembly v2 (writes `reports/phase8_heldout_v2.{json,md}`, never the phase 7 report): `python -m aetherguard.verify heldout --assembly data/processed/heldout_v2 --stem phase8_heldout_v2`. It is a held-out look and follows the one-look-per-adopted-change rule.
