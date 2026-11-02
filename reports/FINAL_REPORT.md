# AetherGuard: final report

Assembled by `python -m aetherguard.finalreport` from the phase reports in `reports/` and the frozen data products. Every number is read from a source file (the JSON output lists each figure with its file and path); a source that is not there yet shows as `pending: <file>`.


## 1. Summary

AetherGuard is a research prototype of a two-stage early-warning pipeline for rain-triggered landslides in the Himalaya and Western Ghats: **stage 1** judges whether each rain sensor reading can be trusted (a sensor-integrity engine trained on faults injected into real gauge series), **stage 2** estimates a calibrated landslide risk per cell-day from trusted multi-source rain, soil wetness and terrain, with an extreme-rain corrector and an alert engine that never stays silent when it is blind. All figures below are read from the phase reports; none is typed by hand. It is not validated for issuing public warnings.

| headline figure | value [95% CI where given] | source |
|---|---|---|
| Integrity engine, TEST macro recall (combined decision at the validation-chosen 1% threshold) | 0.70 | reports/phase2_integrity_report.json |
| ... realised TEST false-flag rate of that decision | 0.049 | reports/phase2_integrity_report.json |
| ... same engine without the two Nepal stations (post hoc), false-flag rate | 0.009 | reports/phase2_integrity_report.json |
| Best rule baseline on TEST (L1 checks), macro recall | 0.30 | reports/phase2_integrity_report.json |
| NOAA-style QA with spatial check (wide neighbours), macro recall | 0.25 | reports/phase2_integrity_report.json |
| Engine matched to the NOAA-style false-flag rate (oracle, not deployable), macro recall | 0.54 | reports/phase2_integrity_report.json |
| Corrector pinball skill vs raw CHIRPS, alpha 0.9 (TEST stations) | 0.432 | reports/phase3_corrector_report.json |
| Corrector, Wayanad 2024-07-30: predicted q90 as a share of the IMD value | 0.40 | reports/phase3_corrector_report.json |
| Day basis: peak lag of the station-vs-IMD correlation (days) | +0 | reports/phase2b_day_basis.json |
| Day basis: peak lag of station vs CHIRPS on the UTC day | -1 | reports/phase2b_day_basis.json |
| Hazard v1 (disclosed history): test_2018 recall at the validation threshold | 0.787 [0.700, 0.875] | reports/phase3_hazard_report_v1.json |
| Hazard v1: false-alarm share at 90% recall minus best baseline, test_2018 (paired, vs intensity-duration) | 0.036 [-0.131, 0.134] | reports/phase3_hazard_report_v1.json |
| Hazard v2 (frozen, single test look): test_2018 in-domain recall at the Watch threshold (target 0.90) | 0.850 [0.775, 0.925] | reports/phase3_hazard_report.json |
| ... false-alarm share of all cell-days at that threshold | 0.214 [0.212, 0.216] | reports/phase3_hazard_report.json |
| ... intensity-duration baseline at its own frozen Watch threshold: recall | 0.875 [0.800, 0.938] | reports/phase3_hazard_report.json |
| ... false-alarm share: intensity-duration minus model (paired) | 0.110 [0.108, 0.112] | reports/phase3_hazard_report.json |
| Alert system (model + uncertain_high + blind rule + hysteresis): test_2018 in-domain recall at Watch+ | 0.912 | reports/phase4_alerts_report.json |
| ... Watch+ alerts per 1000 cell-days | 271.6 | reports/phase4_alerts_report.json |
| Kerala 2018: positive cell-days detected at Watch+ (of 23) | 23 | reports/phase4_alerts_report.json |
| Wayanad 2024: days the focus cell sits at Emergency (of 22; levels saturate, no day singled out) | 22 | reports/phase4_alerts_report.json |

**Hazard model v2** (protocol v2) and the **alert engine**: 
- hazard v2 stage-1 cross-validation report: `reports/phase3_hazard_cv_report.json` (sections 5 and 6)
- hazard v2 test evaluation: `reports/phase3_hazard_report.json` (sections 5 and 6)
- alerts report: `reports/phase4_alerts_report.json` (sections 5 and 6)


## 2. Data

Sources (all open, no login except the NASA Earthdata label catalogs): GHCN-Daily gauges (NOAA), IMD gauge-based 0.25 degree daily grid, CHIRPS v2.0 0.05 degree daily, NASA POWER / MERRA-2 soil wetness, Copernicus GLO-90 terrain, Open-Meteo ERA5 for the two case-study points, and the NASA GLC, COOLR and High Mountain Asia landslide catalogs for labels. Licences are listed in the README.


### Sensors and rain products

| item | value | source |
|---|---|---|
| GHCN-Daily rain gauges selected (India + Nepal) | 140 | reports/phase2a_baselines.json |
| Share of station-days with a value, 1990-2024 | 0.265 | reports/phase2a_baselines.json |
| Clean real station-days (valid, unflagged, station-year >= 200 valid days) | 231,539 | reports/phase2a_baselines.json |
| Stations with >= 365 clean days | 73 | reports/phase2a_baselines.json |
| Clean days with >= 2 valid neighbours, design setting (k=5, 150 km) | 0.051 | reports/phase2a_baselines.json |
| Clean days with >= 2 valid neighbours, wide setting (k=10, 300 km) | 0.784 | reports/phase2a_baselines.json |
| Real NOAA-flagged values inside 2007-2024 (the only ones scorable against references) | 10 | reports/phase2_integrity_report.json |
| IMD grid: covered 0.25 degree points (gauge data on > 95% of days every year) | 4,964 | data/processed/rain/imd_index.json |
| POWER wetness: days in the store | 6,575 | data/processed/rain/power_index.json |
| POWER wetness: first / last day | 2007-01-01 / 2024-12-31 | data/processed/rain/power_index.json |
| Terrain cells (0.05 degree) | 166,728 | data/processed/terrain/terrain_report.json |
| Cells with a region / country label | 166,728 | data/processed/features/cell_regions_report.json |


### Labels and frozen splits

| quantity | value | source |
|---|---|---|
| Day-exact positive cell-days | 919 | data/processed/splits/splits_manifest.json |
| Day-exact events | 956 | data/processed/splits/splits_manifest.json |
| 2023 India window: cells / events | 24 / 176 | data/processed/splits/splits_manifest.json |
| Split train: cell-days / events | 591 / 616 | data/processed/splits/splits_manifest.json |
| Split validation: cell-days / events | 233 / 242 | data/processed/splits/splits_manifest.json |
| Split test_2018: cell-days / events | 85 / 87 | data/processed/splits/splits_manifest.json |
| Split test_sparse: cell-days / events | 10 / 11 | data/processed/splits/splits_manifest.json |

Splits are by event date (train 2007-2015, validation 2016-2017, test 2018, sparse 2019-2024) and by station for the integrity engine; both are frozen with checksums. See `docs/phase1-design.md` for the label rules, the day basis and the negatives.


### Fault dataset for stage 1

Faults are INJECTED into real clean 2007-2024 series (stuck value, zero fault, spike, scale drift, offset noise, duplicate block); episodes per type and split:

| split | stuck_value | zero_fault | spike | scale_drift | offset_noise | duplicate_block |
|---|---|---|---|---|---|---|
| train | 71 | 76 | 67 | 31 | 58 | 67 |
| val | 27 | 29 | 29 | 12 | 22 | 28 |
| test | 22 | 21 | 23 | 14 | 19 | 23 |


## 3. Where existing systems fail, and what AetherGuard does about it

### 3.1 Evidence (from the design spec)

