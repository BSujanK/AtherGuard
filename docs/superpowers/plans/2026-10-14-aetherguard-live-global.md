# AetherGuard Stage A (live-ready best model + daily live run + AWS package) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retrain the hazard model on data that arrives every day (NASA IMERG rain + terrain), make it the most accurate model the data allows, and run it every morning on the laptop to predict today and the next three days.

**Architecture:** New IMERG (and GFS, IMD real-time) ingest feeds a new feature family stored as extra feature tables that the existing hazard training code already knows how to load (`extra_groups` in the config). A separate config (`configs/hazard_v3.yaml`) trains "v3-live" into its own model directory with the unchanged protocol v2 (year-blocked CV), plus per-region calibration. A new `aetherguard.live` package fetches, featurises, scores, alerts and publishes one day at a time; Windows Task Scheduler runs it at 09:30 IST.

**Tech Stack:** Python 3.13 project venv, numpy, pandas, LightGBM, scikit-learn, xarray + netCDF4/h5py (IMERG), GRIB2 or OPeNDAP reader for GFS (chosen in Task 1), imdlib (IMD real-time), FastAPI/Streamlit (existing).

**Spec:** `docs/superpowers/specs/2026-10-14-aetherguard-live-global-design.md`

## Global Constraints

- NO GIT in this project: never run git; there are no commit steps. Review is by reading files and running tests.
- Python: `.venv/Scripts/python` (Git Bash on Windows). New dependencies only when a task says so; add them to `pyproject.toml` and regenerate `requirements-lock.txt` (header style as existing).
- Test-first; offline hermetic tests (synthetic inputs in tmp_path); real downloads only in `@pytest.mark.realdata` / `@pytest.mark.live` tests; new tests pass with `-W error`; full suite stays green (currently 1,323 passed).
- Missing data is explicit (NaN, never 0) and counted. All randomness seeded.
- Frozen v2 artifacts are never modified: `data/processed/hazard/model/` (v2), `data/processed/splits/`, `data/processed/features/samples/`, `data/processed/features/*_features.parquet`.
- Day basis: features use the IMD day D (08:30 IST D−1 to 08:30 IST D). UTC-day products use `0.875 × UTC(D−1) + 0.125 × UTC(D)` (existing `aetherguard.ingest.align.align_utc_to_imd_day`).
- Domain bbox lat 8–36 °N, lon 72–98 °E (`configs/ingest.yaml`). Cells are 0.05° (`aetherguard.grid`).
- Credentials: Earthdata via the user's `~/_netrc`; never print, log or store credential values.
- AWS: no resource is created or launched by any task. Documents only.
- Every report number is read from a result file; strict JSON (NaN → null), relative paths only.

## Review Focus

1. A source is late or missing on the live morning (IMERG Late not yet published, GFS cycle incomplete, IMD real-time 404) → the run still publishes, with data confidence lowered and the failure named in the bulletin; never a silent Normal. (Task 9 tests every source-failure combination.)
2. The live run is started twice for the same date, or for a past date → idempotent skip unless `--force`; a past date uses only inputs that would have existed that morning in backtest mode. (Task 9.)
3. IMERG grid orientation / lon-major arrays and the 0.1° pixel ↔ 0.05° cell mapping → a cell's value equals the hand-read pixel at known coordinates (Wayanad, Kathmandu). (Task 2.)
4. Leakage across the 90-day look-back and the IMERG climatology → climatology uses 2007–2015 only; perturbing any rain after day D leaves features at D unchanged. (Task 3.)
5. Forecast days mixing observed and forecast rain at the IMD-day boundary → D+1 accumulation = observed through D + forecast for (03:00 UTC D, 03:00 UTC D+1]; tested on a synthetic hourly series. (Task 7.)

---

### Task 1: Live data-source spike (real network, decides formats)

**Files:**
- Create: `src/aetherguard/live/__init__.py` (empty docstring module)
- Create: `src/aetherguard/live/probe.py` (CLI `python -m aetherguard.live.probe`)
- Create: `reports/phase6_live_sources_probe.md` and `.json` (written by the CLI)
- Test: `tests/test_live_probe.py` (offline: report assembly from fake probe results)

