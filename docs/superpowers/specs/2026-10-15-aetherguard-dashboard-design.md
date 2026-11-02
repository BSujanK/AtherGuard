# AetherGuard Live dashboard — design spec

Date: 2026-10-15. Status: approved in conversation ("Yes that's good, add a related landing animation"). No git.
Replaces the Streamlit dashboard (`src/aetherguard/serve/dashboard.py`) once these views cover it.

## 1. Decisions taken with the user
| Question | Decision |
|---|---|
| Stack | Vite + React + TypeScript, react-three-fiber (three.js) for 3D, Apache ECharts for charts, Framer Motion for UI motion; built once and served by the existing FastAPI |
| Streamlit | Replaced |
| Views | Live 3D risk map; Alerts and why; Sensors and data sources |
| Visual system | Pinned palette (below); premium fonts; 3D renderings and motion graphics |
| Extra | A landing animation (cinematic intro) before the live map |

## 2. Visual system
Palette (pinned by the user):

| Token | Hex | Role |
|---|---|---|
| `--smoke-black` | #15110F | base background |
| `--burnt-brown` | #4B1F17 | surfaces, panels, depth (with darker/lighter steps derived from it) |
| `--sand` | #F0C27B | primary text on dark, Watch level |
| `--flame-orange` | #F4511E | lead accent, active controls, Warning level |
| `--fire-red` | #D71920 | Emergency level, errors |

Derived steps only by mixing these five (no new hues): sand at 60% / 40% opacity for secondary text, burnt-brown lifted 6% and 12% toward sand for raised surfaces, smoke-black lifted for borders. Normal level uses burnt-brown lifted (calm, no colour shout). Contrast: body text ≥ 4.5:1 on its surface (sand on smoke-black passes).

Type (self-hosted woff2, Fontshare, free licence): **Clash Display** (600/700) for headings, numbers on the map and the landing wordmark; **Satoshi** (400/500/700) for UI and data with tabular numerals. No monospace costume.

Motion grammar: one orchestrated landing sequence; elsewhere motion answers the user (lead switch, cell fly-to, panel open) with exponential ease-out (cubic-bezier(.16,1,.3,1)) 280-600 ms; Emergency cells pulse slowly (2.4 s). `prefers-reduced-motion` turns every animation into an instant state change and skips the landing sequence.

## 3. Landing animation
A single cinematic intro (about 4.5 s, skippable, shown once per session, skipped under reduced motion or on direct deep links):
1. Darkness with rising ember particles (Flame Orange / Sand, additive glow) and faint rain streaks.
2. The domain terrain draws itself as glowing contour lines (shader reveal from low to high elevation) over smoke-black.
3. The wordmark "AetherGuard" assembles letter by letter in Clash Display with a subtle heat-shimmer distortion; a one-line tagline fades in: "Landslide risk for every 5 km of the Himalaya and the Western Ghats, every morning."
4. The contours fill into the shaded terrain, the risk layer blooms in, and the camera dives into the live map; the UI chrome slides in. A "Skip intro" control is visible from the first frame.
Built in the same three.js scene as the live map (no separate video), so the transition is continuous.

## 4. Views
App shell: left navigation rail (three views), a top status strip (data mode Live / Replay, last run time, next scheduled run, counts by level and by confidence), keyboard navigable.

### 4.1 Live 3D risk map (home)
- Full-bleed terrain mesh of the domain (lat 8-36 °N, lon 72-98 °E) from the project's cell terrain statistics (elevation per 0.05° cell), with vertical exaggeration; risk drawn as a heat texture (levels in the palette) on the terrain; alert cells (Watch and above) as instanced glowing columns whose height encodes risk; Emergency pulses.
- Rain layer: animated particles whose density follows the day's rain (IMERG IMD-day accumulation) on a coarse grid.
- Controls: lead switch D0 / D+1 / D+2 / D+3 (forecast leads labelled as less certain), date timeline scrubber (last 30 days of runs plus forecast), level filter, region toggle (Himalaya / Western Ghats), reset view.
- Hover shows cell id, place coordinates, level, risk, confidence; click flies the camera to the cell and opens its detail in the Alerts view drawer.
- Without WebGL: a 2D canvas map with the same data and controls.

### 4.2 Alerts and why
- Live alert feed (virtualised list), sortable by level, risk, confidence, region; new alerts animate in when the stream reports a new run.
- Detail drawer per cell: level and confidence with causes; SHAP top-5 contribution bar chart; rain sources side by side for D (IMERG, IMD real-time, nearest trusted gauge, GFS for forecast leads); 30-day rain history and risk trend charts; a small 3D view of the cell's neighbourhood.