**Verified with live requests during design (2026-09-30):**
- Wayanad (11.55 N, 76.13 E), 29–30 July 2024, 48-hour rainfall: ERA5 ≈ 107 mm, ECMWF IFS ≈ 106 mm, MERRA-2 (NASA POWER) ≈ 80 mm, versus ≈ 572 mm reported from local gauges (secondary source). A ~25 km grid cell vs. a point gauge explains part of, but unlikely all of, a 5–7× gap.
- GHCN-Daily stations with precipitation, active 2015–2024: **138 in India, 2 in Nepal** — real labelled gauge data is thin in the Himalaya.
- IMERG and the NSIDC High Mountain Asia landslide catalog require a free NASA Earthdata login.
- Open with no login: Open-Meteo (ERA5/IFS), NASA POWER (MERRA-2), CHIRPS, Copernicus DEM 30 m, ESA WorldCover, NOAA GHCN-Daily / ISD, Zenodo. SoilGrids: file host reachable, REST endpoint timed out. NASA Global Landslide Catalog: no scriptable download found; export is via the Landslide Viewer UI.

**From literature and press (search summaries only — primary sources to be read before figures are quoted in reports):**
- NASA LHASA probability of detection reportedly 8–60 % depending on rain product and evaluation window.
- India's GSI regional landslide forecast (launched 19 July 2024) was experimental; Wayanad rated "low" until the day; rain forecast for 30 July was ~15 mm vs. observed extreme; IMD red alert issued after the slides.
- Tipping-bucket gauges: clogging → zero rain during storms; power/transmission gaps; undercatch of ~2–30 %.
- Geographical landslide early-warning systems lack uniform validation criteria; low thresholds cause many false alarms (Guzzetti et al., 2020).

### 3.2 Failure → design response (from the design spec)

| # | Failure | AetherGuard response |
|---|---|---|
| F1 | Global rain products badly under-measure extreme orographic rain | Multi-source rain fusion; source *disagreement* used as a risk feature; upper-quantile rain corrector; honest uncertainty widening (§7) |
| F2 | Sensor faults undetected or indistinguishable from real extremes (a blocked gauge reads "no rain" in a storm) | Stage-1 integrity engine with cross-source and physical-coupling checks (§6) |
| F3 | Low detection / many false alarms from static thresholds | Stage-2 model on rain history, soil wetness, terrain; calibrated probabilities; recall-first operating point (§7) |
| F4 | Inflated accuracy from random splits and biased labels | Time- and region-blocked frozen test set; per-event evaluation; false alarms reported as upper bounds (§4.3, §10) |
| F5 | No uncertainty, no degraded mode, silent failure | Data-confidence flag; escalate (never silent "Normal") when blind and independent sources show heavy rain (§8) |

---


### Measured here

**CHIRPS misses the Wayanad event day** (a daily artifact of the product, see the finding quoted in section 8). Wayanad cell, IMD day 2024-07-30:

| source | mm on 2024-07-30 | from |
|---|---|---|
| IMD grid | 179.2 | reports/phase3e_case_inputs.json |
| CHIRPS aligned | 43.5 | reports/phase3e_case_inputs.json |
| CHIRPS UTC day | 0.0 | reports/phase3e_case_inputs.json |
| ERA5 UTC day | 53.3 | reports/phase3e_case_inputs.json |
| ERA5 IMD day (exact) | 66.9 | reports/phase3e_case_inputs.json |
| nearest trusted gauge (distance below) | 154.9 | reports/phase3e_case_inputs.json |
| corrector q90 | 63.8 | reports/phase3e_case_inputs.json |
| corrector q99 | 134.7 | reports/phase3e_case_inputs.json |

The nearest gauge is 45 km away with out-of-fold trust 0.99.

**ERA5 hourly data: UTC day versus IMD day.** The D5 approximation (0.875 x UTC(D-1) + 0.125 x UTC(D)) against the exact IMD-day total from hourly ERA5 at the Wayanad point:

| measure | value | source |
|---|---|---|
| days compared | 34 | reports/phase3e_case_inputs.json |
| mean absolute error (mm) | 1.85 | reports/phase3e_case_inputs.json |
| largest absolute error (mm) | 10.5 | reports/phase3e_case_inputs.json |
| relative error on heavy days (>= 10 mm) | 0.077 | reports/phase3e_case_inputs.json |

**Which day does a gauge value belong to?** Lag correlation of clean station days against IMD and CHIRPS (medians over stations):

- imd: median Pearson peaks at lag +0 (0.688, 95% CI [0.530, 0.882]; 11 stations); Spearman peaks at lag +0; per-station peak lags: {'0': 11}.
- chirps_utc: median Pearson peaks at lag -1 (0.378, 95% CI [0.295, 0.426]; 11 stations); Spearman peaks at lag -1; lag 0 is NOT the maximum (median Pearson 0.156, CI [0.124, 0.207]); per-station peak lags: {'-2': 1, '-1': 10}.
- chirps_aligned: median Pearson peaks at lag +0 (0.378, 95% CI [0.318, 0.458]; 11 stations); Spearman peaks at lag +0; per-station peak lags: {'-1': 1, '0': 10}.
- Implication for D5: station vs IMD agrees best at lag 0 (same day label); CHIRPS on the UTC day is best matched by the previous UTC day (lag -1), as an IMD-day label (03:00 UTC D-1 to 03:00 UTC D) predicts; the D5-aligned CHIRPS agrees best at lag 0, which supports the alignment.

| product | peak lag (days) | median Pearson at lag 0 [95% CI] | median Pearson at the peak [95% CI] | stations |
|---|---|---|---|---|
| imd | +0 | 0.688 [0.530, 0.882] | 0.688 [0.530, 0.882] | 11 |
| chirps_utc | -1 | 0.156 [0.124, 0.207] | 0.378 [0.295, 0.426] | 11 |
| chirps_aligned | +0 | 0.378 [0.318, 0.458] | 0.378 [0.318, 0.458] | 11 |

**NOAA-style QA misses the faults that matter for rain gauges.** TEST recall of the NOAA-style re-implementation (streak, duplicate block, climatological outlier, spatial check) against the engine, injected faults only:

| fault type | NOAA-style, design neighbours | NOAA-style, wide neighbours | AetherGuard engine |
|---|---|---|---|
| zero_fault | 0.03 (fpr 0.001) [0.00, 0.06] | 0.19 (fpr 0.013) [0.10, 0.33] | 0.80 (fpr 0.049) [0.69, 0.87] |
| scale_drift | 0.00 n/a (degenerate) (fpr 0.001) | 0.01 (fpr 0.013) [0.00, 0.02] | 0.22 (fpr 0.049) [0.05, 0.31] |
| offset_noise | 0.00 n/a (degenerate) (fpr 0.001) | 0.00 n/a (degenerate) (fpr 0.013) | 0.51 (fpr 0.049) [0.38, 0.58] |

What AetherGuard does about it, in the design's terms: multi-source rain with source disagreement as a feature (F1), a stage-1 integrity engine with cross-source checks (F2), a calibrated stage-2 model (F3), frozen time- and region-blocked evaluation (F4) and an alert engine with a data-confidence flag that escalates, never silently stays Normal, when blind (F5).


## 4. Stage 1: sensor-integrity results

Evaluation is on the TEST stations (frozen, unseen), recall per injected fault type with 95% bootstrap CIs over stations; rule flags show their realised false-flag rate on clean days, score methods are matched to 1%. The combined engine uses the threshold chosen on the validation stations.


### TEST recall per fault type