**Interfaces:**
- Produces: a JSON report with, per source: `reachable`, `url_pattern`, `auth`, `format`, `variables`, `bytes_per_day_domain`, `seconds_per_day`, `latency_hours` (issued minus valid end), `history_start`, `decision` (`use` / `fallback` / `drop`) and `notes`. Later tasks read their chosen access path from this report (copied into `configs/live.yaml` in Task 2).

- [ ] **Step 1:** Write `tests/test_live_probe.py`: build the report from a list of fake probe dicts; assert strict JSON, decision values limited to `use|fallback|drop`, and that a probe raising an exception becomes `reachable: false` with the error class name (never the message if it may contain a URL with credentials).
- [ ] **Step 2:** Run it, expect FAIL (module missing). Implement `probe.py` report assembly; run, expect PASS.
- [ ] **Step 3:** Implement the real probes (each time-boxed, all using `aetherguard.http` and the `_netrc`):
  - IMERG V07 Late daily `GPM_3IMERGDL` and Early daily `GPM_3IMERGDE` for 2018-08-15 and for the most recent available day: GES DISC OPeNDAP spatial subset to the domain bbox (try `.nc4` subset via OPeNDAP constraint expression; fall back to full-file download + crop and record size). Record the array dims order and lat/lon orientation, the variable name holding mm/day, the fill value.
  - IMERG half-hourly Late (`GPM_3IMERGHHL`) for one day: time per day and bytes per day subset; extrapolate to 2006-10-01..2018-12-31 and to the monsoon months only; decision on the intensity group (`use` only if the monsoon-only estimate is under 12 h download and 20 GB).
  - GFS 0.25°: (a) NOMADS grib filter for the latest cycle, APCP 0–96 h, domain subset; (b) NOMADS OPeNDAP for the same; (c) AWS Open Data `noaa-gfs-bdp-pds` historical file for 2023-07-15 00Z f024 with `.idx` byte-range fetch of APCP only. Test whether `eccodes`/`cfgrib` installs and decodes on this machine (`pip install eccodes cfgrib` in a throwaway check; do not add to the project unless the decision is `use`). Choose the live path and the archive path.
  - IMD real-time: `imdlib.get_real_data('rain', yesterday, yesterday)` and read; record latency and grid.
  - GHCN-Daily recent: NCEI access-data-service (`https://www.ncei.noaa.gov/access/services/data/v1?dataset=daily-summaries&stations=...&dataTypes=PRCP,...&startDate=...&endDate=...&format=json`) for 10 of the 140 stations and the last 120 days; record latency and whether quality flags are returned.
- [ ] **Step 4:** Run `.venv/Scripts/python -m aetherguard.live.probe`; check the report; run `pytest tests/test_live_probe.py -W error`.

### Task 2: IMERG ingest and daily store

**Files:**
- Create: `configs/live.yaml` (sources chosen in Task 1, bbox, history start 2006-10-01, store paths, schedule 09:30 IST, GFS cycle rules)
- Create: `src/aetherguard/ingest/imerg.py`, CLI `src/aetherguard/ingest/imerg_build.py`
- Test: `tests/test_ingest_imerg.py`
- Data: `data/raw/imerg/{late,early}/...`, `data/processed/rain/imerg_late_<year>.npy`, `imerg_index.json`; Early store for backtest windows `imerg_early_<year>.npy` (2018-06-01..2018-09-30 and 2023-05-01..2023-08-15, 2024-06-01..2024-08-15)

**Interfaces:**
- Consumes: Task 1 report (format, URL pattern), `aetherguard.http.download`, `aetherguard.manifest.Manifest`.
- Produces:
  - `imerg_pixel(cell_id) -> tuple[int, int]` (row, col into the domain grid; 0.1° pixels; row 0 = southern edge).
  - `class ImergStore(processed_dir, run: str = "late")` with `.dates() -> list[date]`, `.has_date(d) -> bool`, `.gather(rows, cols, first_day: date, length: int) -> np.ndarray[float32] (n, length)` (NaN for missing days), `.update(days: list[date]) -> dict` (download + crop + append, idempotent).
  - CLI: `python -m aetherguard.ingest.imerg_build [--run late|early] [--start] [--end] [--workers N]`.

