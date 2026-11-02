# Ground-Truth Expansion and Benchmarks (W1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Grow the held-out test set from 56 events (2018) towards the roadmap's 150-event gate with dated, located,
source-cited Indian landslide events from 2019 to 2025, score those seasons with the frozen v3, and add the NASA LHASA v2
and an IMERG-fitted rainfall-threshold benchmark, so gates G1-G4 can be tested.

**Architecture:** Reported events enter as CSVs in the W0 ledger format (`verify/ledger.py` docstring). A geocoder turns
place text into coordinates with the GeoNames table the dashboard already uses. New held-out seasons are scored with the
existing backtest machinery (`live/backtest.py`) into panels shaped like the 2018 one, and `verify/report.py` gains the
extra seasons and benchmark models. Nothing in the live run changes.

**Tech Stack:** Python 3.13, numpy, pandas, xarray/netCDF4 (LHASA), requests via `aetherguard.http`, pytest.

**Spec:** `docs/superpowers/specs/2026-11-02-aetherguard-accuracy-roadmap.md` (§2 gates, §3 protocol v3, §4 W1).

## Global Constraints

- Reported-event CSV columns: `date` (YYYY-MM-DD, IST), `latitude`, `longitude`, `location_text`, `source_url`, `accuracy_km`; one row per landslide location and day; files stay under `data/raw/manual/reported_events/` (git-ignored).
- Only events inside the two region boxes of `configs/domain.yaml` count; only day-exact dates count for the test set.
- An event is admitted only with a source URL a reader can open; licence or terms of every source are recorded in `manifests/data_manifest.jsonl`; sources that restrict redistribution are used locally and never committed.
- The frozen v3 model and the §11 rules score the new seasons; nothing is tuned on them. They are a held-out set read once per adopted change (protocol v3).
- Earthdata credentials come from `~/_netrc`; never print or store credential values or authenticated URLs.
- No account registration on the user's behalf (GSI Bhukosh, GSMaP): those are listed as user actions.

## Review Focus

1. A place name that exists in two states (common in India) must be resolved within the state the source names, or rejected; never the first match.
2. The same landslide reported by several outlets on the same or next day is one event, not several.
3. A news date is often the report date, not the event date; a row is day-exact only when the text states the event day ("on Tuesday night", "on 14 July").
4. LHASA probabilities are on a ~1 km grid; a cell takes the maximum over its pixels, and a cell with no LHASA pixel is unscored for that model, never 0.
5. A new season's panel must hold exactly the 36,792 candidate cells in the 2018 panel's order, or the report raises.

---

### Task 1: Place-name geocoder

**Files:** Create `src/aetherguard/verify/geocode.py`; Test `tests/test_verify_geocode.py`.

**Interfaces:** Produces `def geocode(place: str, district: str | None, state: str, places: pd.DataFrame) -> tuple[float, float, float] | None`: (lat, lon, accuracy_km) from `data/processed/places` GeoNames extract (populated places with admin1 / admin2 names). Matching is case-insensitive on ASCII-folded names, restricted to the named state (and district when given). One match gives accuracy 5 km; several matches within one district give the district centroid with accuracy equal to the distance to the farthest match; matches in different districts give `None`. `def load_places() -> pd.DataFrame`.

- [ ] Step 1: failing tests: a unique village name returns its coordinates and 5.0; a name present in two districts of one state without a district returns None; with the district it returns that one; a state mismatch returns None.
- [ ] Step 2: run `.venv/Scripts/python -m pytest tests/test_verify_geocode.py -q`; expected FAIL (ImportError).
- [ ] Step 3: implement.
- [ ] Step 4: run again and with `-W error`; expected all pass.
- [ ] Step 5: commit `verify: GeoNames geocoder for reported landslide places`.

### Task 2: Reported-event inventory 2019-2025 (research + validation)

**Files:** Create `src/aetherguard/verify/inventory.py` (`def build_inventory(raw_dir: Path, places) -> pd.DataFrame` and CLI `python -m aetherguard.verify inventory`), `tests/test_verify_inventory.py`; data under `data/raw/manual/reported_events/` (local only).

**Interfaces:** Consumes `geocode` (Task 1) and `ledger.load_reported` (W0 Task 5). Research input files `data/raw/manual/reported_events/raw/<year>.csv` with columns `event_date, date_basis (stated|report), place, district, state, source_url, outlet, description`. `build_inventory` geocodes, keeps `date_basis == "stated"`, de-duplicates rows of the same `(date, cell_id)` and of the same place within 1 day across outlets, and writes `<year>.csv` in the ledger format plus `inventory_report.json` (counts per year and region, rejected rows with reasons).

