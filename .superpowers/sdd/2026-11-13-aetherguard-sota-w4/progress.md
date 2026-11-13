# W4 soil moisture / antecedent wetness: progress ledger (agent w4-wetness, branch w4-soil-moisture)

2026-11-13 20:05 IST worktree C:\Users\sujan\AtherGuard-wt-w4 from w5-static-susceptibility (dc93f98)
2026-11-13 20:30 IST Task 1 source probe done: reports/phase8_wetness_sources_probe.{json,md} (features.wetness_probe). SMAP fails history; ERA5 via ARCO anonymous, ERA5T ~6 d behind; IFS vsw and GFS SOILW fail the pre-declared mapping check against ERA5 (rank difference 0.140 / 0.114 > 0.10); GLDAS/FLDAS/MERRA-2 weeks behind. Chosen: IMERG Late bucket, lag 2 (32/33 live runs had UTC D-2 from Late).
2026-11-13 20:40 IST Task 2 spec docs/superpowers/specs/2026-11-13-aetherguard-w4-wetness.md written before any model result; configs hazard_w4_wet.yaml, hazard_v5.yaml
2026-11-13 20:40 IST Task 3 code: features.wetness (iwet group, live adapter), hazard.v4_int generalised by config (other extra groups, labelled stage 1, incumbent_dev guard, requires.stage_one by name, wetness card, season group tables), hazard.w4_wetness (checks C1-C3, ablation, reports); tests 19 + 9 + 20 new, v4_int/v4_static 80 unchanged and passing