- [ ] **Step 1:** Tests first (synthetic netCDF written with xarray in tmp_path in the exact layout Task 1 recorded): orientation (a value planted at 11.47 N 76.13 E is read back at `imerg_pixel(latlon_to_cell(11.47, 76.13))`), fill value → NaN, missing day → NaN row and listed in the index, idempotent rerun (no re-download when the manifest is current), year-boundary `gather`, `update` appends today without rewriting older years.
- [ ] **Step 2:** Run tests, expect FAIL; implement; run, expect PASS (`-W error`).
- [ ] **Step 3:** Real build: Late run 2006-10-01..yesterday; Early run for the backtest windows. Real-data test (`realdata`): Wayanad cell 2024-07-29/30 values are finite and positive; Kathmandu cell finite (IMERG covers Nepal); report days present / missing per year and total bytes.
- [ ] **Step 4:** Add any reader dependency chosen in Task 1 (`netCDF4` or `h5py`) to `pyproject.toml` and regenerate the lock; full suite green.

### Task 3: v3-live feature tables

**Files:**
- Create: `src/aetherguard/features/imerg_features.py` (pure functions), `src/aetherguard/features/imerg_build.py` (CLI)
- Test: `tests/test_features_imerg.py`
- Data: `data/processed/features/imerg/<name>_{irain,iapi,inbr}.parquet` for the 9 sample files, each with `<group>_columns.json` and `<group>_manifest.json` in the format `hazard.data.load_table` verifies (same `cell_id`, `date` keys and row order as `<name>_features.parquet`)

