# W4: soil moisture / antecedent wetness inputs and the combined model v5 (pre-declared)

Date: 2026-11-13. Status: pre-declared before any model result of this workstream. Roadmap section 4 W4. The source probe
(`reports/phase8_wetness_sources_probe.{json,md}`, `aetherguard.features.wetness_probe`) is done; no development or held-out
number of a wetness input exists yet.

## 1. Why, and what the probe decided

Wet ground is the best-documented precondition of rain-triggered slides. v4 (41 inputs) knows antecedent wetness only through
rain accumulations of 1 to 90 days. The probe tested the soil-moisture products that could give the model a true soil state:

- SMAP L4 starts 2015-03-31 (8 of the 11 development years missing): fails history.
- ERA5 (the public ARCO store, no account) has the history and is the training candidate; its ERA5T tail is about 6 days
  behind. As live stand-ins, the IFS open-data analysis (`vsw`, from 2024-11-13) and the GFS analysis (`SOILW`) both FAILED the
  mapping check fixed before it was measured (median per-pixel percentile-rank difference to ERA5 above 0.10 in every pair).
  ERA5T itself, with a declared lag of at least 7 days, is not chosen: a week-old state, one latency observation, an update
  schedule nobody guarantees.
- GLDAS, FLDAS and MERRA-2 are weeks to months behind. Snow (MODIS) is not pursued for a June-December panel.
- History: in v2 dropping MERRA-2 wetness, and in v3 adding the antecedent precipitation index, each moved development FA@90
  by less than one bootstrap SE.

Chosen: a bucket water balance on the IMERG Late store the model already reads: no new source, the same quantity in training
and live by construction. It is also the baseline any later external product must beat.

## 2. Inputs (group `iwet`, `aetherguard.features.wetness`)

Per 0.1-degree IMERG pixel (cells map to pixels as for `irain`), a Manabe bucket of 150 mm: each IMD day the loss is
PET * min(1, W / (0.75 * 150)), the rain of the IMD day is added, W is kept in [0, 150]. PET is a climatological loss computed
exactly from latitude and day of year (0.25 of the extraterrestrial radiation of FAO-56 eq. 21, in mm of water): 3.5-4.5 mm/day
in the monsoon, 1.5-3 in winter. Nothing is fitted. Each value is a run from an empty bucket over the 120 IMD days ending at
E = D - 2.

| input | meaning | live lag | constraint, and why |
|---|---|---|---|
| `iwet_sat_l2` | W / 150 at the end of IMD day D-2 | 2 IMD days | non-decreasing: wetter ground never lowers the hazard |
| `iwet_sat_anom_l2` | `iwet_sat_l2` minus its mean for the pixel and calendar month over 2007-2015 (train range only) | 2 IMD days | non-decreasing: unusually wet for the place and season |
| `iwet_satdays30_l2` | IMD days of the 30 ending at D-2 with the bucket at least 95% full | 2 IMD days | non-decreasing: longer near saturation, higher pore pressure |

Lag 2 is measured, not assumed: in 32 of the 33 published live runs the UTC day D-2 came from the Late store at the run's start
(`run.json` `imd_day_inputs`; the exception, 2026-10-25, started at 07:00 UTC with the Late file late), so IMD day D-2 (0.875 of
UTC D-3, 0.125 of UTC D-2) is all Late. On a day without it the adapter returns NaN; the wiring step decides what the live run
does then. Nothing from
the Early run or the GFS tail enters, and no rain after 03:00 UTC of D-2 enters (a unit test checks this). The trigger rain of
IMD days D-1 and D stays where it is (`irain`, `iint`). NaN rule: a missing rain day adds no rain; a missing day among the last
30 makes the three inputs NaN. The live adapter `wetness.live_features` is the training function for one day; wiring it into
`live/run.py` is a later, reviewed step.

## 3. Candidates (two models, as W5/W6)

- **w4_wet** (stage 1) = the frozen v3-live configuration (folds, seeds, hyper-parameters, tree-count rule, 20-member ensemble,
  per-region isotonic calibration, monotone constraints) plus the three `iwet` inputs, non-decreasing. Run by
  `hazard.v4_int` with `configs/hazard_w4_wet.yaml`.
- **v5** (stage 2) = v4's inputs (v3-live, the six `iint` inputs lagged 1 day, non-decreasing, and the nine static inputs,
  unconstrained) plus the three `iwet` inputs, non-decreasing. Run by `hazard.v4_combined` (the `hazard.v4_int` stages) with
  `configs/hazard_v5.yaml`.

No other candidate is selected on. The ablation of section 5 is reported, never used to choose inputs.

## 4. Pre-declared criteria

