# W1b: second ground-truth expansion, held-out assembly v2 (pre-declared)

Date: 2026-11-13. Status: pre-declared. Written after the source survey and after the per-source inventories were built
(their admitted row counts per year are known), but before any record was assembled, deduplicated across sources,
clustered or counted against the 150-event gate, and before any model was scored on a new event. Roadmap §2 (gate),
§3 (protocol v3), §4 W1. Survey: `reports/phase8_ground_truth_survey.md`.

## 1. What enters assembly v2

| stratum | sources | years | how found |
|---|---|---|---|
| held-out, day-precise | the W1 assembly unchanged (2018 catalog `test_2018`, the 30 W1 reported events, the in-domain `test_sparse` catalog positives); BIPAD Nepal | 2018-2025 | catalog and W1: reported; BIPAD: reported (Nepal Police and agencies) |
| held-out, window | imagery-mapped inventories with a window of at most 7 days | 2018-2025 | imagery |
| development labels | GFLD v2; BIPAD Nepal | 2007-2017 | reported |
| live | BIPAD Nepal from 2026-10-09 (review queue only, never auto-admitted) | 2026 | reported |

The W1 frozen assembly and the frozen splits are never modified; v2 is a new directory.

## 2. Admission (new sources)

- Date: known to the day (`date_basis` stated), or a stated window of at most `MAX_WINDOW_DAYS` = 7 days (`window`).
  Longer windows (the Kerala 2018 inventory of Hao et al. 2020 is dated only to 1 June - 26 August 2018) are recorded
  in the survey and never scored as dated events.
- Location: `accuracy_km` at most 5 km. For BIPAD this is the distance from the incident point to the farthest corner
  of its ward's bounding box (the point is a per-ward point, so the ward is the location); for GFLD the radius of a
  circle with the area of the mapped polygon. The W1 rows keep the limit they were admitted at (10 km).
- Domain: the record's 0.05-degree cell must be a scored cell (`live.backtest.universe_cell_ids`, 36,792 cells,
  India, Nepal and Bhutan). A record in a box but outside the scored cells is rejected (`outside_scored_cells`).
- Cause: trigger rain or unknown. Earthquake, construction or mining, snow, any other named cause and any glacial lake
  outburst are rejected with the reason kept. BIPAD records of hazard "Landslide" with no cause count as unknown.
- QA: every admitted row has a QA record in its source's `qa/qa_results.csv` (rule checks for every row, a manual
  spot-check of a random sample against an independent report); a QA action (correct / exclude) applies to the whole
  duplicate group (the W1 rule, `inventory._apply_corrections`). An admitted row without a QA record is flagged.

## 3. Duplicates

Within a source: the W1 rule (`inventory._duplicate`): the same cell on the same day, or within one day and 5 km.
Across sources, in assembly v2: the same rule on cell centres (W1 catalog events carry only a cell), with priority
W1 assembly > GFLD > BIPAD; the kept record takes the earliest date of its group. A window record never merges with a
day record.

## 4. Matching of window records

A window record is detected at level L when an alert at level >= L lies within 10 km of it on any day from the
window's first day minus 1 to its last day plus 1. It is reported in its own stratum, with its own counts, and is
never pooled with the day-precise records in a headline number; any pooled figure must show the breakdown beside it.
Assembly v2 holds no window record (section 7), so the held-out runner refuses a non-empty window table rather than
mixing it.

## 5. Independence and the gate count

Three counts are reported for every set:

1. **records** (cell-days after duplicates);
2. **independent slides**: the W1 rule, records within 10 km and 1 day merge (single linkage, `heldout.event_clusters`);
3. **storm clusters**: slides in the same 1-degree tile (by the floor of the cell centre's latitude and longitude)
   whose dates fall in one storm episode. Within a tile, slides are taken in date order; an episode opens on the first
   slide not yet assigned and holds every slide of the tile dated up to 4 days after that opening day (a fixed 5-day
   window, no chaining, so a wet season does not collapse into one cluster). A 2-degree tile is reported as a
   sensitivity.

**The gate uses storm clusters.** Records from one storm share the same rain forcing and the same model inputs, so the
model's skill on them is close to one draw: 40 ward reports of one July deluge in central Nepal are not 40 tests. The
slide count already merges reports of one slide, but not neighbouring slides of one storm. The storm-cluster count is
the stricter of the two and is the honest basis for a claim; the slide count is shown beside it.

The gate set is the POOLED held-out set on panel days (June-December of 2018-2025), day-precise stratum only. The
verdict is printed four ways, the first deciding: all sources; without BIPAD (its register states no licence, a user
decision); India only; Nepal and Bhutan only. A pass carried by Nepal records shows nothing about India, and the report
says so.

## 6. Development labels

GFLD and BIPAD records of 2007-2017 that pass section 2 and are not within 1 day and 5 km (or the same cell and day) of
an existing development positive (`positive_cell_days.parquet`, splits train and validation) form a new table
`data/processed/labels_dev_v2/added_positives.parquet`. Nothing is retrained in W1b; using the table is a later,
separately declared step (a new label source changes the development folds' class balance and must be read under
protocol v3).

## 7. Known content at the time of writing (not results)

- The open survey found no imagery-mapped inventory inside the scored cells dated to 7 days or better: the window
  stratum is empty in v2.
- BIPAD records are reported by police and agencies, so they follow roads and settlements like the W1 news rows, and
  the 5 km bound keeps mostly small (hill and town) wards, which strengthens that bias.

## 8. What is not done in W1b

No model is scored on a v2 event. The held-out look on v2 belongs to the lead and follows the existing per-change
rule (one look per adopted change, criterion declared first). The command that would re-run the W1 report on v2 is
written into `reports/phase8_ground_truth_expansion.md`.
