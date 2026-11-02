# AetherGuard Live dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Streamlit dashboard with an industry-grade React + three.js dashboard in the user's fire palette: landing animation, live 3D risk map, alerts with reasons, sensors and data-source health, updated in real time.

**Architecture:** FastAPI gains `/api/*` endpoints (grid, terrain, rain, sources status, SSE stream) over the existing replay store and the future live run outputs; a Vite + React + TS app in `dashboard/` renders the views and is served by FastAPI from `dashboard/dist`.

**Tech Stack:** Python/FastAPI (existing), Node 24, Vite, React 18+, TypeScript, @react-three/fiber + drei + three, Apache ECharts, Framer Motion, TanStack Query, Zustand, Vitest + Testing Library, Fontshare fonts (Clash Display, Satoshi) self-hosted.

**Spec:** `docs/superpowers/specs/2026-10-15-aetherguard-dashboard-design.md`

## Global Constraints
- NO GIT. Python `.venv/Scripts/python`; Node from PATH. Exact palette hex values only: #15110F, #4B1F17, #F0C27B, #F4511E, #D71920 (derived steps by mixing these only).
- Fonts self-hosted woff2 in `dashboard/public/fonts/` (Fontshare ITF Free Font Licence; keep the licence file).
- API binds 127.0.0.1 only; no secrets in the frontend.
- Python tests offline (fixture stores), `-W error`; full Python suite stays green. Frontend: `npm run test` (Vitest) and `npm run build` pass with zero TypeScript errors.
- Data shown is real (replay store / live run); when nothing live exists the UI says "Replay" with the set name — never fake numbers.
- Reduced motion respected everywhere; landing skippable from frame one.
- Do not edit files other builders own in parallel: `src/aetherguard/ingest/*`, `src/aetherguard/hazard/*`, `src/aetherguard/features/*`.

## Review Focus
1. No replay or live data present (fresh install) → the dashboard loads, says so plainly, no crash or blank 3D canvas.
2. WebGL unavailable or very slow GPU → 2D fallback map with the same controls; frame-time watchdog lowers particles and pixel ratio.
3. The SSE stream drops (server restart) → the client reconnects with backoff and shows a "reconnecting" state, then refreshes data.
4. A cell id or date not in the store (deep link) → clear empty state, not an exception.
5. Very many alerts (thousands of Watch cells) → list virtualised, instanced columns stay one draw call, no frame drop below 30 fps.

---

### Task D1: Dashboard API (Python)
**Files:** Create `src/aetherguard/serve/dash_api.py` (router with prefix `/api`), `src/aetherguard/serve/terrain_grid.py` (builds and caches the elevation grid from `data/processed/terrain/cell_terrain.parquet`), modify `src/aetherguard/serve/api.py` (include the router; mount `dashboard/dist` at `/` when it exists; keep existing routes), tests `tests/test_serve_dash_api.py`.
**Interfaces:** endpoints exactly as spec §5. Grid payload: `{date, lead, n, cells: base64(uint32 cell_id), risk: base64(float32), level: base64(uint8), confidence: base64(uint8 0=High 1=Degraded 2=Insufficient), lat0, lon0, step}`; terrain payload: `{rows, cols, lat0, lon0, step, elev: base64(float16 little-endian, NaN = no data)}`; SSE events `run`, `sources`, `heartbeat` (data JSON). Mode resolution: live set (`data/live/` runs or replay-store set `live`) else newest replay set.
- [ ] Tests first (fixture replay store + fake live dir): each endpoint's shapes and dtypes round-trip; empty-store responses (404 with message for grid, mode = `none`); SSE emits `run` when a new run file appears (use a short poll interval in tests) and heartbeats; dist mount serves index.html and does not shadow `/api` or existing routes.
- [ ] Implement; run tests `-W error`; full suite green.

### Task D2: Frontend scaffold, design system, landing animation, app shell
**Files:** `dashboard/` (Vite React TS): `package.json`, `vite.config.ts` (dev proxy `/api` → 127.0.0.1:8765), `src/styles/tokens.css` (palette + type scale + motion tokens), `src/fonts.css`, `public/fonts/*` (Clash Display 600/700, Satoshi 400/500/700 woff2 + licence), `src/app/Shell.tsx` (rail nav, status strip), `src/app/router.tsx` (three routes), `src/data/api.ts` (typed client, base64 decoders), `src/data/stream.ts` (SSE with reconnect/backoff), `src/scene/Landing.tsx` (intro sequence per spec §3), `src/scene/TerrainScene.tsx` (shared canvas, terrain mesh from `/api/terrain`, contour-reveal shader used by the landing), tests under `src/**/*.test.ts(x)`.
- [ ] Tests first: base64 decoders; stream reconnect logic (fake EventSource); landing skip and reduced-motion skip; shell renders the three nav items and the status strip from a mocked `/api/mode`.
- [ ] Implement; `npm run test`, `npm run build` clean; run against the real API and capture screenshots of the landing (three moments) and the shell.

### Task D3: Live 3D risk map view
**Files:** `dashboard/src/views/LiveMap.tsx`, `src/scene/RiskLayer.tsx` (DataTexture heat overlay), `src/scene/AlertColumns.tsx` (instanced columns + Emergency pulse), `src/scene/RainParticles.tsx`, `src/scene/CameraRig.tsx` (fly-to), `src/views/Map2D.tsx` (no-WebGL fallback), `src/scene/perf.ts` (frame-time watchdog), tests.
- [ ] Tests first: grid → texture mapping (cell → texel), level colours exactly the palette, fallback chosen when WebGL is missing, watchdog lowers quality after sustained slow frames.
- [ ] Implement controls (lead switch, timeline scrubber, level filter, region toggle, reset), hover card, click fly-to → opens the alert drawer; `npm run test`/`build`; screenshots at 1440×900 and 1024×768.

### Task D4: Alerts and why view
**Files:** `dashboard/src/views/Alerts.tsx`, `src/components/AlertFeed.tsx` (virtualised), `src/components/AlertDrawer.tsx`, `src/charts/ShapBars.tsx`, `src/charts/SourcesCompare.tsx`, `src/charts/RainHistory.tsx`, `src/charts/RiskTrend.tsx` (ECharts themed to the palette), tests.
- [ ] Tests first: sorting/filtering; drawer content from a fixture `/risk/cell` response; chart option builders produce palette colours and correct series.
- [ ] Implement; `npm run test`/`build`; screenshots.

### Task D5: Sensors and data sources view
**Files:** `dashboard/src/views/Sensors.tsx`, `src/components/GaugeMap.tsx`, `src/components/FaultList.tsx`, `src/components/SourceHealth.tsx`, `src/charts/LatencyHistory.tsx`, tests.
- [ ] Tests first: trust → colour mapping, source status classification (ok / late / failed) from freshness data, live update when the stream emits `sources`.
- [ ] Implement; `npm run test`/`build`; screenshots.

### Task D6: Integration, Streamlit removal, smoke test
**Files:** modify `src/aetherguard/serve/api.py` (serve dist), remove `src/aetherguard/serve/dashboard.py` and `figures.py` with their tests once D3-D5 are accepted, update `README.md`, `configs/pipeline.yaml` (dashboard build stage), add `scripts/start_dashboard.ps1` (build if needed, start API, open browser); browser smoke test script.
- [ ] Full Python suite, `npm run test`, `npm run build`; smoke: start the API, load `/`, skip landing, each view shows real replay data; screenshots desktop and 1024 px.