**Interfaces:**
- Consumes: `ImergStore`, `imerg_pixel`, `aetherguard.ingest.align.align_utc_to_imd_day`, `aetherguard.features.compute.trailing_window_sums` (reuse), terrain table.
- Produces columns (float32):
  - `irain_acc_{1,3,5,7,14,30,60,90}`, `irain_max1d_{7,30}`, `irain_wetdays_30`, `irain_days_since_10mm`, `irain_share1_3`, `irain_acc{3,7,30}_vs_clim`
  - `iapi_{85,90,95}`
  - `inbr_max_acc_{1,3}`, `inbr_mean_acc_{1,3}` (3×3 IMERG pixels around the cell's pixel, edges use available pixels only)
  - `build_imerg_features(frame: pd.DataFrame, store: ImergStore, clim: ClimTable) -> pd.DataFrame` (row order = `frame`)

Key formulas (implement exactly):
```python
# IMD-day series from UTC days: x_imd[d] = 0.875 * x_utc[d-1] + 0.125 * x_utc[d]   (NaN if either is NaN)
# Antecedent precipitation index on the IMD-day series, spin-up of 120 days before the first needed day:
def api(series: np.ndarray, k: float) -> np.ndarray:      # series shape (n, T), NaN treated as missing -> carry decay only
    out = np.empty_like(series); acc = np.zeros(series.shape[0])
    for t in range(series.shape[1]):
        p = np.nan_to_num(series[:, t], nan=0.0); acc = k * acc + p; out[:, t] = acc
    return out
# Accumulations: NaN if any day in the window is missing (same rule as the v2 feature store).
# Climatology: mean of the N-day trailing IMD-day accumulation per (pixel, calendar month) over 2007-01-01..2015-12-31 only.
```

- [ ] **Step 1:** Tests first: D5 conversion against hand values; accumulations and the NaN rule; API recursion against a hand-computed 5-day example; neighbourhood max/mean at an interior pixel and at a domain edge; climatology uses only 2007–2015 (perturb 2016+ values, climatology unchanged); causality (perturb every value after D, features at D unchanged); key/order identity with the base features file; manifest/columns files accepted by `hazard.data.load_table` (round-trip test with a tiny fake features dir).
- [ ] **Step 2:** Run, expect FAIL; implement; run, expect PASS (`-W error`).
- [ ] **Step 3:** Real build for all 9 sample files; report NaN share per column per file and runtime; spot values for the Wayanad cell on 2024-07-30 and a Kerala 2018-08-15 positive.

### Task 4: v3 training config, per-region calibration, train

**Files:**
- Create: `configs/hazard_v3.yaml` (copy of `configs/hazard.yaml` with the changes below)
- Modify: `src/aetherguard/hazard/train.py` (add `--config PATH`), `src/aetherguard/hazard/model.py` (`hazard_config(path=None)`), `src/aetherguard/hazard/calibration.py` and `src/aetherguard/hazard/cv.py` (optional per-region calibrator), `src/aetherguard/hazard/model.py` (`HazardModel.score` uses the region calibrator when present)
- Test: `tests/test_hazard_v3_config.py`, extend `tests/test_hazard_calibration.py`
- Data: `data/processed/hazard/model_v3_live/` (never touches v2)

**Interfaces:**
- `configs/hazard_v3.yaml` changes: `extra_groups` adds `irain`, `iapi`, `inbr` (and `iint` if Task 1 said `use`), all `subdir: imerg`, each with its own `suffix`, `columns_file`, `manifest_file`; `monotone.increasing` adds `irain_acc_*`, `irain_max1d_*`, `irain_acc*_vs_clim`, `irain_wetdays_30`, `iapi_*`, `inbr_*`; `monotone.decreasing` adds `irain_days_since_10mm`; `group_stages`: stage 1 candidates `{name: imerg_core, groups: [irain, stat]}`, `{name: imerg_core_noelev, groups: [irain, stat], exclude: [stat_elev_mean, stat_elev_std]}`; stage 2 `{name: "+iapi", add_groups: [iapi]}`, `{name: "+inbr", add_groups: [inbr]}`, `{name: "+iapi+inbr", add_groups: [iapi, inbr]}`; `calibration.per_region: true`; `model_dir: model_v3_live`.
- `MonotoneCalibrator` unchanged; new `RegionCalibrator(by_region: dict[str, MonotoneCalibrator], pooled: MonotoneCalibrator, min_positives: int = 25)` with `.predict(raw, region) -> np.ndarray`; regions with fewer than `min_positives` OOF positives use the pooled calibrator; saved as `calibrator_regions.json`.
- `HazardModel.score(frame)` uses the region calibrator when the card says `per_region` and `frame` has a `region` column; otherwise unchanged (v2 behaviour identical — test this).

- [ ] **Step 1:** Tests first: v2 config still trains/scores exactly as before (a tiny synthetic fit with and without `per_region`; v2 path byte-identical predictions); `RegionCalibrator` monotone per region, fallback when positives < 25, JSON round trip; `--config` loads the v3 file and writes to `model_v3_live`; leakage guard still refuses test/case rows.
- [ ] **Step 2:** Run, expect FAIL; implement; run, expect PASS (`-W error`); full suite green.
- [ ] **Step 3:** Real run: `.venv/Scripts/python -m aetherguard.hazard.train --config configs/hazard_v3.yaml`. Stage-1 report only (no test data): `reports/phase6_v3_cv_report.md/.json` with grid, group selection table, selected config, OOF thresholds, per-region cross-fitted calibration, and the paired OOF comparison against frozen v2 (both models' OOF scores on the identical development rows; v2's OOF is in `data/processed/hazard/model/cv_results.json` — recompute if the per-row scores are not stored).

### Task 5: Challenger experiments (only adopted if they win by more than one SE)

**Files:**
- Create: `src/aetherguard/hazard/challengers.py`, CLI `python -m aetherguard.hazard.challengers --config configs/hazard_v3.yaml`
- Test: `tests/test_hazard_challengers.py`
- Report: `reports/phase6_challengers.md/.json`

**Interfaces:**
- CatBoost (add `catboost` dependency) with the v3 selected columns, monotone constraints, a 4-point grid (depth {4, 6} × l2_leaf_reg {3, 10}), same folds, same metric; and the half-hourly intensity group `iint` if Task 1 said `use`.
- Rule: a challenger replaces the selected v3 configuration only if its pooled OOF FA@90 is lower by more than its bootstrap SE; adoption for CatBoost requires a `model_type` switch in `hazard.model` (fit/predict/save/load) covered by the same round-trip tests; otherwise the report records the result and nothing changes.

- [ ] **Step 1:** Tests first: CatBoost fit/predict on a tiny synthetic frame honours monotone constraints (partial-dependence check), deterministic with seed, the adoption rule on hand-made OOF numbers.
- [ ] **Step 2:** Run, expect FAIL; implement; run, expect PASS (`-W error`).
- [ ] **Step 3:** Real run; if adopted, retrain v3 via Task 4's CLI with the switch and regenerate the Stage-1 report.

### Task 6: v3 freeze and evaluation (single test look, backtests)

**Files:**
- Modify: `src/aetherguard/hazard/freeze.py`, `src/aetherguard/hazard/evaluate_report.py` (accept `--config` / `--model`; v2 behaviour unchanged)
- Create: `src/aetherguard/live/backtest.py` (operational backtest)
- Test: `tests/test_live_backtest.py`, extend `tests/test_hazard_evaluate_report.py`
- Report: `reports/phase6_live_model_report.md/.json`

**Interfaces:**
- `operational_features(day: date, cells, stores) -> pd.DataFrame`: features for day D using Late-run days up to UTC D−1 and the Early-run value for UTC D (the morning of D at 09:30 IST), never anything later.
- `run_backtest(start, end, model_dir) -> dict`: daily scoring over the window for all candidate cells; detection and lead time of the 2018 test positives that fall in the window, alert share per day, Kerala 2018 and Wayanad 2024 replays, 2023 window detection.

- [ ] **Step 1:** Tests first: the operational feature builder never reads a value with valid time after 03:00 UTC D (planted-future-value test); backtest metrics on a toy store with a known answer.
- [ ] **Step 2:** Run, expect FAIL; implement; run, expect PASS (`-W error`).
- [ ] **Step 3:** Freeze v3 (`FROZEN.json` in `model_v3_live`), then run the single test evaluation (`--config configs/hazard_v3.yaml`) and the backtests. The report states: OOF v3 vs v2 (paired), the "best" verdict per the spec's acceptance rule, test_2018 as a disclosed second look, backtest results, cases, and limits.

### Task 7: GFS forecast ingest (live + archive)

**Files:**
- Create: `src/aetherguard/ingest/gfs.py`, CLI `src/aetherguard/ingest/gfs_build.py`
- Test: `tests/test_ingest_gfs.py`
- Data: `data/raw/gfs/...`, `data/processed/rain/gfs_imdday_<issue-date>.npz` (forecast IMD-day totals for D+1..D+3 on the IMERG 0.1° domain grid, bilinear from 0.25°)

**Interfaces:**
- `latest_complete_cycle(now_utc) -> datetime` (a cycle counts as complete when its f096 APCP is published; otherwise the previous cycle).
- `forecast_imd_days(cycle: datetime, issue_day: date) -> np.ndarray (3, rows, cols)`: IMD-day totals for D+1, D+2, D+3 where D = issue_day, IMD day D+k = (03:00 UTC D+k−1, 03:00 UTC D+k]; built from cumulative APCP differences.
- `fetch_archive(days: list[date], cycle_hour=0) -> dict` (2021-2024 June–September, path chosen in Task 1).

- [ ] **Step 1:** Tests first: IMD-day accumulation from a synthetic hourly cumulative APCP series (window boundaries exactly at 03:00 UTC), cycle selection rules at boundary times, regrid 0.25° → 0.1° preserves a uniform field and the domain-mean total within 1%, missing forecast hour → NaN day and a recorded gap.
- [ ] **Step 2:** Run, expect FAIL; implement; run, expect PASS (`-W error`).
- [ ] **Step 3:** Real: latest cycle for today; archive for 2021–2024 June–September 00Z runs.

### Task 8: Forecast-day skill and interval widening

**Files:**
- Create: `src/aetherguard/live/forecast_skill.py`, CLI
- Test: `tests/test_live_forecast_skill.py`
- Report: `reports/phase6_forecast_skill.md/.json`

**Interfaces:**
- Rain skill: GFS IMD-day totals vs IMERG Late for lead 1, 2, 3 (bias, MAE, quantiles of the ratio per rain bin), June–September 2021–2024.
- Hazard skill: v3 risk from forecast-driven features (observed through D, forecast after) vs risk from observed features, for days with labels (2023 window inventory, sparse 2019–2024 records): detection at Watch, and agreement of levels.
- Produces `forecast_widening.json`: per lead day, multiplicative factors applied to `risk_lo`/`risk_hi` (10th/90th percentile of the observed/forecast risk ratio), consumed by Task 9.

- [ ] **Step 1:** Tests first: widening factors from a synthetic ratio distribution; the forecast feature builder uses observed rain for days ≤ D and forecast for > D only.
- [ ] **Step 2:** Run, expect FAIL; implement; run, expect PASS (`-W error`).
- [ ] **Step 3:** Real run and report; state plainly how thin the labels are.

### Task 9: Daily live runner

**Files:**
- Create: `src/aetherguard/live/run.py` (CLI `python -m aetherguard.live run --date today|YYYY-MM-DD [--force] [--backtest]`), `src/aetherguard/live/__main__.py`, `src/aetherguard/live/sources.py` (fetch + freshness), `src/aetherguard/live/bulletin.py`, `src/aetherguard/live/adapter.py` (maps live sources onto the alert engine's expected columns)
- Create: `scripts/install_daily_task.ps1` (registers a Windows scheduled task "AetherGuard daily" at 09:30 local time running the CLI with the project venv; `-Remove` switch unregisters)
- Test: `tests/test_live_run.py`, `tests/test_live_sources.py`, `tests/test_live_bulletin.py`
- Data: `data/live/<date>/{raw/, freshness.json, features_D0.parquet, risk_D{0..3}.parquet, alerts.parquet, run.json}`, `reports/live/<date>.md`, replay-store set `live`

**Interfaces:**
- `fetch_all(day, cfg) -> dict[str, SourceStatus]` where `SourceStatus(name, ok: bool, valid_through: datetime|None, issued: datetime|None, latency_h: float|None, error: str|None)`.
- `adapter.alert_frame(features, imd_rt, imerg) -> pd.DataFrame`: supplies the columns the confidence logic reads (`src_imd_acc_*` from IMD real-time, `src_chi_acc_*` from IMERG as the satellite source, `src_dis_*` recomputed, `integ_*` from the integrity engine run on recent GHCN data, `rain_source`).
- `run_day(day, cfg, force=False, backtest=False) -> dict` writes everything above; returns the run summary.
- Integrity on live gauges: `aetherguard.integrity.engine.IntegrityEngine.load(...).predict(...)` on the last 120 days of GHCN records fetched via the Task 1 path.

- [ ] **Step 1:** Tests first (all offline, fake sources): full happy path writes all files and a replay-store `live` set the API can read; idempotent rerun skips; `--force` recomputes; each single source failure and the all-fail case produce a bulletin naming the failed sources and lower confidence where the model input was missing (IMERG missing ⇒ Insufficient and a blind-rule check; IMD real-time missing ⇒ Degraded only); hysteresis uses the previous day's live state; backtest mode refuses inputs issued after 09:30 IST of the date.
- [ ] **Step 2:** Run, expect FAIL; implement; run, expect PASS (`-W error`); full suite green.
- [ ] **Step 3:** Real: run for today, then backfill the last 7 days; check the bulletin and `/risk?set=live`; install the scheduled task with `scripts/install_daily_task.ps1` and show it with `Get-ScheduledTask`.

### Task 10: Dashboard, API, reports and README integration

**Files:**
- Modify: `src/aetherguard/serve/dashboard.py` + `figures.py` (Live page: today's map, D+1..D+3 tabs, source freshness, bulletin), `src/aetherguard/serve/api.py` (`/live/latest`, `/live/{date}`), `src/aetherguard/finalreport/build.py` (phase 6 sections), `configs/pipeline.yaml` (stages imerg, imerg_features, hazard_v3_train, hazard_v3_freeze, hazard_v3_report, gfs, forecast_skill), `README.md`
- Test: extend `tests/test_serve_api.py`, `tests/test_serve_dashboard.py`, `tests/test_finalreport.py`, `tests/test_pipeline.py`

- [ ] **Step 1:** Tests first: API endpoints on a fixture live store; dashboard Live page figure builders; final report renders phase 6 numbers from the new JSON files (pending when absent); pipeline config lists the new stages in order and every module exists.
- [ ] **Step 2:** Run, expect FAIL; implement; run, expect PASS (`-W error`); full suite green; regenerate `reports/FINAL_REPORT.md`.

### Task 11: AWS application package (controller-written documents)

**Files:**
- Create: `docs/aws/gpu-quota-request.md`, `docs/aws/credit-usage-plan.md`, `docs/aws/gpu-requirements.md`

- [ ] **Step 1:** Write the three documents per spec section 6, using only real project numbers (from `reports/FINAL_REPORT.md` and the phase 6 reports), the $140 credit as the budget ceiling, approximate prices clearly marked as to be verified at launch time, guardrails (budget alarms at $100 and $130, auto-stop, teardown), and no instruction that creates resources.

### Task 12: Final review and report

- [ ] **Step 1:** Fresh whole-change review (reviewer subagent) against the spec; fix findings in one round.
- [ ] **Step 2:** Full suite, `pipeline status`, regenerate the final report; update the technical PDF only if the user asks.
