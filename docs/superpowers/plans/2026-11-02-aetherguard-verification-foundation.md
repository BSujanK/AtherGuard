# Verification Foundation (W0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure the pipeline the way an early-warning service is judged (event-based detection and precision with a
distance / time tolerance, with confidence intervals and baselines), on the 2018 held-out season, the development
seasons and every live day, so later workstreams can prove or disprove a gain.

**Architecture:** A new package `src/aetherguard/verify/` with four focused modules: tolerance matching, scores with
bootstrap, baselines, and the live verification ledger, plus a CLI (`python -m aetherguard.verify`). It reads level
matrices (cells x days) that the existing code already produces (`live/hardening_dev.season_levels`, the published
`data/live/<date>/*.parquet`) and never changes the live run.

**Tech Stack:** Python 3.13, numpy, pandas, pytest (hermetic synthetic fixtures), the project's `grid` helpers.

**Spec:** `docs/superpowers/specs/2026-11-02-aetherguard-accuracy-roadmap.md` (§3 protocol v3, §4 W0).

## Global Constraints

- Tolerance default: 10 km great-circle distance between cell centres (`grid.cell_center`, haversine, R = 6371.0088 km) and ±1 day.
- Cell-exact verification (0 km, 0 days) is always reported next to the tolerant one.
- Levels: 0 Normal, 1 Watch, 2 Warning, 3 Emergency (`alerts.levels`); "level ≥ L" means at L or above.
- Bootstrap: `live.backtest.BOOTSTRAP` (n 2000, seed 31337, level 0.95); days are the resampling unit for cell-day counts, events for detection.
- Missing values are NaN, never 0; every reported number comes from a result file.
- Never modify frozen artifacts, `live/run.py`, `live/postrules.py` or published `data/live` tables.
- New code test-first; new tests also pass under `-W error`. Commit per task on branch `w0-verification`.

## Review Focus

1. An event whose own cell is not in the panel (outside the candidate set) must still be matched against panel cells within 10 km, not dropped.
2. An event dated outside the panel's days is excluded and counted as `outside_window`, never as a miss.
3. East-west distance shrinks with latitude: 2 cells east is 9.6 km at 30N but 11.0 km at 8N, so matching must use distance, not a cell radius.
4. Several catalog records on one cell and date are one event.
5. A published level on an unscored row (a held or blind-raised level) is still an alert: it counts in alert cell-days and can detect an event.

---

### Task 1: Tolerance matching

