# Phase 6: prediction integrity audit (spec section 13)

Every number below is read from `reports/live/audit/*.json` (`<day>.json`, `summary.json`, `api_parity_2026-10-24.json`,
`rain_registration_study.json`), written by `python -m aetherguard.live.audit --date all --rescore`, `... --api http://127.0.0.1:8790`
and `python -m aetherguard.live.audit_registration`, or from a comparison of the published tables before and after the re-publication
(copies of the earlier tables are kept outside the project). Days audited: 2026-10-09 .. 2026-10-24 (16 published days, 183,960 rows each:
alerts + risk_D0..D3, and the four features tables besides).

## 1. Result

After the fixes below and the re-publication of all 16 days, `python -m aetherguard.live.audit --date all --rescore` exits 0: every
check family is zero on every day and table, and the pooled rain-registration test passes with the live IMD sampling best at zero offset.
Three defects were found in what had been published:

1. **risk_hi above 1** (fixed): the widening factor was applied without a cap; 3 cells on 2 days.
2. **uncertain_high of D+1..D+3 tested on the widened interval** although the rules say `unwidened` (fixed by the coordinator; found by
   the new `reproducible` check): 5,656 to 9,788 forecast rows per lead and day.
3. **IMD longitude registration** (fixed in the live path only): the IMD grid was read one 0.25-degree column too far east of where
   gauges place its data (`imd_lon_offset_columns: -1`).

## 2. The checks, what each proves, and the result

Definitions are in `docs/superpowers/specs/2026-10-14-aetherguard-live-global-design.md` section 13 and the docstrings of
`live/audit_math.py`, `live/audit_geo.py`, `live/audit_rescore.py`, `live/audit_parity.py`.

| check | proves | result on the 16 days (after re-publication) |
|---|---|---|
| probability | risk, risk_lo, risk_hi finite and in [0,1] where scored, level 0..3, level_name, level_min <= level <= level_max | 0 (3 before the fix) |
| dates | date = run date + lead, lead column, no duplicate cell, same cells and lat/lon/region in all 9 tables of a run | 0 |
| rain_math | every identity of the irain/iapi/inbr features | 0 |
| rain_chain | lead-k features follow from the forecast days and lead 0 | 0 |
| reproducible | re-scoring every stored features table with the frozen model reproduces risk/lo/hi (1e-9), the scored rows are the complete-input rows, one widening factor per lead, and uncertain_high equals the rules' test on the unwidened interval | 0 (373,749 before, all in uncertain_high of D+1..D+3) |
| shap | listed contributions sorted, model inputs, values equal the features table, reasons_json equals the row; base + all contributions = margin; the five listed are the largest | 0 |
| grid | cell_id = latlon_to_cell, lat/lon = cell_center exactly, region = region_labels | 0 |
| land | every scored cell centre is land in the base-map mask | 0 (2 sea-mask cells are notes, section 6) |
| georef (terrain) | stat_elev_mean correlates with ETOPO at the same cell, best at zero offset | 0; r = 0.99999 at zero offset, best one-cell shift 0.98389 (2026-10-24) |
| georef (IMD sampling) | `src_imd_acc_1` equals the IMD grid read at the configured column | 0 on every day with a stored IMD value (days 2026-10-09..15 store none) |
| georef (rain, pooled) | IMERG vs IMD, shifts +-1, +-2 IMD cells and +-1 day, relative to the live sampling | 0 (section 5) |
| places | every scored cell has a label, distance_km = haversine within 0.52 km, country matches the mask | 0 |
| api_parity | `/api/grid` and `/risk/cell/{id}` equal the parquet rows | 0 mismatches in 18,904 comparisons (1,200 cells: 300 per lead, 2026-10-24, after the dashboard restart) |
| describeOdds (vitest) | N within the two-significant-figure rounding of 1/risk, same N in all variants | 4 new tests pass |

The nine checks of section 11 (interval, level, rain_rule, blind_hold, confidence, forecast_confidence, certainty, per_100k,
lead0_table) are 0 on all days.

