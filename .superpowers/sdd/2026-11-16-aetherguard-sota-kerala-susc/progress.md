# Ledger: kerala-susc (two-stage susceptibility from the Kerala 2018 mapped inventory)

Branch `sota-kerala-susc` in worktrees/AtherGuard-wt-kerala, from w5-static-susceptibility (fast-forwarded to 18955b2).
Spec: docs/superpowers/specs/2026-11-17-aetherguard-kerala-susceptibility.md. The worktree has a `data` junction to the
main tree's data: remove it with `cmd /c rmdir data` before deleting the worktree; never `git clean` here.

- 2026-11-17 inventory located: data/raw/manual/kerala2018_hao2020 (CC-BY-4.0, DANS doi 10.17026/dans-x6c-y7x2), 4,728 points; 351 of 1,063 Kerala-district domain cells hold a point.
- 2026-11-17 spec written and committed before any stage 1, stage 2 or held-out number (criteria in sections 3-6, leakage design section 4).
- 2026-11-17 stage 1 built (src/aetherguard/features/susc_kerala.py, 11 tests): `python -m aetherguard.features.susc_kerala` (29 s, light). Result data/processed/features/susc_kerala/stage_one.json; rerun with --force reproduced metrics, selection and table checksum exactly.
- 2026-11-17 STAGE 1 FAILED its pre-declared rule (spec section 3): S_gbm pooled leave-one-district-out ROC AUC 0.817 against 0.831 for stat_slope_mean alone (S_lr 0.806). Per the spec the study ends: no stage 2, no season scoring, no preflight, no held-out look. Report: reports/phase9_kerala_susceptibility.{md,json} (`... susc_kerala report`).