| method | stuck_value | zero_fault | spike | scale_drift | offset_noise | duplicate_block | macro |
|---|---|---|---|---|---|---|---|
| range check | 0.00 n/a (degenerate) (fpr 0.000) | 0.00 n/a (degenerate) (fpr 0.000) | 0.00 n/a (degenerate) (fpr 0.000) | 0.00 n/a (degenerate) (fpr 0.000) | 0.00 n/a (degenerate) (fpr 0.000) | 0.00 n/a (degenerate) (fpr 0.000) | 0.00 |
| L1 deterministic checks | 1.00 n/a (degenerate) (fpr 0.002) | 0.00 n/a (degenerate) (fpr 0.002) | 0.00 n/a (degenerate) (fpr 0.002) | 0.00 n/a (degenerate) (fpr 0.002) | 0.03 (fpr 0.002) [0.00, 0.04] | 0.77 (fpr 0.002) [0.51, 1.00] | 0.30 |
| NOAA-style QA (design neighbours) | 0.88 (fpr 0.001) [0.74, 0.96] | 0.03 (fpr 0.001) [0.00, 0.06] | 0.26 (fpr 0.001) [0.05, 0.53] | 0.00 n/a (degenerate) (fpr 0.001) | 0.00 n/a (degenerate) (fpr 0.001) | 0.00 n/a (degenerate) (fpr 0.001) | 0.20 |
| NOAA-style QA (wide neighbours) | 0.89 (fpr 0.013) [0.76, 0.96] | 0.19 (fpr 0.013) [0.10, 0.33] | 0.35 (fpr 0.013) [0.14, 0.58] | 0.01 (fpr 0.013) [0.00, 0.02] | 0.00 n/a (degenerate) (fpr 0.013) | 0.06 (fpr 0.013) [0.03, 0.12] | 0.25 |
| robust z-score | 0.16 [0.00, 0.33] | 0.00 n/a (degenerate) | 0.39 [0.05, 0.68] | 0.00 [0.00, 0.01] | 0.00 n/a (degenerate) | 0.03 [0.00, 0.06] | 0.10 |
| isolation forest | 0.00 n/a (degenerate) | 0.00 n/a (degenerate) | 0.22 [0.00, 0.48] | 0.00 n/a (degenerate) | 0.00 n/a (degenerate) | 0.00 n/a (degenerate) | 0.04 |
| engine, model score only (1%) | 0.84 [0.80, 0.86] | 0.63 [0.47, 0.73] | 0.57 [0.33, 0.81] | 0.02 [0.00, 0.03] | 0.19 [0.14, 0.21] | 0.02 [0.00, 0.04] | 0.38 |
| **engine, combined, VAL-chosen 1% threshold** | 0.97 (fpr 0.049) [0.94, 1.00] | 0.80 (fpr 0.049) [0.69, 0.87] | 0.87 (fpr 0.049) [0.76, 1.00] | 0.22 (fpr 0.049) [0.05, 0.31] | 0.51 (fpr 0.049) [0.38, 0.58] | 0.83 (fpr 0.049) [0.60, 1.00] | 0.70 |
| engine, combined, no arbiter | 1.00 n/a (degenerate) (fpr 0.051) | 0.80 (fpr 0.051) [0.69, 0.87] | 0.87 (fpr 0.051) [0.76, 1.00] | 0.28 (fpr 0.051) [0.09, 0.38] | 0.51 (fpr 0.051) [0.38, 0.58] | 0.84 (fpr 0.051) [0.61, 1.00] | 0.71 |
| engine, oracle-matched to NOAA-wide rate (not deployable) | 0.97 (fpr 0.013) [0.94, 1.00] | 0.65 (fpr 0.013) [0.51, 0.74] | 0.57 (fpr 0.013) [0.33, 0.81] | 0.03 (fpr 0.013) [0.00, 0.05] | 0.22 (fpr 0.013) [0.14, 0.24] | 0.78 (fpr 0.013) [0.51, 1.00] | 0.54 |


### Operating points of the combined engine

| target false-flag rate | threshold | VAL realised rate | VAL macro recall | TEST realised rate | TEST macro recall |
|---|---|---|---|---|---|
| 0.005 | 0.714 | 0.0050 | 0.643 | 0.0348 | 0.658 |
| 0.01 | 0.507 | 0.0100 | 0.695 | 0.0492 | 0.702 |
| 0.02 | 0.344 | 0.0199 | 0.730 | 0.0684 | 0.747 |

At the VAL-chosen 1% tau the combined engine flags 0.0100 of VAL clean days but 0.0492 of TEST clean days. 91% of the TEST false flags (496 of 545) come from the two Nepal stations, which hold 51% of the TEST clean days and are the only TEST stations outside the training distribution of Indian stations; without them the TEST rate is 0.0089. The threshold does not transfer to those stations: the engine is NOT at 1% on TEST, so the full-engine recalls below are at a higher false-flag rate than the baselines (read the oracle-matched rows and the model-score rows for matched-rate comparisons).

Concentration of the TEST false flags: 496 of 545 come from the two Nepal stations (TEST rate without them 0.0089).


### Genuine-extreme retention and the arbiter's cost

Retained / extremes among clean, unflagged readings at or above each station's 99.5th wet-day percentile; no single number is the safety result. `design-strict` and `wide` need two corroborating neighbours, `uncorroborated` is a proxy that includes unverified readings.

| method | design | wide | wide_1neighbour | uncorroborated |
|---|---|---|---|---|
| engine (with arbiter) | 3/3 | 9/9 | 17/18 | 24/26 |
| engine without arbiter | 3/3 | 9/9 | 17/18 | 24/26 |
| model score only | 3/3 | 9/9 | 18/18 | 25/26 |
| robust z-score | 3/3 | 5/9 | 13/18 | 21/26 |
| NOAA-style, wide | 3/3 | 9/9 | 18/18 | 26/26 |

Injected spikes flagged without the arbiter / with it / retained by the arbiter: 20 / 20 / 0.


### Repair (flagged, non-retained injected-fault days)

| estimate | MAE mm | median abs error mm |
|---|---|---|
| engine repair (weighted median of references) | 11.24 | 6.00 |
| previous day | 19.44 | 12.10 |
| neighbour mean | 15.34 | 8.35 |
| zero fill | 13.17 | 5.10 |
| no repair (observed) | 27.71 | 11.65 |

Band coverage 0.755; hazard-safe check (repaired >= half of the truth on days with >= 50 mm): 0.425 of 40 days. Repaired values never feed the rain features.


### Ablations, seed stability, real flags

| variant (model score, TEST macro recall at 1%) | macro recall |
|---|---|
| full model | 0.377 |
| own_only | 0.255 |
| no_grid | 0.404 |
| no_nbr | 0.400 |
| no_wet | 0.333 |
| no_dropout | 0.370 |
| no_extra_seeds | 0.277 |

Stability over three further injection seeds (combined engine, TEST macro recall): mean 0.679, min 0.649, max 0.702.

Real NOAA flags 2007-2024 (n = 10, too few to rank methods): the engine flags 9, NOAA-style QA (wide) 6, L1 0.

Out-of-fold outputs for the hazard model: 920,500 station-days, trust NaN on 0.769 (days without a value).


### Baselines on the full 1990-2024 history (phase 2a)

| rule | false-flag rate on real clean days |
|---|---|
| bounds | 0.00000 |
| stuck | 0.00075 |
| duplicate_block | 0.00000 |
| l1_flag | 0.00075 |


## 5. Stage 2: hazard model and extreme-rain corrector


### Hazard model v1 (disclosed history)

v1 selected hyper-parameters on the validation split and re-used it for calibration and the threshold; it is kept as disclosed history because the protocol change that produced v2 was partly prompted by its test result. False-alarm share at 90% recall, model versus each baseline (paired bootstrap, positive favours the model):

| baseline | validation: baseline minus model [95% CI] | test_2018: baseline minus model [95% CI] |
|---|---|---|
| intensity-duration | 0.134 [0.065, 0.191] | 0.036 [-0.131, 0.134] |
| LHASA-style | 0.199 [0.124, 0.257] | 0.119 [-0.050, 0.185] |
| logistic regression | 0.207 [0.118, 0.246] | 0.207 [-0.001, 0.243] |

test_2018 recall at the validation-chosen threshold (in-domain events, target 90%): 0.787 [0.700, 0.875] of 80 events. only 80 positive cell-days (< 100): intervals are wide and unstable


### Protocol v2 and the final hazard model

#### Protocol v2 (controller ruling, 2026-10-02, after the v1 run) (from docs/phase3-design.md)

