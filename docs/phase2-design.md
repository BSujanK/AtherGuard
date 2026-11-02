# Phase 2 design addendum — sensor integrity engine (stage 1)

Parent: `docs/superpowers/specs/2026-09-30-aetherguard-design.md` section 6, and `docs/phase1-design.md`. No git. Workflow per task: builder (Sonnet) test-first -> independent reviewer (Sonnet) -> controller adjudicates.

## What the real data allows (measured in Phase 0)
- Real sensors: 140 GHCN-Daily rain-gauge series (`data/raw/ghcnd/dly/*.dly`, 138 India + 2 Nepal; metadata in `data/raw/ghcnd/ghcnd-stations.txt`, selection logic `aetherguard.audit.ghcnd.select_stations`). 3,099,630 valid values, only **391 real NOAA-flagged** values, 245 of them at four stations in 1930-1966 (duplicate months), and only **10 flagged values in 2007-2024**. Real supervised fault labels are therefore too few to train or score the engine on their own.
- Consequence (spec 4.4/14): train and score on **faults injected into REAL clean series**, with magnitudes calibrated to real faults, and report injected-fault results separately from the real-flag results. The 391 real flags are a sanity check, not the headline.
- No open labelled landslide-site sensor dataset exists in South Asia. The Gaolan dataset (China) is optional physics material (Phase 2c stretch).
- Day basis: GHCN-D India gauges report 24-hour totals at 08:30 IST, the same convention as the IMD grid; this is an assumption to be TESTED (lag correlation against IMD and CHIRPS once those stores exist) — never assumed silently.

## Sensor model and faults
- A sensor is one station's daily rain series (mm, NaN = missing) with latitude, longitude, elevation and the real NOAA QC flag per day.
- Fault types (daily resolution), each injected as episodes into clean real series, with per-day labels: `stuck_value` (a constant positive value repeats), `zero_fault` (gauge reads 0 while it is raining around: blocked gauge or dropout-to-zero), `spike` (implausibly large single-day values), `scale_drift` (multiplicative bias drifting over weeks), `offset_noise` (small positive readings on dry days), `duplicate_block` (a block of days is a copy of an earlier block, like NOAA flag D). Missing values (NaN) are handled as `gap`, not as a class to learn.
- Injection parameters (durations, magnitudes) are drawn from ranges documented in code and calibrated against the real flagged faults (duplicate block lengths, streak lengths); all draws are seeded.
- Stations are split by station id (fixed seed) into train / validation / test for the integrity engine (leave-station-out); the split list is written to `data/processed/integrity/station_splits.json` and never changed.
- A day is "clean real" if it has a value, no NOAA flag, and the station-year has at least 200 valid days (`MIN_VALID_DAYS_PER_YEAR`; ruling after measurement: 300 leaves 59 stations / 124k clean days, 200 gives 73 stations with >= 365 clean days / 231k, see `reports/phase2a_baselines.md`); only clean stretches receive injected faults.

## Engine layers (spec 6.2), concretely
1. L1 deterministic checks: physical bounds, flat-line/stuck detection, duplicate-block detection, gaps, non-finite values. Transparent rules, each returns a reason code.
2. L2 + L3 learned model (one LightGBM multiclass model with calibrated probabilities): own-series features (rolling 7/14/30-day mean, std, zero fraction, max, number of distinct values, longest identical run, run-length encodings, climatology anomaly) plus cross-source features: residual against the k nearest stations within 150 km (inverse-distance weighted), residual against the gridded products at the station location (IMD where covered, CHIRPS), neighbour agreement count. The "physical coupling" idea (rain -> soil wetness) is represented by the POWER soil-wetness change where available.
3. L4 arbiter and repair: a reading that looks anomalous but is corroborated (at least two independent references at or above 30% of the value, or the value is within the reference ensemble's upper range) is retained as a genuine extreme; uncorroborated suspicious readings stay in the data marked low-trust (never deleted); repair = reference-ensemble estimate with an uncertainty band (empirical residual quantiles), never lowering a hazard estimate below what independent sources imply.
4. Output per sensor-day: `trust` (probability the reading is sound), `fault_type`, `repaired`, `repaired_lo`, `repaired_hi`, `genuine_extreme`, `reasons`.

## Evaluation (Phase 2 gate)
- Per fault type on the TEST stations: recall at a fixed false-flag rate of 1% on clean days, time-to-detect within an episode, PR-AUC; overall macro recall; bootstrap confidence intervals over stations.
- Safety metric: genuine-extreme retention = share of real, corroborated extreme readings (clean, unflagged, at or above the station's 99.5th wet-day percentile and corroborated by neighbours or grids) that the engine does NOT mark as faulty. Target: as close to 100% as the data allow; always reported with its denominator.
- Baselines to beat: range check only; NOAA-style QA re-implementation (streak, duplicate, climatological outlier, spatial check); robust rolling z-score on the own series; IsolationForest on the same rolling features.
- Ablations: no cross-source features; no arbiter.
- Real-flag sanity: how many of the 391 real NOAA flags (especially the 10 in 2007-2024) the engine and the baselines flag, reported separately.
- Day-basis experiment: lag correlation of station series against IMD and CHIRPS at lags -2..+2 days over India stations (validates the D5 alignment and the same-convention assumption).

## Tasks
2a. Station dataset + calibrated fault injection + station splits + neighbour references + L1 checks + baselines + evaluation harness (no gridded products needed).
2b. Gridded references (IMD/CHIRPS/POWER), learned model, arbiter, repair, full evaluation, day-basis experiment (needs the Phase 1 rain stores).
2c (optional stretch, time-boxed): real physics check on Gaolan (download one monthly archive, inspect format) for rain -> pore-pressure consistency.

## Gate outcome and controller rulings (2026-10-02)
Full numbers: `reports/phase2_integrity_report.md`.
- Combined engine (L1 or model, after arbiter) at the VAL-chosen 1% threshold: TEST macro recall 0.70 vs best baseline 0.30 (L1), but realised TEST false-flag rate 4.9%, not 1%. Cause: 91% of TEST false flags come from the two Nepal stations, both of which fell in TEST (none in TRAIN/VAL), i.e. out-of-distribution stations. The other 24 TEST stations realise 0.9%. At a matched 1.3% rate (oracle, not deployable) the engine still beats every baseline on zero_fault and offset_noise, ties on spike/duplicate/drift, loses to L1 on stuck.
- RULING: Phase 2 is accepted with this shortfall reported; no retraining after seeing TEST (that would tune on TEST). Remedy goes into Phase 4: an out-of-distribution guard per station (trailing flag rate far above target -> station trust state `uncertain`, data-confidence `Degraded`, never silently `faulty`).
- RULING (hazard safety): repair under-estimates heavy rain (42.5% of repaired values on >= 50 mm days reach half the truth). Downstream, a flagged station reading is never used to LOWER rain below the gridded references; repaired values only feed the integrity summary, not the rain features.
- scale_drift is essentially undetected on TEST by every method (14 episodes, shortfall noted); duplicate_block and stuck rely on L1.
- Genuine-extreme retention (TEST): design-strict 3/3, wide 9/9, wide_1neighbour 17/18, uncorroborated proxy 24/26; arbiter costs no injected-spike recall.
- Downstream the hazard model uses only the out-of-fold engine outputs on the real series (`engine_outputs_2007_oof.parquet`).
