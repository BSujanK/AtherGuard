#!/bin/bash
# Leads v4: IMERG half-hourly days for the lead-intensity study (resumable: imerg_hh skips written days).
# Waits outside 10:40-11:45 IST (the daily run uses the same server). Log: logs/leads_v4_fetch_imerg_hh.log
PY=/c/Users/sujan/AtherGuard/.venv/Scripts/python.exe
export PYTHONPATH=/c/Users/sujan/AtherGuard-wt-leads/src AETHERGUARD_DATA_DIR='C:\Users\sujan\AtherGuard\data'
ROOT=/c/Users/sujan/AtherGuard/data/processed/lead_intensity/imerg_hh
LOG=/c/Users/sujan/AtherGuard/logs/leads_v4_fetch_imerg_hh.log
wait_window() { while true; do t=$(date +%H%M); if [ "$t" -ge 1040 ] && [ "$t" -lt 1145 ]; then sleep 120; else break; fi; done; }
cd /c/Users/sujan/AtherGuard-backups/scratch/leads-v4
run() { wait_window; echo "=== $* $(date)" >> $LOG; $PY -m aetherguard.ingest.imerg_hh --root $ROOT --workers 3 "$@" >> $LOG 2>&1; echo "=== exit $? $(date)" >> $LOG; }
run --run late --start 2026-10-08 --end 2026-11-14
run --run early --live-window --start 2026-10-14 --end 2026-11-14
run --run early --live-window --start 2016-06-01 --end 2016-06-30
run --run early --live-window --start 2016-07-01 --end 2016-07-31
run --run early --live-window --start 2016-08-01 --end 2016-08-31
run --run early --live-window --start 2016-09-01 --end 2016-09-30
run --run early --live-window --start 2017-06-01 --end 2017-06-30
run --run early --live-window --start 2017-07-01 --end 2017-07-31
run --run early --live-window --start 2017-08-01 --end 2017-08-31
run --run early --live-window --start 2017-09-01 --end 2017-09-30
run --run early --live-window --start 2023-06-01 --end 2023-06-30
run --run early --live-window --start 2023-07-01 --end 2023-07-31
run --run early --live-window --start 2023-08-01 --end 2023-08-31
run --run early --live-window --start 2023-09-01 --end 2023-09-30
echo "=== ALL DONE $(date)" >> $LOG
