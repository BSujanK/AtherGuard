# AetherGuard

A sensor-integrity and landslide / extreme-weather early-warning prototype for the Himalaya and the Western Ghats.
**Research prototype: not validated for issuing real public warnings.**

The two problems it addresses: global rain products badly under-measure extreme orographic rain (on 30 July 2024 the IMD
grid shows 179 mm at Wayanad while CHIRPS shows 0 mm and ERA5 about 67 mm), and the few real gauges that exist are
sometimes silently faulty. AetherGuard first judges whether each sensor reading can be trusted (stage 1), then estimates a
calibrated landslide risk per 0.05 degree cell and day from trusted multi-source rain, soil wetness and terrain (stage 2),
and turns that into alerts that escalate rather than stay silent when the data are blind.

Design: `docs/superpowers/specs/2026-09-30-aetherguard-design.md`; per-phase addenda and controller rulings:
`docs/phase1-design.md` ... `docs/phase4-design.md`. Results: `reports/FINAL_REPORT.md`.

## Architecture

```
 sources                ingest               labels / splits          features
 ───────                ──────               ───────────────          ────────
 GHCN-Daily gauges ──┐
 IMD 0.25° grid ─────┤  imd, chirps,        landslide catalogs ─►   rain accumulations, IMD vs CHIRPS
 CHIRPS 0.05° ───────┼► power, terrain ──►  events -> frozen        disagreement, wetness, terrain
 NASA POWER wetness ─┤  (day-basis aligned) splits (by date)  ───►  (frozen feature store + checksums)
 Copernicus DEM ─────┤                                                       │
 NASA / COOLR / HMA ─┘                                                       │
                                                                             ▼
        ┌───────────────── stage 1: sensor integrity ──────────────┐   ┌─ stage 2 ─────────────────────┐
        │ L1 checks -> LightGBM fault model -> arbiter -> repair   │   │ hazard model (LightGBM,       │
        │ trained on faults injected into real gauge series;       ├──►│ calibrated, ensemble spread)  │
        │ out-of-fold trust per station-day (integ_ features)      │   │ extreme-rain corrector        │
        └──────────────────────────────────────────────────────────┘   │ (corr_ features, quantiles)   │
                                                                       └──────────────┬────────────────┘
                                                                                      ▼
                                              alert engine: Normal / Watch / Warning / Emergency, hysteresis,
                                              data-confidence flag, blind-escalation, reasons (SHAP, sources, trust)
                                                                                      ▼
                                                                  read-only API (FastAPI) + dashboard (React, served by the API)
```

Layout: `src/aetherguard/{audit,ingest,events,splits,features,integrity,corrector,hazard,cases,alerts,serve,pipeline,finalreport}`,
the dashboard app in `dashboard/`, configs in `configs/`, frozen data under `data/` (git-ignored), reports in `reports/`, tests in `tests/`.

## Setup (Git Bash on Windows, Python 3.13)

```
py -3.13 -m venv .venv
.venv/Scripts/python -m pip install -e ".[serve,audit,dev]"
```

The `serve` extra (fastapi, uvicorn, httpx2 for the API tests) is declared in `pyproject.toml`. The dashboard needs Node.js 24 and npm
to build (`cd dashboard && npm ci`). A NASA Earthdata login in `~/_netrc` (Windows) or `~/.netrc`
(entry for `urs.earthdata.nasa.gov`) is only needed to re-download the High Mountain Asia / NASA label catalogs; everything
else is open. Data lives in `data/` (set `AETHERGUARD_DATA_DIR` to relocate it).

## Running the pipeline

All stages are module CLIs listed in order in `configs/pipeline.yaml` (module names live there, not in the runner).

```
.venv/Scripts/python -m aetherguard.pipeline status                 # outputs present, frozen-manifest check, last run per stage
.venv/Scripts/python -m aetherguard.pipeline run --dry-run          # what would run / be reused / be skipped
.venv/Scripts/python -m aetherguard.pipeline run                    # everything, stopping at the first failure
.venv/Scripts/python -m aetherguard.pipeline run --from features --to integrity_engine
.venv/Scripts/python -m aetherguard.pipeline run --only corrector --force
.venv/Scripts/python -m aetherguard.pipeline run --offline          # skip network stages unless their outputs exist
.venv/Scripts/python -m aetherguard.finalreport                     # reports/FINAL_REPORT.md from the phase reports
```