**Stage 1 (development, year-blocked CV 2007-2017, v3's folds and seeds):** the reference C0 must reproduce the frozen v3-live
pooled OOF FA@90 (0.1955) to 1e-12 with the same tree count; w4_wet passes when the 95% paired-bootstrap interval of
FA@90(w4_wet) - FA@90(C0) has its lower bound at or below 0 (W5's guard). A failed stage 1 is final for the group: no v5, no
look.

**Stage 2 (development):** v5 passes when the interval of FA@90(v5) - FA@90(C0) has its lower bound at or below 0 (W6's guard)
AND the interval of FA@90(v5) - FA@90(v4) on the same OOF rows (v4's stored OOF scores) has its lower bound at or below 0: v5
must not be significantly worse than the incumbent it would replace. A failure means no look.

**The checks of section 5 must not flag** (rules there). A flag stops the work before the look; it is reported, and nothing
is tuned to clear it.

**Held-out (once, v5 only):** POOLED 2018-2025, 87 independent slides, the W1 assembly. v5 against `v4_ranked`: v4's own season
panels (`v4_seasons`), both ranked by their own calibrated risk (ties by raw score, then the seeded key of W3, seed 20261106)
and cut, season by season, to the Watch+ / Warning+ / Emergency shares v3 realised with the section 11 rules; W3's preflight,
burden matching, tie and look-started guards apply unchanged. v5 is adopted only if its independent-slide detection at
Warning+ and at Emergency is at least `v4_ranked`'s in all four comparisons (tolerant and cell-exact) and higher in at least
one. Watch+ is reported and does not decide. Nothing is tuned after the look. The look's result goes to
`data/processed/hazard/v5/heldout.json` and its report to `reports/phase8_wetness_heldout.{md,json}` (a different stem from
the development report, so the committed development report does not read as a look taken). Adoption into the live run is a
separate, reviewed step.

## 5. Checks before the look (development data only), and the ablation

- **C1 where, not when (W5's lesson).** The climatological part of the wetness, `iwet_sat_clim` = `iwet_sat_l2` -
  `iwet_sat_anom_l2` (a static map per calendar month), says where it is usually wet, which is also where people live and
  slides get reported. Development CV of v3 plus `iwet_sat_clim` alone. **Flag** if its FA@90 is at or below w4_wet's: the gain
  would then be a where-effect, not antecedent wetness.
- **C2 reporting bias by built-up share.** The paired FA@90 difference w4_wet - C0 within the terciles of the W5 `lc_built`
  share (positives and universe negatives of each tercile, cell joined on `cell_id`). **Flag** if the top tercile's
  difference is negative while both other terciles' are at or above 0 (the whole gain where slides are reported most).
- **C3 missingness.** The NaN share of each input among development positives and among universe negatives. **Flag** if
  they differ by more than 1 percentage point (missingness standing in for the label).
- **C4 lag and leakage**, by tests: no rain after IMD day D-2 enters a value of day D; a row's value does not depend on the
  rows computed with it; the live adapter is the training function; development stages read no 2018-2025 outcome.
- **Ablation by input** (reported only): v3 plus each `iwet` input alone, and v3 plus the three minus each one.

## 6. Outputs and commands

`data/processed/features/imerg/{*_iwet.parquet, season_<year>_iwet.parquet, iwet_columns.json, iwet_manifest.json,
iwet_report.json, iwet_clim.npz}`; `data/processed/hazard/w4_wet/`, `data/processed/hazard/v5/`,
`data/processed/alerts/v5_seasons/`; `reports/phase8_wetness.{md,json}` (development half);
`reports/phase8_wetness_heldout.{md,json}` (after the look).

    python -m aetherguard.features.wetness tables
    python -m aetherguard.hazard.v4_int dev --config configs/hazard_w4_wet.yaml          # stage 1
    python -m aetherguard.hazard.w4_wetness checks                                       # section 5 (development only)
    python -m aetherguard.hazard.v4_combined dev --config configs/hazard_v5.yaml        # stage 2
    python -m aetherguard.hazard.v4_combined seasons --config configs/hazard_v5.yaml
    python -m aetherguard.hazard.v4_combined preflight --config configs/hazard_v5.yaml
    python -m aetherguard.hazard.w4_wetness report                                       # reports/phase8_wetness.*
    python -m aetherguard.hazard.v4_combined heldout --config configs/hazard_v5.yaml    # the one look (lead only)

Caveats carried into every report: ground truth after 2018 is very incomplete, so held-out detection counts compare models at
equal burden and are not absolute; tolerant matching has a high chance floor at Watch+ and Warning+.

## 7. Amendment 2026-11-14 (after the development stages, before any held-out number of v5)

Written after stage 1 (w4_wet - C0 +0.0003 [-0.0209, +0.0141], no gain), stage 2 (v5 - C0 -0.0241 [-0.0515, +0.0052];
v5 - v4 -0.0058 [-0.0167, +0.0113]) and a passed preflight (54 of 54 checks, no outcome computed), and before any held-out
number of v5 exists. Nothing in sections 3-5 changes.

- **The deciding comparison stays exactly as declared in section 4:** v5 against `v4_ranked` on the licence-clean W1 assembly
  (POOLED 2018-2025, 92 records of 87 independent slides: `catalog_2018`, `catalog_sparse`, `reported`), at equal burden,
  every independent-slide detection row at Warning+ and Emergency (tolerant and cell-exact) not lower and at least one higher.
- **Assembly v2** (`data/processed/heldout_v2`, frozen 2026-11-13, 1,509 day records: 1,417 from the Nepal BIPAD register,
  91 India, 1 Bangladesh) is reported beside it and decides nothing: the same v5 against `v4_ranked` comparison at the same
  burden, broken down by country and with and without BIPAD. The BIPAD register states no licence; by the user's decision
  (2026-11-14) it is used locally only and its numbers may appear in public reports, always beside the licence-clean numbers
  and marked as from a source without a stated licence. The register data itself is never committed.
- The v2 beside-report is computed after the look, from the stored v5 and v4 season panels, and cannot change the decision of
  section 4. If it disagrees with the W1 result, the report says so; nothing is tuned to reconcile them.
