# W2 Operating Point Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Find region x month alert thresholds (and optionally an Emergency confirmation rule) that keep v3's detection and minimise alert cell-days, select on development data, and test once on the expanded held-out set under the pre-declared criterion.

**Architecture:** A new module `src/aetherguard/verify/operating_point.py` (stratum curves, Lagrangian allocation, candidate levels) and a CLI subcommand; it reuses W0/W1 verification (`matching`, `scores`, `heldout`) and the development / held-out panels. The live run is not changed here.

**Tech Stack:** Python 3.13, numpy, pandas, pytest.

**Spec:** `docs/superpowers/specs/2026-11-06-aetherguard-w2-operating-point.md`

## Global Constraints

- Strata: region (himalaya, western_ghats) x month (6, 7, 8, 9); months 10-12 keep the v3 region thresholds.
- Candidate thresholds: v3 risk quantiles 50% to 99.9% in 200 steps, per level.
- Lambda by bisection so total development hits at each level are >= v3's (cell-exact, own cell, event day).
- Development alert cell-days on universe-sample cells only (W0 R11); detection over all development events.
- Section 11 post-model rules and hysteresis applied unchanged after the raw levels.
- Held-out evaluation once, with `heldout`'s POOLED set (87 independent slides), tolerant and cell-exact, burden reported.
- Never modify frozen artifacts, `live/run.py`, `live/postrules.py` or `data/live`. Test-first; `-W error`.

## Review Focus

1. A stratum with no development events must not get a threshold of "never alert": it keeps the v3 threshold.
2. Thresholds must be non-decreasing Watch <= Warning <= Emergency within each stratum after the per-level fits.
3. A cell-day in October-December uses the unchanged v3 region thresholds.
4. Hits are counted per event (own cell, event day), not per cell-day, and the same event never counts twice.
5. The held-out look happens once: the evaluation refuses to run a second time if its result file exists.

---

### Task 1: Stratum curves and Lagrangian allocation

**Files:** Create `src/aetherguard/verify/operating_point.py`; Test `tests/test_verify_operating_point.py`.

**Interfaces (produces):**
- `def stratum_curves(risk: np.ndarray, region: np.ndarray, month: np.ndarray, universe: np.ndarray, events: pd.DataFrame, candidates: np.ndarray) -> dict[tuple[str, int], dict]` — per stratum, arrays `thresholds`, `hits` (events whose own-cell risk on the event day >= t), `alerts` (universe cell-days with risk >= t).
- `def allocate(curves: dict, target_hits: int) -> dict[tuple[str, int], float]` — thresholds maximising sum(hits - lambda*alerts) with lambda bisected so total hits >= target_hits; a stratum with zero events gets `None` (keep v3).
- `def monotone(by_level: dict[int, dict]) -> dict[int, dict]` — enforce Watch <= Warning <= Emergency per stratum (raise the higher levels).

- [ ] Step 1: failing tests: two strata, one with dense events per alert and one sparse: at equal total hits the allocation puts a lower threshold where events are dense and a higher one where sparse, and total alerts are below the uniform-threshold solution; zero-event stratum -> None; total hits >= target; monotone() raises Warning to Watch when Warning < Watch.
- [ ] Step 2: run `.venv/Scripts/python -m pytest tests/test_verify_operating_point.py -q`; expected FAIL (ImportError).
- [ ] Step 3: implement. Step 4: pass (also `-W error`). Step 5: commit `verify: region x month threshold allocation`.

### Task 2: Candidate levels on a panel

**Files:** Modify `src/aetherguard/verify/operating_point.py`; Test same file.

**Interfaces:** `def candidate_levels(season, thresholds: dict[int, dict[tuple[str,int], float|None]], config, base_rules, confirm_emergency: bool) -> np.ndarray` — raw point level per cell-day from the stratum thresholds (v3 region thresholds for None and for months 10-12), the uncertain-high bound as in `hardening_dev.season_levels`, the C2 confirmation (Emergency only if the previous day's raw level >= Warning, else Warning), then the section 11 rain cap and hysteresis exactly as `hardening_dev.season_levels` applies them (reuse its internals; do not reimplement the rules).

- [ ] Step 1: failing tests: with thresholds equal to v3's everywhere and confirm off, `candidate_levels` equals `season_levels`; a lowered Western Ghats July Warning threshold raises only WG July cells; October cells unchanged; the confirmation demotes a first-day Emergency to Warning.
- [ ] Steps 2-5: run (fail), implement, pass, commit `verify: candidate levels for region x month thresholds`.

### Task 3: Fit, select, single held-out look, report

**Files:** Modify `operating_point.py`, `src/aetherguard/verify/__main__.py` (subcommand `operating-point`); Create `reports/phase7_operating_point.{md,json}` (generated); Test same file.

- [ ] Step 1: failing tests: selection prefers the candidate with fewer development Warning+ alert cell-days at equal-or-higher detection, ties to C1; the evaluation refuses a second run when `data/processed/alerts/w2_heldout.json` exists; the adoption decision applies the spec's criterion exactly.
- [ ] Step 2-4: implement `fit` (development, both candidates, thresholds per level per stratum), `select`, `evaluate_once` (POOLED held-out via `heldout`'s assembly, v3 vs selected, tolerant and cell-exact, independent-slide detection, alert cell-days with paired bootstrap), `decide`; write `thresholds_w2_candidate.json`, the report and `w2_heldout.json`.
- [ ] Step 5: run `python -m aetherguard.verify operating-point` for real; report the per-stratum thresholds, development burden change, held-out detection and burden change, and the adoption decision.
- [ ] Step 6: commit `verify: W2 operating point, development fit and single held-out look`.

Wiring an adopted candidate into the live run (thresholds by region and month in `live/run.py`, the dashboard and the audit) is a separate plan, written only if the criterion passes.
