# W3 Rain Intensity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build half-hourly IMERG rain-intensity inputs, train one challenger (v4-int = v3 + intensity), and test it under the pre-declared criterion.

**Architecture:** A resumable half-hourly store (`ingest/imerg_hh.py`) reduces each IMD day to max-1/3/6-hour and wet-duration fields; a feature builder adds six `iint_*` features; the challenger reuses the v3.1 challenger machinery (`hazard/v31_challenger.py`, `cv.run_cv`); evaluation reuses `verify/heldout.py`.

**Tech Stack:** Python 3.13, numpy, xarray/netCDF4, requests, LightGBM, pytest.

**Spec:** `docs/superpowers/specs/2026-11-06-aetherguard-w3-rain-intensity.md`

## Global Constraints

- OPeNDAP DAP4 domain subset, index box as `ingest/imerg.py` (260 lon x 280 lat); at most 4 parallel connections; retries per request; credentials from `~/_netrc` only, never printed or stored.
- IMD day = 03:00 UTC D-1 to 03:00 UTC D; derived fields float32; raw half-hourly subsets deleted after each day is reduced.
- Resumable: a day is written atomically once complete; a re-run skips finished days.
- Frozen v3 artifacts never modified; the challenger writes to `data/processed/hazard/v4_int/`.
- Test-first, hermetic (no network in the default suite); `-W error`.

## Review Focus

1. A half-hour missing from the archive leaves that day's maxima NaN (not 0), unless the gap is filled by nothing else: never treat missing as dry.
2. Rolling windows never cross the IMD-day boundary.
3. The live (HHE, truncated) features and the training (HHL, full) features are computed by the same function with a different window end.
4. The challenger differs from v3 only by the six features.
5. The held-out look happens once.

---

### Task 1: Half-hourly store and daily reduction

**Files:** Create `src/aetherguard/ingest/imerg_hh.py`, `tests/test_ingest_imerg_hh.py`.

**Interfaces:** `def granules(run: str, day: date) -> list[str]` (CMR, run "late"|"early", the 48 half-hours of the IMD day); `def reduce_day(fields: np.ndarray) -> dict[str, np.ndarray]` (48 x 280 x 260 mm/h -> max1h, max3h, max6h, wet_hours, n_halfhours); `def build(run, start, end, root, workers=4) -> None` (resumable; writes `<root>/<run>/<yyyy>/<yyyymmdd>.npz`); CLI `python -m aetherguard.ingest.imerg_hh --run late --start ... --end ...`.

- [ ] Step 1: failing tests (synthetic fields): rolling max 1/3/6 h are sums of 2/6/12 consecutive half-hours (mm/h x 0.5) within the day; a NaN half-hour makes the affected maxima NaN; wet_hours counts >= 0.1 mm/h; a finished day is skipped on re-run; the subset URL built from a CMR link carries the index box.
- [ ] Steps 2-4: run (fail), implement (reuse the auth/session and retry pattern of `ingest/imerg.py` and `verify/lhasa.py`), pass.
- [ ] Step 5: start the real build in the background: Late, June-September 2007-2017 then June-December 2018-2025 (log `logs/imerg_hh.log`); commit `ingest: half-hourly IMERG store reduced to daily intensity fields`.

### Task 2: Intensity features and the train-serve gap

**Files:** Create `src/aetherguard/features/imerg_intensity.py`, `tests/test_features_imerg_intensity.py`.

- [ ] Steps: TDD the six features per cell from the daily fields (cell-to-pixel mapping as the daily IMERG features); the truncated-window variant (last 4 half-hours missing) via the same function; measure the 2024 gap (HHE truncated vs HHL full, median relative error of max3h over wet cell-days) and apply the spec's 20% rule; write the feature table for the development and held-out cell-days into the feature store; commit.

### Task 3: Challenger v4-int, development CV, single held-out look

**Files:** Create `src/aetherguard/hazard/v4_int.py`, `configs/hazard_v4_int.yaml`, tests; `reports/phase7_rain_intensity.{md,json}`.

- [ ] Steps: TDD the config (v3 + six non-decreasing features, nothing else); run the CV with v3's folds/seeds and reproduce v3's FA@90 as the reference; the paired-bootstrap FA@90 comparison; if it passes, score the held-out seasons with v4-int, burden-match to v3 per season, independent-slide detection tolerant and cell-exact; decide per spec section 3; one-shot guard (result file in data/ AND the committed report); commit.

Wiring an adopted v4-int into the live run is a separate plan.
