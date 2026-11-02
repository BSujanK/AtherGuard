# AetherGuard: live-ready best model, daily live run, AWS application (Stage A) — design spec

Date: 2026-10-14. Status: approved in conversation ("go for it"), awaiting review of this written spec. No git in this project.
Parent work: `docs/superpowers/specs/2026-09-30-aetherguard-design.md`, `docs/phase1-design.md` … `docs/phase4-design.md`, `reports/FINAL_REPORT.md`.

## 1. Purpose

Turn the research pipeline into one that predicts every day on its own, from data that actually arrives every day, with the most accurate model those data allow; prepare an AWS application for future heavy (GPU) training. Worldwide coverage follows later as Stage B.

### Decisions taken with the user
| Question | Decision |
|---|---|
| "Global best" | Both, staged: Stage A = best accuracy on the current regions (Himalaya + Western Ghats) with live data; Stage B = worldwide coverage, separate spec later. |
| Daily output | Today (nowcast) plus the next 3 days (forecast-driven). |
| Where it runs | This laptop, scheduled daily. |
| AWS | Write a GPU service-quota request and a usage plan that stays inside the existing $140 credit; launch nothing now. Any future launch needs the user's explicit yes after stating $/hour and $/day. |

### Why a retrain is required (the key fact)
The frozen v2 hazard model (`data/processed/hazard/model/`, 30 inputs: 14 rain, 6 soil-wetness, 10 terrain) was trained on the IMD final gauge grid (published yearly), CHIRPS final (about 3 weeks behind) and MERRA-2 wetness (weeks behind). None of these arrive daily, and feeding substitutes the model never saw shifts its inputs silently. A daily system needs a model trained on the same products it will receive live.

## 2. Scope

Stage A has three deliverables:
- **A1 Live-consistent model ("v3-live")**: same labels, splits and sampled rows as v2; features rebuilt from live-available sources; accuracy upgrades selected by cross-validation.
- **A2 Daily live runner**: scheduled fetch, predict (D, D+1..D+3), alert, bulletin, dashboard "Live" view.
- **A3 AWS application package**: documents only.

Out of scope for Stage A: worldwide coverage (Stage B), cloud deployment, push notifications, retraining on post-2018 labels beyond what exists, any AWS resource creation.

## 3. Data sources for live use

| Role | Source | History | Live latency | Coverage | Access |
|---|---|---|---|---|---|
| Primary rain (model input) | NASA GPM IMERG V07, Late Run daily (`GPM_3IMERGDL`); Early Run (`GPM_3IMERGDE`) as a same-morning fallback | 2000 to today | Late about 12-14 h, Early about 4 h | Global 0.1° | Earthdata login (existing `_netrc`), spatial subset via GES DISC OPeNDAP |
| Second opinion rain (alert engine only) | IMD real-time gridded rainfall (imdlib `get_real_data`) | Real-time product, recent | About 1 day | India 0.25° | Open |
| Forecast rain D+1..D+3 | NOAA GFS 0.25° (NOMADS grib filter, domain subset) | Archive on AWS Open Data (`noaa-gfs-bdp-pds`) from 2021 | Runs 4x daily | Global | Open, no key |
| Terrain | Copernicus GLO-90 cell statistics (existing `cell_terrain.parquet`) | Static | n/a | Domain | Already built |
| Rain gauges (integrity engine, alert confidence) | NOAA GHCN-Daily | 1990 to today | 1-3 days, irregular | 140 stations | Open |

Soil wetness for the model is derived from IMERG rain itself (antecedent precipitation index), so history and live inputs match exactly. MERRA-2 is dropped from the live model (the v2 cross-validation showed the wetness group adds only about 1.4 false-alarm points).

Day basis: IMERG daily files are UTC days; they are converted to the IMD day (08:30 IST) with the validated D5 approximation `0.875 × UTC(D−1) + 0.125 × UTC(D)` (mean absolute error 1.85 mm against exact hourly totals at Wayanad). The live runner at 09:30 IST therefore needs UTC days D−1 and D: D−1 from the Late Run, the first hours of D from the Early Run, with the dependency recorded per run.

## 4. A1 — the live-consistent model

### 4.1 Rows, labels, splits
Reuse the frozen label store, splits and sample files unchanged (`data/processed/splits`, `data/processed/features/samples`): train 2007-2015, validation 2016-2017 (pooled for year-blocked cross-validation), test 2018, window test 2023, case studies Kerala 2018 and Wayanad 2024. Only the feature values are recomputed, from IMERG. No change to positives, negatives or universe weights, so comparisons with v2 are row-for-row.

### 4.2 Features (groups selectable by cross-validation)
- `irain_`: IMD-day accumulations over 1, 3, 5, 7, 14, 30, 60, 90 days; max 1-day rain in 7 and 30 days; wet days in 30; days since 10 mm; 1-day share of 3-day total; 3/7/30-day totals relative to the cell's own 2007-2015 IMERG climatology (train years only).
- `iapi_`: antecedent precipitation index with decay 0.85, 0.90 and 0.95 (wetness proxy).
- `inbr_`: maximum and mean of 1- and 3-day rain over the 3×3 neighbouring cells (storm position uncertainty).
- `stat_`: the 10 terrain inputs, unchanged.
- `iint_` (conditional): peak 3-hour and 6-hour intensity from half-hourly IMERG, built only if a feasibility spike shows the download and compute fit the laptop (estimate per day and total before committing); otherwise recorded as dropped.

Monotone constraints as in v2: non-decreasing in rain accumulations, intensity, API, neighbourhood rain, slope and relief; non-increasing in days since 10 mm.

### 4.3 Model selection (protocol v2, unchanged)
- Year-blocked cross-validation over 2007-2017, folds {2007-08, 2009-10, 2011-12, 2013-14, 2015, 2016, 2017}.
- Metric: pooled out-of-fold false-alarm share at 90% recall (weighted universe), tie-break log-loss; bootstrap CIs.
- Candidates: LightGBM (regularised grid as in v2) and CatBoost (small grid); feature-group candidates as in 4.2 with the simpler-unless-better-by-SE rule.
- Calibration: isotonic on pooled out-of-fold scores, fitted per region (Himalaya, Western Ghats) to address the 3× Ghats under-prediction, with the pooled calibrator as fallback when a region has too few positives in a fold.
- Alert thresholds Watch / Warning / Emergency from pooled out-of-fold scores, recall-first margin as in v2.

### 4.4 Acceptance
- v3-live is **"best"** only if its pooled out-of-fold FA@90 beats frozen v2 with a paired bootstrap interval excluding zero. Otherwise it is reported as live-capable and "not better than v2", and the report says so.
- Regardless, v3-live is the model the live runner uses (v2 cannot run live). The frozen v2 stays as the archive reference.

### 4.5 Evaluation
- Out-of-fold metrics against v2 and the three baselines (same protocol).
- test_2018: evaluated once, with the model frozen and checksummed first. Disclosed as the second look at 2018 (v2 already used it).
- Operational backtest: simulate a daily run for every day 1 Jun - 30 Sep 2018 using only inputs available at 09:30 IST that day (Late Run D−1, Early Run D), and score detection and lead time; same for the 2023 window and the Kerala 2018 and Wayanad 2024 replays.
- Report: `reports/phase6_live_model_report.md/.json`, appended to the final report generator.

