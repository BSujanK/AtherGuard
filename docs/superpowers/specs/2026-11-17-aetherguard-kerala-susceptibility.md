# Two-stage susceptibility: a surface from the imagery-mapped Kerala 2018 inventory, then v4 (pre-declared)

Date: 2026-11-17. Status: pre-declared before any stage 1, stage 2 or held-out number of this study. Roadmap section 4
W5 ("optional two-stage model: susceptibility from undated inventories x dynamic trigger"). Research prototype; nothing
here is wired into the live run.

## 1. Why

v4's static inputs were learned from reported, dated events. Reported slides sit where people and roads are, so a
surface learned from them learns where slides get recorded as well as where the ground fails (W5 amendment of
2026-11-11: the built-up share was dropped for exactly that). An inventory mapped from imagery records slides on empty
slopes too. The open one in the domain is the Kerala 2018 monsoon inventory, dated only to a season, so it can teach
WHERE and never WHEN. The idea: stage 1 learns a susceptibility surface from that inventory; stage 2 gives the surface
to v4 as one more per-cell input and lets the daily rain decide WHEN.

## 2. The inventory and its licence

Hao et al. 2020 (ESSD 12, 2899-2918) and van Westen 2020, DANS, https://doi.org/10.17026/dans-x6c-y7x2, licence
CC-BY-4.0 (DANS record). Local copy with checksums: `data/raw/manual/kerala2018_hao2020/` (`PROVENANCE.json`). 4,728
slide points, window 1 June - 26 August 2018, no per-slide date. Found by NRSC post-event imagery (2,899), GSI field
survey (1,395) and the authors' Google Earth mapping (856 new); 973 points are GSI-only. Attribution goes in every
report. Raw rows are not committed (they live under `data/`, which is git-ignored); the surface built from them may be
described in reports.

Bias that remains: the GSI-only part was found in the field, and 40% of those points touched a road against 19% of all
points, so the field part leans toward roads. Mapping effort followed the districts that were hit, and the surface
reflects the 2018 storm's footprint unless that is controlled (section 3).

No other licence-clean mapped inventory is usable: NASA HMA_MTLI (open) is dated by year and maps only three Nepal
highway corridors and the Arun basin, so it is road-centred by construction; GSI Bhukosh and NRSC Bhuvan need an
account or a data request (user decisions, survey `reports/phase8_ground_truth_survey.md`); Kodagu 2018 and Himachal
2023 are not open.

## 3. Stage 1: the surface (fitted on the inventory only)

- **Cells.** The 1,063 domain cells that `data/processed/districts/cell_districts.parquet` assigns to the 14 Kerala
  districts (all in region `western_ghats`). Label 1 when at least one inventory point falls in the cell (351 cells,
  4,679 points), else 0. The 49 points in 14 cells outside these districts are dropped: their neighbours were not mapped.
- **Inputs.** The ten terrain statistics v3 reads (`cell_terrain.parquet`, the `stat_` inputs), the nine physical W5
  columns (`lc_tree`, `lc_shrub_grass`, `lc_crop`, `lc_bare`, `soil_clay`, `soil_sand`, `soil_coarse`, `ter_steep25`,
  `ter_steep35`), and one trigger covariate `rain_2018`: the IMERG V07 Late total of 1 June - 26 August 2018 at the
  cell's 0.1 degree pixel. Never inputs: `road_density`, `lc_built` (exposure), any date, any reported event.
- **The trigger is held fixed.** The surface is the model's probability with `rain_2018` set to its median over the
  1,063 cells, for every cell of the domain: susceptibility under the same storm everywhere, so that the 2018 rain
  footprint is not baked into WHERE.