Each stage runs as a subprocess; its log is `logs/pipeline/<stage>.log` and every run is recorded in
`logs/pipeline/run_<timestamp>.json`. Stages whose outputs are frozen (checksummed manifests) and verify intact, or whose
completion markers exist, are reported as *reused*; `--force` reruns them. The Phase 0 audit (`audit`) is skipped unless named
(`--include audit`). Frozen outputs (splits, samples, features, integ and corrector tables) are read-only and are only
replaced deliberately with the stage's own `--force`.

## Serving and the dashboard

```
.venv/Scripts/python -m aetherguard.alerts.replay                      # build the replay store (alerts_replay stage)
powershell -File scripts/start_dashboard.ps1                           # build if needed, start the API, open the browser
powershell -File scripts/start_dashboard.ps1 -Stop                     # stop the API that script started
.venv/Scripts/python -m aetherguard.serve.api --port 8790              # the API alone (binds 127.0.0.1 only)
```

`scripts/start_dashboard.ps1` builds `dashboard/dist` (`npm ci` when `node_modules` is missing, then `npm run build`) when it is
missing or older than the sources, starts the API on `127.0.0.1:8790` hidden, records its process id in `data/run/dashboard.pid`,
waits until `/api/mode` answers and opens `http://127.0.0.1:8790/`. If something already answers there it only opens the
browser. `-Stop` stops only the process in the pid file. API output goes to `logs/dashboard_api.*.log`. The pipeline stage
`dashboard_build` does the same build (`npm ci && npm run build`; `--offline` skips `npm ci`).

Local hosting: the Windows scheduled task **AetherGuard dashboard** runs `scripts/start_dashboard.ps1 -Serve` one minute
after logon: it rebuilds the app if the sources changed (keeping the previous build if that fails) and runs the API in the
foreground, supervised by Task Scheduler (no time limit, restarted after a crash). The dashboard is therefore served at
`http://127.0.0.1:8790/` after every restart (localhost only). With the task present, `start_dashboard.ps1` starts the task
and `-Stop` stops it and the server it runs. Remove it with `Unregister-ScheduledTask -TaskName 'AetherGuard dashboard'`.

The API serves the built app at `/` (client routes `/map`, `/alerts-why`, `/sensors-sources` load it) next to the JSON routes
`/api/*`, `/risk`, `/sensors`, `/alerts`, `/health` and `/docs`. It is read-only and bound to localhost (`AETHERGUARD_REPLAY_DIR`
points it at another replay store).

**Data mode.** The status strip says what the dashboard is showing. *Live* is the newest live run under `data/live/<date>/`
(or a replay set named `live`); with no live run it shows the newest replay set, labelled *Replay* with the set name. With no
data at all it says so. The scheduled daily run (`scripts/install_daily_task.ps1`, 11:00 IST) writes a new live run; the open
dashboard learns about it over a server-sent stream and refreshes, and the strip shows the next scheduled run.

**The three views.**
- *Live map*: the domain terrain in 3D with the risk of each 0.05 degree cell, columns on cells at Watch and above, and rain
  streaks from the day's rain. Controls: lead D0 and D+1 to D+3 (forecast leads exist only for live runs that have them),
  date scrubber, level filter, region toggle (Himalaya / Western Ghats), reset. Hover shows the cell, risk, confidence and, for
  a level above the risk band, why; click flies to the cell and opens its explanation. Without WebGL a 2D map with the same
  controls is drawn.
- *Alerts and why*: the alert feed (sortable, filterable) and, per cell, level and confidence with their causes, the top model
  inputs (SHAP), the rain sources side by side, and the 30-day rain and risk history.
- *Sensors and sources*: rain gauges coloured by trust with their fault types, and the health of each data source (last
  success, data valid through, latency, ok / late / failed).

Intro: a short landing animation plays once per session; **Skip intro** is visible from the first frame, and reduced-motion
settings skip it.

**Developing the dashboard.** `cd dashboard`, then `npm ci`, `npm run dev` (Vite on `http://localhost:5173`, proxying the API
to `127.0.0.1:8790`; set `AETHERGUARD_API_ORIGIN` to point at another API), `npm run test` (Vitest), `npm run build`
(type-checks, then writes `dist/`). `npm run smoke -- http://127.0.0.1:8790` drives the built app in headless Chromium
(Playwright): each view must show real data, an alert drawer must open, and there must be no console error or 5xx.