- [ ] Step 1: failing tests for de-duplication across outlets, rejection of `date_basis == "report"`, rejection of an ungeocodable place with its reason, and output that `ledger.load_reported` accepts.
- [ ] Step 2: run, expected FAIL. Step 3: implement. Step 4: run, pass (also `-W error`). Step 5: commit `verify: reported-event inventory builder`.
- [ ] Step 6 (research, one research agent per year 2019-2025, run in parallel): fill `raw/<year>.csv` from news and official sources for the monsoon (June-October) and, for the Western Ghats, the north-east monsoon (October-December). Every row carries a URL the agent opened. Then run `python -m aetherguard.verify inventory`; expected: exit 0 and a per-year count. Spot-check 10% of rows against their URLs (a second agent); the error rate is reported in `inventory_report.json`.

### Task 3: Score the held-out seasons 2019-2025

**Files:** Modify `src/aetherguard/live/backtest.py` (a set `season_<year>` for 2019-2025, June-October; Western Ghats rows also October-December); Create `src/aetherguard/verify/seasons.py` (`def score_season(year: int) -> Path` writing `data/processed/alerts/heldout_seasons/season_<year>.npz` with the same fields as `season_2018_operational.npz`); Test `tests/test_verify_seasons.py`.

- [ ] Step 1: failing test: on a synthetic store, `score_season` writes a panel whose cell order equals the candidate set and whose v3 levels equal those of `hardening_dev.season_levels` on it.
- [ ] Step 2-4: implement reusing `backtest.run_set` with the training-style features (the IMERG Late archive 2006-2026 is stored under `data/raw/imerg/late`), pass.
- [ ] Step 5: run all seven seasons in the background (log under `logs/`); expected: seven panel files, each with 36,792 cells.
- [ ] Step 6: commit `verify: held-out season panels 2019-2025`.

### Task 4: NASA LHASA v2 benchmark

**Files:** Create `src/aetherguard/verify/lhasa.py` (`def fetch_lhasa(day: date, cache: Path) -> Path`, `def cell_max(path: Path, cell_ids: np.ndarray) -> np.ndarray`), `tests/test_verify_lhasa.py`.

- [ ] Step 1: find the GES DISC LHASA v2 daily nowcast path for 2018-06-01 (archive 2015-04-03 to 2021-02-10) and record it with its terms in the data manifest; if the archive is gone, record that and skip Tasks 4's real run (the report then says "LHASA not available").
- [ ] Step 2: failing tests: `cell_max` on a synthetic 0.01-degree grid returns the maximum of the pixels inside each 0.05-degree cell and NaN for a cell with no pixel.
- [ ] Step 3-4: implement, pass.
- [ ] Step 5: fetch 2018 June-September and 2019-2020 (the archive years that overlap the new seasons) into `data/processed/benchmarks/lhasa_<year>.npz` aligned to the season panels.
- [ ] Step 6: commit `verify: LHASA v2 benchmark aligned to the season panels`.

### Task 5: Rainfall-threshold benchmark and the expanded report

**Files:** Modify `src/aetherguard/verify/report.py` (models `lhasa_v2` and `ed_threshold`; sets 2018 and 2019-2025 with the reported events), `src/aetherguard/verify/baselines.py` (`def ed_threshold_levels(event_rain, duration, alpha, gamma, shares)`), tests.

- [ ] Step 1: take the India-wide event-duration threshold E = alpha * D^gamma fitted on IMERG-Early by Brunetti et al. (2021, HESS) from its published table (record the coefficients and source in the code docstring); if the table cannot be read, fit the same form on the development seasons and label it "refitted".
- [ ] Step 2: failing tests for `ed_threshold_levels` (an event above E alerts, below does not; burden-matched levels via `burden_matched_cuts` on E-exceedance ratio).
- [ ] Step 3-4: implement, pass.
- [ ] Step 5: extend `python -m aetherguard.verify baseline` and run it; expected: the report gains `lhasa_v2` and `ed_threshold` rows, the 2019-2025 sets, and a line stating the held-out event count against the 150-event gate.
- [ ] Step 6: commit `verify: LHASA and rainfall-threshold benchmarks, expanded held-out report`; push the branch.

---

## User actions (not blocking)

- GSI Bhukosh account and terms, to add the Geological Survey of India landslide incidents (2007-2022), the largest possible source of dated Indian events.
- A request to the Global Fatal Landslide Database authors for research access, if fatal-event coverage is wanted.