## 5. A2 — daily live runner

### 5.1 Flow (package `aetherguard.live`)
1. `fetch`: IMERG Late D−1 and Early D (domain subset), IMD real-time D (India), GFS latest cycle precipitation for D+1..D+3 (domain subset), GHCN-Daily recent records. Each source writes to `data/live/<date>/raw/` with a manifest row and a freshness record (issued time, valid time, latency).
2. `features`: build v3-live features for every candidate cell for D from the IMERG history store (kept current by the daily fetch) and terrain. For D+1..D+3, rain accumulations combine observed days with GFS forecast days; forecast-derived rows are flagged.
3. `predict`: v3-live score, calibrated risk and 10-90% interval; forecast days widen the interval by the out-of-sample forecast error measured in 5.3.
4. `alerts`: the existing alert engine (levels, hysteresis against the previous day's live state, data confidence, blind-sensor rule using the maximum of IMERG, IMD real-time and trusted gauges).
5. `publish`: `data/live/<date>/risk_D{0..3}.parquet`, `alerts.parquet`, a bulletin `reports/live/<date>.md` (top cells by level, sources and their freshness, confidence), and a "Live" set in the replay store so the dashboard and API show it.

### 5.2 Schedule and operation
- Windows Task Scheduler, daily 09:30 IST, command `python -m aetherguard.live run --date today`; a `--date YYYY-MM-DD` rerun recomputes any past day (backfill and debugging).
- Idempotent: a completed day is skipped unless `--force`; partial days resume.
- Failure modes are explicit: a missing or late source lowers data confidence to Degraded or Insufficient for the affected cells and is written into the bulletin; the run never publishes a silent Normal. A fully failed fetch still writes a bulletin stating which sources failed.
- Logs: `logs/live/<date>.log`; health summary in `/health`.

### 5.3 Forecast-day skill
GFS forecast skill for the hazard model is measured on 2021-2024 with archived GFS runs from AWS Open Data (forecast issued on D, used for D+1..D+3), scoring against the labels that exist (2023 window inventory, sparse 2019-2024 records). The thin labels are a stated limitation; the measured forecast rain error is what widens the forecast-day intervals.

## 6. A3 — AWS application package (documents only)

Files under `docs/aws/`:
- `gpu-quota-request.md`: ready-to-paste Service Quotas justification for "Running On-Demand G and VT instances" and "All G and VT Spot Instance Requests", 8 vCPUs each. The case rests on the project's real results (data scale, models, test results) and a concrete training plan.
- `credit-usage-plan.md`: how future GPU and storage work fits inside the existing $140 credit, with instance options, approximate hourly prices (to be verified with AWS pricing before any launch), hours per workload, region choice (near NASA Earthdata Cloud and the Copernicus DEM bucket), spot versus on-demand, S3 storage estimate, and guardrails: a budget alarm at $100 and $130, auto-stop, everything torn down after each job. Nothing is created until the user approves.
- `gpu-requirements.md`: the future heavy-training workloads and their needs — Stage B worldwide training (LightGBM/CatBoost GPU on tens of millions of rows), deep spatio-temporal nowcasting on IMERG rain fields (ConvLSTM / U-Net), and large hyper-parameter sweeps — each with GPU memory, recommended instance (for example g4dn.xlarge with a 16 GB T4, or g5.xlarge with a 24 GB A10G), estimated hours, and why CPU is not enough for it.

## 7. Stage B (outline only; own spec later)
Worldwide coverage: global NASA landslide catalog labels (same label rules, all countries), IMERG rain (already global), global terrain statistics computed from the Copernicus DEM read in place on AWS, region-aware calibration, and continent-blocked validation. Heavy steps are the candidates for the AWS GPU and compute plan in `docs/aws/`.

## 8. Testing
- Offline hermetic tests for every new module (synthetic IMERG/GFS/IMD files in tmp_path), `realdata` and `live` markers for real downloads.
- Feature causality test (nothing after day D, forecast rows flagged), D5 alignment on IMERG, API recursion, neighbourhood maxima at grid edges.
- Live runner: idempotency, rerun by date, every source-failure combination produces a bulletin with the right confidence, hysteresis continuity across days.
- Freeze checks as in v2 before the single test evaluation.
- Full existing suite stays green.

## 9. Risks and limits
- IMERG at 0.1° smooths orographic extremes too (it is not a gauge); the alert engine keeps IMD real-time and gauges as second opinions, and the Wayanad replay reports how IMERG behaved there.
- IMERG Late arrives about 12-14 h after the UTC day ends; at 09:30 IST the most recent hours come from the Early Run. Measured in the operational backtest.
- Forecast days inherit GFS rain errors; their skill is measured on thin 2021-2024 labels.
- A second look at 2018 weakens it as a clean test; disclosed.
- The laptop must be on for the daily run.
- Half-hourly intensity features may prove too heavy for the laptop; decided by the spike.
- AWS prices in the plan are approximate until checked against AWS pricing at launch time.

## 10. Amendment (2026-10-15): live timing corrected from measured latencies
The Task 1 probe measured IMERG latency (CMR ingest time minus end of the UTC day) at a median of **14.5 h for Late** and **4.5 h for Early**. At 09:30 IST on day D (04:00 UTC) the newest UTC day of *either* run is D−2, so §3 and §5.1 ("Late D−1 + Early D") were not achievable. Replaced by:
- **Run time 11:00 IST** (05:30 UTC D), Task Scheduler retries every 30 min up to 3 times (last attempt 12:30 IST).
- **Rain inputs at run time:** Late for every UTC day up to D−2; **Early for UTC D−1**, mapped to the Late scale by an Early→Late quantile mapping fitted on the Early/Late overlap (June–September 2019–2024 excluding the 2018 test season; checked on 2018); the **00–03 UTC D** part of IMD day D from the GFS 00Z cycle 0–3 h accumulation (the exact hours that the 0.125 × UTC(D) term approximates in training).
- Hence IMD day D = 0.875 × mapped Early(D−1) + GFS 0–3 h(D); IMD day D−1 = 0.875 × Late(D−2) + 0.125 × mapped Early(D−1); earlier days unchanged from training.
- The operational backtest (Task 6) uses exactly this construction with inputs issued before 11:00 IST of each day; it measures the train/live gap these substitutions cause.
- If Early D−1 is missing at the last attempt, the run publishes with IMERG-based cells marked Insufficient for D and the blind-escalation rule applied, and the bulletin names the gap (§5 failure rules unchanged).

## 11. Amendment (2026-10-23): interval and post-model rules

Prompted by two user-confirmed false alarms of the 2026-10-23 run (cell 23965166, Warning with its point outside its own
range; cell 24605098 at Katra, Emergency held through an input outage), both with 0 mm of IMERG rain over 7 days. The
frozen v3 artifacts (model, ensemble, card, calibrators) do not change; this amends the scoring code and adds rules
after the model. Every value was chosen on the development years (2007-2017) out of fold with the Task 6b fold models;
2018 and the live day were evaluated once afterwards (`reports/phase6_accuracy_hardening.md`).

**11.1 Interval.** `risk_lo` / `risk_hi` are no longer percentiles of the calibrated members (the point lay outside them on
3.2% of development cell-days). They are the members' spread re-centred on the point in logit space,
`expit(logit(point) - (logit(median_m) - logit(p10_m)))` and `expit(logit(point) + (logit(p90_m) - logit(median_m)))`
(raw scores clipped to [1e-12, 1 - 1e-12]), calibrated like the point, so `risk_lo <= risk <= risk_hi` always.
`HazardModel.score` also returns `member_median_risk` (calibrated member median) and `ensemble_agreement` (the share of
members whose calibrated risk reaches the threshold of the level the point reaches, the card's thresholds per region).
`ensemble_percentile` is re-centred the same way. `uncertain_high` tests the new `risk_hi`, which raises more cell-days
to Watch (development Watch+ 58.8% -> 61.9%, one more event); the rain trigger below more than offsets it.

**11.2 Ensemble disagreement.** A point at Warning or above with `ensemble_agreement` < 0.25 is capped at Degraded,
cause `ensemble_disagrees` ("most of the 20 ensemble models put this cell lower"); the level does not change.

**11.3 Rain trigger.** A level needs recent rain: `irain_acc_7 >= 11.50 mm` (the 5th percentile of the in-domain
development positives). A cell-day failing it is capped after the model and before the hysteresis: Watch -> Normal,
Warning -> Watch, Emergency -> Watch, reason code `no_recent_rain`; blind-escalated cells (heavy rain in an independent
source) and cells without rain inputs are exempt. Hysteresis may hold a level only while the rule passed on one of the
3 days ending on the day (D-2..D); otherwise the hold falls to the capped level. Adopted at all three levels by the
pre-declared rule (at most 1% of that level's development events lost, and a lower share).

**11.4 Blind-hold limit.** A cell whose model inputs are missing is held at most H = 2 consecutive days without a score
(the largest lag at which development Emergency, Warning and Watch points are still at their level at least half the
time), then lowered one level per further missing day; it stays Insufficient with code `held_while_blind`. The
blind-escalation rule still applies.

**11.5 Forecast leads.** The rain cap uses the lead's own 7-day rain (observed days plus the GFS forecast); there is no
hysteresis or blind rule. `uncertain_high` tests the re-centred ensemble `risk_hi` of the forecast features, NOT the
widened one: on the forecast-skill pairs (488 GFS issue days of June-September 2021-2024, 2,536 cells) its pooled
level agreement with the observed-feature level is 0.810 against 0.717 for the widened bound and 0.798 without
`uncertain_high` (pre-declared: higher agreement wins). The widening factors still widen the published `risk_lo` /
`risk_hi`. A forecast day has no observation, so a lead is never High: a scored lead is Degraded with causes
`forecast_day`, `observed_through_d_<D0 state>` and `forecast_widened` (or `forecast_uncertainty_uncalibrated`), an
unscored one Insufficient (`forecast_input_missing`).

**11.6 Audit.** `python -m aetherguard.live.audit --date YYYY-MM-DD|all` checks every published row (lead 0 and the
forecast leads) for the interval, a level explained by its codes, the rain rule, the blind-hold limit, confidence and
causes, a High forecast row, and `risk_per_100k`; it writes `reports/live/audit/<date>.json` and exits 2 on any
violation. The runner audits each day it publishes and records the result in run.json and the bulletin. The rules live in
`data/processed/alerts/post_rules_v3.json` (`configs/live_run.yaml` `post_rules`); the runner applies them through
`aetherguard.live.postrules`.

## 12. Amendment (2026-10-23, user request): more accurate forecast days and per-cell certainty
User: "forecast — less certain why this is for D+1, 2, 3. I want the certain predictions" → after the explanation: "go for which make the system more precise and accurate".
Future rain cannot be made certain; the aim is (a) the most skilful forecast rain available for free, (b) honest per-cell certainty instead of one blanket label.

**F1 Scenario certainty (per cell, per forecast day).** Each D+k row is scored under three rain scenarios with the same model and post-model rules: `dry` (no rain after D), `forecast` (the chosen forecast), `wet` (the forecast's heavy-rain bound: the 90th percentile of the ensemble members when an ensemble exists, else the forecast × the lead's high widening factor). Certainty = `firm` when the published level is identical in all three (the level is set by rain already on the ground), else `depends_on_forecast` with the level range shown. Dashboard: "Firm" / "Depends on rain forecast (Watch–Warning)" replaces the blanket "forecast — less certain"; D0 has no such label.

**F2 Better forecast rain.** Candidate sources, all free and without an account: ECMWF IFS open data (HRES `oper` and the 51-member ensemble `enfo`, total precipitation, 0.25° since 2024-02, archive from 2023 on the public `ecmwf-forecasts` bucket and data.ecmwf.int), NOAA GEFS (31 members) and the current GFS. IMD-day totals built exactly as for GFS (cycles issued no later than 03:00 UTC of D; the 00Z run is published around 06:00-08:00 UTC by ECMWF, so the live run uses the 12Z run of D−1 when 00Z of D is not yet out — measured, not assumed).

**F3 Rain bias correction.** Quantile mapping forecast → IMERG Late per lead and region, fitted on the development seasons of the forecast archive (June–September 2021–2023 for GFS; 2023 for ECMWF) and checked on 2024.

**Selection (pre-declared).** On June–September 2024 (held out from F3's fit) and, as a secondary check, 2023: per lead, the forecast configuration (source × corrected or not × deterministic / ensemble mean) is chosen by (1) hazard level agreement with the observed-feature level (primary), (2) recall of observed-feature Watch+ and Warning+, (3) rain CRPS / MAE and the ≥ 50 mm hit rate / false-alarm ratio. A candidate replaces GFS only if it beats it on the primary metric by more than the bootstrap SE (cell-days resampled by day) and does not lower Warning+ recall. GFS stays the fallback when the chosen source is late or missing (recorded per run). Widening factors (§5.3) are re-derived for the chosen configuration.

### 12.1 Implementation and results (2026-10-24)
Code: `ingest/ecmwf.py`, `ingest/ecmwf_build.py` (F2 sources, publication probe), `live/forecast_map.py` (F3), `live/forecast_choice.py`
(configurations, per-lead resolution with the GFS fallback, the dry / forecast / wet scenarios), `live/forecast_select.py`
(selection and certainty accuracy), `live/postrules.scenario_certainty`, the runner (`run.json` `forecast_rain`, per-lead
`forecast` and `certainty`; `risk_D<k>` columns `certainty`, `level_min`, `level_max`), the audit check `certainty`, `/api/grid`
and `/risk/cell` fields and the dashboard. Reports: `reports/phase6_ecmwf_publication.md`, `phase6_forecast_selection.md`,
`phase6_forecast_certainty.md`.

**F2.** HRES and the ensemble (`enfo`, mean and p10 / p50 / p90 of the member IMD-day totals) from the public copies of the ECMWF
open data, as IMD-day totals on the IMERG grid. Measured publication (bucket `Last-Modified`): the 00Z run is complete at
07:56 UTC (HRES) and 08:47 UTC (ensemble), the 18Z run of D-1 at 01:13 and 02:12 UTC, the 12Z run at 19:56 and 20:49 UTC of D-1;
the 00Z run of D is therefore never out at the 05:30 UTC run and the live run uses the newest cycle that is out (18Z of D-1 from
02:15 UTC), recorded per lead in `run.json`. The archive evaluation uses the 12Z run of D-1 (complete on the Google Cloud copy;
the AWS copy answers HTTP 503 `SlowDown` at about 0.5 requests per second). Archive: June-September 2024 (122 days) and
2023-07-13..2023-09-30 (80 days); June and 1-12 July 2023 are missing on the Google copy and were not fetched from AWS (about 42
days x 204 requests at that rate). The 2026 live ensemble files carry the 50 perturbed members only. GEFS was not archived: its
APCP is stored as 3- and 6-hour buckets without a running total (about 29 range requests per member, 31 members, about 66 GB for
the two seasons), beyond the one-hour allowance.

**F3.** Frequency-matched quantile mapping per source x lead x region (`himalaya`, `western_ghats`, `rest`); GFS fitted on
June-September 2021-2023, ECMWF on the 80 days of 2023.

**Selection (2024, pre-declared rule, 2,536 cells).** D+1: GFS stays (best candidate +0.0098 agreement is `ecmwf_ens_mean+map`, but
its Warning+ recall 0.763 is below GFS 0.795, so it is not eligible); D+2: ECMWF ensemble mean, raw (agreement 0.8036 vs 0.7967,
+0.0068, bootstrap SE 0.0020; Warning+ recall 0.797 vs 0.745); D+3: ECMWF ensemble mean, bias-corrected (0.7863 vs 0.7726, +0.0137,
SE 0.0026; Warning+ recall 0.707 vs 0.705). Widening factors re-derived on 2024 for the chosen configuration (lo / hi): D+1
0.176 / 4.24, D+2 0.176 / 3.67, D+3 0.151 / 5.92; the old GFS factors are kept as `fallback.leads` of
`reports/forecast_widening.json`.

**F1 (2024).** Share of cells that are firm 52% / 58% / 58% at D+1 / D+2 / D+3; the forecast level equals the observed-feature
level for 96.1% / 96.0% / 94.4% of firm cells against 66.4% / 58.8% / 57.1% of the cells that depend on the forecast.

## 13. Amendment (2026-10-24, user request): prediction integrity audit

The consistency audit of §11 (`live.audit`) is extended so that every published row is also checked for mathematical and
geographical errors. Ten check families join the nine of §11; each is a named entry of `audit.CHECKS`, with a count and up to five
examples per table, and any count above zero is a violation (exit code 2). A finding about plausibility rather than computation is a
NOTE: it is counted in `note_counts` of the table and never in `violations`. Every identity is one that follows from the
definition of the quantity; the defining function is cited in the docstring of the check (`live.audit_math`, `live.audit_geo`,
`live.audit_rescore`). A table lacking the columns a check needs is skipped (`checked` stays false).

**13.1 Mathematics** (`audit_math`, every risk table and every `features_D<k>.parquet`).
* `probability`: `risk`, `risk_lo`, `risk_hi` are finite and in [0, 1] exactly where the row is scored (all three missing together
  otherwise); the level is 0..3 and `level_name` is its name; `level_min <= level <= level_max`.
* `dates`: `date` is the run date + lead, `lead` is the file's lead, a `cell_id` appears once, and every table of the run holds the
  same cells at the same `lat`, `lon`, `region`.
* `rain_math` (features, `features.imerg_features`): accumulations are non-negative and non-decreasing in the window, a missing day
  makes every longer window missing; `irain_max1d_w` lies between acc_w / w and acc_w and acc_1 <= max1d_7 <= max1d_30;
  `irain_wetdays_30` is an integer 0..30, 0 exactly when max1d_30 < 1 mm, and acc_30 >= wetdays_30 mm; `irain_share1_3` is acc_1 /
  acc_3 when acc_3 >= 1 mm and missing otherwise; `irain_days_since_10mm` is an integer 0..90 that agrees with acc_1, max1d_7 and
  max1d_30 against 10 mm; `*_vs_clim` >= 0; `iapi_k` >= 0, non-decreasing in k, >= k^(n-1) acc_n, missing exactly with the day's
  rain; `inbr_*`: mean <= max, own total <= max, own total / 9 <= mean. Tolerance 1e-4 mm + 1e-5 relative (float32).
* `rain_chain` (features of lead k against the forecast days `gfs_rain_d1..dk` and lead 0 of the same run): acc_1(k) is d_k; acc_n(k)
  is d_1 + .. + d_k + acc_(n-k)(0), bracketed by the stored windows when n-k is not one; max1d, wetdays and days-since follow from the
  forecast days and lead 0; `iapi_c(k) <= c iapi_c(k-1) + d_k`. Lead 0 of the run is not compared with the previous run's forecast.
* `shap`: `shap_json` lists min(5, #inputs) model inputs for a scored row and none otherwise, sorted by |contribution|, each `value` equal
  to the row's value in the lead's features table (1e-4 relative); `reasons_json` repeats risk (point, lo, hi, per 100k), level name,
  contributions, codes and confidence. With a model (below) base + the sum of ALL LightGBM contributions equals the raw margin to 1e-6 and
  the listed ones are the five largest.
* `reproducible` (`audit_rescore`): scoring each stored feature table again with the frozen model reproduces `risk`, `risk_lo`,
  `risk_hi` (and at lead 0 `risk_per_100k`, `member_median_risk`, `ensemble_agreement`) within 1e-9 relative, the scored rows are
  exactly the rows with complete rain inputs, and a forecast lead's interval is the model's times one constant factor per bound (read off
  the rows the clip leaves alone; `risk_hi` is capped at 1, a probability). Also `uncertain_high` is recomputed from the re-scored UNWIDENED interval (not from the run's own `lead_scores`) with the bound
  that `rules.lead_uncertain_bound` names, so a flag computed from another interval (the widened one under an `unwidened` rule) is flagged.

**13.2 Geography** (`audit_geo`).
* `grid`: `cell_id == grid.latlon_to_cell(lat, lon)`, `(lat, lon) == grid.cell_center(cell_id)` exactly, `region == grid.region_labels`;
  a cell in no region box or in a box that disagrees is a violation.
* `land` (alerts table; the cell set is the same in every table): the centre of every scored cell is land in the base map's country mask.
  Sea in the mask is a violation unless the base map's own elevation there is above sea level (the 1:10m coastline misses the centre of a
  coastal cell; counted as the note `land_coastal_masked_as_sea`). Cells in Nepal, Bhutan and other countries are notes
  (`land_<country>`).
* `georef`: `stat_elev_mean` correlates > 0.95 with the base map elevation of the same cell and more than with any one-cell shift (per
  day). Rain: over all published days, IMERG `irain_acc_1` against the IMD real-time grid at the cell's nearest point shifted by +-1 and
  +-2 IMD cells in latitude and longitude and by +-1 day (`audit_geo.rain_georef`, pooled Pearson correlation); a shifted product that
  correlates better than the aligned one by more than `SHIFT_MARGIN = 0.02` is a violation of the summary of `--date all`. The
  per-product study that says which product is displaced is `live.audit_registration` (gauges as point truth). The live IMD sampling is moved by `imd_lon_offset_columns` (-1: one column west) of `configs/live_run.yaml`, the correction that study found
  (the IMD grid's data lie about one 0.25-degree column east of its `66.5 + 0.25 j` labels); the rain test is taken relative to it, so with the
  correction zero offset is best. Only the live adapter (`adapter.imd_cell_series`, `src_imd_*`, `imd_acc_1`) uses it: `features.sources._imd_pixels`
  keeps offset 0 for the frozen v2 store, the integrity engine and the replay, and a column outside the grid is missing, never the next row.
  A further `georef` check compares the stored `src_imd_acc_1` of lead 0 with the grid read at the configured column.
* `places` (alerts): every scored cell has a label in `cell_places.parquet`, `distance_km` equals the great-circle distance from the
  cell centre to the place within 0.52 km (it is stored as an integer and the place position as 1e-4 degrees), the place name is not
  empty, and the country of a cell the mask puts in India, Nepal or Bhutan is that country. Places over 30 km are a note.

**13.3 Parity with the API** (`audit_parity`, `python -m aetherguard.live.audit --api URL`, not part of the daily run): for a seeded sample
of 300 cells per lead of the newest day (stratified so every level present is included), `/api/grid` and `/risk/cell/{id}` equal the
parquet rows in risk, bounds, per 100k, level, confidence and causes, place, rain (lead 0: the evidence of `reasons_json`; lead k: the
forecast days of `features_D<k>`), certainty and date. The dashboard's odds sentence (`describeOdds`) has a table-driven test that N is
within the two-significant-figure rounding of 1 / risk and is the same in the sentence, the short form and the capped and
disagreeing variants.

**13.4 Notes** (`note_counts`, never violations): alerts per level on cells with `stat_slope_mean` < 5 degrees
(`slope_lt_5deg_<level>`) and with `stat_elev_mean` < 100 m (`elev_lt_100m_<level>`) for the alerts table and each forecast lead; cells per
country class; places over 30 km. They count; they do not judge (the terrain and rain-floor question is §14).

**13.5 Running it.** `python -m aetherguard.live.audit --date all|YYYY-MM-DD [--rescore]` writes `reports/live/audit/<date>.json` and
`summary.json` (with the pooled rain-registration table). The daily run audits every row it publishes with all checks, including the
rescoring with the model it just scored with (`live.run.audit_run`); the checks that read files (base map `basemap_file`, place table
`places_table`) are skipped with a note when the file is absent. The stand-alone CLI scores again only with `--rescore`. Cost and the
findings of the first full run: `reports/phase6_integrity_audit.md`.

## 14. Amendment (2026-10-24): Precision rules: terrain plausibility and per-level rain floors

Prompted by the live day 2026-10-24: of 3,660 Watch-or-above cells, 773 have a mean slope under 5 degrees and 760 a mean elevation
under 100 m; for 383 of the 1,035 Emergencies the largest SHAP contribution is `stat_elev_mean` pushing the risk UP (cell 19625150
near Kanyakumari: 31 m, mean slope 2.8 degrees, Emergency, High confidence, `stat_elev_mean` +2.13); Himalaya Warnings reach High
confidence on only 11-16 mm of 3-day IMERG rain (Jammu, Manipur). Hypotheses: (a) catalog positives mislocated onto lowland or
flood-type events taught the model "low coastal land = risk"; (b) the single 7-day 11.5 mm trigger (§11.3) is too weak for the
Warning and Emergency levels. **This is an analysis only.** Nothing here changes the frozen model, `postrules.py`, the live run, the
configs or the published tables; the candidate rules are written to `data/processed/alerts/post_rules_v4_candidate.json`, which no
run reads. Code: `src/aetherguard/live/precision_study.py` (`dev`, `heldout`, `live-replay`, `report`); report
`reports/phase6_precision_rules.{md,json}`.

This section, including the adoption criterion, was written BEFORE any 2018 number of this study was computed. Selection uses the
development panels only (`accuracy_hardening_oof`, out of fold, June-September 2007-2017: every development-event cell plus the
seeded 5,000 universe cells) and the development positives; 2018 is evaluated once (`accuracy_hardening_heldout`, the single
look of §11) and nothing is tuned after it.

**14.1 Baseline.** The §11 levels: re-centred `uncertain_high`, the 7-day 11.50 mm rain cap at Watch, Warning and Emergency, hold
windows Watch 2 / Warning 1 / Emergency 1 days, blind-hold limit 2 days (`post_rules_v3.json`). Reproduced from the panels and
checked against `evaluation.json` (2018: 48/56 Watch+, 40 Warning+, 30 Emergency events) before anything else is reported.

**14.2 Rule T (terrain plausibility).** A cell-day on a cell whose terrain variable is below `T_min` cannot exceed Watch: Warning
and Emergency become Watch (Watch stays Watch). Applied after the §11 rain cap and before the hysteresis; a held Warning or
Emergency on such a cell is released directly to Watch on the next day (hold window 1).
- Candidate variables: `stat_slope_p90`, `stat_slope_mean`, `stat_relief`. For each, `T_min` is the 5th percentile
  (`numpy.percentile`, linear) of the variable over the in-domain development positives (train and validation samples, every
  month, the population of the 11.50 mm rule).
- Terrain variable chosen: the candidate whose `T_min` removes the largest share of development NEGATIVE alert cell-days, where an
  alert cell-day is a scored universe cell-day (June-September, seeded sample) whose POINT level (risk against the card's
  thresholds of the cell's region) is Warning or above and that is not a labelled event cell-day. Ties go to the order listed.
- Terrain values of the panel cells, the live cells and the 2018 cells are the own-cell values of the scored-cell terrain table.

**14.3 Rule R (per-level rain floors).** For w in {1, 3, 7}: `m_w^Warning` is the 5th percentile of `irain_acc_w` over the
development positives (event cell-days of the development panels, out of fold, with a score) whose POINT level on the event day
reaches Warning or above; `m_w^Emergency` likewise over those reaching Emergency. A cell-day passes the Warning test when ANY window
reaches its floor (the OR form of `RainRule`), the Emergency test likewise with the Emergency floors. A window whose 5th percentile
is 0 mm admits every cell-day and is dropped from the OR (a vacuous window would void the rule); if all three are 0 the rule is
reported as vacuous and not evaluated. Raw level Emergency failing the Emergency test becomes Warning; a level Warning (including
that one) failing the Warning test becomes Watch. The §11 7-day 11.50 mm rule is unchanged and applies first. Hold release (same
windows as §11): a held Warning is released to Watch when the §11 rule or the Warning test failed on the hold window's day; a held
Emergency is released to Warning (one step, as the hysteresis library does; to Watch on a flat cell under T) when the §11 rule or
the Emergency test failed on its hold window's day.

**14.4 Evaluation.** Conditions: baseline, T, R, T+R. Per condition and level (Watch+, Warning+, Emergency): own-cell events
detected on the event day out of the events, alert cell-days of the universe cells at each level or above, cell-days at Warning+
on cells below the terrain floor, precision proxy (detected events per 1,000 alert cell-days at that level or above; development
cell-days are scaled from the 5,000 sampled to all 36,792 universe cells, as in §11), and the paired bootstrap (seed and 2,000
resamples of `backtest.BOOTSTRAP`; days as the unit for cell-days, events for detection) of the change against the baseline in
Warning+ alert cell-days and in Warning+ detection. The development evaluation is in-sample for the floors (it selected them); the
decision is made on 2018.

**14.5 Live replay.** The days 2026-10-16..2026-10-24 are recomputed offline from the stored `features_D0.parquet` and
`alerts.parquet` (the published point risk and raw level): the baseline and each condition run through the same hysteresis
(`levels.apply_hysteresis`, the §11 hold windows) as one continuous chain seeded from the previous published days; the baseline chain
is compared to the published levels. Counted: alerts changed per level, flat-cell and low-rain alerts changed, and the named cells
19625150 (Kanyakumari) and the Jammu cells within 0.25 degrees of 33.1N 74.7E. Nothing is written to `data/live`.

**14.6 PRE-DECLARED ADOPTION CRITERION.** A rule (T, R or T+R) is recommended for adoption only if on 2018 it (a) loses at most 1
Warning+ event, (b) loses at most 1 Emergency event, (c) loses at most 1 Watch+ event, all against the baseline's own-cell
event-day detection, AND (d) reduces the Warning+ alert cell-days of the universe cells with a paired-bootstrap 95% confidence
interval of the per-day reduction that excludes 0. Otherwise it is reported as not adopted. Among rules that meet it, the one with the
larger reduction is recommended. No threshold, floor or form is changed after 2018 is read; a failed rule is reported as failed.

**14.7 Diagnosis (not a rule).** How many development positives lie on cells with a mean slope under 5 degrees or a mean elevation
under 100 m, by region and catalog source (`positive_cell_days.sources`) and by the catalog's location accuracy; the positive share
of the development samples by elevation band; and the partial dependence (PD) and individual conditional expectation (ICE) of the
frozen v3-live model on `stat_elev_mean` over a seeded sample of in-domain development rows (seed 20261024; up to 1,000 positives and
1,000 negatives), overall and by region, to say whether the model's dependence is decreasing at low elevation. This informs whether
a later retrain (dropping or monotone-constraining elevation) is warranted; no model is retrained here.

### 14.8 Results (2026-10-24; written after the runs, the sections above are unchanged)
Source: `reports/phase6_precision_rules.{md,json}`, `data/processed/alerts/precision_study/`. Floors from the development years: rule T
variable `stat_relief` < 180.44 m (slope_p90 9.72 degrees removes 4.1% and slope_mean 4.28 degrees 3.3% of the development negative
Warning+ cell-days against relief's 4.3%); rule R Warning floors 3.18 / 13.25 / 42.36 mm (1 / 3 / 7 day), Emergency floors 8.32 / 25.31 /
52.07 mm. 2018 (single look, baseline reproduces 48 / 40 / 30): T loses 1 Warning+ and 1 Emergency event, removes 42,541 of 996,517
Warning+ cell-days (4.3%); R loses 1 Warning+ event, removes 35,845 (3.6%); T+R loses 2 Warning+ events. By 14.6, T and R meet the
criterion, T+R does not, and T is the recommended rule. The same rules on the development panels (in-sample for the floors) lose 18
(T) and 2 (R) of 539 Warning+ events, so the 2018 result rests on 56 events and is not strong evidence. Neither rule addresses the
motivating cells: T on relief does not touch cell 19625150 (relief 328 m), and R lowers only 3 Warning cells on 2026-10-24 because the
1-day floor (3.18 mm) admits almost every wet cell-day. The terrain variable sensitivity (slope_p90, slope_mean; development and
replay only, not 2018) lowers the Kanyakumari cell. Nothing is wired; adoption into the live run is a separate decision.

## 15. Amendment (2026-10-24): v3.1 challenger: label audit and physical constraints

Prompted by §14.8: post-model terrain and rain rules were not selective, so the cause is looked for in the model and its labels.
§14.7 found 103 of the 789 in-domain development positives (13.1%) on cells with a mean slope under 5 degrees or a mean elevation
under 100 m (57 of the 107 Western Ghats positives, 46 of the 682 Himalaya ones; all 107 Western Ghats positives come from the
COOLR reports catalog), and a partial dependence of the frozen v3-live model on `stat_elev_mean` that falls from 0 to 300 m. This
amendment is a pre-declared study of whether a retrained v3.1 model that removes that dependence, or the labels behind it, is more
physically plausible without losing accuracy. **Nothing here changes the frozen v2/v3 artifacts (`model_v3_live` is read only), the
live run, `postrules.py`, `run.py`, `audit.py` or `data/live`**; challengers write to new directories
(`data/processed/hazard/v31_challenger/`, `data/processed/alerts/v31_replay/`) and nothing is wired. Code:
`src/aetherguard/hazard/v31_labels.py` (audit), `v31_challenger.py` (candidates, cross-validation, selection), `v31_eval.py`
(test_2018 and the live replay), `v31_report.py`; configuration `configs/hazard_v31_challenger.yaml`; report
`reports/phase6_v31_challenger.{md,json}`.

This section was written BEFORE any cross-validation, calibration, threshold or test_2018 number of this study was computed. The
only numbers already known when it was written are the label audit of 15.2 (catalog fields and cell terrain, no model) and the
frozen v3-live results of earlier reports. test_2018 is read once, for the selected candidate only (15.6).

**15.1 What the brief assumed and what v3-live already is.** The brief's candidate C1 was "C0 with monotone constraints:
non-decreasing in every IMERG rain accumulation / intensity input and in `stat_slope_mean`, `stat_slope_p90`, `stat_slope_max`,
`stat_relief`; others unconstrained". v3-live already trains with those constraints and more: the `monotone` block of
`configs/hazard_v3.yaml` (saved in `model.txt` as `monotone_constraints=0 0 1 1 1 1 0 0 0 0 1 1 1 1 1 1 1 1 1 1 1 -1 0 1 1 1`) is +1 on
`stat_relief`, `stat_slope_mean`, `stat_slope_p90`, `stat_slope_max`, on the eight `irain_acc_*`, on `irain_max1d_7/30`,
`irain_wetdays_30` and the three `irain_acc*_vs_clim`, and -1 on `irain_days_since_10mm`; `stat_elev_mean`, `stat_elev_std`,
`stat_curvature_mean`, the aspect terms, `stat_twi_proxy` and `irain_share1_3` are unconstrained (§14.7 records the same:
`monotone_constraint_on_elevation` 0). v3-live has no `iapi_*` or `inbr_*` inputs. A literal C1 would therefore be C0 with some of its
constraints removed, which is not a physical constraint. The only physical-plausibility constraint v3-live lacks is on elevation, the
input whose fall from 0 to 300 m §14.7 found. **Resolution (a deviation from the brief, decided here before any result):** C1 is C0 with
`stat_elev_mean` additionally constrained non-decreasing ("at the same rain, slope and relief a lower cell is never riskier"). C2 and
C3 are as briefed. A global non-decreasing constraint cannot be limited to the first 300 m; if C1 fails on high-elevation cells that
is a result, not a reason to redefine it.

**15.2 Label audit (Step 1; `v31_labels.py`; `data/processed/hazard/v31_challenger/label_audit.{parquet,json}`).** All positive
cell-days of the development period and of test_2018 (909: 591 train, 233 validation, 85 test_2018; 945 catalog records, `hma` 776 and
`coolr_reports` 169; 40 of the cell-days are below the slope floor and are never fitted or scored) are joined to the raw catalog
records behind them (HMA fields `ls_cat`, `ls_trig`, `loc_accu`, `ls_setting`, `ev_title`, `ev_desc`, `loc_desc`, `comments`; COOLR
reports `landslide_category`, `landslide_trigger`, `location_accuracy`, `landslide_setting` and the same texts) and to the static
terrain of their cell. Low terrain is a mean slope under 5 degrees or a mean elevation under 100 m: 154 cell-days (103 in-domain
development, 11 in-domain 2018, 40 below the slope floor). What the fields hold on the 161 records of the low-terrain cell-days:
category `landslide` 142, `mudslide` 14, `rock_fall` 4, `other` 1; trigger `downpour` 75, `rain` 48, `continuous_rain` 29, `monsoon` 9
(a non-rain trigger can never be a positive, `events/policy.py`); location accuracy exact 9, 1 km 64, 5 km 88 (no positive record is
coarser than the 5.56 km grid cell, so a "coarser than the cell" rule selects nothing); setting `unknown` 101, `above_road` 28,
`urban` 11, `natural_slope` 10, `retaining_wall` 4, `mine` 2, `below_road` 2, `engineered_slope` 1, `deforested_slope` 1, `other`
1; source `coolr_reports` 87, `hma` 74. The low-terrain positives are therefore overwhelmingly ordinary rain-triggered reports of
"landslide": a category or trigger screen cannot separate them. They are concentrated (116 distinct cells for 154 cell-days; the
largest are Guwahati cell 23235435 with 9, Mumbra / Thane cell 21835060 with 8 and Mangalore cell 20575097 with 6), as reports of
slope failures on cut hills inside cities and along railways and roads. The 20 example rows with their texts are in the JSON and
the report.

*The pre-declared implausible-label rule* (catalog fields and cell terrain only; `v31_labels.py` and
`configs/hazard_v31_challenger.yaml`). A positive cell-day is PHYSICALLY IMPLAUSIBLE when its cell is low-terrain AND every catalog
record behind it has at least one flag: `setting` (setting in {`retaining_wall`, `engineered_slope`, `mine`}: an engineered or
excavated slope); `category` (category in {`riverbank_collapse`, `other`, `unknown`, `snow_avalanche`}: not a hillslope landslide);
`geocode` (the text says "closest to predicted location of X (N km)" with N at least 25 km: the position is a name match far from
where the text places the event); `structure` (title, description, place or comments match, as whole words and case blind: retaining
wall, guard wall, compound wall, factory wall, quarry, mining, mine, construction site, embankment). `urban`, `above_road`,
`below_road` and `mudslide` are not flagged: urban and road-cut failures on real hill slopes are the bulk of the low-terrain
reports and the audit has no field that separates them from the rest. Result: 31 cell-days carry flagged records only, of which 16
are on low terrain and so implausible (13 Western Ghats, 3 Himalaya; by reason: structure 6, setting plus structure 4, setting 3,
geocode 2, category 1). Of these 9 are in-domain development positives (7 train, 2 validation: 1.1% of the 789), 2 are in-domain
test_2018 positives and 5 are below the slope floor. The rule thus marks 9 of the 103 low-terrain development positives (8.7%):
most of the low-terrain mass cannot be removed by catalog fields, and C3 is a mild intervention by construction. A cell-day with a
mix of flagged and plain records would count as plausible (none occurs).

**15.3 Candidates (Step 2).** All use the frozen v3-live inputs (`imerg_core`: the 26 `irain` + `stat` columns of
`model_v3_live/cv_results.json`), the selected v3 hyper-parameters (`num_leaves` 7, `min_data_in_leaf` 40, `feature_fraction` 0.5,
`lambda_l2` 0, learning rate 0.05), negative mix `matched_plus_universe`, the seven year-blocked folds, seed 20261001 plus fold, the
same universe-negative draws, the same early stopping and median tree count, the 20-member bootstrap ensemble (seed 7000), the
per-region isotonic calibrator (`min_region_positives` 25) and the same alert-level derivation, by calling the code of `hazard.cv` and
`hazard.train` with the settings of `configs/hazard_v3.yaml` (named as `base_config`, never edited). They differ only in:
* **C0** the v3-live refit. It must reproduce the frozen pooled OOF FA@90 0.195541 and 315 trees (tolerance 5e-4 and the same tree
  count) or the study stops: a harness that does not reproduce v3 proves nothing about its challengers.
* **C1** C0 with `stat_elev_mean` constrained +1 (15.1).
* **C2** C0 without `stat_elev_mean` (25 inputs; `stat_elev_std` stays: the brief names only the mean).
* **C3** C2 trained without the 9 implausible in-domain development positives (15.2), both in the fitting rows and in the held-out
  early-stopping rows of each fold, and in the final refit. The 10:1 matched negatives of the removed positives stay (the samples
  carry no link to them). Evaluation is always on ALL 789 original positives (the layout and the OOF scoring are built from the
  unfiltered rows), so C3 cannot win by deleting hard cases.

**15.4 Metrics (development OOF only).** Pooled OOF raw scores of the 789 positives and the year-weighted universe negatives (their
weights are the cell-days they stand for). Per candidate the alert levels are re-derived exactly as v3's were (`cv.operating_thresholds`
on its own pooled OOF scores: Watch is the highest raw threshold whose bootstrap 5th-percentile OOF recall is at least 90%, Warning the
raw score reaching 75% OOF recall, Emergency 50%; the region risk thresholds are those raw scores passed through the per-region
isotonic calibrators fitted on that candidate's OOF scores). "Warning+ cell-days" are the weighted universe negatives plus the
positives at or above the Warning raw threshold (point level, before any post-model rule or hysteresis). Reported per candidate: the
pooled OOF FA@90 with the bootstrap CI of `configs/hazard_v3.yaml` (2,000 resamples, seed 31337, positives as events, universe rows iid
within year-region strata) and its paired difference to C0 (one shared resample per draw, `challengers.paired_fa_differences`);
recall and false-alarm share at C0's raw Watch, Warning and Emergency thresholds and at the candidate's own; Warning+ weighted
cell-days and their share of all cell-days; **the share of Warning+ cell-days on low-terrain cells** (the plausibility objective) with a
bootstrap CI and its paired difference to C0; the low-rain share of Warning+ cell-days (`irain_acc_3` under 20 mm); the precision proxy
(positives at or above the Warning level per 1,000 Warning+ cell-days) with a bootstrap CI; the cross-fitted ECE over deciles of
calibrated risk (pooled and per-region calibrators), with the reliability deciles in the JSON.

**15.5 PRE-DECLARED SELECTION (development OOF only; Step 3).** The primary metric is the pooled OOF FA@90. A challenger (C1, C2, C3)
is eligible when (i) the lower end of the 95% paired-bootstrap interval of FA@90(challenger) minus FA@90(C0) is at most 0 (it is not
significantly worse), AND (ii) its Warning+ low-terrain share is below C0's. The selected candidate is the eligible one with the lowest
Warning+ low-terrain share (point estimate); ties go to the one with fewer changes (C1, then C2, then C3). If none is eligible the
result is "no challenger adopted", test_2018 is not read, and nothing is replayed. Nothing about the choice is revised after any later
number.

**15.6 Step 4 and the PRE-DECLARED ADOPTION CRITERION.** Only the selected candidate is refitted on all development rows (final
booster, 20-member ensemble, per-region calibrator, card; written to `data/processed/hazard/v31_challenger/models/<candidate>/`, never over
v3) and scored ONCE on test_2018 together with the frozen v3-live (re-scored on the same rows; the frozen model is read, not modified);
`heldout` refuses to run again once its result file exists. The 2018 population is the frozen evaluation's: the 80 in-domain
positive cell-days of the test sample table (all months; the 56 June-September events of §14 are a different, operational
population) and the weighted non-buffer universe negatives. The candidate's thresholds are its own, re-derived in 15.4 from
development OOF; v3 uses the frozen card's. The candidate is recommended for adoption into the live run (a later, separate decision)
only if ALL hold: (a) on 2018 its FA@90 is not worse than frozen v3's by the paired bootstrap (the bootstrap of
`configs/hazard_v3.yaml`, strata = region as in the frozen evaluation): the lower end of the 95% interval of FA@90(candidate) minus
FA@90(v3) is at most 0; (b) its Warning+ low-terrain share on the 2018 universe is below v3's; (c) it has at most 1 fewer of the 80
in-domain 2018 positive cell-days at or above the Warning level (calibrated risk against the region thresholds) than v3. Otherwise it
is not recommended. No threshold or rule changes after 2018.

**15.7 Offline live replay.** The days 2026-10-09..2026-10-24 are rescored from the stored `features_D0.parquet` (the days from
10-09 seed the hysteresis chain as in §14.5; 10-16..10-24 are reported) with the frozen v3-live model and with the selected
candidate, through the same chain: calibrated risk and the ensemble `risk_hi`, the level against the per-region thresholds (the card's
for v3, re-derived in 15.4 for the candidate), the published blind-escalation flag, the §11 7-day 11.50 mm rain cap, and the §11
hysteresis with its hold windows and blind-hold limit (`levels.apply_hysteresis`). The v3 replay is compared with the published
`alerts.parquet` levels first: the agreement is reported, not assumed. Output is `data/processed/alerts/v31_replay/` (never
`data/live`). Reported for 10-24 and across the days: levels per day for v3, the candidate and the published table; the flat-cell
(slope_mean under 5 degrees) and low-elevation (under 100 m) Watch+ alerts; Warning+ with a 3-day IMERG rain under 20 mm; cell
19625150 (Kanyakumari); the cells within 0.25 degrees of Jammu (33.1 N 74.7 E) and Manipur (24.1 N 93.3 E); the south-ghats box
(9.0-10.5 N, 76.8-77.6 E) that the external check found justified; and the D1-D3 forecast leads of 10-24 (point level and rain cap,
no hysteresis, v3 and the candidate scored the same way).

**15.8 Limits stated in advance.** (1) Three challengers are compared on the same development rows, so the best-looking one is
optimistic; the single 2018 look has 80 positive cell-days, so its intervals are wide. (2) Low terrain is a static property of a
0.05-degree cell's DEM statistics, not a label of plausibility: a landslide on a cut slope inside a flat-looking cell is real, and a
lower low-terrain share is a plausibility objective, not accuracy. (3) The Warning+ low-terrain share is read at point level on the OOF
rows without post-model rules. (4) The audit rule is a catalog-field screen; it cannot see the many low-terrain reports that are
ordinary city slope failures. (5) Whether v3.1 is more correct on the live days is judged only against the external check of 20-24
October, not against observed events.

### 15.9 Results (2026-10-24; written after the runs, the sections above are unchanged)
Source: `reports/phase6_v31_challenger.{md,json}`, `data/processed/hazard/v31_challenger/`, `data/processed/alerts/v31_replay/`. The
study runs in about 10 minutes on the laptop (four cross-validations 8-14 s each, the bootstraps about 2.5 minutes, the replay of three
challengers and the frozen model about 3 minutes, plus their refits).

**Reference.** C0 reproduces the frozen v3-live exactly: pooled OOF FA@90 0.195541, 315 trees (difference 0).

**Selection (15.5): no challenger adopted.** FA@90 against C0 (paired 95% interval): C1 0.2327, +0.0371 [+0.0109, +0.0555]; C2 0.2309,
+0.0353 [+0.0111, +0.0576]; C3 0.2341, +0.0386 [+0.0128, +0.0598]. All three are significantly worse than C0, so none is eligible, whatever
their low-terrain share. Their Warning+ low-terrain shares are lower than C0's 6.75% (C1 5.96%, C2 6.30%, C3 5.55%), but each
needs more Warning+ cell-days to reach the same 75% OOF recall (C0 12.2 million, C1 14.9, C2 15.7, C3 16.3), and in the Western Ghats the
share only falls from 30.9% to 21-23%. Per 15.5, test_2018 was not read, no candidate was refitted for it, and the adoption criterion of
15.6 was not evaluated. Dropping the 9 implausible in-domain development positives (C3 against C2) moves FA@90 by +0.0033 (not tested separately; both differ from C0).

**Descriptive follow-up (not a selection input).** In the development OOF rows v3-live alerts at Warning on 2.2% of low-terrain cell-days
and on 10.3% of the other cell-days, and its Warning+ cell-days on low terrain hold 0.092 events per 1,000 cell-days against 0.045
elsewhere (the base event rate is 0.0028 against 0.0062 per 1,000 cell-days). So over all months of 2007-2017 the out-of-fold alerts on low terrain are
rarer and more precise than elsewhere, so this population shows no systematic low-terrain over-warning; whether the 24 October symptom
reflects that day's weather or the season was not tested.

**Exploratory replay (outside the pre-declared protocol; no test_2018).** 15.5 says nothing is replayed when no candidate is selected.
The three non-selected challengers were nevertheless refitted from their saved OOF scores (development rows only) and replayed over the
stored live days, as context for the decision, written to `v31_replay`, and used by no rule. Chain check: the frozen v3-live replay
equals the published level on all 588,672 cell-days of 2026-10-09..24 and the published D+1..D+3 lead levels on all 36,792 cells of
2026-10-24 each. Reproducing the leads needs the widened `risk_hi` in the `uncertain_high` test: `run.lead_scores` reads its
`unwidened` bound after widening the frame in place (`with_uncertain_bound` returns the same frame at the default percentile), so the
stored leads behave as `widened` although `post_rules_v3.json` says `unwidened`; the replay reproduces what was published and the point
is reported, not changed (`run.py` is not touched). On 2026-10-24 (published, C1, C2, C3): cell 19625150 Kanyakumari, whose 3-day IMERG
rain is 82.9 mm, is Emergency, Warning, Warning, Warning; flat-cell (slope under 5 degrees) Watch+ alerts 773, 871, 908, 825;
low-elevation (under 100 m) Watch+ alerts 760, 639, 658, 639; low-terrain Warning+ cells 565, 352, 524, 465; Warning+ cells with a
3-day rain under 20 mm 55, 71, 115, 103; the Jammu box Warning cells 16, 13, 11, 16 (3-day rain of the Warning cells 10.5-19.2 mm in every model); the Manipur box Warning cells 4, 4, 8, 5 (17.9-26.2 mm); the south-ghats box (401 cells) Warning plus Emergency 381, 378, 381, 391.
So removing or constraining elevation lowers the Kanyakumari cell and some low-elevation cells, raises other flat-cell and low-rain
alerts, and leaves the Jammu and Manipur Warnings in place (their rain is 10.5-26.2 mm in every model): the Himalayan Warnings do not
depend on the elevation input, and the three challengers do not improve the live-day symptoms taken together.
