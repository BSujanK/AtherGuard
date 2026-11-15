#!/bin/bash
# W7 E2 replays under logs/HEAVY.lock (waits for the lock and outside 10:40-11:45 IST), one set after another; resumable.
#   FIRST=2026-10-14 LAST=2026-11-14 SETS="c a b" bash tools/leads_v4_replays.sh
# Log: logs/leads_v4_replays.log (per set: <out>/<set>.log). Output: C:\Users\sujan\AtherGuard-backups\scratch\leads-v4\replays
WT=/c/Users/sujan/AtherGuard-wt-leads
PY=/c/Users/sujan/AtherGuard/.venv/Scripts/python.exe
OUT=/c/Users/sujan/AtherGuard-backups/scratch/leads-v4/replays
LOCK=/c/Users/sujan/AtherGuard/logs/HEAVY.lock
LOG=/c/Users/sujan/AtherGuard/logs/leads_v4_replays.log
FIRST=${FIRST:-2026-10-14}; LAST=${LAST:-2026-11-14}
export PYTHONPATH=$WT/src AETHERGUARD_DATA_DIR='C:\Users\sujan\AtherGuard\data'
mkdir -p "$OUT"
cd "$WT"
for set in ${SETS:-c a b}; do
  day=$FIRST
  while [ "$(date -d "$day" +%Y%m%d)" -le "$(date -d "$LAST" +%Y%m%d)" ]; do
    while true; do
      t=$(date +%H%M)
      if [ "$t" -ge 1040 ] && [ "$t" -lt 1145 ]; then sleep 120; continue; fi
      if [ -e "$LOCK" ]; then sleep 180; continue; fi
      break
    done
    echo "leads-v4: replay set $set day $day ($WT/tools/leads_v4_replays.sh), started $(date)" > "$LOCK"
    "$PY" "$WT/tools/leads_v4_replay.py" "$OUT" "$set" "$day" "$day" >> "$OUT/$set.log" 2>&1
    echo "set $set $day exit $? $(date)" >> "$LOG"
    rm -f "$LOCK"
    day=$(date -d "$day + 1 day" +%Y-%m-%d)
  done
done
echo "=== ALL DONE $(date)" >> "$LOG"