v1 (`reports/phase3_hazard_report_v1.md`) used the 2016-17 validation split for hyper-parameter selection (48 candidates), early stopping on a noisy false-alarm metric, isotonic calibration AND the 90%-recall threshold. That re-use made the threshold optimistic: test_2018 recall at the validation threshold was 78.8% (target 90%), calibration over-predicted by 36%, and the model tied all baselines on test. `stat_elev_mean` was the top feature (17% gain), a probable location/inventory-bias proxy.
v2, decided before any further look at test_2018:
- Development period 2007-2017 (train + validation splits pooled as rows, never test_2018). Year-blocked cross-validation (folds = contiguous year blocks, e.g. 2007-08, 2009-10, 2011-12, 2013-14, 2015, 2016, 2017) for ALL choices: hyper-parameters (small, regularised grid), number of trees (median of fold-optimal counts), feature groups (incl. dropping elevation-like static columns, adding `integ_` and `corr_` when available).
- Calibration and thresholds from the pooled out-of-fold scores (universe weights per year), recall-first margin: the operating threshold is the highest one whose bootstrap 5th-percentile out-of-fold recall is >= 90%.
- Final model refit on all development rows with the chosen settings; baselines get the identical treatment (thresholds from their own out-of-fold scores over 2007-2017).
- test_2018 is evaluated exactly once with everything frozen; v1 numbers stay in the report as disclosed history (the protocol change was partly prompted by the v1 test result — stated plainly).

**Stage 1 (year-blocked cross-validation on 2007-2017, all choices made out-of-fold):**

##### OOF thresholds and alert levels (model)

recall_first = highest threshold whose bootstrap 5th-percentile OOF recall is at least 90%; Watch = recall_first, Warning = OOF recall 75%, Emergency = OOF recall 50%.

| threshold | raw score | calibrated risk | OOF recall | OOF FA share |
|---|---|---|---|---|
| plain_recall_90 | 0.02738 | 0.000005865 | 90.1% | 18.84% |
| recall_first | 0.02332 | 0.000004134 | 91.8% | 20.95% |
| watch | 0.02332 | 0.000004134 | 91.8% | 20.95% |
| warning | 0.06997 | 0.000015831 | 75.0% | 9.05% |
| emergency | 0.16265 | 0.000036972 | 50.1% | 3.44% |

##### OOF metrics, model versus baselines (same protocol)

| scorer | FA @ 0.8 recall | FA @ 0.9 recall | FA @ 0.95 recall | recall @ FA 0.1% | recall @ FA 1.0% | recall @ FA 5.0% | recall @ FA 10.0% | PR-AUC |
|---|---|---|---|---|---|---|---|---|
| hazard model | 11.2% [9.8, 12.9] | 18.8% [17.3, 21.3] | 28.8% [24.1, 35.1] | 8.0% [6.1, 10.0] | 27.6% [24.5, 30.8] | 58.8% [55.3, 62.2] | 77.4% [74.5, 80.4] | 0.00020 [0.00014, 0.00793] |
| intensity-duration | 22.8% [20.5, 25.1] | 32.1% [30.8, 34.8] | 40.0% [37.4, 45.6] | 1.5% [0.8, 2.5] | 13.4% [11.2, 15.7] | 39.5% [36.1, 42.8] | 56.1% [52.5, 59.4] | 0.00004 [0.00004, 0.00005] |
| LHASA-style | 27.8% [25.7, 30.6] | 37.7% [35.1, 41.4] | 100.0% [43.6, 100.0] | 0.0% [0.0, 0.0] | 2.9% [1.8, 4.1] | 17.0% [14.2, 19.6] | 35.5% [32.1, 39.0] | 0.00002 [0.00002, 0.00002] |
| logistic regression | 23.4% [20.6, 26.0] | 36.1% [31.5, 41.2] | 49.1% [43.6, 55.5] | 1.6% [0.8, 2.7] | 14.6% [12.2, 16.9] | 39.9% [36.2, 43.3] | 60.2% [56.7, 63.4] | 0.00004 [0.00004, 0.00005] |

