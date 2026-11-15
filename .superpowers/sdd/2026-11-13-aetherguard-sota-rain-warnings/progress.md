# SOTA rain warnings (agent rain-warn, branch sota-rain-warnings)

2026-11-14 21:55 worktree AtherGuard-wt-rain created from w5-static-susceptibility (c92bd89); scratch AtherGuard-backups/scratch/rain-warn. Finding so far: data/live/<date>/ keeps features_D0..D3.parquet, risk_*.parquet, imd_rt grd, run.json; no raw ECMWF/GFS grib kept.
2026-11-15 10:10 resumed after usage limit; Task 1 probe in progress.
2026-11-15 10:30 Task 1 probe done; spec docs/superpowers/specs/2026-11-14-aetherguard-rain-warnings.md committed before any skill number (archive: ECMWF ens mean/p10/p50/p90 only, 202 monsoon + 27 live issue days; GFS 488 + 33; no members kept).
2026-11-15 10:22 prob + climatology modules, tests green (17). BACKGROUND climatology (light, resumable by rerun, idempotent): cd C:/Users/sujan/AtherGuard-wt-rain && AETHERGUARD_DATA_DIR=C:/Users/sujan/AtherGuard/data PYTHONPATH=src C:/Users/sujan/AtherGuard/.venv/Scripts/python.exe -m aetherguard.rainwarn climatology > C:/Users/sujan/AtherGuard/logs/rainwarn_climatology.log 2>&1 ; output data/processed/rainwarn/climatology.npz
