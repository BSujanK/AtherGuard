# Ledger: kerala-susc (two-stage susceptibility from the Kerala 2018 mapped inventory)

Branch `sota-kerala-susc` in worktrees/AtherGuard-wt-kerala, from w5-static-susceptibility (fast-forwarded to 18955b2).
Spec: docs/superpowers/specs/2026-11-17-aetherguard-kerala-susceptibility.md. The worktree has a `data` junction to the
main tree's data: remove it with `cmd /c rmdir data` before deleting the worktree; never `git clean` here.

- 2026-11-17 inventory located: data/raw/manual/kerala2018_hao2020 (CC-BY-4.0, DANS doi 10.17026/dans-x6c-y7x2), 4,728 points; 351 of 1,063 Kerala-district domain cells hold a point.
- 2026-11-17 spec written and committed before any stage 1, stage 2 or held-out number (criteria in sections 3-6, leakage design section 4).