## Tests

```
.venv/Scripts/python -m pytest -W error                # default: offline and hermetic (synthetic fixtures)
.venv/Scripts/python -m pytest -m realdata             # builds / checks against the real data under data/
.venv/Scripts/python -m pytest -m live                 # hits real network sources (Open-Meteo, NOAA, ...)
```

Markers: `live` (network) and `realdata` (needs the real data tree) are excluded by default (`addopts` in `pyproject.toml`).
New code is test-first; new tests are also run once with `-W error` so output stays pristine. The dashboard has its own tests
(`cd dashboard && npm run test`).

## Verification

Alerts are checked against landslide events with tolerance matching (10 km, 1 day, or the same cell and day), with
bootstrap intervals, and against two simple models of the same alert burden (3-day rain cuts, a static susceptibility map).
The live ledger scores every published day of `data/live` the same way against landslides people reported, for each lead
0 to 3; days within 14 days of today are marked provisional because reports are still arriving.

```
.venv/Scripts/python -m aetherguard.verify baseline    # reports/phase7_verification_baseline.{json,md}: development seasons and 2018
.venv/Scripts/python -m aetherguard.verify ledger      # reports/live_verification.{json,md}: published alerts vs reported events
```

Reported events are CSV files in `data/raw/manual/reported_events/` (local only, like all of `data/`), one header for every file:

```
date,latitude,longitude,location_text,source_url,accuracy_km
2026-10-22,30.4,79.3,Chamoli,https://example.org/report,2
```

`date` is the IST date (YYYY-MM-DD); the point must lie inside a region of `configs/domain.yaml`; `source_url` is required;
`accuracy_km` may be empty. A bad row stops the ledger with the file and line. An empty folder is valid: events 0, detection
n/a, alert cell-days still counted. `--today YYYY-MM-DD` overrides the IST date.

## Reports

| file | content |
|---|---|
| `reports/FINAL_REPORT.md` / `.json` | assembled final report: every number read from the sources below, `pending:` for what is not produced yet |
| `reports/phase0_data_audit.*`, `phase0_findings.md` | what each data source really provides (measured) |
| `reports/phase2a_baselines.*` | injected-fault dataset, L1 checks, baselines, false-flag rates on real clean days |
| `reports/phase2b_day_basis.*` | which day a gauge value belongs to (lag correlation vs IMD / CHIRPS) |
| `reports/phase2_integrity_report.*` | stage 1: engine vs baselines, arbiter, repair, ablations, out-of-fold outputs |
| `reports/phase3_corrector_report.*` | extreme-rain corrector, Wayanad check |
| `reports/phase3_hazard_report_v1.*`, `phase3_hazard_*` | hazard model v1 (disclosed history) and v2 |
| `reports/phase3e_case_inputs.*` | ERA5 point series, D5 approximation error, Wayanad focus table |
| `reports/phase4_alerts_report.*` | alert engine evaluation and case replays (when produced) |
| `reports/phase7_verification_baseline.*` | v3 against rain and susceptibility baselines, tolerance-matched, development and 2018 |
| `reports/live_verification.*` | published live alerts against reported landslides, by lead and level, recent days provisional |

## Data licences

| source | terms |
|---|---|
| NOAA GHCN-Daily | NOAA NCEI open data (public domain) |
| IMD gridded rainfall | IMD data terms; verify before redistribution |
| CHIRPS v2.0 | see https://www.chc.ucsb.edu/data/chirps; verify terms |
| NASA POWER / MERRA-2 | NASA open data |
| Copernicus DEM GLO-90 | free to use with attribution (ESA / Copernicus); verify terms before redistribution |
| Open-Meteo archive, ERA5 / ERA5-Land | Open-Meteo CC BY 4.0; ERA5 Copernicus Climate Change Service (CC BY 4.0) |
| NASA Global Landslide Catalog, COOLR, High Mountain Asia catalog | NASA / NSIDC terms (Earthdata login for some) |
| GeoNames (event locations) | CC BY 4.0; credit GeoNames |
| OpenStreetMap via Nominatim (event locations) | ODbL; credit "© OpenStreetMap contributors" |
| LHASA v2 landslide nowcast | NASA open data (GES DISC); cite Stanley et al. 2021 |

Every downloaded file is recorded with its source, URL and licence in `manifests/data_manifest.jsonl`.
