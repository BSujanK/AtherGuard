# SOTA year-round alerts: progress ledger

Workstream: make the alerts trustworthy outside June-September (January-May, October-December). Branch `sota-year-round`,
worktree `worktrees/AtherGuard-wt-year`, from `w5-static-susceptibility` 18955b2, with `sota-operating-point` e6b96bc merged
in (its out-of-fold full-year development panels `data/processed/alerts/oof_v4_full/` and its chain/look helpers are reused).
Data junction `data` -> the main tree's data (remove with `cmd /c rmdir data` before deleting the worktree).

- 2026-11-17 01:00: worktree created, w5 fast-forwarded to 18955b2, sota-operating-point merged (clean), junction made,
  import check points at the worktree's src.
