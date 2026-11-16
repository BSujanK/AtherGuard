# SOTA year-round alerts: progress ledger

Workstream: make the alerts trustworthy outside June-September (January-May, October-December). Branch `sota-year-round`,
worktree `worktrees/AtherGuard-wt-year`, from `w5-static-susceptibility` 18955b2, with `sota-operating-point` e6b96bc merged
in (its out-of-fold full-year development panels `data/processed/alerts/oof_v4_full/` and its chain/look helpers are reused).
Data junction `data` -> the main tree's data (remove with `cmd /c rmdir data` before deleting the worktree).

- 2026-11-17 01:00: worktree created, w5 fast-forwarded to 18955b2, sota-operating-point merged (clean), junction made,
  import check points at the worktree's src.
- 2026-11-17 02:30: exploration on development panels (scratch, ops/scratch/year-round): out-of-season alerts are
  fewer but 1.4-4.6x less precise per alert cell-day than monsoon alerts; held-out W1 has 4 out-of-season slides
  (Himalaya Oct-Dec 1, Jan-May 1; Western Ghats Oct-Dec 2). Module verify/year_round.py + 13 tests written.
- 2026-11-17 02:35: JOB year-round-panels (runner, class light, resumable: one file per year and window, existing kept).
  cwd C:\Users\sujan\AetherGuard-Project\worktrees\AtherGuard-wt-year; env PYTHONPATH=C:\Users\sujan\AetherGuard-Project\worktrees\AtherGuard-wt-year\src, AETHERGUARD_DATA_DIR=C:\Users\sujan\AetherGuard-Project\AtherGuard\data;
  cmd "C:\Users\sujan\AetherGuard-Project\AtherGuard\.venv\Scripts\python.exe -m aetherguard.verify.year_round panels"; log ops\jobs\logs\year-round-panels.log;
  output data\processed\alerts\year_round\year_<window>_<year>.json (22 files, about 50 s each).