**Files:**
- Create: `src/aetherguard/verify/__init__.py`, `src/aetherguard/verify/matching.py`
- Test: `tests/test_verify_matching.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Tolerance: km: float = 10.0; days: int = 1` (`km >= 0`, `days >= 0`, else `ValueError`); `CELL_EXACT = Tolerance(0.0, 0)`.
  - `def rows_within(event_cells: np.ndarray, panel_cells: np.ndarray, km: float) -> list[np.ndarray]`: per event cell, the panel row indices whose centres lie within `km` (its own cell's row is always included when present).
  - `@dataclass class Match: event_level: np.ndarray` (int8 per event: highest published level within tolerance, -1 when no panel cell-day lies within it), `alert_verified: np.ndarray` (bool, cells x days: an event lies within tolerance of the cell-day), `events: pd.DataFrame` (the de-duplicated events with columns `cell_id`, `date`), `outside_window: int`.
  - `def match(levels: np.ndarray, cell_ids: np.ndarray, days: list[date], events: pd.DataFrame, tol: Tolerance) -> Match`; `events` needs `cell_id` and `date`.

- [ ] **Step 1: Write the failing tests** (synthetic panel: cells on a 7x7 block centred on 30.025N 78.025E plus a 7x7 block at 8.025N 77.025E, 3 days 2018-07-01..03)

```python
def test_an_alert_two_cells_east_and_one_day_later_detects_the_event():      # 9.6 km at 30N
    m = match(levels_with(cell=east(EVENT_30N, 2), day=2, level=2), CELLS, DAYS, one_event(EVENT_30N, day=1), Tolerance())
    assert m.event_level.tolist() == [2]

def test_three_cells_east_is_beyond_10_km():                                   # 14.4 km
    m = match(levels_with(cell=east(EVENT_30N, 3), day=1, level=3), CELLS, DAYS, one_event(EVENT_30N, day=1), Tolerance())
    assert m.event_level.tolist() == [0]

def test_two_cells_east_at_8n_is_beyond_10_km():                               # 11.0 km: distance, not cell count
    m = match(levels_with(cell=east(EVENT_8N, 2), day=1, level=2), CELLS, DAYS, one_event(EVENT_8N, day=1), Tolerance())
    assert m.event_level.tolist() == [0]

def test_an_event_outside_the_panel_cells_is_matched_by_distance():
    outside = east(EVENT_30N, 4)                                                 # not a panel cell
    m = match(levels_with(cell=east(EVENT_30N, 3), day=1, level=1), CELLS_WITHOUT(outside), DAYS, one_event(outside, day=1), Tolerance())
    assert m.event_level.tolist() == [1]

def test_events_outside_the_days_are_counted_not_missed():
    m = match(ZERO_LEVELS, CELLS, DAYS, events_on(["2018-06-20", "2018-07-02"]), Tolerance())
    assert m.outside_window == 1 and len(m.events) == 1

def test_duplicate_records_are_one_event():
    m = match(ZERO_LEVELS, CELLS, DAYS, pd.concat([one_event(EVENT_30N, day=1)] * 3), Tolerance())
    assert len(m.events) == 1

def test_alert_verified_marks_cell_days_within_tolerance_only():
    m = match(ZERO_LEVELS, CELLS, DAYS, one_event(EVENT_30N, day=1), Tolerance())
    assert m.alert_verified[row(EVENT_30N), :].tolist() == [True, True, True]
    assert not m.alert_verified[row(east(EVENT_30N, 3)), :].any()

def test_cell_exact_needs_the_same_cell_and_day():
    m = match(levels_with(cell=east(EVENT_30N, 1), day=1, level=3), CELLS, DAYS, one_event(EVENT_30N, day=1), CELL_EXACT)
    assert m.event_level.tolist() == [0]

def test_tolerance_rejects_negative_values():
    with pytest.raises(ValueError): Tolerance(km=-1)
    with pytest.raises(ValueError): Tolerance(days=-1)
```

- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_verify_matching.py -q`; expected: FAIL, `ModuleNotFoundError: aetherguard.verify`.
- [ ] **Step 3: Implement** `matching.py`. Distances by haversine between `grid.cell_center` coordinates; candidate rows found by a latitude/longitude window of `km / 111.0` degrees (longitude widened by `1/cos(lat)`), then filtered by exact distance. De-duplicate events on (`cell_id`, date).
- [ ] **Step 4: Run** the same command; expected: 9 passed. Then with `-W error`; expected: 9 passed.
- [ ] **Step 5: Commit** `git add src/aetherguard/verify tests/test_verify_matching.py && git commit -m "verify: tolerance matching of events and alert cell-days"`

### Task 2: Scores with bootstrap

**Files:**
- Create: `src/aetherguard/verify/scores.py`
- Test: `tests/test_verify_scores.py`

**Interfaces:**
- Consumes: `Match` (Task 1).
- Produces:
  - `def level_scores(levels: np.ndarray, scored: np.ndarray, m: Match, min_level: int) -> dict` with keys `events`, `hits`, `pod`, `alert_cell_days`, `verified_alert_cell_days`, `precision`, `alert_share` (alert cell-days / scored cell-days), `events_per_1000_alert_cell_days`. An alert is `levels >= min_level` whether or not the row is scored. `pod` and `precision` are NaN when their denominator is 0.
  - `def bootstrap_scores(levels, scored, m: Match, min_level: int, boot: dict = BOOTSTRAP) -> dict`: `level_scores` plus `pod_ci` (events resampled) and `precision_ci`, `alert_cell_days_ci` (days resampled), each `[lo, hi]`.
  - `def paired_change(levels_a, levels_b, scored, m_a: Match, m_b: Match, min_level: int, boot: dict = BOOTSTRAP) -> dict`: `alert_cell_days_change`, `hits_change`, `precision_change`, each with a `_ci` from resampling the same days (and the events of those days) for a and b.

- [ ] **Step 1: Write the failing tests**

```python
def test_precision_is_verified_alert_cell_days_over_alert_cell_days():
    s = level_scores(LEVELS, SCORED, MATCH, min_level=2)        # fixture: 8 Warning+ cell-days, 3 verified
    assert (s["alert_cell_days"], s["verified_alert_cell_days"]) == (8, 3) and s["precision"] == pytest.approx(3 / 8)

def test_pod_counts_events_with_a_level_at_or_above():
    s = level_scores(LEVELS, SCORED, MATCH, min_level=1)        # fixture event levels [3, 1, 0, -1]
    assert (s["events"], s["hits"]) == (4, 2) and s["pod"] == pytest.approx(0.5)

def test_an_unscored_held_alert_still_counts():
    s = level_scores(LEVELS_HELD_ON_UNSCORED, SCORED, MATCH, min_level=1)
    assert s["alert_cell_days"] == 9

def test_no_events_gives_nan_pod_not_zero():
    assert math.isnan(level_scores(LEVELS, SCORED, EMPTY_MATCH, 1)["pod"])

def test_bootstrap_is_seeded_and_brackets_the_point():
    a, b = bootstrap_scores(LEVELS, SCORED, MATCH, 1), bootstrap_scores(LEVELS, SCORED, MATCH, 1)
    assert a == b and a["precision_ci"][0] <= a["precision"] <= a["precision_ci"][1]

def test_paired_change_of_identical_levels_is_zero():
    c = paired_change(LEVELS, LEVELS, SCORED, MATCH, MATCH, 2)
    assert c["alert_cell_days_change"] == 0 and c["alert_cell_days_change_ci"] == [0, 0]
```

- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_verify_scores.py -q`; expected: FAIL, ImportError.
- [ ] **Step 3: Implement** `scores.py` (percentile bootstrap, `np.random.default_rng(boot["seed"])`).
- [ ] **Step 4: Run** again, then with `-W error`; expected: 6 passed both times.
- [ ] **Step 5: Commit** `git commit -m "verify: event-based detection and precision with bootstrap CIs"`

### Task 3: Baselines

**Files:**
- Create: `src/aetherguard/verify/baselines.py`
- Test: `tests/test_verify_baselines.py`

**Interfaces:**
- Produces:
  - `def burden_matched_cuts(values: np.ndarray, scored: np.ndarray, shares: tuple[float, float, float]) -> tuple[float, float, float]`: cut points so that the shares of scored cell-days at Watch+, Warning+, Emergency equal `shares` (non-increasing; NaN values never alert).
  - `def threshold_levels(values: np.ndarray, cuts: tuple[float, float, float]) -> np.ndarray` (int8, same shape).
  - `def rain_baseline(acc_3: np.ndarray, scored: np.ndarray, dev_acc_3: np.ndarray, dev_scored: np.ndarray, dev_shares) -> np.ndarray`: 3-day IMERG rain thresholds fitted on development cell-days to v3's development alert shares, applied to the evaluated season.
  - `def susceptibility_baseline(static_score: np.ndarray, n_days: int, scored: np.ndarray, shares) -> np.ndarray`: the same alert burden placed every day on the cells of highest static score (no rain), which shows what rain adds.

- [ ] **Step 1: Write the failing tests**

```python
def test_cuts_reproduce_the_target_shares():
    cuts = burden_matched_cuts(np.arange(1000.0), np.ones(1000, bool), (0.5, 0.2, 0.05))
    lv = threshold_levels(np.arange(1000.0), cuts)
    assert [(lv >= k).mean() for k in (1, 2, 3)] == pytest.approx([0.5, 0.2, 0.05], abs=0.001)

def test_nan_rain_never_alerts():
    assert threshold_levels(np.array([np.nan, 50.0]), (1.0, 10.0, 40.0)).tolist() == [0, 3]

def test_susceptibility_baseline_alerts_the_same_cells_every_day():
    lv = susceptibility_baseline(np.array([0.1, 0.9, 0.5, 0.2]), 3, np.ones((4, 3), bool), (0.25, 0.25, 0.25))
    assert lv[1].tolist() == [3, 3, 3] and lv[[0, 2, 3]].max() == 0
```

- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_verify_baselines.py -q`; expected: FAIL, ImportError.
- [ ] **Step 3: Implement** `baselines.py` (`np.nanquantile` over scored cell-days).
- [ ] **Step 4: Run** again, then with `-W error`; expected: 3 passed both times.
- [ ] **Step 5: Commit** `git commit -m "verify: burden-matched rain-threshold and susceptibility-only baselines"`

### Task 4: Baseline report (development seasons and 2018)

**Files:**
- Create: `src/aetherguard/verify/report.py`, `src/aetherguard/verify/__main__.py`
- Modify: `README.md` (a short "Verification" section with the two CLI commands)
- Test: `tests/test_verify_report.py`

**Interfaces:**
- Consumes: Tasks 1-3; development seasons and the 2018 season exactly as `live/precision_study.py` loads them (its `load_inputs`), and v3 levels from `live.hardening_dev.season_levels` with the §11 rules (the study's `baseline` condition, which equals the published chain).
- Produces:
  - `def model_table(levels_by_model: dict[str, np.ndarray], scored: np.ndarray, cell_ids: np.ndarray, days: list[date], events: pd.DataFrame, tolerances: dict[str, Tolerance]) -> dict`: per model, tolerance name and level 1-3, the `bootstrap_scores` dict.
  - CLI `python -m aetherguard.verify baseline` writing `reports/phase7_verification_baseline.json` and `.md`. Models: `v3`, `rain_3d`, `susceptibility`. Tolerances: `tolerant` (10 km, 1 day) and `cell_exact`. Sets: development (pooled 2007-2017, out of fold) and `season_2018`. The report states that 2018 is re-measured with the frozen v3, so this is not a new held-out look.

- [ ] **Step 1: Write the failing test**: `model_table` on a synthetic 2-model panel returns `table["a"]["tolerant"]["2"]["precision"] == pytest.approx(expected)` for a hand-computed fixture, and both tolerance keys exist for each model.
- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_verify_report.py -q`; expected: FAIL, ImportError.
- [ ] **Step 3: Implement** `report.py` and `__main__.py` (argparse subcommands `baseline`, `ledger`).
- [ ] **Step 4: Run** the test (pass), then `.venv/Scripts/python -m aetherguard.verify baseline`; expected: exit 0, both report files written, and the v3 cell-exact Watch+ / Warning+ / Emergency hits on 2018 equal 48 / 40 / 30 (the published figures). A different number is a bug in the loading, not a finding.
- [ ] **Step 5: Commit** `git commit -m "verify: baseline report for development seasons and 2018"`

### Task 5: Live verification ledger

**Files:**
- Create: `src/aetherguard/verify/ledger.py`, `data/raw/manual/reported_events/README.md` (format only; the folder's CSVs stay local)
- Test: `tests/test_verify_ledger.py`

**Interfaces:**
- Consumes: Tasks 1-2.
- Produces:
  - Reported-event CSV columns: `date` (YYYY-MM-DD, IST), `latitude`, `longitude`, `location_text`, `source_url`, `accuracy_km`.
  - `def load_reported(directory: Path) -> pd.DataFrame`: all CSVs, validated: rows with an unparsable date, coordinates outside the two region boxes of `configs/domain.yaml` or an empty `source_url` raise `ValueError` naming the file and line. Adds `cell_id` (`grid.latlon_to_cell`).
  - `def live_levels(live_root: Path, lead: int = 0) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[date]]` (levels, scored, cell_ids, days) over every published day: lead 0 from `alerts.parquet`, lead k from `risk_D{k}.parquet` stacked on the date it forecasts. A day not published is a column of -1 (no alert, not scored).
  - `def ledger(live_root: Path, reported_dir: Path, today: date, tol: Tolerance = Tolerance()) -> dict`: per lead and level, `bootstrap_scores`; days less than 14 days before `today` are marked `provisional` (reports still arriving).
  - CLI `python -m aetherguard.verify ledger` writing `reports/live_verification.json` and `.md`.

- [ ] **Step 1: Write the failing tests** (a temporary live root with three published days and one missing; one CSV)

```python
def test_reported_events_outside_the_domain_are_rejected(tmp_path):
    write_csv(tmp_path, [("2026-10-22", 51.5, -0.1, "London", "https://x", 1)])
    with pytest.raises(ValueError, match="line 2"): load_reported(tmp_path)

def test_a_missing_day_is_not_an_alert_and_not_scored(live_root):
    levels, scored, _, days = live_levels(live_root)
    j = days.index(date(2026, 10, 23))
    assert (levels[:, j] == -1).all() and not scored[:, j].any()

def test_forecast_lead_rows_are_placed_on_the_day_they_forecast(live_root):
    _, _, _, days = live_levels(live_root, lead=2)
    assert days[0] == date(2026, 10, 24)                      # first run 2026-10-22, lead 2

def test_recent_days_are_provisional(live_root, reported):
    out = ledger(live_root, reported, today=date(2026, 11, 2))
    assert out["provisional_from"] == "2026-10-19"
```

- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_verify_ledger.py -q`; expected: FAIL, ImportError.
- [ ] **Step 3: Implement** `ledger.py`.
- [ ] **Step 4: Run** the tests, then with `-W error` (4 passed both times). Then run the full suite: `.venv/Scripts/python -m pytest -q`; expected: all passed. Run `.venv/Scripts/python -m aetherguard.verify ledger`; expected: exit 0, and a report saying how many reported events exist (0 is a valid answer until W1 fills the folder).
- [ ] **Step 5: Commit** `git commit -m "verify: live verification ledger against reported landslides"`, then push the branch and open a pull request into `main`.

---

## After W0

- Copy the measured baseline (tolerant and cell-exact precision and detection per level, with CIs) into §1 of the roadmap spec, and pre-declare the W1 to W8 adoption criteria against those numbers.
- W1 (ground-truth expansion, including the LHASA v2 benchmark for gate G4) gets its own plan next. It is the
  precondition for any "top accuracy" claim.
