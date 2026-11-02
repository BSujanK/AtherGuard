# Phase 4 design addendum — alert engine, API, dashboard

Parent: spec sections 8 and 9; `docs/phase2-design.md` (Gate outcome), `docs/phase3-design.md` (Protocol v2). No git. Builder (Sonnet) test-first, controller review.

## Inputs (all already produced by Phases 1–3)
- Hazard: `aetherguard.hazard.score_frame(df)` -> risk, risk_lo, risk_hi, risk_per_100k, plus SHAP top-5; thresholds Watch / Warning / Emergency from the model card (out-of-fold, recall-first margin).
- Features for any (cell, date) in the frozen feature files (replay), including `rain_source`, `src_dis_*` (IMD vs CHIRPS disagreement), `integ_*` (station trust summary near the cell).
- Integrity engine out-of-fold outputs per station-day (trust, fault_type, genuine_extreme, reasons) for the sensor-trust panel.

## Alert engine (`src/aetherguard/alerts/`)
- **Levels** from calibrated risk vs card thresholds: Normal < Watch <= Warning <= Emergency. The upper interval bound `risk_hi` crossing Watch while the point is below raises Watch with reason `uncertain_high` (recall-first).
- **Hysteresis**: a cell steps DOWN only after 2 consecutive days below the lower level's threshold × 0.8; steps UP immediately. Stateful over a date-ordered sequence per cell; replay is deterministic.
- **Data confidence** per cell-day:
  - High: IMD valid AND CHIRPS valid AND |dis_ratio_3 - 1| moderate (thresholds documented from the out-of-fold distribution), or at least one trusted station within 100 km agreeing.
  - Degraded: one rain source missing, OR sources disagree strongly (dis_ratio_3 outside the 5–95 % development range), OR nearby stations flagged, OR a station in the out-of-distribution state (Phase 2 ruling: trailing-90-day flag rate > 3 × the engine target -> station state `uncertain`, not `faulty`).
  - Insufficient: no valid rain source for the cell on D, or all nearby stations untrusted while sources disagree.
- **No silent Normal when blind** (spec 8): if confidence is Insufficient or Degraded and ANY independent source shows heavy rain (any of IMD acc_1, CHIRPS-aligned acc_1, trusted station max within 100 km ≥ the development 95th percentile of positives' acc_1 lower tail, documented; default 50 mm/day or acc_3 ≥ 100 mm), escalate to at least Watch with reason `sensors_untrusted_heavy_rain` / `sources_disagree_heavy_rain`. The level uses the MAX of the sources, never the min (hazard-safe rule from Phase 2).
- **Reasons** stored with every alert: top-5 SHAP factors (feature, value, contribution), rain-source spread (IMD, CHIRPS, station), sensor-trust summary (n stations, n trusted, flagged types), confidence, interval.
- **Cost–loss report**: for the chosen thresholds, report alerts per 1000 cell-days, recall, and the implied cost ratio C/L at which this operating point is optimal; plus a table for C/L in {1/10, 1/50, 1/200}.
- **Evaluation**: replay over test_2018 universe + positives, window 2023, Kerala 2018 and Wayanad 2024 case sets: event-level detection with lead time (first day at Watch+ within the 7 days before and including the event day), alerted area per day, flapping count with/without hysteresis, number of escalations by the blind rule and how many of those coincide with events. Written to `reports/phase4_alerts_report.md/.json`.

## Serving (`src/aetherguard/serve/`)
- FastAPI app (`uvicorn aetherguard.serve.api:app`): `GET /health` (versions, model card hash, data manifest status), `GET /risk?date=YYYY-MM-DD&region=...&bbox=...` (cells with risk, level, confidence; replay data only), `GET /risk/cell/{cell_id}?date=` (full explanation: reasons, SHAP, sources, interval), `GET /sensors?date=&bbox=` (station trust, fault type, genuine_extreme, reasons), `GET /alerts?start=&end=&min_level=` (alert list with reasons). Read-only, local only (bind 127.0.0.1), pydantic response models, no secrets.
- Replay store: precomputed per-day alert tables for the case sets and test_2018 sample (parquet), so the API answers from disk quickly.
- Live demo mode: OUT of the validated pipeline. A `live_demo` command pulls the latest NOAA GHCN readings for the 140 stations and runs the integrity engine on them, and Open-Meteo recent rain for a short fixed list of focus cells (Wayanad, Kerala ghats, Uttarakhand), clearly labelled `DEMO — unvalidated inputs (ERA5/IFS, not IMD/CHIRPS)`. Optional; built last, quota-aware.

## Dashboard (`src/aetherguard/serve/dashboard.py`, Streamlit)
- Pages: Risk map (date picker, level colours, confidence hatching/opacity, region filter); Why this alert (cell drill-down: SHAP bars, sources table, trust summary, interval); Sensor trust (station map with trust, flagged types, out-of-distribution state); Wayanad 2024 replay (slider 2024-07-15..08-05: IMD vs CHIRPS vs ERA5 series, risk and level per day, honest note that no NASA label exists); Kerala 2018 replay; Evaluation (renders the phase reports' key tables).
- Map rendering with pydeck or plotly (whichever installs cleanly on Python 3.13), no external API keys.

## Dependencies
fastapi, uvicorn, httpx (tests), streamlit, plotly — added to pyproject (`serve` extra) and the lock file.

## Tests
Level mapping and hysteresis sequences; confidence states on crafted rows; blind-escalation rule (incl. MAX-of-sources); reasons completeness; cost–loss arithmetic; API endpoints via TestClient on a tiny fixture store; dashboard import/smoke (functions that build figures from a frame); end-to-end smoke: replay one Kerala 2018 day through features -> hazard -> alerts -> API.
Gate: end-to-end smoke test passes; alerts report written.
