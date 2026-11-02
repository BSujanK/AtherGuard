# AetherGuard build status (2026-10-03): COMPLETE

All phases built, run on real data and verified; full suite 1323 passed (39 realdata/live deselected by default).
Start here: reports/FINAL_REPORT.md (every number read from the phase reports, 0 pending sources).
Run: python -m aetherguard.pipeline status | run ; serve: python -m aetherguard.serve.api --port 8765 ;
dashboard: scripts/start_dashboard.ps1 (React app served by the API on 127.0.0.1:8790; see README)
Hazard model frozen (data/processed/hazard/model/FROZEN.json); test_2018 evaluated once plus one disclosed bug-fix rerun
(docs/phase3-design.md, "Finding: post-evaluation bug fix").