- **Candidates (two):**
  - `S_lr`: logistic regression, L2 penalty, C = 1.0; each input imputed with its training-cell median, clipped to its
    training-cell range (no extrapolation outside Kerala's values) and standardised on the training cells.
  - `S_gbm`: LightGBM binary, 300 trees, learning rate 0.03, 7 leaves, at least 20 cells per leaf, feature and bagging
    fraction 0.8 (bagging every tree), seed 20261117, `rain_2018` constrained non-decreasing, nothing else constrained.
- **Evaluation: spatial blocks.** Leave one district out (14 folds). Pooled out-of-fold ROC AUC and average precision,
  with a 95% interval from 2,000 bootstrap resamples of districts (seed 20261117). Baseline `B_slope`: `stat_slope_mean`
  alone as the score.
- **Selection rule.** The candidate with the higher pooled OOF ROC AUC. Stage 1 passes when that AUC is above
  `B_slope`'s. A failed stage 1 ends the study: no stage 2, no look. The selected form is refitted on all 1,063 cells
  and evaluated on every cell of `cell_terrain.parquet`: `data/processed/features/susc_kerala/cell_susc.parquet`
  (`cell_id`, `susc_kerala`).

### Reporting-bias checks of stage 1 (reported, they decide nothing)

- `R`: the same form as the selected candidate (without `rain_2018`), fitted on every scored domain cell with label 1
  when the cell holds a development positive (2007-2017, the reported and catalogued events v4 learned from). Its ROC
  AUC on the Kerala mapped cells against the surface's out-of-fold AUC: does a surface learned from reports place mapped
  slides?
- Spearman correlation of the surface and of `R` with `road_density` and `lc_built` over the scored cells.
- Imagery-only sensitivity: the selected form refitted with the label from NRSC or Google Earth points only, cells
  whose only points are GSI field points left out; its leave-one-district-out AUC.

## 4. Leakage design (stated before any held-out number)

2018 is a held-out year and Kerala 2018 is a case study that was never used for training or tuning
(`docs/phase1-design.md`; spec 2026-10-14). The surface is fitted on Kerala 2018 slides, and many held-out 2018 events
of the W1 assembly are the same storm's slides, some perhaps the same slides. Scoring them would be circular. So:

1. **Exclusion zone.** A held-out event is excluded from every held-out number of this study when it is dated in 2018
   and its cell centre lies within 20 km of the centre of any stage 1 cell (the 10 km tolerance of protocol v3 plus a
   margin larger than one cell's diagonal). The preflight counts the excluded events (no model output is read for that)
   and freezes the remaining set by checksum. Held-out events in the zone in 2019-2025 stay: a 2018 map used on later
   years is how the surface would be used live, and its labels are not theirs.
2. **No number on the excluded events** is computed by this study, for any model.
3. **The Kerala 2018 case study** (`case_kerala_2018_*` tables) is not read by this study.
4. **Burden is unchanged.** Burden matching ranks every scored cell-day of each season, the zone included, so alerts the
   candidate spends in Kerala in 2018 still count against its share; excluding events only removes detections it could
   claim there.
5. **Development is clean by time.** Stage 2 selects on 2007-2017 only. The surface is a fixed per-cell input, like the
   2021 WorldCover map is for 2007-2025; its labels (2018) are not development labels.
6. **Transfer readout.** Beside the deciding numbers, detection on the held-out events farther than 20 km from every
   stage 1 cell (all years): the gain, if any, outside the area the surface was fitted on.

## 5. Stage 2: v4 with the surface (development, year-blocked CV 2007-2017)

- **Reference** `v4`: the adopted v4 configuration (`configs/hazard_v4.yaml`, candidate `v4`), which must reproduce the
  stored v4 development result (pooled OOF FA@90 to 1e-12, tree count exactly; `data/processed/hazard/v4/dev_results.json`).
- **Candidates (two):** `v4_ks` = v4 plus `susc_kerala` everywhere; `v4_ksg` = v4 plus `susc_kerala` in region
  `western_ghats` only (NaN elsewhere: a Kerala surface may not transfer to the Himalaya). Both constrain `susc_kerala`
  non-decreasing. Same folds, seeds, ensemble and per-region calibration as v4.
- **Development criteria**, all on pooled out-of-fold FA@90 differences against the reference on identical rows
  (lower is better), point estimates, with the paired-bootstrap intervals reported:
  - (a) pooled: below 0;
  - (b) within each region: at most 0 in `himalaya` and in `western_ghats` separately (the gain must survive inside
    regions, not come from mixing them);
  - (c) reporting-bias guard: at most 0 on the development rows in the lowest third of scored cells by `road_density`
    (the gain must not live only where roads are, which is where reports are).
  Reported, not deciding: the difference on development rows farther than 20 km from every stage 1 cell (transfer).
- **Selection.** Of the candidates meeting (a)-(c), the one with the lower pooled FA@90. If none does, the study ends:
  no look.

## 6. The held-out look (once, for the selected candidate only)

POOLED 2018-2025, the W1 assembly, minus the events excluded in section 4. The selected candidate against
`v4_ranked`, the adopted v4 ranked by its own calibrated risk; both cut, season by season, to the Watch+ / Warning+ /
Emergency shares v3 realised with the section 11 rules (W3's burden matching, tie-break and preflight rules unchanged).
Before any candidate outcome, v3 with the rules is scored on the full W1 event set and must reproduce the W1 report's
numbers (the pool check), and the look-started marker is written.

**Adoption criterion:** the candidate is adopted only if its independent-slide detection at Warning+ and at Emergency
is at least `v4_ranked`'s in all four comparisons (tolerant and cell-exact), and higher in at least one, on the
reduced event set. Watch+ and the transfer readout are reported and do not decide. Nothing is tuned after the look.

## 7. What adoption would mean

Adoption here is a research result, not a live change. Using the surface in the live run would change published alert
levels, so it is a model change that needs its own reviewed step and the user's yes. The README's caveat stands: a
research prototype, not validated for issuing public warnings. Ground truth after 2018 is very incomplete; detection
counts compare models at equal burden and are not absolute skill.

## 8. Outputs

`data/processed/features/susc_kerala/` (surface, stage 1 results), `data/processed/hazard/v4_ks/` (development, models,
preflight, the look), `data/processed/alerts/v4_ks_seasons/`, `reports/phase9_kerala_susceptibility.{md,json}`.
