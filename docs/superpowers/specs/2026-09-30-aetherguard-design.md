# AetherGuard — Design Spec

AI-powered sensor-integrity and landslide / extreme-weather early-warning prototype for vulnerable mountain regions.

- **Date:** 2026-09-30
- **Status:** Draft for review (design sections 1–4 approved in conversation)
- **Project root:** the project root (everything lives here)
- **Classification:** Architectural (new project, no existing flow)

---

## 1. Purpose and success criteria

Build an end-to-end, locally runnable pipeline that (a) decides how far each incoming sensor reading can be trusted, and (b) uses trusted inputs to estimate landslide and extreme-rain risk, using **only real-world data**. The work starts from an analysis of where existing systems fail and designs each stage to fix a specific failure.

**This is a research prototype. It must not be used to issue real public warnings.**

### What "highest accuracy" means here
Landslide labels are sparse and biased, so a single accuracy number would be misleading. Success is defined by rigorous held-out results, not a promised figure:

| Criterion | Definition |
|---|---|
| Recall-first detection | Detect **≥ 90 %** of held-out landslide events at the chosen operating point (a target, reported with bootstrap confidence intervals; the false-alarm cost at that point is always reported alongside) |
| Beats baselines | Higher PR-AUC and higher detection rate at a fixed false-alarm rate than each baseline (§6.4, §7.3), with per-event bootstrap CIs |
| Calibration | Reported calibration error and reliability curves for every probability output |
| Genuine-extreme retention | Share of real, corroborated extreme sensor readings wrongly rejected by the integrity engine — reported, driven as close to zero as the data allows |
| Integrity value | Downstream hazard-model improvement with vs without the integrity engine, and vs a simple range check |
| Honesty | Every result labelled by data kind (real flags / real physics / injected faults); limitations section in the final report |