## 3. Before and after the re-publication

Before (the tables as published when the audit first ran), `reproducible` per day and table; all other checks were 0, apart from
`probability` on 2026-10-14 (risk_D2, 2 cells) and 2026-10-15 (risk_D1, 1 cell) and the pooled georef:

| day | risk_D1 | risk_D2 | risk_D3 |
|---|---|---|---|
| 2026-10-09 | 5656 | 6498 | 6969 |
| 2026-10-10 | 6194 | 7265 | 7518 |
| 2026-10-11 | 6865 | 7835 | 7684 |
| 2026-10-12 | 7091 | 7437 | 7286 |
| 2026-10-13 | 7023 | 7474 | 6709 |
| 2026-10-14 | 6804 | 5278 | 7437 |
| 2026-10-15 | 6381 | 5508 | 7611 |
| 2026-10-16 | 6866 | 7581 | 7720 |
| 2026-10-17 | 7203 | 8110 | 8552 |
| 2026-10-18 | 7815 | 8583 | 8338 |
| 2026-10-19 | 7806 | 8480 | 8507 |
| 2026-10-20 | 8136 | 8609 | 8769 |
| 2026-10-21 | 8285 | 8857 | 9284 |
| 2026-10-22 | 8114 | 9226 | 9472 |
| 2026-10-23 | 8830 | 9423 | 9546 |
| 2026-10-24 | 9041 | 8285 | 9788 |

Effect of the re-publication on what is shown (Watch cells and uncertain_high flags per forecast lead, before -> after; alerts = lead 0):

| day | alerts level changed | alerts confidence changed | Watch D+1 | Watch D+2 | Watch D+3 | uncertain_high D+1 | D+2 | D+3 |
|---|---|---|---|---|---|---|---|---|
| 2026-10-09 | 0 | 0 | 12461->9959 | 13566->11106 | 14625->9472 | 8549->2893 | 9401->3073 | 10334->4366 |
| 2026-10-10 | 0 | 0 | 12429->9651 | 13979->10714 | 14376->9042 | 9159->2965 | 10793->3623 | 11225->4454 |
| 2026-10-11 | 0 | 0 | 12981->9905 | 13126->10292 | 12493->8660 | 10530->3665 | 11751->3949 | 11627->4471 |
| 2026-10-12 | 0 | 0 | 12564->9525 | 12871->10023 | 12214->8689 | 11052->3961 | 11450->3949 | 11170->4069 |
| 2026-10-13 | 0 | 0 | 12234->9623 | 11657->9808 | 10498->8129 | 11225->4202 | 11541->4109 | 10731->4183 |
| 2026-10-14 | 0 | 0 | 11019->8967 | 11608->10127 | 7190->5281 | 10707->3903 | 9410->4132 | 11511->4074 |
| 2026-10-15 | 0 | 0 | 9445->7959 | 8461->7080 | 6161->4302 | 10383->4002 | 8998->3490 | 11724->4113 |
| 2026-10-16 | 13 | 1374 | 8134->6334 | 7185->5023 | 6091->4299 | 10836->3970 | 11765->4184 | 11981->4261 |
| 2026-10-17 | 39 | 1244 | 7396->5401 | 6238->4052 | 6476->4027 | 11534->4331 | 12432->4322 | 13288->4736 |
| 2026-10-18 | 28 | 1434 | 6233->4102 | 6088->3731 | 4734->2912 | 12251->4436 | 13138->4555 | 12862->4524 |
| 2026-10-19 | 4 | 1424 | 5461->3595 | 4970->3049 | 3218->1676 | 12510->4704 | 13193->4713 | 13231->4724 |
| 2026-10-20 | 6 | 1403 | 4787->2934 | 3677->1996 | 2901->1632 | 12887->4751 | 13474->4865 | 13714->4945 |
| 2026-10-21 | 6 | 1311 | 3727->2104 | 3189->1713 | 2607->1429 | 13182->4897 | 13799->4942 | 14485->5201 |
| 2026-10-22 | 2 | 1371 | 2762->1686 | 2891->1489 | 2743->1206 | 13147->5033 | 14569->5247 | 14514->5220 |
| 2026-10-23 | 2 | 1000 | 3410->2080 | 2941->1465 | 2255->986 | 14336->5506 | 14470->4979 | 14350->5029 |
| 2026-10-24 | 6 | 1090 | 3243->2016 | 1850->1344 | 2199->1062 | 14471->5430 | 13195->4910 | 14598->4810 |