Own-OOF thresholds (each scorer's thresholds from its own pooled OOF scores):

| scorer | threshold | raw score | OOF recall [95% CI] | OOF FA share [95% CI] |
|---|---|---|---|---|
| hazard model | plain | 0.02738 | 90.1% [88.0, 92.3] | 18.8% [18.7, 19.0] |
| hazard model | recall_first | 0.02332 | 91.8% [89.7, 93.7] | 20.9% [20.8, 21.1] |
| intensity-duration | plain | 2.61954 | 90.1% [88.0, 92.1] | 32.1% [31.9, 32.3] |
| intensity-duration | recall_first | 2.38202 | 91.8% [89.7, 93.7] | 33.9% [33.7, 34.1] |
| LHASA-style | plain | 0.69757 | 90.1% [88.0, 92.0] | 37.7% [37.5, 37.9] |
| LHASA-style | recall_first | 0.43955 | 91.8% [89.7, 93.7] | 41.0% [40.8, 41.2] |
| logistic regression | plain | -0.65494 | 90.1% [88.0, 92.1] | 36.1% [35.9, 36.3] |
| logistic regression | recall_first | -0.77190 | 91.8% [89.7, 93.7] | 40.7% [40.5, 40.9] |

Paired OOF difference in FA share at 90% recall (comparator minus model; positive favours the model):

| comparator | difference [95% CI] | share of resamples model better | verdict |
|---|---|---|---|
| intensity-duration | 0.1328 [0.1115, 0.1526] | 1.00 | model better |
| LHASA-style | 0.1882 [0.1584, 0.2189] | 1.00 | model better |
| logistic regression | 0.1731 [0.1271, 0.2160] | 1.00 | model better |

##### integ candidates with and without a nearby station

FA@90 within each subset uses that subset's own 90%-recall threshold; recall @ FA 5% likewise; the key metric is fa_at_recall_0.9

**with station** (341 positives, 17.5% of the universe cell-days)

| candidate | FA@90 (subset threshold) | recall @ FA 5% | PR-AUC |
|---|---|---|---|
| drop_src | 31.6% [27.4, 37.8] | 43.4% [37.8, 49.0] | 0.00027 [0.00018, 0.00914] |
| drop_src+integ | 32.7% [25.9, 38.7] | 46.9% [41.1, 52.2] | 0.00031 [0.00021, 0.00073] |
| drop_src+integ+corr | 33.2% [28.1, 38.9] | 44.6% [39.0, 49.9] | 0.00022 [0.00015, 0.00045] |

**without station** (448 positives, 82.5% of the universe cell-days)

| candidate | FA@90 (subset threshold) | recall @ FA 5% | PR-AUC |
|---|---|---|---|
| drop_src | 17.6% [14.2, 21.7] | 67.4% [62.9, 71.7] | 0.00680 [0.00010, 0.01795] |
| drop_src+integ | 19.6% [15.7, 24.7] | 69.2% [64.5, 73.2] | 0.00235 [0.00009, 0.00917] |
| drop_src+integ+corr | 19.4% [14.6, 25.8] | 67.4% [62.9, 72.1] | 0.00235 [0.00008, 0.01354] |

**Single frozen test evaluation (test_2018, window 2023, case studies):**

##### 1. Gate assessment

**Recall-first target** (at least 90% of in-domain test_2018 events at the stage-1 Watch threshold, raw score 0.02332 = calibrated risk 0.000004134): NOT reached (shortfall 5.0 points; the 95% CI still contains 90%).

- test recall 85.0% [77.5, 92.5]; false-alarm share at that point 21.4% [21.2, 21.6] (universe non-buffer cell-days alerted)
- plain 90% OOF threshold: recall 82.5% [73.8, 90.0], FA share 19.2% [19.0, 19.4]
- per region: himalaya: recall 87.5% [77.1, 95.8], FA 23.9% [23.6, 24.1]; western_ghats: recall 81.2% [65.6, 93.8], FA 12.6% [12.4, 12.8]
- overall recall counting out-of-domain positives as misses: 80.0% [71.8, 88.2] (in-domain 85.0% [76.2, 92.5])

**Model versus baselines** (paired bootstrap, each scorer at its own frozen Watch threshold; the equal-recall column re-picks each scorer's threshold on the test labels and is descriptive only):

| baseline | model recall | baseline recall | recall: model minus baseline | model FA | baseline FA | FA: baseline minus model | equal-recall FA@90: baseline minus model | verdict |
|---|---|---|---|---|---|---|---|---|
| intensity-duration | 85.0% [77.5, 92.5] | 87.5% [80.0, 93.8] | -0.0250 [-0.0875, 0.0375] | 21.4% [21.2, 21.6] | 32.4% [32.2, 32.7] | 0.1103 [0.1083, 0.1124] | 0.0393 [-0.1572, 0.1620] | tie |
| LHASA-style | 85.0% [77.5, 92.5] | 88.8% [81.2, 95.0] | -0.0375 [-0.1250, 0.0375] | 21.4% [21.2, 21.6] | 39.8% [39.6, 40.1] | 0.1844 [0.1821, 0.1866] | 0.1147 [-0.0728, 0.2440] | tie |
| logistic regression | 85.0% [77.5, 92.5] | 86.2% [78.8, 93.8] | -0.0125 [-0.0625, 0.0375] | 21.4% [21.2, 21.6] | 40.9% [40.6, 41.1] | 0.1945 [0.1923, 0.1969] | 0.1992 [0.0293, 0.2774] | model better |

Verdict is read from the equal-recall FA@90 interval: `model better` / `<baseline> better` only when the 95% interval excludes 0, otherwise `tie`. Intervals that include 0 mean test_2018 cannot separate the scorers.

**Limits**

- Statistical power is low: test_2018 has 80 in-domain positive cell-days (48 Himalaya, 32 Ghats), so every interval is wide and per-region and per-baseline comparisons are mostly unresolved.
- The landslide inventory is partial and rain-triggered only (NASA catalogs); unlabeled landslides sit among the universe negatives, so false-alarm shares are upper bounds. The inventory's yearly recording rate varies more than 10-fold across 2007-2017 (8 positives in 2007 and 2008 against 100+ in later years).
- Rain is the 0.25 degree IMD gauge grid (CHIRPS 0.05 degree elsewhere) at daily resolution: no hourly intensity, so short intense bursts are not resolved.
- Positives below the slope floor (outside the model domain) are excluded from training and the primary metrics and counted as misses in the overall recall.
- Elevation (`stat_elev_mean`) is the top feature and dropping it worsened cross-validated FA@90 by more than its standard error; it may act as a location or inventory-reporting proxy. Leave-region-out (with and without elevation) is the check, and with few positives it is only indicative.
- Calibrated probabilities use one pooled base rate; the cross-validated per-year observed rate varied by more than 10x, so the probabilities are uncertain by about a factor of two even where the ranking is good.
- Source-disagreement features (`src_`) were not selected; source disagreement is handled by the alert engine. The integ and corr groups were not selected, so how their features were constructed relative to the CV folds does not affect the frozen model.
- Labels are rain-triggered cell-days only; earthquake, construction and unknown triggers are excluded from positives and kept as buffer.

##### 2. Stage-1 cross-validation results (summary; full tables in `reports/phase3_hazard_cv_report.md`)

Year-blocked CV over 2007-2017, folds [[2007, 2008], [2009, 2010], [2011, 2012], [2013, 2014], [2015], [2016], [2017]]. Selected feature set `drop_src` (30 inputs), 15 leaves, min_data_in_leaf 40, feature_fraction 0.5, lambda_l2 0, learning_rate 0.05, neg_mix `matched_plus_universe`, 118 trees (median of fold optima). The integ and corr groups were evaluated and not selected.

##### 8. Leave-region-out (elevation-as-proxy check)

Frozen hyper-parameters, neg_mix and tree count, refitted on ONE region's development rows (no early stopping) and scored on the other region's test_2018 rows; the full model (trained on both regions) is the reference. Thresholds are re-picked on the test labels per scorer, so this compares ranking only. `no_elevation` drops the elevation-like columns (stat_elev_mean, stat_elev_std). Warnings flag fewer than 100 positives.

**himalaya development rows -> western_ghats test_2018** (32 positives) - WARNING: only 32 positive cell-days (< 100): intervals are wide and unstable

| scorer | FA @ 90% recall | recall @ FA 5% | PR-AUC | FA@90: scorer minus full model |
|---|---|---|---|---|
| full model | 29.5% [8.6, 38.5] | 65.6% [50.0, 81.2] | 0.00026 [0.00014, 0.00081] | - |
| region_only | 23.1% [9.6, 26.6] | 71.9% [56.2, 87.5] | 0.00026 [0.00013, 0.00080] | -0.0643 [-0.1376, 0.0355] (tie) |
| region_only_no_elevation | 20.9% [7.4, 45.4] | 68.8% [53.1, 84.4] | 0.00042 [0.00015, 0.00259] | -0.0864 [-0.1409, 0.0939] (tie) |

**western_ghats development rows -> himalaya test_2018** (48 positives) - WARNING: only 48 positive cell-days (< 100): intervals are wide and unstable

| scorer | FA @ 90% recall | recall @ FA 5% | PR-AUC | FA@90: scorer minus full model |
|---|---|---|---|---|
| full model | 28.8% [16.7, 43.0] | 43.8% [31.2, 58.3] | 0.00007 [0.00003, 0.00017] | - |
| region_only | 53.7% [32.3, 70.9] | 33.3% [20.8, 45.8] | 0.00002 [0.00002, 0.00004] | 0.2493 [0.1185, 0.3201] (full model better) |
| region_only_no_elevation | 52.1% [35.9, 66.5] | 33.3% [20.8, 45.8] | 0.00002 [0.00002, 0.00006] | 0.2337 [0.1339, 0.3701] (full model better) |

##### 9. Ablations on test_2018 (reporting only; nothing selected)

Each stage-1 group candidate is refitted on all development rows with the frozen hyper-parameters and its own cross-validated tree count, and evaluated at ITS OWN out-of-fold recall-first threshold; the last column is the paired FA difference to the frozen model (`drop_src`, positive = variant has more false alarms).

| variant | inputs | trees | threshold | OOF recall / FA | test recall | test FA share | FA: variant minus frozen model |
|---|---|---|---|---|---|---|---|
| full | 43 | 122 | 0.02211 | 91.8% / 21.4% | 83.8% [75.0, 91.2] | 21.6% [21.4, 21.8] | 0.0017 [0.0007, 0.0029] |
| stat_no_elevation | 41 | 106 | 0.01780 | 91.8% / 27.6% | 86.2% [78.8, 93.8] | 27.3% [27.0, 27.5] | 0.0588 [0.0572, 0.0604] |
| drop_src (frozen model) | 30 | 118 | 0.02332 | 91.8% / 20.9% | 85.0% [77.5, 92.5] | 21.4% [21.2, 21.6] | - |
| drop_wet | 37 | 129 | 0.02094 | 91.8% / 22.6% | 83.8% [75.0, 91.2] | 22.9% [22.7, 23.1] | 0.0146 [0.0135, 0.0158] |
| drop_src+integ | 35 | 175 | 0.01746 | 91.8% / 22.9% | 85.0% [76.2, 92.5] | 23.4% [23.2, 23.6] | 0.0199 [0.0189, 0.0210] |
| drop_src+corr | 34 | 147 | 0.01830 | 91.8% / 22.5% | 83.8% [75.0, 91.2] | 23.0% [22.8, 23.2] | 0.0162 [0.0151, 0.0173] |
| drop_src+integ+corr | 39 | 118 | 0.01990 | 91.8% / 22.0% | 82.5% [73.8, 91.2] | 22.4% [22.2, 22.6] | 0.0098 [0.0086, 0.0109] |


### Extreme-rain corrector

Gauge daily rain from CHIRPS-side predictors (no IMD: the IMD grid probably ingests the same gauges); LightGBM quantile regression, TEST stations only, 95% CIs over stations. Pinball loss in mm, lower is better:

| method | alpha 0.5 | alpha 0.9 | alpha 0.99 |
|---|---|---|---|
| raw CHIRPS | 4.81 [2.94, 6.55] | 4.68 [2.52, 6.63] | 4.65 [2.44, 6.61] |
| linear quantile scaling | 3.82 [2.38, 5.15]; vs raw -0.99 [-1.41, -0.57] | 3.51 [2.79, 4.22]; vs raw -1.16 [-2.47, 0.24] | 0.80 [0.73, 0.90]; vs raw -3.85 [-5.77, -1.71] |
| corrector (headline) | 3.50 [2.32, 4.66]; vs raw -1.30 [-1.94, -0.60] | 2.66 [2.01, 3.40]; vs raw -2.02 [-3.41, -0.52] | 0.65 [0.52, 0.85]; vs raw -4.00 [-5.91, -1.92] |
| corrector with IMD (leakage-risk) | 3.44 [2.58, 4.39]; vs raw -1.37 [-2.39, -0.29] | 2.92 [2.72, 3.61]; vs raw -1.75 [-3.78, 0.42] | 0.77 [0.68, 1.10]; vs raw -3.88 [-5.85, -1.75] |

Coverage of the quantiles on TEST (0.9 / 0.99): corrector 0.902 / 0.987; raw CHIRPS 0.641. Bias on the top 1% of gauge days (mm, q99): 4.8 [-14.0, 12.1] versus raw CHIRPS -66.6 [-84.1, -59.3].

Exceedance of the station 99th wet-day percentile, PR-AUC: corrector 0.071 [0.045, 0.253] versus raw CHIRPS 0.047 [0.031, 0.154] (33 TEST exceedance days).

Wayanad 2024-07-30 (IMD 179.2 mm): the CHIRPS-only corrector predicts q50 31.2, q90 71.1, q99 127.1 mm. It does **not** close the gap.


## 6. Alerts

### Same-day event detection (sample positives)

| events | detected | rate | with history | median lead (d) | lead >= 1 d | Watch+ | Warning+ | Emergency |
|---|---|---|---|---|---|---|---|---|
| 80 | 73 | 0.912 | 2 | 0.0 | 2 | 73 | 56 | 31 |

### Cost-loss

An alert is optimal when risk >= C/L, so each threshold is the cost ratio at which it is optimal. `relative expense` is expense / min(never alert, always alert); below 1 the rule beats both.

| rule | threshold | C/L | alerts / 1000 | recall | relative expense |
|---|---|---|---|---|---|
| watch threshold | 4.13e-06 | 4.13e-06 | 218.03 | 0.863 | 0.429 |
| warning threshold | 1.58e-05 | 1.58e-05 | 91.40 | 0.688 | 0.541 |
| emergency threshold | 3.70e-05 | 3.70e-05 | 35.17 | 0.388 | 0.818 |
| C/L = 1/10 | 0.100 | 0.100 | 0.00 | 0.000 | 1.000 |
| C/L = 1/50 | 0.020 | 0.020 | 0.00 | 0.000 | 1.000 |
| C/L = 1/200 | 0.005 | 0.005 | 4.39e-03 | 0.000 | 1.003 |


**What this implies.** The event base rate is 0.000006 per cell-day, so calibrated risks are tiny (the largest risk in the test_2018 universe is 0.01). Alerting is cost-justified when risk >= C/L, so the Watch, Warning and Emergency thresholds are optimal only if acting costs at most 4.13e-06, 1.58e-05 and 3.70e-05 of the loss it avoids (relative expense 0.43, 0.54, 0.82; below 1 beats both never and always alerting). At C/L = 1/10, 1/50 and 1/200 the cost-optimal rule is effectively never to alert on these data (0.000, 0.000, 0.004 alerts per 1000 cell-days, recall 0, relative expense about 1): almost no cell-day reaches a risk that high, so at those ratios this model supports no alert at all. The alert levels are defensible only where acting is very cheap relative to the loss avoided.

### Blind escalations (universe)

| cell-days | blind-rule applies | level actually raised | cells raised | raised near an event | events covered |
|---|---|---|---|---|---|
| 200000 | 4997 | 1300 | 1069 | 0 | 0 |

Positives whose level was raised by the blind rule: 0.

the sample files hold the event day only, so lead time is 0 by construction; the universe rows are random cell-days (not consecutive), so flapping and area per day do not apply

### Flapping

| level used | cell-days | level changes | per 1000 | flaps | per 1000 |
|---|---|---|---|---|---|
| with hysteresis | 188278 | 29748 | 158.00 | 2390 | 12.69 |
| without hysteresis (raw level) | 188278 | 47613 | 252.89 | 4363 | 23.17 |


## 7. Case studies

Wayanad (Mundakkai / Chooralmala) 2024-07-25 to 08-02, cell nearest the landslide point; mm per IMD day. No NASA landslide label exists for this event, so this is a qualitative replay, never trained or tuned on.

| day | IMD | CHIRPS aligned | CHIRPS UTC | ERA5 UTC | ERA5 IMD day | corrector q90 | nearest gauge |
|---|---|---|---|---|---|---|---|
| 2024-07-25 | 25.6 | 31.2 | 44.1 | 38.4 | 25.2 | 35.9 | 39.1 |
| 2024-07-26 | 53.3 | 38.6 | 0.0 | 23.4 | 33.8 | 42.4 | 23.1 |
| 2024-07-27 | 37.8 | 12.4 | 99.4 | 2.4 | 21.3 | 27.0 | 30.0 |
| 2024-07-28 | 5.0 | 87.0 | 0.0 | 11.2 | 2.5 | 65.4 | 6.1 |
| 2024-07-29 | 6.6 | 6.2 | 49.7 | 56.9 | 12.8 | 23.7 | 33.0 |
| 2024-07-30 | 179.2 | 43.5 | 0.0 | 53.3 | 66.9 | 63.8 | 154.9 |
| 2024-07-31 | 16.7 | 6.2 | 49.7 | 26.4 | 42.5 | 19.4 | 36.1 |
| 2024-08-01 | 31.6 | 43.5 | 0.0 | 26.3 | 25.0 | 46.1 | 38.1 |
| 2024-08-02 | 42.5 | 0.0 | 0.0 | 13.2 | 28.0 | 19.4 | 34.0 |

Kerala 2018 points (the three wettest positive cells of 15-16 August), ERA5 on the event day, UTC day versus exact IMD day (mm):

| point | event day | UTC day | IMD day exact | D5 approx. |
|---|---|---|---|---|
| kerala_cell_19965138 | 2018-08-16 | 67.4 | 134.2 | 131.2 |
| kerala_cell_20065137 | 2018-08-16 | 102.6 | 200.3 | 193.5 |
| kerala_cell_20065129 | 2018-08-16 | 61.0 | 131.4 | 129.0 |

Case replays with the alert engine (from the alerts report):

### Kerala 2018 (2018-08-01 .. 2018-08-20, 8048 cells)

#### Event detection with lead time

| events | detected | rate | with history | median lead (d) | lead >= 1 d | Watch+ | Warning+ | Emergency |
|---|---|---|---|---|---|---|---|---|
| 23 | 23 | 1.000 | 23 | 7.0 | 23 | 23 | 20 | 14 |

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
| 20385120 | 2018-08-09 | yes | 7 | 8 |
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

#### Alerted area per day

| days | cells/day | Watch+ share mean | Watch+ share max | Warning+ share mean | Watch+ km2 mean | Watch+ km2 max | peak day |
|---|---|---|---|---|---|---|---|
| 20 | 8048 | 0.4531 | 0.6667 | 0.2009 | 108790 | 159327 | 2018-08-17 |

#### Flapping

| level used | cell-days | level changes | per 1000 | flaps | per 1000 |
|---|---|---|---|---|---|
| with hysteresis | 160960 | 19602 | 121.78 | 1659 | 10.31 |
| without hysteresis (raw level) | 160960 | 29921 | 185.89 | 3568 | 22.17 |

#### Blind escalations

| cell-days | blind-rule applies | level actually raised | cells raised | raised near an event | events covered |
|---|---|---|---|---|---|
| 160960 | 18705 | 6485 | 1183 | 0 | 0 |

#### Level and confidence mix

| Normal | Watch | Warning | Emergency | High conf. | Degraded | Insufficient |
|---|---|---|---|---|---|---|
| 0.5469 | 0.2522 | 0.0982 | 0.1027 | 0.7404 | 0.2595 | 0.0002 |

Confidence limited by (cell-days): sources_disagree 32087, station_out_of_distribution 26553, stations_flagged_nearby 9721, all_nearby_stations_untrusted 89.

#### Share of cell-days at each level after each layer

| level | point_risk | plus_uncertain_high | plus_blind_rule | after_hysteresis |
|---|---|---|---|---|
| Watch | 0.3186 | 0.3686 | 0.4089 | 0.4531 |
| Warning | 0.1570 | 0.1570 | 0.1570 | 0.2009 |
| Emergency | 0.0698 | 0.0698 | 0.0698 | 0.1027 |

### Wayanad 2024 (2024-07-15 .. 2024-08-05, 140 cells)

#### Alerted area per day

| days | cells/day | Watch+ share mean | Watch+ share max | Warning+ share mean | Watch+ km2 mean | Watch+ km2 max | peak day |
|---|---|---|---|---|---|---|---|
| 22 | 140 | 0.7461 | 0.9714 | 0.4795 | 3163 | 4117 | 2024-07-31 |

#### Flapping

| level used | cell-days | level changes | per 1000 | flaps | per 1000 |
|---|---|---|---|---|---|
| with hysteresis | 3080 | 554 | 179.87 | 44 | 14.29 |
| without hysteresis (raw level) | 3080 | 797 | 258.77 | 68 | 22.08 |

#### Blind escalations

| cell-days | blind-rule applies | level actually raised | cells raised | raised near an event | events covered |
|---|---|---|---|---|---|
| 3080 | 83 | 60 | 40 | n/a | n/a |

#### Level and confidence mix

| Normal | Watch | Warning | Emergency | High conf. | Degraded | Insufficient |
|---|---|---|---|---|---|---|
| 0.2539 | 0.2666 | 0.1331 | 0.3464 | 0.9669 | 0.0331 | 0.0000 |

Confidence limited by (cell-days): sources_disagree 179.

#### Share of cell-days at each level after each layer

| level | point_risk | plus_uncertain_high | plus_blind_rule | after_hysteresis |
|---|---|---|---|---|
| Watch | 0.6058 | 0.6675 | 0.6870 | 0.7461 |
| Warning | 0.3987 | 0.3987 | 0.3987 | 0.4795 |
| Emergency | 0.2510 | 0.2510 | 0.2510 | 0.3464 |

#### Limitation: the alert levels saturate

Focus cell 20295122 (nearest the Mundakkai point, 0.8 km away) is at Emergency on every one of the 22 days. Over all cells the share at Emergency per day averages 0.346 (range 0.164 to 0.500). The calibrated risk takes 10 distinct values over the 22 days and its maximum (4.52e-04) is reached on 2024-07-17, 2024-07-30 (tied). The landslide struck on 2024-07-30: that day shares the maximum with 2024-07-17 (rank 1).

So the level cannot rank the days of this event, and the risk ordering gives no unique top day. This is a reported limitation of the model and the alert levels, not something tuned away: Wayanad is a never-tuned case study with no label, and no threshold or rule was changed after seeing it.

| date | level | risk | risk rank (1 = highest) |
|---|---|---|---|
| 2024-07-15 | Emergency | 2.27e-04 | 3 |
| 2024-07-16 | Emergency | 2.27e-04 | 3 |
| 2024-07-17 | Emergency | 4.52e-04 | 1 |
| 2024-07-18 | Emergency | 2.27e-04 | 3 |
| 2024-07-19 | Emergency | 2.27e-04 | 3 |
| 2024-07-20 | Emergency | 2.27e-04 | 3 |
| 2024-07-21 | Emergency | 8.14e-05 | 16 |
| 2024-07-22 | Emergency | 1.06e-04 | 15 |
| 2024-07-23 | Emergency | 1.23e-04 | 12 |
| 2024-07-24 | Emergency | 8.14e-05 | 16 |
| 2024-07-25 | Emergency | 1.23e-04 | 12 |
| 2024-07-26 | Emergency | 2.27e-04 | 3 |
| 2024-07-27 | Emergency | 2.27e-04 | 3 |
| 2024-07-28 | Emergency | 7.47e-05 | 18 |
| 2024-07-29 | Emergency | 4.26e-05 | 21 |
| 2024-07-30 | Emergency | 4.52e-04 | 1 |
| 2024-07-31 | Emergency | 1.83e-04 | 11 |
| 2024-08-01 | Emergency | 2.27e-04 | 3 |
| 2024-08-02 | Emergency | 1.23e-04 | 12 |
| 2024-08-03 | Emergency | 7.47e-05 | 18 |
| 2024-08-04 | Emergency | 6.43e-05 | 20 |
| 2024-08-05 | Emergency | 3.74e-05 | 22 |

no landslide label exists for this case (no NASA record), so no detection statistics


## 8. Limitations and honest shortfalls

Stated by the reports themselves; nothing here has been softened.

#### Gate outcome and controller rulings (2026-10-02) (phase2-design.md)

Full numbers: `reports/phase2_integrity_report.md`.
- Combined engine (L1 or model, after arbiter) at the VAL-chosen 1% threshold: TEST macro recall 0.70 vs best baseline 0.30 (L1), but realised TEST false-flag rate 4.9%, not 1%. Cause: 91% of TEST false flags come from the two Nepal stations, both of which fell in TEST (none in TRAIN/VAL), i.e. out-of-distribution stations. The other 24 TEST stations realise 0.9%. At a matched 1.3% rate (oracle, not deployable) the engine still beats every baseline on zero_fault and offset_noise, ties on spike/duplicate/drift, loses to L1 on stuck.
- RULING: Phase 2 is accepted with this shortfall reported; no retraining after seeing TEST (that would tune on TEST). Remedy goes into Phase 4: an out-of-distribution guard per station (trailing flag rate far above target -> station trust state `uncertain`, data-confidence `Degraded`, never silently `faulty`).
- RULING (hazard safety): repair under-estimates heavy rain (42.5% of repaired values on >= 50 mm days reach half the truth). Downstream, a flagged station reading is never used to LOWER rain below the gridded references; repaired values only feed the integrity summary, not the rain features.
- scale_drift is essentially undetected on TEST by every method (14 episodes, shortfall noted); duplicate_block and stuck rely on L1.
- Genuine-extreme retention (TEST): design-strict 3/3, wide 9/9, wide_1neighbour 17/18, uncorroborated proxy 24/26; arbiter costs no injected-spike recall.
- Downstream the hazard model uses only the out-of-fold engine outputs on the real series (`engine_outputs_2007_oof.parquet`).

#### Protocol v2 (controller ruling, 2026-10-02, after the v1 run) (phase3-design.md)

v1 (`reports/phase3_hazard_report_v1.md`) used the 2016-17 validation split for hyper-parameter selection (48 candidates), early stopping on a noisy false-alarm metric, isotonic calibration AND the 90%-recall threshold. That re-use made the threshold optimistic: test_2018 recall at the validation threshold was 78.8% (target 90%), calibration over-predicted by 36%, and the model tied all baselines on test. `stat_elev_mean` was the top feature (17% gain), a probable location/inventory-bias proxy.
v2, decided before any further look at test_2018:
- Development period 2007-2017 (train + validation splits pooled as rows, never test_2018). Year-blocked cross-validation (folds = contiguous year blocks, e.g. 2007-08, 2009-10, 2011-12, 2013-14, 2015, 2016, 2017) for ALL choices: hyper-parameters (small, regularised grid), number of trees (median of fold-optimal counts), feature groups (incl. dropping elevation-like static columns, adding `integ_` and `corr_` when available).
- Calibration and thresholds from the pooled out-of-fold scores (universe weights per year), recall-first margin: the operating threshold is the highest one whose bootstrap 5th-percentile out-of-fold recall is >= 90%.
- Final model refit on all development rows with the chosen settings; baselines get the identical treatment (thresholds from their own out-of-fold scores over 2007-2017).
- test_2018 is evaluated exactly once with everything frozen; v1 numbers stay in the report as disclosed history (the protocol change was partly prompted by the v1 test result — stated plainly).

#### Finding: CHIRPS daily artifact at Wayanad (controller check, 2026-10-03) (phase3-design.md)

Raw CHIRPS v2.0 p05 files (not our store) for the Wayanad 3x3 pixel block read exactly 0.0 on 2024-07-26, 07-28, 07-30 and repeat identical non-zero values on alternate days (e.g. centre pixel 49.7 mm on 07-29 and 07-31; neighbours 61.6/45.4/47.5 repeated). Our cropped store reproduces the source faithfully. Interpretation: an artifact of CHIRPS's daily disaggregation of pentadal totals, not a processing bug. Consequence: on the Wayanad event day CHIRPS-UTC = 0 mm while IMD = 179 mm, the nearest trusted gauge (45 km) = 154.9 mm and ERA5 (IMD-day exact) = 66.9 mm. Reported as a limitation of CHIRPS as a daily trigger source; it is the motivating case for the IMD-vs-CHIRPS disagreement features and the alert engine's max-of-sources escalation rule.

#### Finding: post-evaluation bug fix and disclosed rerun (2026-10-03) (phase3-design.md)

After the single frozen test_2018 evaluation, controller review found a sign bug in the POINT value of the paired recall difference at fixed thresholds (`recall_model_minus_baseline`, `hazard/evaluate.py::_paired_fixed`): the bootstrap interval was model minus baseline but the point value was baseline minus model (e.g. reported +0.025 vs intensity-duration while model recall 0.850 < baseline 0.875). Fixed, with a regression test whose two scorers have different recalls (the old test had equal recalls, so it could not catch it). The evaluation was re-run once with `--rerun` (logged in `data/processed/hazard/model/TEST_EVALUATION.json`, runs at 11:54Z and 16:23Z); the model freeze verified before and after; nothing else changed: recall at Watch 0.850 [0.775, 0.925], FA share 0.214, FA differences and all verdicts identical. Corrected recall differences at the frozen Watch thresholds: model minus intensity-duration -0.025 [-0.088, 0.038], minus LHASA-style -0.038 [-0.125, 0.038], minus logistic -0.013 [-0.063, 0.038] — all within noise.


### From the reports

- Hazard v1, test_2018: only 80 positive cell-days (< 100): intervals are wide and unstable
- scale_drift has 14 TEST episodes (below the planned minimum): its recall rests on very few episodes.
- Stage 1: only 11 TEST stations (and 11 VAL) carry injected episodes and scale_drift has the fewest; the CHIRPS-aligned reference correlates only about 0.38 with the stations; IMD is not independent of the gauges (arbiter variants with and without IMD are both reported); every fault is injected into real series, so recall measures detection of synthetic faults, not of the faults real gauges produce (the 10 real flags are too few to say); references exist only from 2007, so none of the 1990-2004 clean data is used.
- Corrector: Headline predictors exclude IMD; `corrector_with_imd` is a leakage-risk variant, not for use.
- Corrector: The exceedance threshold is the station's own 99th wet-day percentile in 2007-2015; on cells the classifier is applied with the same absolute predictors, so corr_p_exceed99 means 'exceeds a typical station p99', not a per-cell percentile.
- Corrector: elev_point is the station elevation for stations and the cell's mean elevation for cells.
- Corrector: Terrain is missing for stations whose cell is not in the terrain store (NaN, handled natively by LightGBM).
- Corrector: Few usable stations: TEST has very few stations with clean, unflagged, CHIRPS-covered days, so every CI is wide.
- Corrector: Gauge rain is the target; the corrector can only learn the gauge-vs-satellite relation at the 36 station sites, mostly lowland: it cannot be assumed to transfer to windward slopes.
- Case inputs: Open-Meteo hourly precipitation is stamped by the PRECEDING hour; UTC day D = stamps 01:00 D..00:00 D+1, IMD day D = stamps 04:00 D-1..03:00 D (exact), D5 = 0.875 UTC(D-1) + 0.125 UTC(D).
- Case inputs: ERA5 / ERA5-Land are reanalysis point values (about 0.25 / 0.1 degree cells), not gauge data.
- Case inputs: Licence: Open-Meteo CC BY 4.0; ERA5 / ERA5-Land Copernicus (CC BY 4.0).
- Hazard v1:
  - Statistical power is low: test_2018 has 80 in-domain positive cell-days (48 Himalaya, 32 Ghats); every interval is a bootstrap over events and universe rows and is wide.
  - The landslide inventory is partial (NASA catalogs, rain-triggered, accuracy <= 5 km); unlabeled landslides sit among the negatives, so false-alarm shares are upper bounds.
  - Rain comes from the 0.25 degree IMD gauge grid (CHIRPS 0.05 degree elsewhere) at daily resolution: no hourly intensity, so short intense bursts are not resolved.
  - Labels are rain-triggered cell-days only; earthquake, construction and unknown triggers are excluded from positives and kept as buffer.
  - Positives below the slope floor (outside the model domain) are excluded from training and the primary metrics and counted as misses in the overall recall.
  - Calibrated probabilities refer to the all-year operating base rate of the evaluation split (of order 1e-6 per cell-day); isotonic calibration is fitted on validation, so validation ECE is in-sample.
  Note: validation figures favour the hazard model by construction (hyper-parameters, early stopping and the calibrator were chosen on validation; the baselines have no tuned parameters). test_2018 is the out-of-sample comparison.
- Open-Meteo series unavailable (wayanad_mundakkai|era5_land): every hourly precipitation value is null for era5_land (variable not provided by the model)
- Open-Meteo series unavailable (kerala_cell_19965138|era5_land): every hourly precipitation value is null for era5_land (variable not provided by the model)
- Open-Meteo series unavailable (kerala_cell_20065137|era5_land): every hourly precipitation value is null for era5_land (variable not provided by the model)
- Open-Meteo series unavailable (kerala_cell_20065129|era5_land): every hourly precipitation value is null for era5_land (variable not provided by the model)


## 9. How to run

Setup, licences and the layout are in `README.md`. The whole pipeline runs stage by stage from `configs/pipeline.yaml`; stages whose outputs are frozen and verify intact are reused.

```
python -m aetherguard.pipeline status
python -m aetherguard.pipeline run --dry-run
python -m aetherguard.pipeline run [--from STAGE] [--to STAGE] [--only STAGE] [--offline] [--force]
python -m aetherguard.finalreport
```

| stage | module | network | runs by default |
|---|---|---|---|
| audit | `aetherguard.audit.run` | yes | no (use --include) |
| labels | `aetherguard.events.build` | no | yes |
| splits | `aetherguard.splits.build` | no | yes |
| imd | `aetherguard.ingest.imd_build` | yes | yes |
| chirps | `aetherguard.ingest.chirps_build` | yes | yes |
| power | `aetherguard.ingest.power_build` | yes | yes |
| terrain | `aetherguard.ingest.terrain_build` | yes | yes |
| regions | `aetherguard.features.regions_build` | yes | yes |
| samples | `aetherguard.features.samples_build` | no | yes |
| features | `aetherguard.features.features_build` | no | yes |
| integrity_2a | `aetherguard.integrity.baseline_report` | no | yes |
| engine_data | `aetherguard.integrity.engine_data` | no | yes |
| day_basis | `aetherguard.integrity.day_basis` | no | yes |
| integrity_engine | `aetherguard.integrity.engine_report` | no | yes |
| integ_features | `aetherguard.integrity.hazard_features` | no | yes |
| corrector | `aetherguard.corrector.report` | no | yes |
| hazard_train | `aetherguard.hazard.train` | no | yes |
| hazard_freeze | `aetherguard.hazard.freeze` | no | yes |
| hazard_report | `aetherguard.hazard.evaluate_report` | no | yes |
| cases | `aetherguard.cases.series` | yes | yes |
| alerts_derive | `aetherguard.alerts.derive` | no | yes |
| alerts_replay | `aetherguard.alerts.replay` | no | yes |
| alerts_report | `aetherguard.alerts.report` | no | yes |
| final_report | `aetherguard.finalreport` | no | yes |
