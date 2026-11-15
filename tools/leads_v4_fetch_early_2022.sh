#!/bin/bash
# Leads v4 E1: the Early live window of the June-September 2022 issue days (resumable; pauses between months inside 10:40-11:45 IST).
PY=/c/Users/sujan/AtherGuard/.venv/Scripts/python.exe
export PYTHONPATH=/c/Users/sujan/AtherGuard-wt-leads/src AETHERGUARD_DATA_DIR='C:\Users\sujan\AtherGuard\data'
ROOT=/c/Users/sujan/AtherGuard/data/processed/lead_intensity/imerg_hh
LOG=/c/Users/sujan/AtherGuard/logs/leads_v4_fetch_imerg_hh.log
cd /c/Users/sujan/AtherGuard-backups/scratch/leads-v4
for m in 06-01:06-30 07-01:07-31 08-01:08-31 09-01:09-30; do
  while [ "$(date +%H%M)" -ge 1040 ] && [ "$(date +%H%M)" -lt 1145 ]; do sleep 120; done
  echo "=== early 2022 $m $(date)" >> $LOG
  $PY -m aetherguard.ingest.imerg_hh --root $ROOT --workers 3 --run early --live-window --start 2022-${m%%:*} --end 2022-${m##*:} >> $LOG 2>&1
  echo "=== exit $? $(date)" >> $LOG
done
echo "=== EARLY 2022 DONE $(date)" >> $LOG