On 2026-10-24, the full level counts (Normal / Watch / Warning / Emergency): alerts 33132 / 1711 / 914 / 1035 -> 33130 / 1713 / 914 / 1035;
D+1 32050 / 3243 / 827 / 672 -> 33277 / 2016 / 827 / 672; D+2 33228 / 1850 / 520 / 1194 -> 33734 / 1344 / 520 / 1194; D+3
33328 / 2199 / 432 / 833 -> 34465 / 1062 / 432 / 833. Warning and Emergency do not move on that day (the flag only raises a level below Watch
to Watch). On 2026-10-09..13 the D+2/D+3 Warning and Emergency counts also fall: those days were first produced before section 12 and the
re-run brings them to the current forecast configuration (ECMWF ensemble mean from cycles issued before the cut-off, the leads'
wet bound from the ensemble spread), so their D+2/D+3 differ for that reason as well, not only through the `uncertain_high` fix. Lead 0 changes
only through the IMD fix (section 5): none on 2026-10-09..15, where the IMD file for the day had not been published at run time.

## 4. Bugs found

1. **risk_hi above 1** (`probability`). Root cause: `live.run.lead_scores` multiplied the model's `risk_hi` by the lead's widening factor
   (4.2 to 5.9 on the live days) without a cap. Published: 2026-10-14 risk_D2 (cells 19945136, 20235129) and 2026-10-15 risk_D1 (cell
   20455111). Fix: `risk_hi = max(min(raw_hi x factor, 1), risk)`; the `reproducible` check expects the same cap. Tests:
   `test_a_widened_interval_never_leaves_the_probability_range` (red before, green after) and the probability tests of
   `tests/test_live_audit_math.py`. One older assertion (`test_live_run.py::test_forecast_widening_factors_are_applied_when_present`) expected a
   widened `risk_hi` above 1 on a saturated test model; it now asserts `<= 1`.
2. **uncertain_high of the forecast leads on the widened interval.** Root cause: `unwidened = with_uncertain_bound(scored, ...)` returned
   `scored` itself and the widening then overwrote `risk_hi` in place, so the "unwidened" bound was the widened one while
   `post_rules_v3.json` says `unwidened`. Fixed by the coordinator (`scored.copy()`). The audit now recomputes the flag independently of
   `lead_scores` (`audit_rescore.check_uncertain`: re-score the stored features, take the unwidened `risk_hi` or the configured ensemble
   percentile, apply `rules.lead_uncertain_bound`, `levels.uncertain_high_mask`); tests plant a flag from the widened bound
   (`tests/test_live_audit_rescore.py`). On 2026-10-24 every flagged row was a flag set that the unwidened bound does not give (D+1 9,041,
   D+2 8,285, D+3 9,788) and none the other way.