**Definition of a detected event (fixed in `configs\` before any modelling, then frozen):** a held-out landslide event counts as *detected* if an alert of level **Watch or higher** is issued for the event's cell **or any of its 8 neighbouring cells** on the event date **or the day before**. The neighbour and one-day tolerance reflect the ~5 km location accuracy and day-level timing of the catalogs. The ≥ 90 % target applies at the Watch threshold; Warning and Emergency thresholds are set at higher-precision points and reported separately. The false-alarm cost is reported as alerted cell-days per detected event, as an upper bound (§4.2).

Nothing in this table is a guarantee. If a phase misses its target, the outcome is reported as-is (§11).

---

## 2. Scope

### In scope (v1)
- Domain: **Himalaya** (Uttarakhand, Himachal Pradesh, Sikkim, north-east India, Nepal) and **Western Ghats** (Kerala, Karnataka, Goa, Maharashtra Ghats).
- Period: 2007–2024 where data allow.
- Resolution: daily, 0.05° cells (~5 km), matching CHIRPS.
- Outputs: (1) landslide probability per cell-day (same-day nowcast); (2) extreme-rain flag (corrected probability of exceeding the local 99th percentile); (3) per-sensor trust scores, fault types and repaired estimates; (4) alert level + data-confidence flag with reasons.
- Replay mode (historical evaluation, case studies) and a live demo mode.
- FastAPI service and Streamlit dashboard.

### Out of scope (v1)
- Hourly or multi-day-ahead forecasting (v2).
- Deep neural networks / GPU training (no GPU on this machine; insufficient labelled data).
- Any claim of operational readiness or guaranteed accuracy.
- Field hardware or new sensor deployment.

### Constraints
- Windows 11, 16 GB RAM, no dedicated GPU detected, ~218 GB free disk. Raw data capped at ~60 GB. Year-by-year processing into Parquet; LightGBM / scikit-learn.
- Python 3.13; project-local `.venv` (global Python untouched).

---

## 3. Where existing systems fail (evidence) → what AetherGuard does

### 3.1 Evidence
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

### 3.2 Failure → design response

| # | Failure | AetherGuard response |
|---|---|---|
| F1 | Global rain products badly under-measure extreme orographic rain | Multi-source rain fusion; source *disagreement* used as a risk feature; upper-quantile rain corrector; honest uncertainty widening (§7) |
| F2 | Sensor faults undetected or indistinguishable from real extremes (a blocked gauge reads "no rain" in a storm) | Stage-1 integrity engine with cross-source and physical-coupling checks (§6) |
| F3 | Low detection / many false alarms from static thresholds | Stage-2 model on rain history, soil wetness, terrain; calibrated probabilities; recall-first operating point (§7) |
| F4 | Inflated accuracy from random splits and biased labels | Time- and region-blocked frozen test set; per-event evaluation; false alarms reported as upper bounds (§4.3, §10) |
| F5 | No uncertainty, no degraded mode, silent failure | Data-confidence flag; escalate (never silent "Normal") when blind and independent sources show heavy rain (§8) |

---

## 4. Data foundation

### 4.1 Landslide ground truth
- NASA Global Landslide Catalog / COOLR (manual one-time export from the Landslide Viewer).
- NSIDC High Mountain Asia Landslide Catalog v2 (~2,800 events, 2007–2018; Earthdata login).
- Kerala 2018 inventories (NRSC / KSDMA-derived).
- Nepal landslide inventory collection (Zenodo record holds the database of inventories; the individual inventories are separate downloads).
- Events kept only if located to within ~5 km (cell size).

### 4.2 Label bias handling
A cell-day with no report may simply be unreported (remote areas). Therefore: negatives are sampled from buffered cell-days away from any event, in the same region and season; evaluation is per event; false-alarm rates are reported as **upper bounds**, not exact rates.

### 4.3 Inputs
| Group | Sources |
|---|---|
| Rain | CHIRPS (0.05°), ERA5, ECMWF IFS (Open-Meteo), MERRA-2 (NASA POWER); IMERG optional (Earthdata login). Gauge references: NOAA GHCN-Daily / ISD; IMD gauge-based gridded rainfall (candidate — access to be verified) |
| Antecedent wetness | ERA5 soil moisture via Open-Meteo (one ERA5-Land call returned empty during design — verify in Phase 0) |
| Terrain / static | Copernicus DEM 30 m (slope, curvature, relief, aspect, topographic wetness), ESA WorldCover, SoilGrids (file host), OpenStreetMap roads, lithology (candidate open source, e.g. GLiM — availability to be verified in Phase 0) |

### 4.4 Sensor data for the integrity engine (three kinds, always reported separately)
1. **Real faults:** NOAA station records; NOAA's own quality flags (streaks, duplicates, spatial inconsistency, etc.) act as real fault labels. Coverage limited to faults NOAA checks (daily data).
2. **Real physics:** Gaolan Mountain loess-slope monitoring dataset (Zenodo, CC-BY-4.0, ~48.7 GB, Aug 2019–Mar 2020: rainfall, pore pressure, displacement, seismic). No fault labels documented; used to test cross-sensor coupling only.
3. **Injected faults:** stuck, drift, spike, dropout, clogged-gauge, scale/offset errors, with magnitudes calibrated from the real flagged faults. Never mixed into real-flag headline results.

### 4.5 Data hygiene
Timestamps normalised to UTC; units and ranges validated on ingest; missing data explicit (never silently filled); a manifest records every downloaded file with source URL, date, size, licence and checksum.

---

## 5. Architecture (two-stage gated pipeline)

```
raw sources ─► ingest/QA ─► feature store (Parquet)
                               │
   sensor streams ─► [Stage 1: Integrity engine] ─► trust score, fault type,
                               │                    repaired value ± uncertainty
                               ▼
              [Stage 2: Hazard + extreme-rain models] ─► calibrated probabilities ± interval
                               ▼
                    [Alert engine] ─► level + data-confidence + reasons
                               ▼
                 FastAPI service · Streamlit dashboard · evaluation reports
```

Chosen over (a) a single joint model (needs far more labelled fault+landslide data than exists; not auditable stage by stage) and (b) rules/physics only (the approach that failed at Wayanad; retained as a baseline). Each stage has one purpose, a defined interface, and is testable alone.

---

## 6. Stage 1 — Sensor integrity engine

### 6.1 Outputs (per sensor, per timestamp)
- **Trust score** in [0, 1], calibrated as the probability the reading is faulty.
- **Fault type:** stuck, drift, spike, dropout, clogged gauge, scale/offset error, or none.
- **Repaired estimate** with an uncertainty band, derived from independent sources.
- **Genuine-extreme decision:** keep a real sudden signal; do not mistake it for a fault.

### 6.2 Layers (cheapest first)
1. **Deterministic checks:** physical limits, maximum rate of change, flat-line run length (with legitimate-constant exemptions), gaps, duplicates, timestamp monotonicity.
2. **Per-sensor learned model:** gradient-boosted classifier on rolling statistics, trained on real NOAA-flagged plus injected faults; change-point detection for slow drift.
3. **Cross-source consistency (main differentiator):**
   - *Spatial:* residual z-scores versus nearest stations and gridded rain, robust and terrain-zone-scaled.
   - *Physical coupling:* rain → soil wetness → pore pressure → displacement, with realistic lags. Example: neighbours raining + soil wetness rising + this gauge reads zero ⇒ strong clog evidence.
4. **Fusion + arbiter:** calibrated trust score; asymmetric rule — a reading that looks anomalous but is confirmed by an independent source or physical response is retained as a genuine extreme and never deleted.

### 6.3 Safety defaults
- A suspicious reading that nothing can confirm or refute is **kept and marked low-trust**, not removed (accepting slightly more false alarms to avoid hiding real events).
- Repair can **never lower** the hazard estimate below what independent sources imply.
- Raw streams are always preserved alongside repaired values.

### 6.4 Evaluation
Per fault type: detection rate at a fixed false-flag rate, time-to-detect. Safety metric: genuine-extreme retention. Downstream: hazard-model performance with vs without the engine. Baselines: range checks only, NOAA-style QA flags, a standard outlier detector (e.g. isolation forest / robust z-score).

### 6.5 Runtime
Streaming design: fixed window per sensor, O(window) per update, CPU only.

---

## 7. Stage 2 — Hazard and extreme-rain models

### 7.1 Landslide model
LightGBM, one row per cell per day.
- **Rain features:** accumulations over 1, 3, 5, 7, 14, 30 days; peak hourly intensity (from hourly reanalysis/forecast products); rain relative to local climatology; **inter-source disagreement**.
- **Wetness:** antecedent soil moisture.
- **Static:** slope, curvature, relief, aspect, topographic wetness, land cover, soil, roads, lithology (if an open source is verified).
- **Integrity features:** trust-weighted nearby station rain, fraction of trusted sensors, station-vs-grid discrepancy.
- **Monotonic constraints:** more rain and steeper slope never lower risk.
- **Calibration:** isotonic calibration on validation data; uncertainty interval on every probability.
- **Explanations:** per-alert contributions from LightGBM's built-in SHAP values (no extra dependency).

### 7.2 Extreme-rain corrector and flag
A model predicting gauge-observed rain from gridded products plus terrain and monsoon-wind exposure, using an **upper-quantile loss** so extremes are not regressed toward the mean. Extreme-rain flag = corrected probability of exceeding the local 99th percentile. Tested on held-out stations.

**Known risk:** with ~138 mostly lowland gauges the corrector may not close a Wayanad-scale gap. If it does not, the system widens its uncertainty and leans on source disagreement and soil moisture, and reports this explicitly. IMD's gauge-based grid will be assessed in Phase 0 as a better reference.

### 7.3 Baselines it must beat
(1) Wayanad-style rainfall threshold (intensity-duration / antecedent-rain), (2) LHASA-style susceptibility × rain rule, (3) logistic regression.

### 7.4 Case studies (never trained on)
Wayanad 2024 and Kerala 2018 are excluded from training entirely. Question asked of each: would AetherGuard have warned, and how early?

### 7.5 Ablations
Remove in turn: integrity features, source-disagreement features, rain corrector — to show which components earn their place.

---

## 8. Alert engine

- **Hazard levels:** Normal, Watch, Warning, Emergency, derived from calibrated probability using thresholds set on validation data to reach the **≥ 90 % detection** target. Hysteresis prevents flapping.
- **Data confidence** (separate flag): High, Degraded, Insufficient.
- **No silent "Normal" when blind:** if data confidence is Insufficient and independent sources indicate heavy rain, escalate to at least Watch with reason "sensors untrusted".
- **Reasons stored with every alert:** top contributing factors, sensor-trust summary, rain-source spread.
- **Operating point:** chosen by cost–loss reasoning (a miss costs far more than a false alarm); resulting false-alarm cost always reported.

---

## 9. Serving and interfaces

- **Replay mode:** historical runs for evaluation and case studies.
- **Live demo mode:** pulls the latest rain and soil data and newest NOAA station readings and runs daily. No open live landslide-site sensor feeds exist, so the demo sensor stream is a **replay of real recorded data, clearly labelled**.
- **FastAPI:** health, risk-per-cell, sensor-integrity, alerts endpoints.
- **Streamlit dashboard:** risk map; sensor-trust panel; "why this alert" view; Wayanad 2024 replay slider; evaluation report page.

---

## 10. Validation protocol

- Test set **frozen and checksummed before any modelling**; never used for tuning.
- Splits blocked by **time** and by **region** (train on one range, test on the other). Because the HMA catalog ends in 2018, the temporal hold-out draws on Global Landslide Catalog/COOLR events 2019–2024 plus Kerala 2019 and 2024; exact cut dates are fixed in Phase 1 after the data audit.
- Metrics: PR-AUC; detection rate at fixed false-alarm rate; calibration (reliability curves, calibration error); warning lead time; per-event bootstrap confidence intervals.
- All comparisons include the baselines in §7.3 and §6.4.

---

## 11. Build phases (each ends with a stop-and-report gate)

| Phase | Deliverable | Gate |
|---|---|---|
| 0 | **Data audit:** verify each source (access, size, licence, coverage, date range), IMD gridded rain, ERA5 soil moisture, lithology, geospatial libraries on Python 3.13; env + manifest | Report before any modelling; drop or replace sources that fail |
| 1 | Ingest → Parquet feature store; frozen, checksummed splits | Split integrity tests pass |
| 2 | Baselines + integrity engine | Integrity engine beats baselines on real-flag data; extreme-retention reported |
| 3 | Hazard model + rain corrector | Beats baselines with CIs; recall-first operating point reached or shortfall reported |
| 4 | Alert engine, API, dashboard | End-to-end smoke test passes |
| 5 | Final evaluation report, case studies, limitations | Honest report regardless of outcome |

If a phase misses its target, work stops and the shortfall is reported rather than hidden.

---

## 12. Project layout

```
AtherGuard/
  pyproject.toml   README.md   .gitignore
  configs\                      # sources, splits, thresholds (config-driven runs)
  data\{raw,interim,processed}\ # git-ignored; manifest with checksums tracked
  src\aetherguard\{data,integrity,hazard,alerts,serve,eval}\
  tests\
  reports\
  docs\superpowers\{specs,plans}\
  .venv\                        # project-local, git-ignored
```

---

## 13. Testing and reliability

- **Unit tests** for every deterministic check and feature builder.
- **Data-contract tests:** schema, units, ranges, UTC time, no leakage; test that the frozen test set is never read during training.
- **Property tests for the safety rules:** more rain never lowers risk; repair never lowers the hazard estimate; a corroborated real extreme is never deleted.
- **Smoke test:** whole pipeline on a tiny sample.
- **Reproducibility test:** headline metrics regenerate from fixed seeds and pinned dependencies.
- **Error handling:** source outage → last good cached copy + data confidence downgraded; schema drift detected on ingest; missing data explicit.

---

## 14. Risks and open items

| Item | Handling |
|---|---|
| Label sparsity/bias | §4.2; per-event evaluation; false alarms as upper bounds |
| Rain corrector may not fix extreme under-measurement | §7.2; widen uncertainty; report plainly |
| Thin real gauge data in Nepal/Himalaya | Region-blocked validation exposes it; report per region |
| Real-fault labels cover only NOAA-checked faults | Injected faults reported separately, never in headline |
| Sources unverified: IMD grid, ERA5-Land soil moisture, lithology, SoilGrids REST | Phase 0 audit |
| Literature figures from search summaries only | Read primary sources before quoting |
| Geospatial libraries on Python 3.13 (Windows) | Phase 0 check; fall back to alternatives if wheels are missing |
| Manual steps only the user can do | See §15 |

---

## 15. User actions required

1. Create a free **NASA Earthdata** account (HMA landslide catalog v2, optional IMERG). Credentials are supplied via environment variable or `.netrc`; never committed or shown to the assistant.
2. **Export the NASA Global Landslide Catalog / COOLR** once from the Landslide Viewer (browser) and place the file in `data\raw\`.
3. Network access for tens of GB of downloads.