### 4.3 Sensors and data sources
- Gauge map (3D or 2D) with trust colour (sand → orange → red for low trust), flagged gauges pulse, fault type on hover; fault list with time and type.
- Source health panel: for IMERG Late, IMERG Early, GFS, IMD real-time, GHCN gauges — last success, data valid through, latency, status (ok / late / failed), and a latency history chart; updates live from the stream.

## 5. Data and API (FastAPI, prefix `/api`)
Existing endpoints keep working (`/health`, `/risk`, `/risk/cell/{id}`, `/sensors`, `/alerts`); new ones:
- `GET /api/mode` → `{mode: "live"|"replay", set, latest_date, dates}` (live set if present, else the newest replay set, clearly labelled).
- `GET /api/grid?date=&lead=0..3` → compact risk grid for all cells (typed arrays as base64 or binary: cell index, risk, level, confidence) for one day and lead.
- `GET /api/terrain` → static elevation grid for the domain (binary float16 + shape + bbox), cached.
- `GET /api/rain?date=` → coarse rain field for the particle layer.
- `GET /api/sources/status` → per-source freshness from the newest run's `freshness.json` (or a clear "no live run yet").
- `GET /api/stream` → Server-Sent Events: `run` (a new day's run landed), `sources` (freshness changed), `heartbeat` (every 15 s). Implemented by watching `data/live/` and the replay store manifest.
- FastAPI serves the built app (`dashboard/dist`) at `/`; binding stays 127.0.0.1.

## 6. Engineering
- `dashboard/` (Vite + React + TS), `npm run build` → `dashboard/dist`; `npm run dev` proxies `/api` to 127.0.0.1:8765.
- State: TanStack Query for data, a small store (Zustand) for view state; SSE invalidates queries.
- Performance: terrain about 290k vertices with one draw call; instanced columns; DataTexture updates on date/lead change; target 60 fps on the laptop, degrade particle counts and pixel ratio automatically when frame time is high.
- Accessibility: keyboard navigation, visible focus in Flame Orange, ARIA labels, text alternatives for the 3D map (list of top alerts), reduced motion respected.
- Tests: Vitest + React Testing Library for components and data adapters; pytest for every new endpoint (fixture stores); a browser smoke test (built app loads, landing skip works, each view renders data from a fixture API).
- Streamlit removal after the three views pass review; README and pipeline config updated.

## 7. Out of scope
Model and case-replay views (not chosen), public hosting, authentication, mobile phone layout beyond a readable fallback.

## 8. Amendment (2026-10-16, user request): whole-India map and a new theme
User: "in the 3D map show the entire india, change the theme to INK black as bg, NEON Cyan, royal blue, fire red and Flame orange and neon lime".

**Palette (replaces §2)** — exact values chosen by the controller where the user gave names only:

| Token | Hex | Role |
|---|---|---|
| `--ink-black` | #0A0B10 | page and scene background |
| `--neon-cyan` | #00F0FF | accent: active controls, focus ring, selection, contours, rain particles, headings accents |
| `--royal-blue` | #4169E1 | surfaces/panels (mixed toward ink), borders (alpha), Normal risk level |
| `--neon-lime` | #C6FF00 | Watch level |
| `--flame-orange` | #F4511E | Warning level |
| `--fire-red` | #D71920 | Emergency level, errors (never body text: about 3.9:1 on ink) |
| `--text` | #E6FBFF | body text (cyan-tinted near-white; neon cyan is too tiring for paragraphs) |

Derived steps only by mixing these. Contrast: body text ≥ 4.5:1 on its surface. Level ramp cool→hot: Normal royal blue (dimmed), Watch lime, Warning orange, Emergency red. Landing embers become cyan/lime sparks with occasional orange; the motion grammar is unchanged.

**Map extent (amends §4.1)**: the 3D map shows the whole of India (official India point-of-view national outline incl. J&K, Ladakh, Arunachal Pradesh, Andaman & Nicobar and Lakshadweep) plus Nepal and Bhutan, as a public-domain relief base layer on the same 0.05° global grid as the risk cells. Risk colours and alert columns appear only on the modelled candidate cells (36,792; Himalaya and Western Ghats); other land is drawn as terrain marked "not modelled" in the legend. All-India risk is Stage B, not faked here.
