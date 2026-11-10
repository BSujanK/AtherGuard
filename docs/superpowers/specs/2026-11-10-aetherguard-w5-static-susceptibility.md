# W5 + W6: static susceptibility inputs and the combined model (pre-declared)

Date: 2026-11-10. Status: pre-declared before any result. Roadmap §4 W5 and W6. Written while the W3 data steps run;
no W3 development or held-out number exists yet.

## 1. Why

v3 knows the ground only through ten statistics of a 90 m elevation model. It cannot tell forest from cropland, a
road-cut slope from an untouched one, or clay from sand, and the W0/W1 reports show its Watch+ and Warning+ levels
barely beat a static map. Better static knowledge sharpens *where* an alert is spent at the same burden. Static
inputs have no latency, so the live run reads exactly what training read.

## 2. Inputs (one table, one row per 0.05-degree cell of `cell_terrain.parquet`)

| feature | source (licence) | reduction to the cell |
|---|---|---|
| `lc_tree`, `lc_shrub_grass`, `lc_crop`, `lc_built`, `lc_bare` | ESA WorldCover 2021 v200, 10 m (CC BY 4.0) | share of the cell's pixels in the class (10/20+30/40/50/60+70), read from the tile overviews at about 80 m; water, wetland and no-data pixels leave the denominator |
| `road_density` | GRIP4 total road density, 5 arcmin (CC0) | the value of the density pixel holding the cell centre (m of road per km2) |
| `soil_clay`, `soil_sand`, `soil_coarse` | ISRIC SoilGrids 2.0, 1 km aggregate, 15-30 cm (CC BY 4.0) | mean of the pixels in the cell (percent) |
| `ter_steep25`, `ter_steep35` | Copernicus DEM GLO-90 (the tiles already on disk) | share of the cell's valid 90 m pixels with slope of at least 25 and 35 degrees |

A cell a source does not cover has NaN for that source's features (LightGBM handles missing values); the report
counts them. Not included, and why: lithology (the openly downloadable GLiM grid is 0.5 degrees, ten cells wide; the
vector needs a request form), OpenStreetMap roads (1.7 GB extract; GRIP4 first, OSM only if `road_density` earns its
place), forest loss (time-varying; a later study). Known caveat: WorldCover is a 2021 map applied to 2007-2025; a
landslide scar is far below the share of a 5 km cell, so leakage from the label is negligible, and it is stated.

## 3. Candidates (two, no more)

- **v4-static** = the v3-live configuration plus the eleven features, unconstrained (no monotone direction is assumed
  for ground properties). Same folds, seeds, 20-member ensemble, per-region isotonic calibration.
- **v4** (W6) = v3-live plus every group that passed its own development criterion: `iint` (W3 stage 1) and/or
  `static` (this spec, stage 1). If only one group passed, v4 is that group's model; if none, there is no v4.

## 4. Pre-declared criteria

**Stage 1, development (year-blocked CV 2007-2017, v3's folds and seeds):** v4-static passes when the paired-bootstrap
95% interval of pooled out-of-fold FA@90(v4-static) - FA@90(v3 refit) has its lower bound at or below 0, with the v3
refit reproducing the published v3 number exactly (as in W3). A failed stage 1 is final for the group.

**Stage 2, held-out, once, for v4 only** (v4-static alone takes no held-out look, so the test set is read once for
W5 and W6 together): POOLED 2018-2025, 87 independent slides, the W1 assembly. v4 against `incumbent_ranked`, where
the incumbent is v4-int if W3 adopted it and v3 otherwise; both ranked by their own calibrated risk and cut, season
by season, to the shares v3 realised with the section 11 rules (W3's burden-matching, tie-break and preflight rules
apply unchanged, including the look-started marker). v4 is adopted only if its independent-slide detection at
Warning+ and at Emergency is at least the incumbent's in all four comparisons (tolerant and cell-exact) and higher in
at least one. If v4 would be identical to the incumbent (only `iint` passed and W3 already looked), there is no
second look and nothing changes.

Nothing is tuned after a look. Adoption into the live run is a separate, reviewed step.

## 5. Outputs

`data/processed/features/static_w5/cell_static.parquet` and its report; `data/processed/hazard/v4_static/`,
`data/processed/hazard/v4/`; `reports/phase7_static_susceptibility.{md,json}`.