3. **IMD longitude registration** (section 5). Live path only: `imd_lon_offset_columns: -1` in `configs/live_run.yaml`, used by
   `adapter.imd_cell_series` (the source of `src_imd_*` and `imd_acc_1`). `_imd_pixels(cell_ids, lon_offset_columns=0)` keeps its
   behaviour for the frozen v2 store (`load_imd`), the integrity engine and the replay. A column outside the grid is missing (-1), never the
   next row. Tests: `tests/test_live_imd_offset.py` (offset moves the sampled value by exactly one column, edge column is NaN, a live run
   reads the configured column and leaves the model's IMERG rain untouched); the audit now also checks that the stored `src_imd_acc_1`
   equals the grid read at the configured column.

Re-publication (all 16 days, in date order because the hysteresis of a day reads the published days before it): 2026-10-09..15 with
`python -m aetherguard.live run --date D --force --backtest`, 2026-10-16..24 with `run --date D --force`, as each was first produced
(`run.json` `backtest`). The earlier tables are kept outside the project. Each run's own audit (with rescoring) reported 0 violations.

## 5. IMD longitude registration

**Finding before the fix.** Pooled over the 16 days, IMD sampled one column west of the nearest point correlated better with IMERG than the
nearest point: 0.6637 against 0.6366, above the 0.02 margin. `rain_registration_study.json` (131 GHCN gauges as point truth, 100 monsoon days
from 10 June, square-root rain correlation): the IMD grid read at the nearest point 0.7712, one column west 0.8634, one column east 0.6251;
latitude shifts symmetric about zero. For the monsoons of 2015, 2018, 2023 and 2024 the lookup "nearest point minus one column" gives
0.908 / 0.854 / 0.881 / 0.863 against 0.836 / 0.747 / 0.782 / 0.771 at the nearest point (2015 is a training year); the same preference holds in the
Himalaya and the Western Ghats stations separately. IMERG at the station pixel: 0.6427 at zero, 0.648 one 0.1-degree column west, falling at two
columns (0.6297) and three (0.6174): no displacement of the 0.2 to 0.25 degrees. Station coordinates match known places (Shimla, Bombay
Santacruz, New Delhi Safdarjung), so the gauges are not the cause.

**Is the reader off by one element?** No. (i) The real-time file has exactly 129 x 135 x 4 bytes, so there is no header that would shift
the flattened data, and `parse_imd_grid` and `imdlib` (`lon = linspace(66.5, 100, 135)`, C-order reshape) read it the same way. (ii) The set of
grid points that hold data (the -999 sea and outside mask) is identical in the real-time file of 2026-10-24 and in the final store (4,964
points in both), so the two download paths agree with each other. (iii) That footprint against the India land fraction of each 0.25-degree box
of the Natural Earth mask (correlation by longitude offset of the labels): -0.25 0.9271, -0.125 0.9449, 0 0.9570, +0.125 0.9600, +0.25
0.9536, +0.375 0.9384. The mask is therefore not displaced westward relative to the coastline, it is consistent with an offset between 0 and
+0.25 degrees (data east of the labels) but too coarse to separate it from zero; it does not support a half-cell "lower-edge" reading either
(the gauges prefer a whole column over "floor"). The offset is the product's own convention (its data lie about one column east of the
`66.5 + 0.25 j` labels), identical in the final grid and the real-time grid; the gauges, the only point truth, place it. IMD's own
documentation of its grid could not be checked offline.

**After the fix** (`summary.json` `rain_georef`, `lon_offset_columns: -1`, sampling relative to the live one): aligned 0.6637; one column
back to the old position (0,1) 0.6366, (0,-1) 0.6267, (1,0) 0.6247, (-1,0) 0.6472, (0,+-2) 0.5867 / 0.5682, (+-2,0) 0.5686 / 0.5971. Day lag: the
day before 0.2586, same day 0.6637, the day after 0.3209. Zero offset is best in every case; no violation.

**Effect.** Only the second-opinion rain (`src_imd_*`, `imd_acc_1`): the model does not use IMD. With the new sampling `imd_acc_1` changed by more
than 5 mm at 315 to 3,067 of the 30,941 cells with IMD data per day (before the fix, versus the column west), and 26 to 830 cells per day cross
the heavy-rain threshold (32.5 mm in 1 day). On the published days that moved 1,000 to 1,434 cell confidence states and 2 to 39 lead-0 levels per day
(table in section 3). The integrity engine's gauge references (`ImdGrid.nearest_index`, trained that way) and the alert-engine thresholds
derived on the old lookup are unchanged; whether to re-derive the confidence thresholds on the corrected lookup is open.

