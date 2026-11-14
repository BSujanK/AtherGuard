# SDD ledger: W1b ground-truth expansion (SOTA programme, agent ground-truth)
Branch w1b-ground-truth from w5-static-susceptibility dc93f98; worktree C:\Users\sujan\AtherGuard-wt-gt (data/ is a junction to the main tree's data).

2026-11-13 worktree + junction created; read roadmap, W1 plan + ledger, inventory/geocode/heldout, label store, QA files
2026-11-13 survey: BIPAD Nepal register (public API, no licence stated) 6,672 landslide incidents 2011-2026; GFLD v2 (OGL v2, public feature service) 1,431 points IN/NP/BT 2004-2017; Hao 2020 Kerala (CC BY 4.0, DANS) 4,728 slides dated only to 1 Jun-26 Aug 2018; COOLR refresh adds nothing (max event_date 2025-05-18 = loaded)
2026-11-13 inventory.py extended (located rows, trigger, window basis, accuracy limit); 20 new tests; open_sources.py fetch + normalise
2026-11-13 per-source inventories built at 5 km: GFLD 546 admitted of 1,431; BIPAD 2,009 of 6,672 (4,174 over 5 km, 489 duplicates)
2026-11-13 spec 2026-11-13-aetherguard-w1b-ground-truth.md written BEFORE assembly / clustering / gate counting
2026-11-13 commit 8c7591a: open_sources + inventory extension + assembly + heldout --assembly/--stem (311 tests of touched modules pass)
2026-11-13 QA: rule records for all admitted rows (GFLD 545 keys / 546 rows, BIPAD 2,009); manual spot-check of 8 random BIPAD held-out rows: 2 consistent with an independent report, 6 no independent report found, 0 contradicted; GFLD not spot-checked
2026-11-13 froze data/processed/heldout_v2 (1,509 day records, 0 window) and labels_dev_v2 (506 added); gate storm clusters: all 701 MET, without BIPAD 72 NOT MET, India 71 NOT MET
2026-11-14 laptop restart killed the first GDELT harvest (429 on the first call); harvester retries 429/plain-text notices with 30-240 s back-off and never caches them (eae9e95)
2026-11-14 lead: BIPAD has no licence -> raw rows local only, gate stated with and without BIPAD (expansion report headline + survey)
2026-11-14 GDELT answered 429 for hours to our User-Agent (5 of 74 country-days cached); harvester now paces 15 s, backs off 60-480 s, stops after a failed day and lists the days not fetched (4ca45ce). Full suite: 3,140 passed, 1 failed (test_splits_freeze project-relative path: only in this worktree because data/ is a junction; passes in the main tree; code untouched)
2026-11-14 background job (resumable, reads its cache, never starts over): cd C:\Users\sujan\AtherGuard-wt-gt && PYTHONPATH=src C:\Users\sujan\AtherGuard\.venv\Scripts\python.exe -m aetherguard.verify harvest --start 2026-10-09 --end 2026-11-14 --out C:\Users\sujan\AppData\Local\Temp\claude\4bf4e77bb90de3e2\6ffc6a00-665d-4e6a-9184-f49567f49766\scratchpad\ground-truth\harvest --bipad   (log C:\Users\sujan\AtherGuard\logs\gt_harvest.log)
