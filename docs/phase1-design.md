# Phase 1 design addendum — ingest, labels, frozen splits, feature store

Status: decided by the controller on 2026-09-30 from the Phase 0 findings (`reports/phase0_findings.md`) and the real catalog contents. Each decision is a recommendation the user can overturn at the Phase 1 gate; changing one means regenerating the derived files, not redoing the work. The parent design is `docs/superpowers/specs/2026-09-30-aetherguard-design.md`.

No git in this project (user decision). Workflow per task: builder (Sonnet) writes code test-first → verifier/reviewer (Sonnet) reads the files and runs the tests → controller adjudicates. A phase ends with a stop-and-report gate.

## Facts that drive the design (measured, not assumed)
- Label files in `data/raw/manual/`: `nasa_glc.csv` (legacy GLC, 11,033 rows, 1988–2017), `coolr_reports_points.csv` (14,750, 1974–2025, has location accuracy), `coolr_events_points.csv` (40,154, 2011–2024, mapped inventories, no accuracy field), `hma/HMA_LS_Cat_point_v02.0.{shp,shx,dbf,prj,cpg}` (2,801, 1990–2018). GLC, COOLR reports and HMA share an `event_id` namespace (HMA `ev_id` 684 = GLC `event_id` 684). The COOLR events layer has its own ids.
- Post-2018 labels are almost absent: Western Ghats has none in the events layer and ~0 reports after 2018; Himalaya has the 2023 India inventory (176 events) and only a handful of reports for 2019–2022. Wayanad 2024 is not in any NASA catalog. Kerala 2018 has 83 report events (56 in Aug 2018).
- The coarse Himalaya box (lat 22–36, lon 72–98) also contains Myanmar (6,823 automated events dated 2015), Bangladesh (715 in 2023), Pakistan, China. They must not be counted.
- Rain products disagree on the "day": IMD day = 08:30 IST → 08:30 IST (labelled by the end date); CHIRPS and the POWER zarr `utc` store = UTC calendar day; ERA5 via Open-Meteo = UTC or IST depending on the `timezone` parameter. A landslide at 02:00 IST on date D is captured by IMD day D but by UTC day D-1.
- IMD gauge-based grid is India-only (NaN at Kathmandu, Pokhara). It is the closest product to gauge totals at Wayanad (179 mm vs ~56 mm ERA5 and 0 mm CHIRPS for 30 Jul 2024).

## D1 Regions (refined, replaces the coarse boxes for labels)
- `himalaya`: `country_code` in {IN, NP, BT}, inside lat 22–36 / lon 72–98, and not inside the Ghats box.
- `western_ghats`: `country_code` = IN, inside lat 8–21.5 / lon 72.5–78.5.
- Everything else (PK, BD, MM, CN, ...) is out of scope and dropped from the label store (kept in the raw files).