IMD day alignment in a live run: `src_imd_acc_1` / `imd_acc_1` of run D is the real-time file `rain=DDMMYYYY` for D (stored
`raw/imd_rt/D.grd`, found in the run's own folder or, for D-1 and D-2, in the folders of the later runs that fetched them), valid through 03:00
UTC of D, one IMD day = 03 UTC D-1 to 03 UTC D; IMERG `irain_acc_1` for D is 0.875 x UTC(D-1) (Early) + 0.125 x the GFS 00Z 0-3 h accumulation
of D. The lag test confirms the labels agree. On 2026-10-09..15 the IMD file for D was not yet published at run time (`imd_rt` state `late`), so
`src_imd_acc_1` is missing for all cells; from 2026-10-16 it is present for 85.2% of the cells (the rest lie outside the IMD grid).

## 6. Notes (modelling plausibility; counted, never violations)

Alerts table, per day (`note_counts` of each day file):
scored cells per country class are constant: India 30,652 (30,648 on days with 4 unscored cells), Nepal 4,562, Bhutan 1,439, other land 137;
2 coastal cells the mask calls sea but whose ETOPO elevation is above sea level (cells 20575098 at 12.875/74.925 and 21235069 at
16.175/73.475, both land; labelled Mangaluru and Malvan); places over 30 km: 10,511 to 10,515. Alerts on low-slope or low-elevation cells, taken from
the final audit's day files:

| day | slope<5 Watch | Warning | Emergency | elev<100 m Watch | Warning | Emergency |
|---|---|---|---|---|---|---|
| 2026-10-09 | 716 | 57 | 8 | 674 | 74 | 1 |
| 2026-10-10 | 823 | 106 | 22 | 676 | 148 | 20 |
| 2026-10-11 | 661 | 125 | 26 | 576 | 148 | 29 |
| 2026-10-12 | 552 | 115 | 18 | 489 | 114 | 22 |
| 2026-10-13 | 458 | 45 | 2 | 359 | 38 | 3 |
| 2026-10-14 | 345 | 46 | 5 | 332 | 28 | 3 |
| 2026-10-15 | 389 | 29 | 29 | 361 | 16 | 1 |
| 2026-10-16 | 546 | 188 | 95 | 364 | 217 | 73 |
| 2026-10-17 | 575 | 232 | 95 | 327 | 264 | 98 |
| 2026-10-18 | 633 | 200 | 39 | 467 | 188 | 36 |
| 2026-10-19 | 639 | 148 | 18 | 512 | 136 | 14 |
| 2026-10-20 | 564 | 136 | 19 | 538 | 162 | 29 |
| 2026-10-21 | 495 | 165 | 42 | 486 | 219 | 54 |
| 2026-10-22 | 362 | 125 | 135 | 278 | 181 | 177 |
| 2026-10-23 | 334 | 151 | 222 | 194 | 215 | 315 |
| 2026-10-24 | 408 | 226 | 140 | 237 | 307 | 216 |

(The forecast leads' counts are in the day files under `risk_D1..3.<note>`.) These count the situation the precision study (section 14) addresses;
they do not say it is wrong.

## 7. Cost

* The checks that read only the day's tables: about 4.5 s per day (about 1 s before).
* The rescoring with the model already in memory (`reproducible`, the full-vector `shap`, the `uncertain_high` recompute), always on in
  `live.run.audit_run`: 17.7 to 31.6 s per day in the final all-days run (`rescore` seconds of the day files, including the model load of the
  stand-alone CLI; 50 to 64 s earlier when other jobs shared the machine).
* A forced re-run of one day (`run.json` `seconds`, audit included) took 42.5 to 135.5 s in this session, against about 80 s for the earlier runs.
* API parity: about 4 minutes (1,200 requests), not part of the daily run.

## 8. What could not be verified

* IMD's own statement of its grid convention.
* That IMERG is registered exactly: the gauge test cannot resolve less than about 0.1 degree.
* Whether the thresholds of the alert engine, derived on the old IMD lookup, should be re-derived.
