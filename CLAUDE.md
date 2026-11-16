# AetherGuard

Sensor-integrity and landslide early-warning prototype for the Himalaya and the Western Ghats: a daily live run scores a frozen hazard model per 0.05 degree cell and publishes alerts through a read-only API and a React dashboard. Research prototype, not validated for issuing public warnings. Read `README.md` for the architecture and the full command list.

## Commands

Git Bash on Windows, Python 3.13, virtual environment in `.venv`. The `.ps1` scripts run in PowerShell.

| Task | Command |
|---|---|
| Install | `.venv/Scripts/python -m pip install -e ".[serve,audit,dev]"` |
| All tests (offline, hermetic) | `.venv/Scripts/python -m pytest -W error` |
| One test file | `.venv/Scripts/python -m pytest -W error -q tests/test_config.py` |
| Tests on real data / network | `-m realdata` / `-m live` (both excluded by default) |
| Pipeline state, dry run | `.venv/Scripts/python -m aetherguard.pipeline status`, `... run --dry-run` |
| Live run | `.venv/Scripts/python -m aetherguard.live run` |
| Verification | `.venv/Scripts/python -m aetherguard.verify baseline`, `... verify ledger` |
| API | `.venv/Scripts/python -m aetherguard.serve.api --port 8790` |
| Dashboard | `cd dashboard && npm ci`, then `npm run test`, `npm run lint`, `npm run build` |
| Dashboard smoke test | `npm run smoke -- http://127.0.0.1:8790` (needs the API running) |

## Layout that is not obvious

- Pipeline stages are modules under `src/aetherguard/`. Their order and module names live in `configs/pipeline.yaml`, not in the runner.
- `data/` and `logs/` are git-ignored and exist only on the machine that ran the pipeline. `AETHERGUARD_DATA_DIR` relocates the data tree.
- `reports/` is written by code. Every number there is read from a source file, so change the code or the inputs, never the number.
- Specs and plans are in `docs/superpowers/`. Each plan has a ledger at `.superpowers/sdd/<plan>/progress.md` that records rulings, held-out looks and the commands to resume a run. Read the ledger before continuing a plan. `docs/STATUS.md` is a snapshot from 2026-10-03 and is out of date.
- `docs/aws/` holds documents only.
- Parallel work happens in sibling git worktrees, one branch and one agent per worktree.

## Invariants

- **Frozen outputs are read-only.** Splits, samples, feature stores, integrity and corrector tables and frozen models (`FROZEN.json`) are checksummed. They are replaced only on purpose, with the owning stage's `--force`.
- **Held-out data is looked at once per pre-declared decision.** Write the success criteria first, record the look in the ledger, and tune only on development seasons. A held-out number produced any other way is not reported.
- **Splits are by date.** Cross-validation is year-blocked.
- **The repository is public.** Never commit anything under `data/` or `logs/`, model files, credentials, personal paths or email addresses. Some sources restrict redistribution.
- **Unlicensed data stays local.** Raw rows from the Nepal BIPAD register are never committed. A number that depends on them is shown beside the licence-clean number and labelled, and adoption decisions rest on the licence-clean set.
- **The API is read-only and binds to 127.0.0.1.**
- **Dates in live runs and reported events are IST.**
- **The IMD longitude offset differs on purpose:** `imd_lon_offset_columns: -1` in `configs/live_run.yaml` applies to the live run only. The frozen offline artifacts keep offset 0. Do not align one to the other.

## Proving a change works

- Python: the full default suite passes with `-W error` and prints no warnings. New code is written test-first.
- Dashboard: `npm run test` and `npm run build` pass, then the smoke test against a running API shows real data in each view with no console error.
- Model, alert-rule or threshold changes: compare against the baselines at the same alert burden with bootstrap intervals (`aetherguard.verify`), on development seasons.
- Live chain: the integrity audit (`src/aetherguard/live/audit*.py`) exits 0 for every published day.

## Working rules

- Branch for new work. Do not commit to `main` directly and never force-push. Commit each finished piece and push the working branch.
- Before starting a background job, write its exact resume command and log path in the ledger and commit that.
- Use the repo-local git identity as configured.
- Changes to alert rules, held-out evaluation code or anything that writes frozen data get an independent review before merge.

## Never without asking

- Launching or resizing any cloud resource.
- Looking at held-out data, replacing a frozen artifact, or changing the operating point or alert thresholds.
- Starting work on worldwide coverage (Stage B).
- Stopping or changing the scheduled daily run or the dashboard task.