## D2 Unified label store (`data/processed/labels/events.parquet`)
One row per source record with: `uid` (`<source>:<id>`), `source` (hma | coolr_reports | glc | coolr_events), `event_id`, `event_date` (date, the catalog's own calendar date — no timezone conversion, raw string kept in `event_date_raw`), `latitude`, `longitude`, `cell_id` (0.05° grid), `accuracy_km`, `trigger_raw`, `trigger_class` (rain | earthquake | construction_mining | snow | other | unknown), `country_code`, `region`, `is_positive` (bool), `drop_reason` (null when kept as positive).
- Source priority for duplicates: hma > coolr_reports > glc > coolr_events. Exact duplicates in the shared id namespace (hma/coolr_reports/glc) are removed by `event_id`; any record of lower priority with the same `event_date` within 2 km of a higher-priority record (any source pair) is removed and counted as `near_duplicate`.
- `coolr_events` points are individual mapped landslides: `accuracy_km` is set to 1.0 (documented assumption).
- Rain-class triggers: any trigger text (case-insensitive, underscores/spaces/hyphens equivalent) containing `rain`, `downpour`, `monsoon` or `cyclone` (covers rain, downpour, continuous_rain, heavy rain, heavy rainfall, tropical_cyclone). `flooding` is deliberately NOT rain-class (conservative: excluded from positives, kept as a buffer record). `unknown` triggers are NOT positives. `label_report.json` lists every distinct raw trigger string with its class and kept count so unmapped strings are visible.
- `drop_reason` values, in order: `missing_date`, `bad_coordinates`, then region by box: outside both boxes -> `out_of_scope_region`; inside a box with a blank country -> `missing_country` (no country is guessed); inside a box with a country outside IN/NP/BT -> `out_of_scope_region`; then `duplicate_id`, `near_duplicate`. The report counts blank-country rows inside the boxes.
- `date_basis`: `event_day` (hma, coolr_reports, glc: the catalog date of the event) or `inventory_window` (coolr_events: the date is the inventory headline date; the real landslide dates lie between `sat_date_before` and `sat_date_after`, carried as `date_window_start` / `date_window_end`). Inventory-window records are never day-exact positives.
- Timestamps with a UTC offset are rejected loudly (no timezone conversion is done anywhere); the store records the catalog's own calendar date.
- `is_positive` = rain-class trigger AND `accuracy_km` ≤ 5 AND `event_date` within 2007-01-01..2024-12-31 AND region in (himalaya, western_ghats) AND valid coordinates.
- Every dropped or excluded record keeps a `drop_reason` (and the store reports counts per reason) — nothing disappears silently. Records that are not positives but are real events (unknown/non-rain trigger, poor accuracy) stay in the store: they define the exclusion buffer for negatives.

## D3 Modelling unit and negatives
- Unit: (0.05° cell, calendar date). A positive cell-day = at least one DAY-EXACT positive event (`date_basis = event_day`) in that cell on that date (collapse multiple events; 1,132 positives collapse to 943 cell-days today, up to 38 events in one cell-day).
- Exclusion buffer for negatives: every record with a valid date and valid coordinates counts, whatever its `drop_reason` (including `out_of_scope_region`, duplicates, non-rain, poor accuracy, inventory-window records), so events just across a border or flood-triggered events never become negatives.
- Negatives (sampled later, after terrain is available): same region, same calendar months as positives, at least 3 cells (0.15°) and ±3 days away from ANY event in the store (positive or not), drawn among cells with slope above the 5th percentile of positive cells. Seeded and deterministic. Ratio 10:1 per split.

## D4 Frozen splits (by event date; `data/processed/splits/`)
- `train`: 2007-01-01..2015-12-31. `validation`: 2016-01-01..2017-12-31.
- `test_2018`: 2018-01-01..2018-12-31 (Kerala floods for the Ghats, plus Himalaya 2018).
- `test_2023_india_window`: the 176 positives of the 2023 India inventory (`date_basis = inventory_window`, window 2023-06-16..2023-07-31). NOT a daily test: scored at window level (a cell is detected if an alert of Watch or higher occurs in it or its 8 neighbours on ANY day of the window; false alarms are an upper bound because the inventory is partial). Kept in a separate file because it cannot be mixed with day-exact cell-days.
- `test_sparse`: all remaining positives dated 2019..2024 (reporting only; too few to score).
- Also recorded per row: `region` so leave-region-out evaluation (train Himalaya → test Ghats and back) is available later. Wayanad 2024 and Kerala 2018 are case studies and are never used for training or tuning.
- Frozen = the parquet files plus `splits_manifest.json` holding row counts, date bounds and SHA-256 of each file; split-integrity tests assert no (cell, date) appears in two splits, no positive dated after a split's boundary leaks backwards, and the files still match their recorded checksums.

## D5 Day basis for rain features (Review Focus #5)
- Canonical feature day `D` = the catalog's local calendar date of the event; rain windows END on the IMD day `D` (08:30 IST D-1 → 08:30 IST D). For IMD data that is the native day. For UTC-day products (CHIRPS, POWER zarr utc) the IMD-day total is approximated as `0.875 × P_utc(D-1) + 0.125 × P_utc(D)` (window 03:00 UTC D-1 → 03:00 UTC D = last 21 h of UTC day D-1 plus first 3 h of D). This approximation is explicit, unit-tested, and stored next to the raw values. Features record `rain_source` (imd | chirps_aligned) per row; a cell with both uses IMD as primary and CHIRPS as the independent second source (their disagreement is a Phase 3 feature).

## D6 Rain and wetness ingest
- IMD gauge grid 2007–2024 (yearly files via `imdlib`, ~25 MB each) → per-year arrays on the native 0.25° grid, India only; looked up by nearest cell.
- CHIRPS v2.0 daily 0.05° for 2007–2018 and 2023 (years with labels, plus the 30-day look-back), cropped to the refined domain boxes and stored compactly (float16 npy per year + index); the downloader is idempotent and resumable (manifest); negatives < 0 are masked because the files declare `nodata=None` but use −9999.
- NASA POWER zarr soil wetness (`GWETTOP`, `GWETROOT`) at the MERRA-2 grid for the same years, read as domain slabs; day basis UTC, treated like the other UTC-day products.

## D7 Terrain (after labels are frozen)
- Copernicus DEM 30 m tiles are downloaded only for 1° tiles that contain at least one positive or sampled cell; slope, relief and curvature per 0.05° cell from zonal statistics of the 30 m DEM; WorldCover and roads are Phase 3 candidates, not Phase 1.

## Phase 1 tasks (each test-first, offline tests, real-data smoke at the end)
1. **Label store** — readers for the four sources (incl. shapefile DBF/SHP reader without new dependencies), D1/D2 rules, parquet + counts report.
2. **Positives, splits and integrity tests** — D3 positives collapse, D4 splits, `splits_manifest.json`, leakage and checksum tests.
3. **Rain ingest** — IMD, CHIRPS (background download), POWER wetness, plus D5 alignment functions with tests.
4. **Terrain ingest** — DEM tiles for needed cells, per-cell slope/relief/curvature.
5. **Negative sampling and feature store** — D3 sampling, rain accumulations (1, 3, 5, 7, 14, 30 days), antecedent wetness, source-disagreement features, feature parquet per split.
Gate: split-integrity tests pass, label/feature counts reported per region and split, the user reviews D1–D7.
