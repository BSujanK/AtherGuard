# AetherGuard Phase 0 — Foundation and Data Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the project foundation (environment, grid, checksummed downloader, catalog and station readers) and a data-audit tool that probes every planned real-data source and writes an evidence report, so Phase 1 is planned against verified facts.

**Architecture:** A small installable Python package (`aetherguard`) with shared primitives (config, 0.05° grid, manifest, resilient downloader) and an `audit` subpackage. Each audit probe returns a uniform `ProbeResult`; a runner executes all probes (never aborting on one failure), then renders a Markdown + JSON report. Phase 0 ends at a **human gate**: the user reads the report and decides which sources to keep, replace, or drop.

**Tech Stack:** Python 3.13 (project-local `.venv`), numpy, pandas, pyarrow, pyyaml, requests, rasterio, shapely, pyproj, pytest. Audit-only extras: xarray, zarr, s3fs, fsspec, imdlib.

**Spec:** `docs/superpowers/specs/2026-09-30-aetherguard-design.md` (Phase 0 is spec §11 row 0; data sources are spec §4).

## Global Constraints

- Windows 11, 16 GB RAM, no dedicated GPU detected, ~218 GB free disk; raw data capped at ~60 GB. (Spec §2)
- Python 3.13; project-local `.venv`; the global Python is never modified. (Spec §2, §12)
- Everything lives under the project root (note the spelling). (User instruction)
- Real-world data only — no synthetic or simulated data is downloaded or used in this phase. Test fixtures may be synthetic; audit results never are. (Spec §1)
- Grid: 0.05° cells anchored on the CHIRPS pixel grid; domain = Himalaya + Western Ghats; period 2007-01-01 to 2024-12-31. (Spec §2)
- Timestamps normalised to UTC; units and ranges validated on ingest; missing data explicit, never silently filled or dropped. (Spec §4.5)
- A manifest records every downloaded file with source URL, date, size, licence and SHA-256 checksum. (Spec §4.5)
- Secrets (Earthdata credentials) are supplied via environment variable or `.netrc`, never committed, never written to reports or logs. (Spec §15)
- No modelling and no use of landslide labels for anything except counting in this phase. (Spec §11 gate for Phase 0)
- `data/`, `.venv/` are git-ignored; `manifests/`, `reports/`, `configs/` are tracked. (Spec §12)
- Commit messages end with the attribution trailer given in the session's attribution instructions.
- Commands are written for Git Bash; in PowerShell replace `.venv/Scripts/python` with `.venv\Scripts\python`.

## Review Focus

Failure modes the spec implies but no headline requirement exercises. Each has a pinning test in the task that owns the code.

1. **0.05° cell-edge float error.** A coordinate that sits exactly on a cell edge (e.g. lat 11.55) must land in the same cell every time. → `tests/test_grid.py::test_every_cell_edge_maps_to_its_own_index` (Task 2).
2. **GHCN-Daily sentinel and flag semantics.** `-9999` must never become a rainfall value; flagged values are retained with their flag; February/leap-year phantom days must not appear. → `tests/test_ghcnd.py` (Task 4).
3. **Hand-exported catalog quirks.** A UTF-8 BOM, ambiguous `03/04/2013` dates, `unknown` accuracy, blank or (0, 0) coordinates must produce either correctly counted results or a loud error — never silently dropped or mis-dated rows. → `tests/test_landslides.py` (Task 5).
4. **Partial downloads and re-runs.** A truncated file must leave no data file and no manifest entry; a re-run must not re-download a verified file. → `tests/test_http.py` (Task 3).
5. **Rain "day" boundaries differ between products** (UTC day vs. IMD 08:30 IST day vs. POWER local-solar-time day) — a 3–5.5 hour shift moves overnight rain, such as the Wayanad 2024 slide night, into a different day. Every rain probe must state its day definition and the report must show it beside the numbers. → `tests/test_rain.py` (Task 6) and `tests/test_report.py` (Task 9).

## File Structure

```
pyproject.toml   .gitignore   README.md
configs/domain.yaml            # regions, period, cell size
configs/audit.yaml             # reference point, event dates, thresholds, provider limits
manifests/data_manifest.jsonl  # created by the audit run (tracked)
reports/phase0_data_audit.{md,json}   # created by the audit run (tracked)
src/aetherguard/
  __init__.py
  config.py        # PROJECT_ROOT, data_root(), data_dir(), load_config()
  grid.py          # 0.05° cell ids, centres, neighbours, region labels, domain cell counts
  manifest.py      # sha256_file, ManifestEntry, Manifest (append-only JSONL)
  http.py          # DownloadError, fetch_json (retrying), download (atomic, checksummed)
  audit/
    __init__.py
    result.py      # ProbeResult, STATUSES, failure_status
    ghcnd.py       # GHCN-Daily parsing, station selection, flag census, ISD history, probes
    landslides.py  # tolerant catalog CSV reader + summary
    rain.py        # Open-Meteo, NASA POWER (API + zarr), CHIRPS, IMD probes
    static.py      # DEM, WorldCover, SoilGrids, OSM road-extract probes + tile arithmetic
    zenodo.py      # Zenodo record/search probes (Nepal inventories, Gaolan, lithology, Kerala)
    env.py         # geospatial libs, disk, Earthdata-credential presence probes
    labels.py      # manual catalog file probes (NASA GLC, HMA v2)
    feasibility.py # ingest call/volume scenarios (Open-Meteo weighting etc.)
    report.py      # redaction, Markdown + JSON rendering
    run.py         # probe registry, safe execution, CLI
tests/
  conftest.py  test_smoke.py  test_config.py  test_grid.py  test_manifest.py  test_http.py
  test_ghcnd.py  test_landslides.py  test_result.py  test_rain.py  test_static.py
  test_zenodo.py  test_env.py  test_labels.py  test_feasibility.py  test_report.py  test_runner.py
  live/test_live_sources.py   # marked `live`, hits real network, excluded by default
```

---

### Task 1: Project scaffold and environment

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `README.md`, `src/aetherguard/__init__.py`
- Test: `tests/test_smoke.py`

**Interfaces:**
- Produces: installable package `aetherguard` (version string `aetherguard.__version__ == "0.1.0"`); pytest configured with a `live` marker excluded by default.

- [ ] **Step 1: Write the failing test**

Create `tests/test_smoke.py`:

```python
import aetherguard


def test_package_imports_and_has_version():
    assert aetherguard.__version__ == "0.1.0"
```

- [ ] **Step 2: Create the environment and confirm the test fails**

Run:
```bash
cd /c/Users/sujan/AtherGuard
py -3.13 -m venv .venv
.venv/Scripts/python -m pip install --upgrade pip
.venv/Scripts/python -m pip install pytest pyyaml
.venv/Scripts/python -m pytest tests/test_smoke.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'aetherguard'` (package not created/installed yet).

- [ ] **Step 3: Create the scaffold**

`pyproject.toml`:
```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "aetherguard"
version = "0.1.0"
description = "AetherGuard: sensor-integrity and landslide / extreme-weather early-warning prototype"
requires-python = ">=3.13,<3.14"
dependencies = [
  "numpy>=2.2",
  "pandas>=2.3",
  "pyarrow>=23.0",
  "pyyaml>=6.0",
  "requests>=2.32",
  "rasterio>=1.4.3",
  "shapely>=2.0",
  "pyproj>=3.7",
]

[project.optional-dependencies]
audit = ["xarray", "zarr", "s3fs", "fsspec", "imdlib"]
dev = ["pytest>=8.3"]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["live: hits real network sources (excluded by default; run with -m live)"]
addopts = "-m 'not live'"
```

`.gitignore`:
```
.venv/
data/
__pycache__/
*.pyc
.pytest_cache/
*.egg-info/
.env
```

`README.md`:
```markdown
# AetherGuard

Sensor-integrity and landslide / extreme-weather early-warning prototype for the Himalaya and Western Ghats.
Research prototype - not for issuing real public warnings.

Design: `docs/superpowers/specs/2026-09-30-aetherguard-design.md`
Plans:  `docs/superpowers/plans/`

Setup (Git Bash):

    py -3.13 -m venv .venv
    .venv/Scripts/python -m pip install -e ".[dev,audit]"
    .venv/Scripts/python -m pytest
```

`src/aetherguard/__init__.py`:
```python
"""AetherGuard: sensor-integrity and landslide / extreme-weather early-warning prototype."""

__version__ = "0.1.0"
```

- [ ] **Step 4: Install the package with all extras and verify the geospatial stack**

Run:
```bash
.venv/Scripts/python -m pip install -e ".[dev,audit]"
.venv/Scripts/python -c "import rasterio, shapely, pyproj, pyarrow, pandas, numpy; print('rasterio', rasterio.__version__, 'GDAL', rasterio.__gdal_version__)"
.venv/Scripts/python -m pytest tests/test_smoke.py -v
```
Expected: the import line prints a rasterio and GDAL version; pytest reports `1 passed`.
If any package fails to install or import: **STOP and report the exact pip/import error to the user. Do not substitute libraries or improvise** — this is the spec's "geospatial libraries on Python 3.13" check and a Phase 0 finding.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .gitignore README.md src tests
git commit -m "chore: scaffold aetherguard package and environment"
```

---

### Task 2: Configuration, grid and domain

**Files:**
- Create: `configs/domain.yaml`, `configs/audit.yaml`, `src/aetherguard/config.py`, `src/aetherguard/grid.py`, `tests/conftest.py`
- Test: `tests/test_config.py`, `tests/test_grid.py`

**Interfaces:**
- Produces:
  - `config.PROJECT_ROOT: Path`; `config.data_root() -> Path` (honours env `AETHERGUARD_DATA_DIR`); `config.data_dir(*parts: str) -> Path` (creates); `config.load_config(name: str) -> dict`.
  - `grid.CELL_DEG=0.05`, `grid.ID_STRIDE=10_000`; `grid.latlon_to_cell(lat, lon) -> int | np.ndarray[int64]`; `grid.cell_center(cell_id) -> (lat, lon)`; `grid.neighbours(cell_id: int) -> list[int]`; `grid.region_labels(lat, lon) -> np.ndarray[object]` (`""` outside every region); `grid.region_of(lat: float, lon: float) -> str`; `grid.domain_cell_counts(cell_deg: float) -> dict[str, int]`.
  - `conftest.isolated_data_root` fixture (sets `AETHERGUARD_DATA_DIR` to a temp dir, returns the `Path`).

- [ ] **Step 1: Write the failing tests**

`tests/conftest.py`:
```python
import pytest


@pytest.fixture
def isolated_data_root(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("AETHERGUARD_DATA_DIR", str(root))
    return root
```

`tests/test_config.py`:
```python
from aetherguard import config


def test_project_root_contains_pyproject():
    assert (config.PROJECT_ROOT / "pyproject.toml").exists()


def test_data_dir_honours_override_and_creates(isolated_data_root):
    path = config.data_dir("raw", "x")
    assert path == isolated_data_root / "raw" / "x"
    assert path.is_dir()


def test_load_config_domain_has_regions_and_period():
    cfg = config.load_config("domain")
    assert cfg["cell_size_deg"] == 0.05
    assert set(cfg["regions"]) == {"himalaya", "western_ghats"}
    assert cfg["period"] == {"start": "2007-01-01", "end": "2024-12-31"}
```

`tests/test_grid.py`:
```python
import numpy as np
import pytest

from aetherguard import grid


def test_known_cell_and_center():
    cid = grid.latlon_to_cell(11.55, 76.13)
    assert cid == 2031 * 10_000 + 5122
    lat_c, lon_c = grid.cell_center(cid)
    assert lat_c == pytest.approx(11.575)
    assert lon_c == pytest.approx(76.125)


def test_every_cell_edge_maps_to_its_own_index():
    # Regression for binary floating-point error at exact cell edges.
    k = np.arange(0, 3600)
    lat_edges = -90.0 + k * 0.05
    assert (grid.latlon_to_cell(lat_edges, np.zeros(k.shape)) // grid.ID_STRIDE == k).all()
    j = np.arange(0, 7200)
    lon_edges = -180.0 + j * 0.05
    assert (grid.latlon_to_cell(np.zeros(j.shape), lon_edges) % grid.ID_STRIDE == j).all()


def test_just_below_an_edge_stays_in_lower_cell():
    assert grid.latlon_to_cell(11.5499, 76.13) // grid.ID_STRIDE == 2030


def test_negative_coordinates_round_trip_within_half_a_cell():
    cid = grid.latlon_to_cell(-33.9, -70.65)
    lat_c, lon_c = grid.cell_center(cid)
    assert abs(lat_c + 33.9) <= 0.025 + 1e-9
    assert abs(lon_c + 70.65) <= 0.025 + 1e-9


@pytest.mark.parametrize("lat,lon", [(90.0, 0.0), (-91.0, 0.0), (0.0, 180.0), (0.0, -181.0)])
def test_out_of_range_coordinates_rejected(lat, lon):
    with pytest.raises(ValueError):
        grid.latlon_to_cell(lat, lon)


def test_neighbours_interior_and_pole_edge():
    cid = grid.latlon_to_cell(11.55, 76.13)
    n = grid.neighbours(cid)
    assert len(n) == 8 and len(set(n)) == 8 and cid not in n
    top = grid.latlon_to_cell(89.99, 10.0)
    assert len(grid.neighbours(top)) == 5


def test_neighbours_wrap_across_the_antimeridian():
    cid = grid.latlon_to_cell(0.0, 179.99)
    assert 0 in {n % grid.ID_STRIDE for n in grid.neighbours(cid)}


def test_region_labels():
    labels = grid.region_labels([11.55, 27.7, 0.0], [76.13, 85.3, 0.0])
    assert list(labels) == ["western_ghats", "himalaya", ""]
    assert grid.region_of(11.55, 76.13) == "western_ghats"


def test_domain_cell_counts():
    fine = grid.domain_cell_counts(0.05)
    assert fine == {"himalaya": 145_600, "western_ghats": 32_400, "total": 178_000}
    coarse = grid.domain_cell_counts(0.25)
    assert coarse == {"himalaya": 5_824, "western_ghats": 1_296, "total": 7_120}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_config.py tests/test_grid.py -v`
Expected: FAIL/ERROR — `ImportError: cannot import name 'config'` / `grid`.

- [ ] **Step 3: Write the implementation**

`configs/domain.yaml`:
```yaml
# Region boxes are coarse selection windows; terrain and country filters refine them in Phase 1.
cell_size_deg: 0.05
period:
  start: "2007-01-01"
  end: "2024-12-31"
regions:
  himalaya:
    lat_min: 22.0
    lat_max: 36.0
    lon_min: 72.0
    lon_max: 98.0
  western_ghats:
    lat_min: 8.0
    lat_max: 21.5
    lon_min: 72.5
    lon_max: 78.5
```

`configs/audit.yaml`:
```yaml
reference_point:
  name: wayanad_meppadi
  lat: 11.55
  lon: 76.13
event_dates: ["2024-07-28", "2024-07-29", "2024-07-30", "2024-07-31"]
# Secondary source (press / papers); to be checked against a primary source before it is quoted.
reported_local_gauge_48h_mm: 572
ghcnd:
  countries: ["IN", "NP"]
  first_year_max: 2015
  last_year_min: 2024
  upland_min_elev_m: 500
catalog:
  max_accuracy_km: 5.0
  manual_files:
    nasa_glc: "raw/manual/nasa_glc.csv"
    hma_ls_cat: "raw/manual/hma_ls_cat_v2.csv"
disk:
  min_free_gb: 100
# Free-tier limits from https://open-meteo.com/en/pricing (checked 2026-09-30): 10,000 calls/day;
# a call is weighted by max(1, days/14) * max(1, variables/10).
open_meteo:
  free_calls_per_day: 10000
  days_per_call_unit: 14
  vars_per_call_unit: 10
```

`src/aetherguard/config.py`:
```python
"""Project paths and YAML config loading."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def data_root() -> Path:
    """Root of the git-ignored data tree; override with AETHERGUARD_DATA_DIR (used by tests)."""
    override = os.environ.get("AETHERGUARD_DATA_DIR")
    return Path(override) if override else PROJECT_ROOT / "data"


def data_dir(*parts: str) -> Path:
    path = data_root().joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_config(name: str) -> dict:
    path = PROJECT_ROOT / "configs" / f"{name}.yaml"
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)
```

`src/aetherguard/grid.py`:
```python
"""0.05-degree global grid anchored on the CHIRPS pixel grid, plus domain regions."""
from __future__ import annotations

import numpy as np

from .config import load_config

CELL_DEG = 0.05
ID_STRIDE = 10_000  # cell_id = lat_index * ID_STRIDE + lon_index
LAT_ROWS = 3600
LON_COLS = 7200


def _axis_index(values, origin: float) -> np.ndarray:
    # Round before flooring so a coordinate sitting exactly on a cell edge
    # (e.g. 11.55 = -90 + 2031 * 0.05) cannot fall into the wrong cell through
    # binary floating-point error. Coordinates within ~5e-8 degrees below an edge snap up.
    scaled = (np.asarray(values, dtype=float) - origin) / CELL_DEG
    return np.floor(np.round(scaled, 6)).astype(np.int64)


def latlon_to_cell(lat, lon):
    lat_a = np.asarray(lat, dtype=float)
    lon_a = np.asarray(lon, dtype=float)
    if (
        np.any(lat_a < -90.0) or np.any(lat_a >= 90.0)
        or np.any(lon_a < -180.0) or np.any(lon_a >= 180.0)
    ):
        raise ValueError("latitude must be in [-90, 90) and longitude in [-180, 180)")
    ids = _axis_index(lat_a, -90.0) * ID_STRIDE + _axis_index(lon_a, -180.0)
    return int(ids) if ids.ndim == 0 else ids


def cell_center(cell_id):
    ids = np.asarray(cell_id, dtype=np.int64)
    lat = -90.0 + (ids // ID_STRIDE + 0.5) * CELL_DEG
    lon = -180.0 + (ids % ID_STRIDE + 0.5) * CELL_DEG
    if ids.ndim == 0:
        return float(lat), float(lon)
    return lat, lon


def neighbours(cell_id: int) -> list[int]:
    """The (up to) 8 surrounding cells; longitude wraps, latitude does not."""
    ilat, ilon = divmod(int(cell_id), ID_STRIDE)
    out: list[int] = []
    for dlat in (-1, 0, 1):
        for dlon in (-1, 0, 1):
            if dlat == 0 and dlon == 0:
                continue
            nlat = ilat + dlat
            if not 0 <= nlat < LAT_ROWS:
                continue
            out.append(nlat * ID_STRIDE + (ilon + dlon) % LON_COLS)
    return out


def regions() -> dict[str, dict[str, float]]:
    return load_config("domain")["regions"]


def region_labels(lat, lon) -> np.ndarray:
    """Region name per point, or '' when the point is outside every region box."""
    lat_a = np.atleast_1d(np.asarray(lat, dtype=float))
    lon_a = np.atleast_1d(np.asarray(lon, dtype=float))
    labels = np.full(lat_a.shape, "", dtype=object)
    for name, box in regions().items():
        inside = (
            (lat_a >= box["lat_min"]) & (lat_a < box["lat_max"])
            & (lon_a >= box["lon_min"]) & (lon_a < box["lon_max"])
        )
        labels[inside] = name
    return labels


def region_of(lat: float, lon: float) -> str:
    return str(region_labels(lat, lon)[0])


def domain_cell_counts(cell_deg: float) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name, box in regions().items():
        n_lat = round((box["lat_max"] - box["lat_min"]) / cell_deg)
        n_lon = round((box["lon_max"] - box["lon_min"]) / cell_deg)
        counts[name] = n_lat * n_lon
    counts["total"] = sum(counts.values())
    return counts
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_config.py tests/test_grid.py -v`
Expected: all PASS (3 config + 12 grid cases).

- [ ] **Step 5: Commit**

```bash
git add configs src/aetherguard/config.py src/aetherguard/grid.py tests/conftest.py tests/test_config.py tests/test_grid.py
git commit -m "feat: config loading and 0.05-degree grid with region labels"
```

---

### Task 3: Manifest and resilient downloader

**Files:**
- Create: `src/aetherguard/manifest.py`, `src/aetherguard/http.py`
- Test: `tests/test_manifest.py`, `tests/test_http.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `manifest.sha256_file(path) -> str`; `manifest.ManifestEntry(path, source, url, licence, retrieved_utc, size_bytes, sha256)`; `manifest.Manifest(manifest_path: Path, data_root: Path)` with `.relpath(file) -> str`, `.entries() -> dict[str, ManifestEntry]`, `.add(file, source, url, licence) -> ManifestEntry`, `.is_current(file) -> bool`, `.verify() -> list[str]`.
  - `http.DownloadError(message, retriable=False)` (attribute `.retriable: bool`); `http.fetch_json(url, params=None, retries=3, backoff=2.0, timeout=60) -> dict`; `http.download(url, dest, manifest, source, licence, retries=3, backoff=2.0, timeout=120, force=False) -> Path`.

- [ ] **Step 1: Write the failing tests**

`tests/test_manifest.py`:
```python
import hashlib

from aetherguard.manifest import Manifest


def _setup(tmp_path):
    root = tmp_path / "data"
    f = root / "raw" / "a.txt"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"hello")
    return root, f, Manifest(tmp_path / "manifest.jsonl", root)


def test_add_records_size_hash_and_relative_path(tmp_path):
    root, f, m = _setup(tmp_path)
    e = m.add(f, "test", "http://x/a.txt", "CC0")
    assert e.path == "raw/a.txt"
    assert e.size_bytes == 5
    assert e.sha256 == hashlib.sha256(b"hello").hexdigest()
    assert m.is_current(f)
    assert m.verify() == []


def test_verify_detects_checksum_size_and_missing(tmp_path):
    root, f, m = _setup(tmp_path)
    m.add(f, "test", "http://x/a.txt", "CC0")
    f.write_bytes(b"jello")  # same size, different content
    assert m.verify() == ["checksum mismatch: raw/a.txt"]
    assert not m.is_current(f)
    f.write_bytes(b"longer content")
    assert m.verify() == ["size mismatch: raw/a.txt"]
    f.unlink()
    assert m.verify() == ["missing: raw/a.txt"]


def test_later_entry_for_the_same_path_wins(tmp_path):
    root, f, m = _setup(tmp_path)
    m.add(f, "first", "http://x/1", "CC0")
    f.write_bytes(b"new content")
    m.add(f, "second", "http://x/2", "CC0")
    assert m.entries()["raw/a.txt"].source == "second"
    assert m.verify() == []
```

`tests/test_http.py`:
```python
import http.server
import threading

import pytest

from aetherguard.http import DownloadError, download, fetch_json
from aetherguard.manifest import Manifest


class _Handler(http.server.BaseHTTPRequestHandler):
    hits: dict = {}

    def log_message(self, *args):
        pass

    def _send(self, status, body=b"", length=None):
        self.send_response(status)
        self.send_header("Content-Length", str(len(body) if length is None else length))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        _Handler.hits[self.path] = _Handler.hits.get(self.path, 0) + 1
        if self.path == "/ok.bin":
            self._send(200, b"x" * 5000)
        elif self.path == "/truncated.bin":
            self._send(200, b"x" * 100, length=5000)  # promises 5000, sends 100
        elif self.path == "/flaky.json":
            if _Handler.hits[self.path] < 3:
                self._send(503)
            else:
                self._send(200, b'{"ok": true}')
        else:
            self._send(404)


@pytest.fixture
def server():
    _Handler.hits = {}
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", _Handler.hits
    httpd.shutdown()
    httpd.server_close()


def _manifest(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    return root, Manifest(tmp_path / "manifest.jsonl", root)


def test_download_writes_file_and_manifest_entry(server, tmp_path):
    base, hits = server
    root, m = _manifest(tmp_path)
    dest = root / "raw" / "ok.bin"
    assert download(f"{base}/ok.bin", dest, m, "test", "CC0") == dest
    assert dest.stat().st_size == 5000
    assert m.entries()["raw/ok.bin"].size_bytes == 5000


def test_rerun_does_not_download_a_verified_file_again(server, tmp_path):
    base, hits = server
    root, m = _manifest(tmp_path)
    dest = root / "raw" / "ok.bin"
    download(f"{base}/ok.bin", dest, m, "test", "CC0")
    download(f"{base}/ok.bin", dest, m, "test", "CC0")
    assert hits["/ok.bin"] == 1


def test_truncated_download_leaves_no_file_and_no_manifest_entry(server, tmp_path):
    base, hits = server
    root, m = _manifest(tmp_path)
    dest = root / "raw" / "truncated.bin"
    with pytest.raises(DownloadError):
        download(f"{base}/truncated.bin", dest, m, "test", "CC0", retries=2, backoff=0)
    assert not dest.exists()
    assert not (root / "raw" / "truncated.bin.part").exists()
    assert m.entries() == {}
    assert hits["/truncated.bin"] == 2  # retried


def test_client_error_is_not_retried(server, tmp_path):
    base, hits = server
    root, m = _manifest(tmp_path)
    with pytest.raises(DownloadError) as info:
        download(f"{base}/missing", root / "raw" / "m.bin", m, "test", "CC0", retries=3, backoff=0)
    assert info.value.retriable is False
    assert hits["/missing"] == 1


def test_fetch_json_retries_server_errors(server):
    base, hits = server
    assert fetch_json(f"{base}/flaky.json", retries=3, backoff=0) == {"ok": True}
    assert hits["/flaky.json"] == 3


def test_fetch_json_404_raises_immediately(server):
    base, hits = server
    with pytest.raises(DownloadError):
        fetch_json(f"{base}/missing", retries=3, backoff=0)
    assert hits["/missing"] == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_manifest.py tests/test_http.py -v`
Expected: FAIL/ERROR — `ModuleNotFoundError: No module named 'aetherguard.manifest'`.

- [ ] **Step 3: Write the implementation**

`src/aetherguard/manifest.py`:
```python
"""Checksummed, append-only record of every file downloaded into the data tree."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class ManifestEntry:
    path: str  # relative to the data root, POSIX separators
    source: str
    url: str
    licence: str
    retrieved_utc: str
    size_bytes: int
    sha256: str


class Manifest:
    def __init__(self, manifest_path: Path, data_root: Path) -> None:
        self.manifest_path = Path(manifest_path)
        self.data_root = Path(data_root)

    def relpath(self, file_path) -> str:
        return Path(file_path).resolve().relative_to(self.data_root.resolve()).as_posix()

    def entries(self) -> dict[str, ManifestEntry]:
        latest: dict[str, ManifestEntry] = {}
        if not self.manifest_path.exists():
            return latest
        with self.manifest_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    entry = ManifestEntry(**json.loads(line))
                    latest[entry.path] = entry
        return latest

    def add(self, file_path, source: str, url: str, licence: str) -> ManifestEntry:
        file_path = Path(file_path)
        entry = ManifestEntry(
            path=self.relpath(file_path),
            source=source,
            url=url,
            licence=licence,
            retrieved_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            size_bytes=file_path.stat().st_size,
            sha256=sha256_file(file_path),
        )
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with self.manifest_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(asdict(entry), sort_keys=True) + "\n")
        return entry

    def is_current(self, file_path) -> bool:
        path = Path(file_path)
        entry = self.entries().get(self.relpath(path))
        if entry is None or not path.exists():
            return False
        return path.stat().st_size == entry.size_bytes and sha256_file(path) == entry.sha256

    def verify(self) -> list[str]:
        problems: list[str] = []
        for rel, entry in sorted(self.entries().items()):
            path = self.data_root / rel
            if not path.exists():
                problems.append(f"missing: {rel}")
            elif path.stat().st_size != entry.size_bytes:
                problems.append(f"size mismatch: {rel}")
            elif sha256_file(path) != entry.sha256:
                problems.append(f"checksum mismatch: {rel}")
        return problems
```

`src/aetherguard/http.py`:
```python
"""Resilient JSON fetch and atomic, checksummed file download."""
from __future__ import annotations

import time
from pathlib import Path

import requests

from .manifest import Manifest

_JSON_HEADERS = {"User-Agent": "AetherGuard/0.1 (research prototype)"}
_FILE_HEADERS = {**_JSON_HEADERS, "Accept-Encoding": "identity"}  # keeps Content-Length comparable


class DownloadError(RuntimeError):
    def __init__(self, message: str, retriable: bool = False) -> None:
        super().__init__(message)
        self.retriable = retriable


def _check_status(response: requests.Response, url: str) -> None:
    code = response.status_code
    if code == 429 or code >= 500:
        raise DownloadError(f"HTTP {code} from {url}", retriable=True)
    if code >= 400:
        raise DownloadError(f"HTTP {code} from {url}", retriable=False)


def fetch_json(url: str, params: dict | None = None, retries: int = 3,
               backoff: float = 2.0, timeout: float = 60) -> dict:
    error: DownloadError | None = None
    for attempt in range(retries):
        try:
            response = requests.get(url, params=params, timeout=timeout, headers=_JSON_HEADERS)
            _check_status(response, url)
            try:
                return response.json()
            except ValueError as exc:
                raise DownloadError(f"invalid JSON from {url}: {exc}") from exc
        except requests.RequestException as exc:
            error = DownloadError(f"{type(exc).__name__}: {exc}", retriable=True)
        except DownloadError as exc:
            error = exc
        if not error.retriable:
            raise error
        if attempt < retries - 1:
            time.sleep(backoff * 2 ** attempt)
    raise error


def download(url: str, dest, manifest: Manifest, source: str, licence: str,
             retries: int = 3, backoff: float = 2.0, timeout: float = 120,
             force: bool = False) -> Path:
    """Download to `dest` atomically and record it in the manifest.

    A file already recorded in the manifest with a matching size and checksum is not fetched again.
    A truncated transfer leaves no data file and no manifest entry.
    """
    dest = Path(dest)
    if not force and manifest.is_current(dest):
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(dest.name + ".part")
    error: DownloadError | None = None
    for attempt in range(retries):
        try:
            with requests.get(url, stream=True, timeout=timeout, headers=_FILE_HEADERS) as response:
                _check_status(response, url)
                expected = response.headers.get("Content-Length")
                received = 0
                with partial.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1 << 20):
                        handle.write(chunk)
                        received += len(chunk)
            if expected is not None and received != int(expected):
                raise DownloadError(
                    f"truncated download from {url}: got {received} of {expected} bytes", retriable=True)
            if received == 0:
                raise DownloadError(f"empty response from {url}", retriable=True)
            partial.replace(dest)
            manifest.add(dest, source, url, licence)
            return dest
        except requests.RequestException as exc:
            error = DownloadError(f"{type(exc).__name__}: {exc}", retriable=True)
        except DownloadError as exc:
            error = exc
        partial.unlink(missing_ok=True)
        if not error.retriable:
            raise error
        if attempt < retries - 1:
            time.sleep(backoff * 2 ** attempt)
    raise error
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_manifest.py tests/test_http.py -v`
Expected: all PASS (3 manifest + 6 http).

- [ ] **Step 5: Commit**

```bash
git add src/aetherguard/manifest.py src/aetherguard/http.py tests/test_manifest.py tests/test_http.py
git commit -m "feat: checksummed manifest and resilient atomic downloader"
```

---

### Task 4: GHCN-Daily and ISD station readers, real-flag census

**Files:**
- Create: `src/aetherguard/audit/__init__.py`, `src/aetherguard/audit/result.py`, `src/aetherguard/audit/ghcnd.py`
- Test: `tests/test_result.py`, `tests/test_ghcnd.py`

**Interfaces:**
- Consumes: `grid.region_labels`; `http.download`, `http.DownloadError`; `manifest.Manifest`.
- Produces:
  - `result.ProbeResult(name: str, status: str, summary: str, evidence: dict = {}, day_definition: str | None = None)` with `.as_dict()`; `result.STATUSES`; `result.failure_status(errors) -> str`.
  - `ghcnd.QFLAG_MEANINGS: dict[str, str]`; `ghcnd.parse_inventory_line(line) -> dict`; `ghcnd.parse_station_line(line) -> dict`; `ghcnd.select_stations(inventory_lines, station_lines, countries, element, first_year_max, last_year_min, upland_min_elev_m) -> pd.DataFrame` (columns `id, lat, lon, elevation_m, name, first_year, last_year, country, region, upland`); `ghcnd.parse_dly_line(line) -> list[dict]` (keys `station, date, element, value, mflag, qflag, sflag`; `value` is `None` when missing); `ghcnd.read_dly(path, element="PRCP") -> pd.DataFrame`; `ghcnd.flag_census(df) -> dict` (`n_values, n_valid, n_missing, n_flagged, by_flag`); `ghcnd.probe_ghcnd(data_root, manifest, cfg) -> ProbeResult` (name `"ghcnd"`); `ghcnd.probe_isd_history(data_root, manifest, cfg) -> ProbeResult` (name `"isd"`).

- [ ] **Step 1: Write the failing tests**

`tests/test_result.py`:
```python
import pytest

from aetherguard.audit.result import STATUSES, ProbeResult, failure_status


def test_probe_result_validates_status():
    assert ProbeResult("x", "ok", "fine").status == "ok"
    with pytest.raises(ValueError):
        ProbeResult("x", "great", "nope")
    assert "needs_login" in STATUSES and "manual_pending" in STATUSES


def test_as_dict_round_trips_evidence_and_day_definition():
    r = ProbeResult("x", "ok", "s", evidence={"a": 1}, day_definition="UTC day")
    assert r.as_dict() == {"name": "x", "status": "ok", "summary": "s",
                           "evidence": {"a": 1}, "day_definition": "UTC day"}


def test_failure_status_distinguishes_network_from_api_errors():
    class E(Exception):
        def __init__(self, retriable):
            self.retriable = retriable
    assert failure_status([E(True), E(False)]) == "unreachable"
    assert failure_status([E(False)]) == "fail"
    assert failure_status([]) == "fail"
```

`tests/test_ghcnd.py`:
```python
import pytest

from aetherguard.audit import ghcnd


def make_dly_line(station="IN022021900", year=2023, month=2, element="PRCP", days=None):
    """Build a 269-character GHCN-Daily line; `days` maps day -> (raw_value, qflag)."""
    days = days or {}
    body = ""
    for d in range(1, 32):
        raw, q = days.get(d, (-9999, " "))
        body += f"{raw:5d}" + " " + q + "S"  # value, mflag, qflag, sflag
    return f"{station}{year:04d}{month:02d}{element}{body}"


def station_line(sid, lat, lon, elev, state, name):
    return f"{sid:<11} {lat:8.4f} {lon:9.4f} {elev:6.1f} {state:<2} {name:<30}"


def inventory_line(sid, lat, lon, element, first, last):
    return f"{sid:<11} {lat:8.4f} {lon:9.4f} {element:<4} {first:4d} {last:4d}"


def test_line_helper_matches_the_documented_length():
    assert len(make_dly_line()) == ghcnd.DLY_LINE_LENGTH


def test_scaling_and_quality_flags_are_preserved():
    rows = ghcnd.parse_dly_line(make_dly_line(days={1: (125, "K"), 2: (0, " ")}))
    assert rows[0]["value"] == pytest.approx(12.5)
    assert rows[0]["qflag"] == "K"
    assert rows[1]["value"] == 0.0
    assert rows[1]["qflag"] == " "


def test_missing_sentinel_becomes_none_never_a_rainfall_value():
    rows = ghcnd.parse_dly_line(make_dly_line(days={1: (10, " ")}))
    assert rows[2]["value"] is None
    assert all(r["value"] is None or r["value"] >= 0 for r in rows)


def test_month_length_is_respected_including_leap_years():
    assert len(ghcnd.parse_dly_line(make_dly_line(year=2023, month=2))) == 28
    assert len(ghcnd.parse_dly_line(make_dly_line(year=2024, month=2))) == 29
    assert len(ghcnd.parse_dly_line(make_dly_line(month=4))) == 30


def test_short_line_raises_instead_of_guessing():
    with pytest.raises(ValueError):
        ghcnd.parse_dly_line(make_dly_line()[:100])


def test_flag_census_counts_flags_and_missing(tmp_path):
    path = tmp_path / "s.dly"
    path.write_text(
        make_dly_line(month=3, days={1: (0, " "), 2: (500, "K"), 3: (800, "S"), 4: (900, "K")}) + "\n",
        encoding="ascii")
    df = ghcnd.read_dly(path, "PRCP")
    census = ghcnd.flag_census(df)
    assert census["n_values"] == 31
    assert census["n_valid"] == 4
    assert census["n_missing"] == 27
    assert census["n_flagged"] == 3
    assert census["by_flag"] == {"K": 2, "S": 1}


def test_read_dly_filters_by_element(tmp_path):
    path = tmp_path / "s.dly"
    path.write_text(make_dly_line(element="PRCP") + "\n" + make_dly_line(element="TMAX") + "\n",
                    encoding="ascii")
    assert set(ghcnd.read_dly(path, "PRCP")["element"]) == {"PRCP"}


def _station_files():
    stations = [
        station_line("IN000000001", 11.6, 76.1, 900.0, "KL", "WAYANAD UPLAND"),
        station_line("IN000000002", 28.6, 77.2, 216.0, "DL", "DELHI LOWLAND"),
        station_line("NP000000003", 27.7, 85.3, 1400.0, "  ", "KATHMANDU"),
        station_line("US000000004", 40.0, -105.0, 1600.0, "CO", "BOULDER"),
        station_line("IN000000005", 12.0, 76.0, 800.0, "KA", "OLD STATION"),
    ]
    inventory = [
        inventory_line("IN000000001", 11.6, 76.1, "PRCP", 1990, 2025),
        inventory_line("IN000000002", 28.6, 77.2, "PRCP", 1990, 2025),
        inventory_line("NP000000003", 27.7, 85.3, "PRCP", 2010, 2025),
        inventory_line("US000000004", 40.0, -105.0, "PRCP", 1990, 2025),
        inventory_line("IN000000005", 12.0, 76.0, "PRCP", 1990, 2010),  # stopped reporting
        inventory_line("IN000000001", 11.6, 76.1, "TMAX", 1990, 2025),  # wrong element
    ]
    return inventory, stations


def test_select_stations_filters_country_years_element_region_and_upland():
    inventory, stations = _station_files()
    df = ghcnd.select_stations(inventory, stations, ("IN", "NP"), "PRCP", 2015, 2024, 500.0)
    assert sorted(df["id"]) == ["IN000000001", "IN000000002", "NP000000003"]
    by_id = df.set_index("id")
    assert by_id.loc["IN000000001", "region"] == "western_ghats"
    assert bool(by_id.loc["IN000000001", "upland"]) is True
    assert bool(by_id.loc["IN000000002", "upland"]) is False
    assert by_id.loc["NP000000003", "region"] == "himalaya"


def test_probe_ghcnd_aggregates_by_region_and_upland(tmp_path, monkeypatch):
    inventory, stations = _station_files()
    dly = {
        "IN000000001": make_dly_line("IN000000001", month=3, days={1: (0, " "), 2: (500, "K")}),
        "IN000000002": make_dly_line("IN000000002", month=3, days={1: (10, " ")}),
        "NP000000003": make_dly_line("NP000000003", month=3, days={1: (20, "S")}),
    }

    def fake_download(url, dest, manifest, source, licence, **kwargs):
        dest.parent.mkdir(parents=True, exist_ok=True)
        if url.endswith("ghcnd-inventory.txt"):
            dest.write_text("\n".join(inventory) + "\n", encoding="ascii")
        elif url.endswith("ghcnd-stations.txt"):
            dest.write_text("\n".join(stations) + "\n", encoding="ascii")
        else:
            dest.write_text(dly[dest.stem] + "\n", encoding="ascii")
        return dest

    monkeypatch.setattr(ghcnd, "download", fake_download)
    cfg = {"ghcnd": {"countries": ["IN", "NP"], "first_year_max": 2015, "last_year_min": 2024,
                     "upland_min_elev_m": 500}}
    res = ghcnd.probe_ghcnd(tmp_path, manifest=None, cfg=cfg)
    assert res.status == "ok"
    groups = res.evidence["census_by_group"]
    assert groups["western_ghats|upland"]["n_flagged"] == 1
    assert groups["western_ghats|upland"]["by_flag"] == {"K": 1}
    assert groups["himalaya|lowland"]["n_flagged"] == 0
    assert groups["himalaya|upland"]["by_flag"] == {"S": 1}
    assert res.evidence["n_selected"] == 3
    assert res.evidence["by_country"] == {"IN": 2, "NP": 1}


def test_probe_isd_history_counts_active_regional_stations(tmp_path, monkeypatch):
    csv_text = (
        '"USAF","WBAN","STATION NAME","CTRY","STATE","ICAO","LAT","LON","ELEV(M)","BEGIN","END"\n'
        '"430000","99999","KOZHIKODE","IN","","VOCL","11.25","75.78","4.0","19730101","20260929"\n'
        '"424000","99999","KATHMANDU","NP","","VNKT","27.70","85.36","1337.0","19730101","20260929"\n'
        '"999999","99999","DEFUNCT","IN","","","12.0","76.0","10.0","19730101","20100101"\n'
        '"720000","99999","BOULDER","US","CO","KBDU","40.0","-105.2","1600.0","19730101","20260929"\n'
    )

    def fake_download(url, dest, manifest, source, licence, **kwargs):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(csv_text, encoding="utf-8")
        return dest

    monkeypatch.setattr(ghcnd, "download", fake_download)
    cfg = {"ghcnd": {"countries": ["IN", "NP"], "first_year_max": 2015, "last_year_min": 2024,
                     "upland_min_elev_m": 500}}
    res = ghcnd.probe_isd_history(tmp_path, manifest=None, cfg=cfg)
    assert res.status == "ok"
    assert res.evidence["n_selected"] == 2
    assert res.evidence["by_country"] == {"IN": 1, "NP": 1}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_result.py tests/test_ghcnd.py -v`
Expected: FAIL/ERROR — `ModuleNotFoundError: No module named 'aetherguard.audit'`.

- [ ] **Step 3: Write the implementation**

`src/aetherguard/audit/__init__.py`:
```python
"""Phase 0 data-audit probes and report generation."""
```

`src/aetherguard/audit/result.py`:
```python
"""Result type shared by every audit probe."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

STATUSES = ("ok", "partial", "fail", "unreachable", "needs_login", "manual_pending", "inconclusive")


@dataclass
class ProbeResult:
    name: str
    status: str
    summary: str
    evidence: dict = field(default_factory=dict)
    day_definition: str | None = None

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"unknown status {self.status!r}; expected one of {STATUSES}")

    def as_dict(self) -> dict:
        return asdict(self)


def failure_status(errors) -> str:
    """'unreachable' when any error was a retriable network failure, otherwise 'fail'."""
    return "unreachable" if any(getattr(e, "retriable", False) for e in errors) else "fail"
```

`src/aetherguard/audit/ghcnd.py`:
```python
"""GHCN-Daily and ISD helpers: station selection, .dly parsing, real quality-flag census."""
from __future__ import annotations

import calendar
from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd

from ..grid import region_labels
from ..http import DownloadError, download
from .result import ProbeResult

GHCND_BASE = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/"
ISD_HISTORY_URL = "https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv"
DLY_LINE_LENGTH = 269  # 21 header characters + 31 days * 8
MISSING = -9999
DIVISOR = {"PRCP": 10, "TMAX": 10, "TMIN": 10, "TAVG": 10}  # tenths -> mm / degC

# GHCN-Daily QFLAG: a letter means the value FAILED that automated check (the value is kept).
QFLAG_MEANINGS = {
    "D": "duplicate day", "G": "gap check", "I": "internal inconsistency",
    "K": "streak / frequent-value", "L": "multi-day accumulation length",
    "M": "megaconsecutive value", "N": "naught check", "O": "climatological outlier",
    "R": "lagged range", "S": "spatial inconsistency", "T": "temporal inconsistency",
    "W": "temperature too warm for snow", "X": "exceeds bounds / record", "Z": "Datzilla investigation",
}
_STATION_COLUMNS = ["id", "lat", "lon", "elevation_m", "name",
                    "first_year", "last_year", "country", "region", "upland"]
_DLY_COLUMNS = ["station", "date", "element", "value", "mflag", "qflag", "sflag"]
_LICENCE = "NOAA NCEI open data (public domain)"


def parse_inventory_line(line: str) -> dict:
    return {"id": line[0:11], "lat": float(line[12:20]), "lon": float(line[21:30]),
            "element": line[31:35].strip(), "first_year": int(line[36:40]),
            "last_year": int(line[41:45])}


def parse_station_line(line: str) -> dict:
    elevation = float(line[31:37])
    return {"id": line[0:11], "lat": float(line[12:20]), "lon": float(line[21:30]),
            "elevation_m": None if elevation <= -999.0 else elevation, "name": line[41:71].strip()}


def select_stations(inventory_lines, station_lines, countries, element,
                    first_year_max, last_year_min, upland_min_elev_m) -> pd.DataFrame:
    countries = tuple(countries)
    stations = {}
    for line in station_lines:
        if line.strip() and line[0:2] in countries:
            record = parse_station_line(line)
            stations[record["id"]] = record
    rows = []
    for line in inventory_lines:
        if not line.strip() or line[0:2] not in countries:
            continue
        inv = parse_inventory_line(line)
        if (inv["element"] != element or inv["first_year"] > first_year_max
                or inv["last_year"] < last_year_min):
            continue
        station = stations.get(inv["id"])
        if station is None:
            continue
        rows.append({**station, "first_year": inv["first_year"], "last_year": inv["last_year"],
                     "country": inv["id"][0:2]})
    df = pd.DataFrame(rows, columns=_STATION_COLUMNS[:-2])
    if df.empty:
        return df.assign(region=pd.Series(dtype=object), upland=pd.Series(dtype=bool))
    df["region"] = region_labels(df["lat"].to_numpy(), df["lon"].to_numpy())
    # A station with unknown elevation is NOT counted as upland (conservative).
    df["upland"] = df["elevation_m"].fillna(-1e9) >= upland_min_elev_m
    return df[_STATION_COLUMNS]


def parse_dly_line(line: str) -> list[dict]:
    line = line.rstrip("\r\n")
    if len(line) < DLY_LINE_LENGTH:
        raise ValueError(f"short .dly line ({len(line)} characters, expected {DLY_LINE_LENGTH})")
    station, year, month, element = line[0:11], int(line[11:15]), int(line[15:17]), line[17:21]
    divisor = DIVISOR.get(element, 1)
    rows = []
    for day in range(1, calendar.monthrange(year, month)[1] + 1):
        offset = 21 + (day - 1) * 8
        raw = int(line[offset:offset + 5])
        rows.append({
            "station": station, "date": date(year, month, day), "element": element,
            "value": None if raw == MISSING else raw / divisor,
            "mflag": line[offset + 5], "qflag": line[offset + 6], "sflag": line[offset + 7],
        })
    return rows


def read_dly(path, element: str | None = "PRCP") -> pd.DataFrame:
    rows: list[dict] = []
    with Path(path).open("r", encoding="ascii", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            if element is not None and line[17:21] != element:
                continue
            rows.extend(parse_dly_line(line))
    return pd.DataFrame(rows, columns=_DLY_COLUMNS)


def flag_census(df: pd.DataFrame) -> dict:
    valid = df["value"].notna()
    flags = df["qflag"].astype(str).str.strip()
    flagged = flags.ne("")
    counts = Counter(flags[flagged])
    return {"n_values": int(len(df)), "n_valid": int(valid.sum()), "n_missing": int((~valid).sum()),
            "n_flagged": int(flagged.sum()), "by_flag": {k: int(v) for k, v in sorted(counts.items())}}


def _group_key(region: str, upland: bool) -> str:
    return f"{region or 'outside_domain'}|{'upland' if upland else 'lowland'}"


def probe_ghcnd(data_root, manifest, cfg) -> ProbeResult:
    g = cfg["ghcnd"]
    raw = Path(data_root) / "raw" / "ghcnd"
    inventory = download(GHCND_BASE + "ghcnd-inventory.txt", raw / "ghcnd-inventory.txt",
                         manifest, "NOAA GHCN-Daily inventory", _LICENCE)
    stations = download(GHCND_BASE + "ghcnd-stations.txt", raw / "ghcnd-stations.txt",
                        manifest, "NOAA GHCN-Daily stations", _LICENCE)
    selected = select_stations(
        inventory.read_text(encoding="ascii", errors="replace").splitlines(),
        stations.read_text(encoding="ascii", errors="replace").splitlines(),
        g["countries"], "PRCP", g["first_year_max"], g["last_year_min"], g["upland_min_elev_m"])
    groups: dict[str, dict] = {}
    station_rows, failed = [], []
    for rec in selected.to_dict("records"):
        try:
            path = download(f"{GHCND_BASE}all/{rec['id']}.dly", raw / "dly" / f"{rec['id']}.dly",
                            manifest, "NOAA GHCN-Daily station file", _LICENCE)
        except DownloadError as exc:
            failed.append({"id": rec["id"], "error": str(exc)})
            continue
        census = flag_census(read_dly(path, "PRCP"))
        key = _group_key(rec["region"], bool(rec["upland"]))
        slot = groups.setdefault(key, {"n_stations": 0, "n_valid": 0, "n_flagged": 0, "by_flag": Counter()})
        slot["n_stations"] += 1
        slot["n_valid"] += census["n_valid"]
        slot["n_flagged"] += census["n_flagged"]
        slot["by_flag"].update(census["by_flag"])
        station_rows.append({k: rec[k] for k in ("id", "name", "lat", "lon", "elevation_m", "region")}
                            | {"upland": bool(rec["upland"]), "n_valid": census["n_valid"],
                               "n_flagged": census["n_flagged"]})
    for slot in groups.values():
        slot["by_flag"] = dict(sorted(slot["by_flag"].items()))
    total_flagged = sum(s["n_flagged"] for s in groups.values())
    evidence = {
        "n_selected": int(len(selected)),
        "by_country": dict(Counter(selected["country"])) if len(selected) else {},
        "census_by_group": groups, "stations": station_rows, "failed_downloads": failed,
        "qflag_meanings": QFLAG_MEANINGS,
    }
    if selected.empty:
        return ProbeResult("ghcnd", "fail", "no stations matched the selection", evidence)
    status = "ok" if total_flagged > 0 and not failed else "partial"
    return ProbeResult("ghcnd", status,
                       f"{len(selected)} stations selected, {total_flagged} real quality-flagged rain values",
                       evidence)


def probe_isd_history(data_root, manifest, cfg) -> ProbeResult:
    g = cfg["ghcnd"]
    path = download(ISD_HISTORY_URL, Path(data_root) / "raw" / "isd" / "isd-history.csv",
                    manifest, "NOAA ISD station history", _LICENCE)
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    df = df[df["CTRY"].isin(g["countries"])].copy()
    begin = pd.to_numeric(df["BEGIN"].str[:4], errors="coerce")
    end = pd.to_numeric(df["END"].str[:4], errors="coerce")
    df = df[(begin <= g["first_year_max"]) & (end >= g["last_year_min"])]
    lat = pd.to_numeric(df["LAT"], errors="coerce")
    lon = pd.to_numeric(df["LON"], errors="coerce")
    df = df[lat.notna() & lon.notna()]
    regions = region_labels(lat[df.index].to_numpy(), lon[df.index].to_numpy())
    evidence = {
        "n_selected": int(len(df)),
        "by_country": dict(Counter(df["CTRY"])),
        "by_region": dict(Counter(r or "outside_domain" for r in regions)),
        "note": "ISD is hourly station data; per-value QC flags are in the full ISD files (not fetched in Phase 0).",
    }
    status = "ok" if len(df) else "fail"
    return ProbeResult("isd", status, f"{len(df)} active ISD stations in {', '.join(g['countries'])}", evidence)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_result.py tests/test_ghcnd.py -v`
Expected: all PASS (3 result + 10 ghcnd).

- [ ] **Step 5: Commit**

```bash
git add src/aetherguard/audit/__init__.py src/aetherguard/audit/result.py src/aetherguard/audit/ghcnd.py tests/test_result.py tests/test_ghcnd.py
git commit -m "feat: GHCN-Daily/ISD readers and real quality-flag census"
```

---

### Task 5: Tolerant landslide catalog reader

**Files:**
- Create: `src/aetherguard/audit/landslides.py`
- Test: `tests/test_landslides.py`

**Interfaces:**
- Consumes: `grid.region_labels`, `grid.regions`.
- Produces: `landslides.CatalogFormatError`; `landslides.parse_accuracy_km(value) -> float` (NaN when unknown); `landslides.CatalogReport` (fields `path, total_rows, dropped_bad_date, dropped_bad_coordinates, kept_rows, columns_found`; `.as_dict()`); `landslides.read_catalog_csv(path) -> (pd.DataFrame, CatalogReport)` where the frame has columns `event_date (datetime64), latitude, longitude, accuracy_km, trigger, country, region`; `landslides.summarize_catalog(df, max_accuracy_km) -> dict[str, dict]` keyed by region name and `"outside_domain"`, each with `n_total, n_located, n_unknown_accuracy, first_date, last_date, by_year, top_triggers`.

- [ ] **Step 1: Write the failing tests**

`tests/test_landslides.py`:
```python
import math

import pytest

from aetherguard.audit import landslides as ls


def write_csv(tmp_path, text, name="catalog.csv", encoding="utf-8-sig"):
    path = tmp_path / name
    path.write_text(text, encoding=encoding, newline="")
    return path


HEADER = "event_id,event_date,latitude,longitude,location_accuracy,landslide_trigger,country_name\n"


def test_parse_accuracy_km_variants():
    assert ls.parse_accuracy_km("5km") == 5.0
    assert ls.parse_accuracy_km("10 km") == 10.0
    assert ls.parse_accuracy_km("exact") == 0.0
    assert ls.parse_accuracy_km("25") == 25.0
    for unknown in ("unknown", "", None, float("nan")):
        assert math.isnan(ls.parse_accuracy_km(unknown))


def test_bom_iso_dates_and_unknown_accuracy(tmp_path):
    path = write_csv(tmp_path, HEADER
                     + "1,2018-08-16,11.55,76.13,5km,downpour,India\n"
                     + "2,2018-08-17,27.70,85.30,unknown,downpour,Nepal\n")
    df, report = ls.read_catalog_csv(path)
    assert report.total_rows == 2 and report.kept_rows == 2
    assert df["event_date"].dt.strftime("%Y-%m-%d").tolist() == ["2018-08-16", "2018-08-17"]
    assert df["accuracy_km"].iloc[0] == 5.0 and math.isnan(df["accuracy_km"].iloc[1])
    assert df["region"].tolist() == ["western_ghats", "himalaya"]


def test_slash_dates_are_parsed_month_first_when_unambiguous(tmp_path):
    path = write_csv(tmp_path, HEADER
                     + "1,03/27/2013 12:00:00 AM,11.55,76.13,5km,rain,India\n"
                     + "2,04/02/2013 12:00:00 AM,11.60,76.10,5km,rain,India\n")
    df, _ = ls.read_catalog_csv(path)
    assert df["event_date"].dt.strftime("%Y-%m-%d").tolist() == ["2013-03-27", "2013-04-02"]


def test_slash_dates_are_parsed_day_first_when_unambiguous(tmp_path):
    path = write_csv(tmp_path, HEADER + "1,27/03/2013,11.55,76.13,5km,rain,India\n"
                     + "2,02/04/2013,11.60,76.10,5km,rain,India\n")
    df, _ = ls.read_catalog_csv(path)
    assert df["event_date"].dt.strftime("%Y-%m-%d").tolist() == ["2013-03-27", "2013-04-02"]


def test_ambiguous_slash_dates_raise_instead_of_guessing(tmp_path):
    path = write_csv(tmp_path, HEADER + "1,03/04/2013,11.55,76.13,5km,rain,India\n")
    with pytest.raises(ls.CatalogFormatError, match="ambiguous"):
        ls.read_catalog_csv(path)


def test_inconsistent_slash_dates_raise(tmp_path):
    path = write_csv(tmp_path, HEADER + "1,27/03/2013,11.55,76.13,5km,rain,India\n"
                     + "2,03/27/2013,11.55,76.13,5km,rain,India\n")
    with pytest.raises(ls.CatalogFormatError, match="inconsistent"):
        ls.read_catalog_csv(path)


def test_bad_dates_and_coordinates_are_dropped_but_counted(tmp_path):
    path = write_csv(tmp_path, HEADER
                     + "1,2018-08-16,11.55,76.13,5km,rain,India\n"      # good
                     + "2,not-a-date,11.55,76.13,5km,rain,India\n"       # bad date
                     + "3,2018-08-16,,76.13,5km,rain,India\n"            # blank latitude
                     + "4,2018-08-16,0,0,5km,rain,India\n"               # null island
                     + "5,2018-08-16,95.0,76.13,5km,rain,India\n")       # out of range
    df, report = ls.read_catalog_csv(path)
    assert report.total_rows == 5
    assert report.dropped_bad_date == 1
    assert report.dropped_bad_coordinates == 3
    assert report.kept_rows == 1 and len(df) == 1


def test_missing_required_column_lists_what_was_found(tmp_path):
    path = write_csv(tmp_path, "id,when,lat\n1,2018-08-16,11.5\n")
    with pytest.raises(ls.CatalogFormatError) as info:
        ls.read_catalog_csv(path)
    assert "longitude" in str(info.value) and "id" in str(info.value)


def test_semicolon_delimited_file_is_rejected_clearly(tmp_path):
    path = write_csv(tmp_path, "event_date;latitude;longitude\n2018-08-16;11.5;76.1\n")
    with pytest.raises(ls.CatalogFormatError, match="delimiter"):
        ls.read_catalog_csv(path)


def test_latin1_file_is_read(tmp_path):
    path = write_csv(tmp_path, HEADER + "1,2018-08-16,11.55,76.13,5km,rain,C\u00f4te\n", encoding="latin-1")
    df, _ = ls.read_catalog_csv(path)
    assert len(df) == 1


def test_summarize_counts_only_accurate_events_as_located(tmp_path):
    path = write_csv(tmp_path, HEADER
                     + "1,2018-08-16,11.55,76.13,5km,downpour,India\n"
                     + "2,2019-08-08,11.60,76.10,25km,downpour,India\n"
                     + "3,2019-08-09,11.62,76.12,unknown,rain,India\n"
                     + "4,2020-07-01,27.70,85.30,1km,rain,Nepal\n"
                     + "5,2020-07-02,0.5,20.0,1km,rain,Elsewhere\n")
    df, _ = ls.read_catalog_csv(path)
    out = ls.summarize_catalog(df, max_accuracy_km=5.0)
    ghats = out["western_ghats"]
    assert ghats["n_total"] == 3 and ghats["n_located"] == 1 and ghats["n_unknown_accuracy"] == 1
    assert ghats["by_year"] == {2018: 1}
    assert ghats["first_date"] == "2018-08-16" and ghats["last_date"] == "2019-08-09"
    assert out["himalaya"]["n_located"] == 1
    assert out["outside_domain"]["n_total"] == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_landslides.py -v`
Expected: FAIL/ERROR — `ImportError: cannot import name 'landslides'`.

- [ ] **Step 3: Write the implementation**

`src/aetherguard/audit/landslides.py`:
```python
"""Tolerant reader for landslide catalog CSV exports (NASA GLC / COOLR, HMA catalog)."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from ..grid import region_labels, regions


class CatalogFormatError(ValueError):
    """Raised when a catalog file cannot be read without guessing."""


COLUMN_CANDIDATES = {
    "event_date": ["event_date", "date", "event_datetime", "start_date"],
    "latitude": ["latitude", "lat", "y"],
    "longitude": ["longitude", "lon", "lng", "long", "x"],
    "accuracy": ["location_accuracy", "location_accuracy_km", "loc_accuracy"],
    "trigger": ["landslide_trigger", "trigger"],
    "country": ["country_name", "country"],
}
REQUIRED = ("event_date", "latitude", "longitude")


def _normalise(name: str) -> str:
    return re.sub(r"[^0-9a-z]+", "_", str(name).strip().lower()).strip("_")


def parse_accuracy_km(value) -> float:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return float("nan")
    text = str(value).strip().lower()
    if text == "exact":
        return 0.0
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:km)?", text)
    return float(match.group(1)) if match else float("nan")


def _parse_dates(series: pd.Series) -> pd.Series:
    text = series.astype("string").str.strip()
    slash = text.str.match(r"^\d{1,2}/\d{1,2}/\d{4}").fillna(False).astype(bool)
    if slash.any():
        parts = text[slash].str.extract(r"^(\d{1,2})/(\d{1,2})/")
        first_over_12 = bool((parts[0].astype(int) > 12).any())
        second_over_12 = bool((parts[1].astype(int) > 12).any())
        if first_over_12 and second_over_12:
            raise CatalogFormatError("inconsistent day/month ordering in slash-separated dates")
        if not first_over_12 and not second_over_12:
            raise CatalogFormatError(
                "ambiguous slash-separated dates (no value above 12 in either position); "
                "cannot tell day-first from month-first without guessing")
        parsed = pd.to_datetime(text, dayfirst=first_over_12, errors="coerce", format="mixed")
    else:
        parsed = pd.to_datetime(text, errors="coerce", format="mixed")
    return parsed.dt.normalize()


@dataclass
class CatalogReport:
    path: str
    total_rows: int = 0
    dropped_bad_date: int = 0
    dropped_bad_coordinates: int = 0
    kept_rows: int = 0
    columns_found: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


def read_catalog_csv(path) -> tuple[pd.DataFrame, CatalogReport]:
    path = Path(path)
    try:
        raw = pd.read_csv(path, dtype=str, encoding="utf-8-sig", keep_default_na=False)
    except UnicodeDecodeError:
        raw = pd.read_csv(path, dtype=str, encoding="latin-1", keep_default_na=False)
    if raw.shape[1] == 1 and (";" in raw.columns[0] or "\t" in raw.columns[0]):
        raise CatalogFormatError("unsupported delimiter: expected a comma-separated file")

    lookup = {_normalise(c): c for c in raw.columns}
    cols = {}
    for canonical, candidates in COLUMN_CANDIDATES.items():
        cols[canonical] = next((lookup[c] for c in candidates if c in lookup), None)
    missing = [c for c in REQUIRED if cols[c] is None]
    if missing:
        raise CatalogFormatError(f"missing required column(s) {missing}; found columns: {list(raw.columns)}")

    report = CatalogReport(path=str(path), total_rows=len(raw),
                           columns_found={k: v for k, v in cols.items() if v is not None})
    dates = _parse_dates(raw[cols["event_date"]])
    lat = pd.to_numeric(raw[cols["latitude"]].str.strip(), errors="coerce")
    lon = pd.to_numeric(raw[cols["longitude"]].str.strip(), errors="coerce")
    bad_date = dates.isna()
    bad_coord = (lat.isna() | lon.isna() | (lat.abs() > 90) | (lon.abs() > 180)
                 | ((lat == 0) & (lon == 0)))  # (0, 0) is a placeholder for "no coordinates"
    report.dropped_bad_date = int(bad_date.sum())
    report.dropped_bad_coordinates = int((bad_coord & ~bad_date).sum())
    keep = ~bad_date & ~bad_coord
    report.kept_rows = int(keep.sum())

    def column(canonical, default=""):
        return raw.loc[keep, cols[canonical]].str.strip() if cols[canonical] else pd.Series(default, index=raw.index[keep])

    out = pd.DataFrame({
        "event_date": dates[keep],
        "latitude": lat[keep],
        "longitude": lon[keep],
        "accuracy_km": column("accuracy", "unknown").map(parse_accuracy_km),
        "trigger": column("trigger"),
        "country": column("country"),
    }).sort_values("event_date").reset_index(drop=True)
    out["region"] = region_labels(out["latitude"].to_numpy(), out["longitude"].to_numpy())
    return out, report


def summarize_catalog(df: pd.DataFrame, max_accuracy_km: float) -> dict[str, dict]:
    summary: dict[str, dict] = {}
    for name in [*regions().keys(), ""]:
        sub = df[df["region"] == name]
        located = sub[sub["accuracy_km"].le(max_accuracy_km)]  # NaN compares False
        summary[name or "outside_domain"] = {
            "n_total": int(len(sub)),
            "n_located": int(len(located)),
            "n_unknown_accuracy": int(sub["accuracy_km"].isna().sum()),
            "first_date": str(sub["event_date"].min().date()) if len(sub) else None,
            "last_date": str(sub["event_date"].max().date()) if len(sub) else None,
            "by_year": {int(y): int(c) for y, c in
                        located["event_date"].dt.year.value_counts().sort_index().items()},
            "top_triggers": located["trigger"].replace("", "unknown").value_counts().head(5).to_dict(),
        }
    return summary
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_landslides.py -v`
Expected: all PASS (11 tests).

- [ ] **Step 5: Commit**

```bash
git add src/aetherguard/audit/landslides.py tests/test_landslides.py
git commit -m "feat: tolerant landslide catalog reader with explicit drop accounting"
```

---

### Task 6: Rain-product probes

**Files:**
- Create: `src/aetherguard/audit/rain.py`
- Test: `tests/test_rain.py`, `tests/live/test_live_sources.py`

**Interfaces:**
- Consumes: `http.fetch_json`, `http.download`, `http.DownloadError`; `manifest.Manifest`; `audit.result.ProbeResult`, `failure_status`.
- Produces (all return `ProbeResult`; every result sets `day_definition`; every result's `evidence["event_rows"]` is `list[{"label": str, "daily_mm": {iso_date: float | None}}]`):
  - `rain.daily_sums(times: list[str], values: list) -> dict[str, {"sum_mm","n","n_null"}]`
  - `rain.probe_open_meteo(lat, lon, dates) -> ProbeResult` (name `"open_meteo"`)
  - `rain.probe_power_api(lat, lon, dates) -> ProbeResult` (name `"power_api"`)
  - `rain.probe_power_zarr(lat, lon, dates) -> ProbeResult` (name `"power_zarr"`)
  - `rain.probe_chirps(dates, lat, lon, data_root, manifest, period_days) -> ProbeResult` (name `"chirps"`; evidence includes `est_total_gb`)
  - `rain.probe_imd(lat, lon, dates, data_root, manifest) -> ProbeResult` (name `"imd"`)
  - `rain.DAY_DEFINITIONS: dict[str, str]`

- [ ] **Step 1: Write the failing tests**

`tests/test_rain.py`:
```python
from aetherguard.audit import rain
from aetherguard.http import DownloadError

DATES = ["2024-07-28", "2024-07-29", "2024-07-30", "2024-07-31"]


def _hours(dates):
    return [f"{d}T{h:02d}:00" for d in dates for h in range(24)]


def test_daily_sums_counts_nulls_explicitly():
    out = rain.daily_sums(_hours(["2024-07-28"]), [1.0] * 22 + [None, None])
    assert out["2024-07-28"] == {"sum_mm": 22.0, "n": 24, "n_null": 2}


def _fake_open_meteo(soil_null=False):
    def fake(url, params=None, **kwargs):
        times = _hours(DATES)
        variable = params["hourly"]
        if variable == "soil_moisture_0_to_7cm":
            values = [None if soil_null else 0.3] * len(times)
        else:
            values = [1.0] * len(times)
        return {"hourly": {"time": times, variable: values}}
    return fake


def test_open_meteo_ok_states_its_day_definition(monkeypatch):
    monkeypatch.setattr(rain, "fetch_json", _fake_open_meteo())
    res = rain.probe_open_meteo(11.55, 76.13, DATES)
    assert res.status == "ok"
    assert "UTC" in res.day_definition
    rows = {r["label"]: r["daily_mm"] for r in res.evidence["event_rows"]}
    assert set(rows) == {"era5", "era5_land", "ecmwf_ifs"}
    assert rows["era5"]["2024-07-29"] == 24.0


def test_open_meteo_missing_soil_moisture_is_partial(monkeypatch):
    monkeypatch.setattr(rain, "fetch_json", _fake_open_meteo(soil_null=True))
    res = rain.probe_open_meteo(11.55, 76.13, DATES)
    assert res.status == "partial"
    assert any("soil" in p for p in res.evidence["problems"])


def test_open_meteo_network_down_is_unreachable(monkeypatch):
    def boom(*args, **kwargs):
        raise DownloadError("offline", retriable=True)
    monkeypatch.setattr(rain, "fetch_json", boom)
    res = rain.probe_open_meteo(11.55, 76.13, DATES)
    assert res.status == "unreachable"
    assert res.day_definition


def _power_payload(fill_day=None):
    precip = {"20240728": 7.6, "20240729": 52.6, "20240730": 27.5, "20240731": 19.6}
    if fill_day:
        precip[fill_day] = -999.0
    soil = {k: 0.9 for k in precip}
    return {"properties": {"parameter": {"PRECTOTCORR": precip, "GWETTOP": soil, "GWETROOT": soil}},
            "header": {"fill_value": -999.0, "time_standard": "LST"}}


def test_power_api_ok_and_uses_the_reported_time_standard(monkeypatch):
    monkeypatch.setattr(rain, "fetch_json", lambda *a, **k: _power_payload())
    res = rain.probe_power_api(11.55, 76.13, DATES)
    assert res.status == "ok"
    assert "LST" in res.day_definition
    assert res.evidence["event_rows"][0]["daily_mm"]["2024-07-29"] == 52.6


def test_power_api_fill_value_becomes_none_and_status_partial(monkeypatch):
    monkeypatch.setattr(rain, "fetch_json", lambda *a, **k: _power_payload(fill_day="20240730"))
    res = rain.probe_power_api(11.55, 76.13, DATES)
    assert res.status == "partial"
    assert res.evidence["event_rows"][0]["daily_mm"]["2024-07-30"] is None


def test_every_rain_probe_declares_a_day_definition():
    assert set(rain.DAY_DEFINITIONS) >= {"open_meteo", "chirps", "imd", "power_zarr"}
    assert all(text.strip() for text in rain.DAY_DEFINITIONS.values())
```

`tests/live/test_live_sources.py` (hits the real network; run with `-m live`):
```python
import pytest

from aetherguard.audit import rain

pytestmark = pytest.mark.live
DATES = ["2024-07-28", "2024-07-29", "2024-07-30", "2024-07-31"]


def test_open_meteo_live():
    res = rain.probe_open_meteo(11.55, 76.13, DATES)
    assert res.status in ("ok", "partial"), res.summary


def test_power_api_live():
    res = rain.probe_power_api(11.55, 76.13, DATES)
    assert res.status in ("ok", "partial"), res.summary
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_rain.py -v`
Expected: FAIL/ERROR — `ImportError: cannot import name 'rain'`.

- [ ] **Step 3: Write the implementation**

`src/aetherguard/audit/rain.py`:
```python
"""Rain-product probes: what each source returns for the reference point and event dates."""
from __future__ import annotations

import gzip
import shutil
from pathlib import Path

import numpy as np

from ..http import DownloadError, download, fetch_json
from .result import ProbeResult, failure_status

OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
POWER_POINT = "https://power.larc.nasa.gov/api/temporal/daily/point"
POWER_ZARR = "s3://nasa-power/merra2/temporal/power_merra2_daily_temporal_utc.zarr"
CHIRPS_URL = ("https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_daily/tifs/p05/"
              "{y}/chirps-v2.0.{y}.{m}.{d}.tif.gz")

DAY_DEFINITIONS = {
    "open_meteo": "UTC calendar day (hourly values summed 00-23 UTC; timezone=UTC requested)",
    "power_zarr": "NASA POWER analysis-ready 'utc' store: UTC calendar day of MERRA-2",
    "chirps": "UTC calendar day (00-24 UTC) per CHIRPS documentation - confirm in review",
    "imd": ("IMD rainfall day: 08:30 IST previous day to 08:30 IST (= 03:00 UTC to 03:00 UTC) "
            "per IMD convention - confirm in review"),
}
_OPEN_METEO_MODELS = ("era5", "era5_land", "ecmwf_ifs")


def daily_sums(times: list[str], values: list) -> dict[str, dict]:
    """Sum hourly values per calendar day (from the leading YYYY-MM-DD) and count nulls explicitly."""
    out: dict[str, dict] = {}
    for stamp, value in zip(times, values):
        slot = out.setdefault(stamp[:10], {"sum_mm": 0.0, "n": 0, "n_null": 0})
        slot["n"] += 1
        if value is None:
            slot["n_null"] += 1
        else:
            slot["sum_mm"] += float(value)
    return {day: {**slot, "sum_mm": round(slot["sum_mm"], 3)} for day, slot in out.items()}


def _open_meteo_hourly(lat, lon, start, end, model, variable):
    data = fetch_json(OPEN_METEO_ARCHIVE, params={
        "latitude": lat, "longitude": lon, "start_date": start, "end_date": end,
        "hourly": variable, "models": model, "timezone": "UTC"})
    hourly = data["hourly"]
    series = hourly[variable] if variable in hourly else hourly[f"{variable}_{model}"]
    return hourly["time"], series


def probe_open_meteo(lat, lon, dates: list[str]) -> ProbeResult:
    start, end = dates[0], dates[-1]
    rows, problems, errors = [], [], []
    for model in _OPEN_METEO_MODELS:
        try:
            times, values = _open_meteo_hourly(lat, lon, start, end, model, "precipitation")
        except (DownloadError, KeyError) as exc:
            errors.append(exc)
            problems.append(f"{model} precipitation: {exc}")
            continue
        daily = daily_sums(times, values)
        n_null = sum(slot["n_null"] for slot in daily.values())
        if n_null:
            problems.append(f"{model} precipitation: {n_null} null hourly values")
        rows.append({"label": model,
                     "daily_mm": {d: (daily[d]["sum_mm"] if d in daily and daily[d]["n_null"] == 0 else None)
                                  for d in dates}})
    soil = None
    try:
        _, values = _open_meteo_hourly(lat, lon, start, end, "era5_land", "soil_moisture_0_to_7cm")
        soil = {"n": len(values), "n_null": sum(v is None for v in values)}
        if soil["n_null"]:
            problems.append(f"era5_land soil_moisture_0_to_7cm: {soil['n_null']} of {soil['n']} values null")
    except (DownloadError, KeyError) as exc:
        errors.append(exc)
        problems.append(f"era5_land soil_moisture_0_to_7cm: {exc}")

    evidence = {"event_rows": rows, "soil_moisture": soil, "problems": problems}
    if not rows:
        return ProbeResult("open_meteo", failure_status(errors),
                           "no precipitation series could be read", evidence, DAY_DEFINITIONS["open_meteo"])
    healthy = not problems and len(rows) == len(_OPEN_METEO_MODELS)
    return ProbeResult("open_meteo", "ok" if healthy else "partial",
                       f"{len(rows)}/{len(_OPEN_METEO_MODELS)} precipitation models readable; "
                       f"soil moisture {'ok' if soil and not soil['n_null'] else 'problem'}",
                       evidence, DAY_DEFINITIONS["open_meteo"])


def probe_power_api(lat, lon, dates: list[str]) -> ProbeResult:
    try:
        data = fetch_json(POWER_POINT, params={
            "parameters": "PRECTOTCORR,GWETTOP,GWETROOT", "community": "AG", "longitude": lon,
            "latitude": lat, "start": dates[0].replace("-", ""), "end": dates[-1].replace("-", ""),
            "format": "JSON"})
        params = data["properties"]["parameter"]
    except (DownloadError, KeyError) as exc:
        return ProbeResult("power_api", failure_status([exc]), f"NASA POWER API failed: {exc}",
                           {"event_rows": []}, "NASA POWER daily point API (time standard unavailable)")
    header = data.get("header", {})
    fill = header.get("fill_value", -999.0)
    time_standard = header.get("time_standard", "unknown")
    day_definition = f"NASA POWER time_standard={time_standard} (MERRA-2 native daily)"

    def clean(series):
        return {f"{k[:4]}-{k[4:6]}-{k[6:]}": (None if v == fill else v) for k, v in series.items()}

    precip = clean(params.get("PRECTOTCORR", {}))
    soil_ok = all(p in params and all(v != fill for v in params[p].values())
                  for p in ("GWETTOP", "GWETROOT"))
    n_fill = sum(v is None for v in precip.values())
    ok = bool(precip) and not n_fill and soil_ok
    return ProbeResult("power_api", "ok" if ok else "partial",
                       f"PRECTOTCORR days={len(precip)}, fill values={n_fill}, soil wetness "
                       f"{'ok' if soil_ok else 'missing/fill'}",
                       {"event_rows": [{"label": "merra2_power_api", "daily_mm": precip}],
                        "time_standard": time_standard, "fill_value": fill},
                       day_definition)


def probe_power_zarr(lat, lon, dates: list[str]) -> ProbeResult:
    day = DAY_DEFINITIONS["power_zarr"]
    try:
        import xarray as xr
    except ImportError:
        return ProbeResult("power_zarr", "inconclusive",
                           "xarray not installed (pip install -e .[audit])", {"event_rows": []}, day)
    try:
        ds = xr.open_zarr(POWER_ZARR, storage_options={"anon": True}, consolidated=True)
        series = ds["PRECTOTCORR"].sel(lat=lat, lon=lon, method="nearest").sel(
            time=slice(dates[0], dates[-1])).load()
        daily = {str(t)[:10]: (None if np.isnan(v) else round(float(v), 2))
                 for t, v in zip(series["time"].values, series.values)}
        evidence = {
            "event_rows": [{"label": "merra2_power_zarr_utc", "daily_mm": daily}],
            "dims": {k: int(v) for k, v in ds.sizes.items()},
            "n_variables": len(ds.data_vars),
            "soil_variables_present": [v for v in ("GWETTOP", "GWETROOT", "GWETPROF") if v in ds],
            "prectotcorr_chunks": str(ds["PRECTOTCORR"].encoding.get("chunks")),
        }
    except Exception as exc:  # network vs. library/API-shape problems are told apart in the hint
        return ProbeResult(
            "power_zarr", "inconclusive", f"{type(exc).__name__}: {exc}",
            {"event_rows": [],
             "hint": "If this is AttributeError/KeyError/ValueError the probe code may be wrong: inspect "
                     "xarray.open_zarr on the store and fix the probe before concluding the store is "
                     "unusable. A network error means retry."}, day)
    ok = bool(daily) and all(v is not None for v in daily.values())
    return ProbeResult("power_zarr", "ok" if ok else "partial",
                       f"bulk MERRA-2 store readable; {len(daily)} days returned", evidence, day)


def probe_chirps(dates, lat, lon, data_root, manifest, period_days) -> ProbeResult:
    day = DAY_DEFINITIONS["chirps"]
    try:
        import rasterio
    except ImportError as exc:
        return ProbeResult("chirps", "inconclusive", f"rasterio unavailable: {exc}", {"event_rows": []}, day)
    values, sizes, structure = {}, [], {}
    errors: list[Exception] = []
    for d in dates:
        y, m, dd = d.split("-")
        gz = Path(data_root) / "raw" / "audit" / "chirps" / f"chirps-v2.0.{y}.{m}.{dd}.tif.gz"
        try:
            download(CHIRPS_URL.format(y=y, m=m, d=dd), gz, manifest, "CHIRPS v2.0 daily p05",
                     "see https://www.chc.ucsb.edu/data/chirps (verify licence in review)")
        except DownloadError as exc:
            errors.append(exc)
            values[d] = None
            continue
        sizes.append(gz.stat().st_size)
        tif = gz.with_suffix("")
        if not tif.exists():
            with gzip.open(gz, "rb") as source, tif.open("wb") as target:
                shutil.copyfileobj(source, target)
        with rasterio.open(tif) as ds:
            structure = {"shape": tuple(ds.shape), "res": tuple(round(r, 4) for r in ds.res),
                         "bounds": tuple(round(b, 3) for b in ds.bounds), "nodata": ds.nodata}
            row, col = ds.index(lon, lat)
            value = float(ds.read(1, window=((row, row + 1), (col, col + 1)))[0, 0])
        nodata = structure["nodata"]  # read while the dataset was open
        values[d] = None if (nodata is not None and value == nodata) or value < 0 else round(value, 2)
    evidence = {"event_rows": [{"label": "chirps_p05", "daily_mm": values}], **structure}
    if sizes:
        evidence["est_total_gb"] = round(float(np.mean(sizes)) * period_days / 1e9, 1)
    if not sizes:
        return ProbeResult("chirps", failure_status(errors), "no CHIRPS file could be downloaded", evidence, day)
    grid_ok = structure.get("shape") == (2000, 7200) and structure.get("res") == (0.05, 0.05)
    ok = grid_ok and all(v is not None for v in values.values())
    return ProbeResult("chirps", "ok" if ok else "partial",
                       f"grid {structure.get('shape')} at {structure.get('res')} deg; "
                       f"~{evidence.get('est_total_gb')} GB for the full period", evidence, day)


def probe_imd(lat, lon, dates, data_root, manifest) -> ProbeResult:
    day = DAY_DEFINITIONS["imd"]
    hint = ("If this is a network error, retry. If it is AttributeError/TypeError/KeyError, run "
            "`python -c \"import imdlib; help(imdlib.get_data); help(imdlib.open_data)\"`, correct the "
            "probe, and do NOT report IMD gridded rainfall as unavailable until the probe itself is verified.")
    try:
        import imdlib as imd
    except ImportError:
        return ProbeResult("imd", "inconclusive", "imdlib not installed (pip install -e .[audit])",
                           {"event_rows": []}, day)
    year = int(dates[0][:4])
    target = Path(data_root) / "raw" / "audit" / "imd"
    target.mkdir(parents=True, exist_ok=True)
    try:
        imd.get_data("rain", year, year, fn_format="yearwise", file_dir=str(target))
        ds = imd.open_data("rain", year, year, fn_format="yearwise", file_dir=str(target)).get_xarray()
        point = ds["rain"].sel(lat=lat, lon=lon, method="nearest")
        values = {}
        for d in dates:
            v = float(point.sel(time=d).values)
            values[d] = None if (np.isnan(v) or v < 0) else round(v, 2)
        grid_shape = tuple(int(s) for s in ds["rain"].shape)
    except Exception as exc:
        return ProbeResult("imd", "inconclusive", f"{type(exc).__name__}: {exc}",
                           {"event_rows": [], "hint": hint}, day)
    for path in target.rglob("*"):
        if path.is_file() and manifest is not None and not manifest.is_current(path):
            manifest.add(path, "IMD gridded rainfall 0.25 deg (via imdlib)",
                         "https://imdpune.gov.in", "IMD data terms (verify in review)")
    ok = all(v is not None for v in values.values())
    return ProbeResult("imd", "ok" if ok else "partial",
                       f"IMD {year} gridded rain readable; grid shape {grid_shape}",
                       {"event_rows": [{"label": "imd_gauge_grid_0p25", "daily_mm": values}],
                        "grid_shape": grid_shape}, day)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_rain.py -v`
Expected: all PASS (7 tests). (`tests/live/` is excluded by default.)

- [ ] **Step 5: Commit**

```bash
git add src/aetherguard/audit/rain.py tests/test_rain.py tests/live/test_live_sources.py
git commit -m "feat: rain-product probes with explicit day definitions"
```

---

### Task 7: Terrain, land-cover, soil, road and Zenodo probes

**Files:**
- Create: `src/aetherguard/audit/static.py`, `src/aetherguard/audit/zenodo.py`
- Test: `tests/test_static.py`, `tests/test_zenodo.py`

**Interfaces:**
- Consumes: `http.download`, `http.fetch_json`, `http.DownloadError`; `grid.regions`; `audit.result`.
- Produces:
  - `static.dem_tile_name(lat, lon) -> str`; `static.dem_tile_url(lat, lon) -> str`; `static.worldcover_tile_name(lat, lon) -> str`; `static.tiles_needed(box: dict, tile_deg: float) -> int`; `static.domain_tile_count(tile_deg: float) -> int`
  - `static.probe_dem(lat, lon, data_root, manifest) -> ProbeResult` (`"dem"`, evidence `est_total_gb`); `static.probe_worldcover(lat, lon) -> ProbeResult` (`"worldcover"`, `est_total_gb`); `static.probe_soilgrids(lat, lon) -> ProbeResult` (`"soilgrids"`); `static.probe_osm_roads() -> ProbeResult` (`"osm_roads"`)
  - `zenodo.summarize_record(rec: dict) -> dict`; `zenodo.probe_zenodo_record(name, record_id, note) -> ProbeResult`; `zenodo.probe_zenodo_search(name, query) -> ProbeResult`; `zenodo.probe_nepal_inventories()`, `zenodo.probe_gaolan()`, `zenodo.probe_lithology_search()`, `zenodo.probe_kerala_inventory_search()` (names `"nepal_inventories"`, `"gaolan"`, `"lithology_search"`, `"kerala_inventory_search"`).

- [ ] **Step 1: Write the failing tests**

`tests/test_static.py`:
```python
from aetherguard.audit import static


def test_dem_tile_naming_matches_the_published_pattern():
    assert static.dem_tile_name(11.55, 76.13) == "Copernicus_DSM_COG_10_N11_00_E076_00_DEM"
    assert static.dem_tile_name(-0.5, -0.5) == "Copernicus_DSM_COG_10_S01_00_W001_00_DEM"
    assert static.dem_tile_url(11.55, 76.13).endswith(
        "Copernicus_DSM_COG_10_N11_00_E076_00_DEM/Copernicus_DSM_COG_10_N11_00_E076_00_DEM.tif")


def test_worldcover_tiles_are_three_degree_blocks():
    assert static.worldcover_tile_name(11.55, 76.13) == "ESA_WorldCover_10m_2021_v200_N09E075_Map.tif"
    assert static.worldcover_tile_name(-4.0, -70.0) == "ESA_WorldCover_10m_2021_v200_S06W072_Map.tif"


def test_tiles_needed_counts_partial_tiles():
    himalaya = {"lat_min": 22.0, "lat_max": 36.0, "lon_min": 72.0, "lon_max": 98.0}
    ghats = {"lat_min": 8.0, "lat_max": 21.5, "lon_min": 72.5, "lon_max": 78.5}
    assert static.tiles_needed(himalaya, 1.0) == 14 * 26
    assert static.tiles_needed(ghats, 1.0) == 14 * 7
    assert static.domain_tile_count(1.0) == 364 + 98
    assert static.domain_tile_count(3.0) == 45 + 18
```

`tests/test_zenodo.py`:
```python
from aetherguard.audit import zenodo


def test_summarize_record_legacy_file_list():
    rec = {"id": 1, "doi": "10.5281/zenodo.1",
           "metadata": {"title": "T", "license": {"id": "cc-by-4.0"}},
           "files": [{"key": "a.zip", "size": 100}, {"key": "b.zip", "size": 50}]}
    out = zenodo.summarize_record(rec)
    assert out["title"] == "T" and out["license"] == "cc-by-4.0"
    assert out["n_files"] == 2 and out["total_bytes"] == 150
    assert out["files"] == ["a.zip", "b.zip"]


def test_summarize_record_newer_entries_schema_and_missing_license():
    rec = {"id": 2, "metadata": {"title": "T2"},
           "files": {"entries": {"x.csv": {"key": "x.csv", "size": 7}}}}
    out = zenodo.summarize_record(rec)
    assert out["n_files"] == 1 and out["total_bytes"] == 7
    assert out["license"] is None


def test_probe_record_reports_size_and_license(monkeypatch):
    monkeypatch.setattr(zenodo, "fetch_json", lambda *a, **k: {
        "id": 3, "metadata": {"title": "Big", "license": {"id": "cc-by-4.0"}},
        "files": [{"key": "m.7z", "size": 5 * 10**9}]})
    res = zenodo.probe_zenodo_record("gaolan", "15180387", "note")
    assert res.status == "ok"
    assert res.evidence["total_bytes"] == 5 * 10**9


def test_probe_search_fails_when_nothing_found(monkeypatch):
    monkeypatch.setattr(zenodo, "fetch_json", lambda *a, **k: {"hits": {"hits": []}})
    assert zenodo.probe_zenodo_search("lithology_search", "nothing").status == "fail"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_static.py tests/test_zenodo.py -v`
Expected: FAIL/ERROR — `ImportError: cannot import name 'static'`.

- [ ] **Step 3: Write the implementation**

`src/aetherguard/audit/static.py`:
```python
"""Static-layer probes (terrain, land cover, soil, roads) and tile arithmetic."""
from __future__ import annotations

import math
from pathlib import Path

import requests

from ..grid import regions
from ..http import DownloadError, download
from .result import ProbeResult, failure_status

_DEM_BASE = "https://copernicus-dem-30m.s3.amazonaws.com"
_WORLDCOVER_BASE = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map"
_SOILGRIDS_VRT = "/vsicurl/https://files.isric.org/soilgrids/latest/data/clay/clay_0-5cm_mean.vrt"
_GEOFABRIK = {"india": "https://download.geofabrik.de/asia/india-latest.osm.pbf",
              "nepal": "https://download.geofabrik.de/asia/nepal-latest.osm.pbf"}


def _hemispheres(lat_index: int, lon_index: int) -> tuple[str, str]:
    return ("N" if lat_index >= 0 else "S"), ("E" if lon_index >= 0 else "W")


def dem_tile_name(lat: float, lon: float) -> str:
    la, lo = int(math.floor(lat)), int(math.floor(lon))
    ns, ew = _hemispheres(la, lo)
    return f"Copernicus_DSM_COG_10_{ns}{abs(la):02d}_00_{ew}{abs(lo):03d}_00_DEM"


def dem_tile_url(lat: float, lon: float) -> str:
    name = dem_tile_name(lat, lon)
    return f"{_DEM_BASE}/{name}/{name}.tif"


def worldcover_tile_name(lat: float, lon: float) -> str:
    la, lo = int(math.floor(lat / 3) * 3), int(math.floor(lon / 3) * 3)
    ns, ew = _hemispheres(la, lo)
    return f"ESA_WorldCover_10m_2021_v200_{ns}{abs(la):02d}{ew}{abs(lo):03d}_Map.tif"


def tiles_needed(box: dict, tile_deg: float) -> int:
    n_lat = math.ceil(box["lat_max"] / tile_deg) - math.floor(box["lat_min"] / tile_deg)
    n_lon = math.ceil(box["lon_max"] / tile_deg) - math.floor(box["lon_min"] / tile_deg)
    return n_lat * n_lon


def domain_tile_count(tile_deg: float) -> int:
    return sum(tiles_needed(box, tile_deg) for box in regions().values())


def probe_dem(lat, lon, data_root, manifest) -> ProbeResult:
    try:
        import rasterio
    except ImportError as exc:
        return ProbeResult("dem", "inconclusive", f"rasterio unavailable: {exc}")
    dest = Path(data_root) / "raw" / "audit" / "dem" / f"{dem_tile_name(lat, lon)}.tif"
    try:
        download(dem_tile_url(lat, lon), dest, manifest, "Copernicus DEM GLO-30",
                 "Copernicus DEM licence (free, attribution; verify in review)")
    except DownloadError as exc:
        return ProbeResult("dem", failure_status([exc]), f"DEM tile download failed: {exc}")
    with rasterio.open(dest) as ds:
        row, col = ds.index(lon, lat)
        elevation = float(ds.read(1, window=((row, row + 1), (col, col + 1)))[0, 0])
        shape, res = tuple(ds.shape), tuple(round(r, 6) for r in ds.res)
    tiles = domain_tile_count(1.0)
    evidence = {"shape": shape, "res_deg": res, "elevation_m_at_point": elevation,
                "tiles_for_domain": tiles,
                "est_total_gb": round(dest.stat().st_size * tiles / 1e9, 1)}
    plausible = -100.0 < elevation < 9000.0
    return ProbeResult("dem", "ok" if plausible else "fail",
                       f"tile {dest.name}: elevation at point {elevation:.0f} m; "
                       f"~{evidence['est_total_gb']} GB for the domain", evidence)


def probe_worldcover(lat, lon) -> ProbeResult:
    url = f"{_WORLDCOVER_BASE}/{worldcover_tile_name(lat, lon)}"
    try:
        response = requests.head(url, allow_redirects=True, timeout=60)
    except requests.RequestException as exc:
        return ProbeResult("worldcover", "unreachable", f"{type(exc).__name__}: {exc}")
    if response.status_code != 200:
        return ProbeResult("worldcover", "fail", f"HTTP {response.status_code} for {url}")
    size = int(response.headers.get("Content-Length", 0))
    tiles = domain_tile_count(3.0)
    evidence = {"tile_bytes": size, "tiles_for_domain": tiles, "est_total_gb": round(size * tiles / 1e9, 1)}
    return ProbeResult("worldcover", "ok", f"tile reachable; ~{evidence['est_total_gb']} GB for the domain", evidence)


def probe_soilgrids(lat, lon) -> ProbeResult:
    try:
        import rasterio
        from pyproj import Transformer
    except ImportError as exc:
        return ProbeResult("soilgrids", "inconclusive", f"library unavailable: {exc}")
    try:
        with rasterio.Env(GDAL_HTTP_TIMEOUT="60", GDAL_HTTP_MAX_RETRY="3",
                          GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
            with rasterio.open(_SOILGRIDS_VRT) as ds:
                x, y = Transformer.from_crs("EPSG:4326", ds.crs, always_xy=True).transform(lon, lat)
                row, col = ds.index(x, y)
                value = float(ds.read(1, window=((row, row + 1), (col, col + 1)))[0, 0])
                evidence = {"crs": ds.crs.to_string()[:80], "nodata": ds.nodata, "value_at_point": value}
    except rasterio.errors.RasterioIOError as exc:
        return ProbeResult("soilgrids", "unreachable", f"GDAL could not read the remote VRT: {exc}")
    except Exception as exc:
        return ProbeResult("soilgrids", "inconclusive", f"{type(exc).__name__}: {exc}")
    ok = evidence["nodata"] is None or value != evidence["nodata"]
    return ProbeResult("soilgrids", "ok" if ok else "partial",
                       f"clay 0-5 cm at point = {value} (nodata={evidence['nodata']})", evidence)


def probe_osm_roads() -> ProbeResult:
    sizes, errors = {}, []
    for region, url in _GEOFABRIK.items():
        try:
            response = requests.head(url, allow_redirects=True, timeout=60)
        except requests.RequestException as exc:
            errors.append(f"{region}: {type(exc).__name__}: {exc}")
            continue
        if response.status_code == 200:
            sizes[region] = int(response.headers.get("Content-Length", 0))
        else:
            errors.append(f"{region}: HTTP {response.status_code}")
    evidence = {"pbf_bytes": sizes, "errors": errors,
                "note": "Reading .pbf files needs an extra dependency (e.g. pyosmium); decide in Phase 1."}
    if not sizes:
        return ProbeResult("osm_roads", "unreachable" if errors else "fail", "no Geofabrik extract reachable", evidence)
    total_gb = round(sum(sizes.values()) / 1e9, 2)
    return ProbeResult("osm_roads", "ok" if not errors else "partial",
                       f"Geofabrik extracts reachable, {total_gb} GB combined", evidence)
```

`src/aetherguard/audit/zenodo.py`:
```python
"""Zenodo record and search probes (Nepal inventories, Gaolan sensors, lithology, Kerala)."""
from __future__ import annotations

from ..http import DownloadError, fetch_json
from .result import ProbeResult, failure_status

ZENODO_API = "https://zenodo.org/api/records"


def summarize_record(rec: dict) -> dict:
    meta = rec.get("metadata", {})
    files = rec.get("files") or []
    if isinstance(files, dict):  # newer schema: {"entries": {name: {...}}}
        files = list(files.get("entries", {}).values())
    return {
        "id": rec.get("id"),
        "doi": rec.get("doi") or meta.get("doi"),
        "title": meta.get("title"),
        "license": (meta.get("license") or {}).get("id"),
        "n_files": len(files),
        "total_bytes": sum(int(f.get("size", 0)) for f in files),
        "files": [f.get("key") or f.get("filename") for f in files][:20],
    }


def probe_zenodo_record(name: str, record_id: str, note: str) -> ProbeResult:
    try:
        rec = fetch_json(f"{ZENODO_API}/{record_id}")
    except DownloadError as exc:
        return ProbeResult(name, failure_status([exc]), f"Zenodo record {record_id} failed: {exc}")
    info = summarize_record(rec) | {"note": note}
    return ProbeResult(name, "ok", f"{info['title']} | {info['license']} | "
                       f"{info['n_files']} files, {info['total_bytes'] / 1e9:.2f} GB", info)


def probe_zenodo_search(name: str, query: str) -> ProbeResult:
    try:
        data = fetch_json(ZENODO_API, params={"q": query, "size": 5})
    except DownloadError as exc:
        return ProbeResult(name, failure_status([exc]), f"Zenodo search failed: {exc}")
    hits = [summarize_record(h) for h in data.get("hits", {}).get("hits", [])]
    if not hits:
        return ProbeResult(name, "fail", f"no Zenodo records for query {query!r}", {"query": query, "hits": []})
    return ProbeResult(name, "ok", f"{len(hits)} candidate record(s); top: {hits[0]['title']}",
                       {"query": query, "hits": hits})


def probe_nepal_inventories() -> ProbeResult:
    return probe_zenodo_record(
        "nepal_inventories", "10410752",
        "Database of 117 Nepal landslide inventories (metadata); each inventory is a separate download.")


def probe_gaolan() -> ProbeResult:
    return probe_zenodo_record(
        "gaolan", "15180387",
        "Gaolan Mountain loess-slope multi-sensor dataset (China): real physics, no fault labels documented.")


def probe_lithology_search() -> ProbeResult:
    return probe_zenodo_search("lithology_search", "global lithological map GLiM")


def probe_kerala_inventory_search() -> ProbeResult:
    return probe_zenodo_search("kerala_inventory_search", "Kerala landslide inventory 2018")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_static.py tests/test_zenodo.py -v`
Expected: all PASS (3 static + 4 zenodo).

- [ ] **Step 5: Commit**

```bash
git add src/aetherguard/audit/static.py src/aetherguard/audit/zenodo.py tests/test_static.py tests/test_zenodo.py
git commit -m "feat: terrain, soil, road and Zenodo probes with tile arithmetic"
```

---

### Task 8: Environment, credential, catalog-file and feasibility probes

**Files:**
- Create: `src/aetherguard/audit/env.py`, `src/aetherguard/audit/labels.py`, `src/aetherguard/audit/feasibility.py`
- Test: `tests/test_env.py`, `tests/test_labels.py`, `tests/test_feasibility.py`

**Interfaces:**
- Consumes: `landslides.read_catalog_csv/summarize_catalog/CatalogFormatError`; `grid.domain_cell_counts`; `audit.result`.
- Produces:
  - `env.probe_geolibs() -> ProbeResult` (`"geolibs"`); `env.probe_disk(path, min_free_gb) -> ProbeResult` (`"disk"`); `env.probe_earthdata_credentials() -> ProbeResult` (`"earthdata_credentials"`, evidence only booleans).
  - `labels.probe_manual_catalogs(data_root, cfg) -> list[ProbeResult]` (names `"catalog_nasa_glc"`, `"catalog_hma_ls_cat"`; `manual_pending` when the file is absent; evidence `report` and `summary`).
  - `feasibility.open_meteo_call_units(n_points, days, n_vars, days_per_unit=14, vars_per_unit=10) -> float`; `feasibility.scenarios(domain_cfg, audit_cfg) -> list[dict]` (each `name, points, days, variables, call_units, days_at_free_limit`); `feasibility.probe_feasibility(domain_cfg, audit_cfg) -> ProbeResult` (`"feasibility"`).

- [ ] **Step 1: Write the failing tests**

`tests/test_env.py`:
```python
import json

from aetherguard.audit import env


def test_geolibs_reports_versions_on_this_interpreter():
    res = env.probe_geolibs()
    assert res.evidence["versions"]["rasterio"]
    assert res.evidence["versions"]["python"].startswith("3.13")
    assert res.status == "ok"


def test_disk_probe_thresholds(tmp_path):
    assert env.probe_disk(tmp_path, min_free_gb=0.001).status == "ok"
    assert env.probe_disk(tmp_path, min_free_gb=10**9).status == "fail"


def test_earthdata_presence_never_exposes_values(monkeypatch):
    monkeypatch.setenv("EARTHDATA_USERNAME", "someone-name")
    monkeypatch.setenv("EARTHDATA_PASSWORD", "hunter2-secret")
    res = env.probe_earthdata_credentials()
    assert res.status == "ok"
    assert res.evidence["env_vars"] is True
    dumped = json.dumps(res.as_dict())
    assert "hunter2-secret" not in dumped and "someone-name" not in dumped


def test_earthdata_missing_means_needs_login(monkeypatch, tmp_path):
    monkeypatch.delenv("EARTHDATA_USERNAME", raising=False)
    monkeypatch.delenv("EARTHDATA_PASSWORD", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    res = env.probe_earthdata_credentials()
    assert res.status == "needs_login"
    assert res.evidence == {"env_vars": False, "netrc": False}
```

`tests/test_labels.py`:
```python
from aetherguard.audit import labels

CFG = {"catalog": {"max_accuracy_km": 5.0,
                   "manual_files": {"nasa_glc": "raw/manual/nasa_glc.csv",
                                    "hma_ls_cat": "raw/manual/hma_ls_cat_v2.csv"}}}
HEADER = "event_id,event_date,latitude,longitude,location_accuracy,landslide_trigger,country_name\n"


def test_missing_manual_files_are_pending_not_failed(tmp_path):
    results = {r.name: r for r in labels.probe_manual_catalogs(tmp_path, CFG)}
    assert results["catalog_nasa_glc"].status == "manual_pending"
    assert results["catalog_hma_ls_cat"].status == "manual_pending"
    assert "raw/manual/nasa_glc.csv" in results["catalog_nasa_glc"].summary


def test_present_catalog_is_summarised(tmp_path):
    path = tmp_path / "raw" / "manual" / "nasa_glc.csv"
    path.parent.mkdir(parents=True)
    path.write_text(HEADER + "1,2018-08-16,11.55,76.13,5km,downpour,India\n", encoding="utf-8")
    res = {r.name: r for r in labels.probe_manual_catalogs(tmp_path, CFG)}["catalog_nasa_glc"]
    assert res.status == "ok"
    assert res.evidence["summary"]["western_ghats"]["n_located"] == 1
    assert res.evidence["report"]["kept_rows"] == 1


def test_unreadable_catalog_fails_loudly_with_the_reason(tmp_path):
    path = tmp_path / "raw" / "manual" / "nasa_glc.csv"
    path.parent.mkdir(parents=True)
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    res = {r.name: r for r in labels.probe_manual_catalogs(tmp_path, CFG)}["catalog_nasa_glc"]
    assert res.status == "fail"
    assert "missing required column" in res.summary


def test_catalog_with_no_accurate_in_domain_events_is_partial(tmp_path):
    path = tmp_path / "raw" / "manual" / "nasa_glc.csv"
    path.parent.mkdir(parents=True)
    path.write_text(HEADER + "1,2018-08-16,11.55,76.13,unknown,downpour,India\n", encoding="utf-8")
    res = {r.name: r for r in labels.probe_manual_catalogs(tmp_path, CFG)}["catalog_nasa_glc"]
    assert res.status == "partial"
```

`tests/test_feasibility.py`:
```python
import pytest

from aetherguard.audit import feasibility as f


def test_call_units_follow_the_published_weighting():
    assert f.open_meteo_call_units(1, 14, 10) == 1.0
    assert f.open_meteo_call_units(1, 7, 3) == 1.0            # never below one call
    assert f.open_meteo_call_units(1, 14, 15) == pytest.approx(1.5)   # provider's 2-week/15-var example
    assert f.open_meteo_call_units(1, 28, 15) == pytest.approx(3.0)   # provider's 4-week example
    assert f.open_meteo_call_units(10, 28, 10) == pytest.approx(20.0)


def test_scenarios_show_full_grid_is_infeasible_and_sampling_is_not():
    domain = {"period": {"start": "2007-01-01", "end": "2024-12-31"}}
    audit = {"open_meteo": {"free_calls_per_day": 10_000, "days_per_call_unit": 14, "vars_per_call_unit": 10}}
    by_name = {s["name"]: s for s in f.scenarios(domain, audit)}
    full_025 = by_name["full domain, ERA5 0.25 deg grid, whole period"]
    assert full_025["points"] == 7_120 and full_025["days"] == 6_575
    assert full_025["days_at_free_limit"] > 300
    full_005 = by_name["full domain, 0.05 deg grid, whole period"]
    assert full_005["days_at_free_limit"] > 5_000   # about 8,360 days: hopeless on the free tier
    sampled = by_name["sampled case-control, 30,000 points x 60 days"]
    assert sampled["days_at_free_limit"] < 30


def test_probe_feasibility_is_ok_and_carries_scenarios():
    res = f.probe_feasibility({"period": {"start": "2007-01-01", "end": "2024-12-31"}},
                              {"open_meteo": {"free_calls_per_day": 10_000, "days_per_call_unit": 14,
                                              "vars_per_call_unit": 10}})
    assert res.status == "ok"
    assert len(res.evidence["scenarios"]) == 3
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_env.py tests/test_labels.py tests/test_feasibility.py -v`
Expected: FAIL/ERROR — `ImportError: cannot import name 'env'`.

- [ ] **Step 3: Write the implementation**

`src/aetherguard/audit/env.py`:
```python
"""Environment probes: geospatial stack, disk space, Earthdata credential presence."""
from __future__ import annotations

import importlib
import netrc
import os
import platform
import shutil
import sys
from pathlib import Path

from .result import ProbeResult

_MODULES = ("numpy", "pandas", "pyarrow", "rasterio", "shapely", "pyproj", "yaml", "requests")


def probe_geolibs() -> ProbeResult:
    versions: dict[str, str] = {}
    missing: list[str] = []
    for name in _MODULES:
        try:
            module = importlib.import_module(name)
            versions[name] = str(getattr(module, "__version__", "unknown"))
        except ImportError as exc:
            missing.append(f"{name}: {exc}")
    if "rasterio" in versions:
        import rasterio
        versions["gdal"] = rasterio.__gdal_version__
    versions["python"] = platform.python_version()
    ok = not missing and sys.version_info[:2] == (3, 13)
    summary = "geospatial stack imports on Python 3.13" if ok else f"problems: {missing or 'not Python 3.13'}"
    return ProbeResult("geolibs", "ok" if ok else "fail", summary, {"versions": versions, "missing": missing})


def probe_disk(path, min_free_gb: float) -> ProbeResult:
    usage = shutil.disk_usage(Path(path))
    free_gb = round(usage.free / 1e9, 1)
    evidence = {"free_gb": free_gb, "total_gb": round(usage.total / 1e9, 1),
                "cpu_count": os.cpu_count(), "required_free_gb": min_free_gb}
    ok = free_gb >= min_free_gb
    return ProbeResult("disk", "ok" if ok else "fail",
                       f"{free_gb} GB free (need {min_free_gb} GB)", evidence)


def probe_earthdata_credentials() -> ProbeResult:
    """Report only whether credentials exist - never their values."""
    env_vars = bool(os.environ.get("EARTHDATA_USERNAME") and os.environ.get("EARTHDATA_PASSWORD"))
    try:
        in_netrc = netrc.netrc().authenticators("urs.earthdata.nasa.gov") is not None
    except (FileNotFoundError, netrc.NetrcParseError, OSError):
        in_netrc = False
    evidence = {"env_vars": env_vars, "netrc": in_netrc}
    if env_vars or in_netrc:
        return ProbeResult("earthdata_credentials", "ok", "Earthdata credentials are configured", evidence)
    return ProbeResult(
        "earthdata_credentials", "needs_login",
        "no Earthdata credentials found; create a free account at urs.earthdata.nasa.gov and set "
        "EARTHDATA_USERNAME / EARTHDATA_PASSWORD (or a .netrc entry) to unlock the HMA catalog and IMERG",
        evidence)
```

`src/aetherguard/audit/labels.py`:
```python
"""Probes for the hand-placed landslide catalog files."""
from __future__ import annotations

from pathlib import Path

from .landslides import CatalogFormatError, read_catalog_csv, summarize_catalog
from .result import ProbeResult

_NAMES = {"nasa_glc": "catalog_nasa_glc", "hma_ls_cat": "catalog_hma_ls_cat"}


def probe_manual_catalogs(data_root, cfg) -> list[ProbeResult]:
    max_km = cfg["catalog"]["max_accuracy_km"]
    results = []
    for key, rel in cfg["catalog"]["manual_files"].items():
        name = _NAMES.get(key, f"catalog_{key}")
        path = Path(data_root) / rel
        if not path.exists():
            results.append(ProbeResult(
                name, "manual_pending", f"file not found: place the CSV export at data/{rel}",
                {"expected_path": f"data/{rel}"}))
            continue
        try:
            df, report = read_catalog_csv(path)
        except CatalogFormatError as exc:
            results.append(ProbeResult(name, "fail", f"cannot read {path.name}: {exc}", {"path": str(path)}))
            continue
        summary = summarize_catalog(df, max_km)
        located = sum(v["n_located"] for k, v in summary.items() if k != "outside_domain")
        evidence = {"report": report.as_dict(), "summary": summary, "max_accuracy_km": max_km}
        status = "ok" if located > 0 else "partial"
        results.append(ProbeResult(
            name, status,
            f"{report.kept_rows} events kept of {report.total_rows}; {located} in-domain within {max_km} km",
            evidence))
    return results
```

`src/aetherguard/audit/feasibility.py`:
```python
"""Ingest feasibility: how many Open-Meteo call units each fetching strategy would need."""
from __future__ import annotations

from datetime import date

from ..grid import domain_cell_counts
from .result import ProbeResult


def open_meteo_call_units(n_points: int, days: int, n_vars: int,
                          days_per_unit: float = 14, vars_per_unit: float = 10) -> float:
    """Provider weighting: max(1, days/14) * max(1, variables/10) per location."""
    return n_points * max(1.0, days / days_per_unit) * max(1.0, n_vars / vars_per_unit)


def _period_days(domain_cfg: dict) -> int:
    start = date.fromisoformat(domain_cfg["period"]["start"])
    end = date.fromisoformat(domain_cfg["period"]["end"])
    return (end - start).days + 1


def scenarios(domain_cfg: dict, audit_cfg: dict) -> list[dict]:
    om = audit_cfg["open_meteo"]
    days_full = _period_days(domain_cfg)
    variables = 3  # precipitation, soil moisture, one more hourly variable
    plans = [
        ("full domain, ERA5 0.25 deg grid, whole period", domain_cell_counts(0.25)["total"], days_full),
        ("full domain, 0.05 deg grid, whole period", domain_cell_counts(0.05)["total"], days_full),
        ("sampled case-control, 30,000 points x 60 days", 30_000, 60),
    ]
    out = []
    for name, points, days in plans:
        units = open_meteo_call_units(points, days, variables, om["days_per_call_unit"], om["vars_per_call_unit"])
        out.append({"name": name, "points": points, "days": days, "variables": variables,
                    "call_units": round(units), "days_at_free_limit": round(units / om["free_calls_per_day"], 1)})
    return out


def probe_feasibility(domain_cfg: dict, audit_cfg: dict) -> ProbeResult:
    plans = scenarios(domain_cfg, audit_cfg)
    return ProbeResult(
        "feasibility", "ok",
        "per-cell Open-Meteo ingestion for the whole grid is infeasible on the free tier; "
        "bulk sources or sampling are required",
        {"scenarios": plans, "source": "https://open-meteo.com/en/pricing (checked 2026-09-30)"})
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_env.py tests/test_labels.py tests/test_feasibility.py -v`
Expected: all PASS (4 env + 4 labels + 3 feasibility). The credential tests redirect `HOME`/`USERPROFILE` to a temp folder, so the user's real `.netrc` is never read or modified.

- [ ] **Step 5: Commit**

```bash
git add src/aetherguard/audit/env.py src/aetherguard/audit/labels.py src/aetherguard/audit/feasibility.py tests/test_env.py tests/test_labels.py tests/test_feasibility.py
git commit -m "feat: environment, credential-presence, catalog-file and feasibility probes"
```

---

### Task 9: Report writer and audit runner

**Files:**
- Create: `src/aetherguard/audit/report.py`, `src/aetherguard/audit/run.py`
- Test: `tests/test_report.py`, `tests/test_runner.py`

**Interfaces:**
- Consumes: every probe from Tasks 4–8; `manifest.Manifest`; `http.DownloadError`; `config.load_config/data_root/PROJECT_ROOT`.
- Produces:
  - `report.collect_secrets() -> list[str]`; `report.redact(text: str, secrets: list[str]) -> str`; `report.render_markdown(results: list[ProbeResult], generated_utc: str, cfg: dict, manifest_entries: dict | None = None) -> str`; `report.write_reports(results, out_dir, secrets, cfg, manifest_entries=None) -> tuple[Path, Path]` (writes `phase0_data_audit.md` and `.json`).
  - `run.build_registry() -> dict[str, Callable[[Context], ProbeResult | list[ProbeResult]]]`; `run.safe(name, fn, ctx) -> list[ProbeResult]`; `run.run_audit(only: set[str] | None = None, reports_dir: Path | None = None) -> list[ProbeResult]`; CLI `python -m aetherguard.audit.run [--only a,b] [--reports-dir DIR]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_report.py`:
```python
import json

from aetherguard.audit.report import redact, render_markdown, write_reports
from aetherguard.audit.result import ProbeResult

CFG = {"reported_local_gauge_48h_mm": 572,
       "reference_point": {"name": "wayanad_meppadi", "lat": 11.55, "lon": 76.13}}


def _results():
    return [
        ProbeResult("open_meteo", "ok", "3 models",
                    {"event_rows": [{"label": "era5", "daily_mm": {"2024-07-29": 33.2, "2024-07-30": 73.9}}]},
                    "UTC calendar day (hourly values summed 00-23 UTC; timezone=UTC requested)"),
        ProbeResult("imd", "ok", "readable",
                    {"event_rows": [{"label": "imd_gauge_grid_0p25", "daily_mm": {"2024-07-29": 80.0, "2024-07-30": 200.0}}]},
                    "IMD rainfall day: 08:30 IST previous day to 08:30 IST"),
        ProbeResult("earthdata_credentials", "needs_login", "no credentials", {"leak": "hunter2-secret"}),
        ProbeResult("catalog_nasa_glc", "manual_pending", "file not found", {}),
    ]


def test_markdown_shows_day_definition_beside_every_rain_row():
    md = render_markdown(_results(), "2026-09-30T00:00:00Z", CFG)
    assert "UTC calendar day" in md
    assert "08:30 IST" in md
    assert "572" in md and "secondary" in md.lower()
    assert "needs_login" in md and "manual_pending" in md


def test_needs_attention_section_lists_non_ok_probes():
    md = render_markdown(_results(), "2026-09-30T00:00:00Z", CFG)
    section = md.split("## Needs human action")[1].split("\n## ")[0]
    assert "earthdata_credentials" in section and "catalog_nasa_glc" in section
    assert "open_meteo" not in section


def test_redact_replaces_secrets_and_ignores_short_or_empty_ones():
    assert redact("password is hunter2-secret ok", ["hunter2-secret"]) == "password is [REDACTED] ok"
    assert redact("abc", ["", "ab"]) == "abc"  # empty and very short values are never substituted


def test_written_reports_contain_no_secret_and_round_trip(tmp_path):
    md_path, json_path = write_reports(_results(), tmp_path, ["hunter2-secret"], CFG)
    assert "hunter2-secret" not in md_path.read_text(encoding="utf-8")
    text = json_path.read_text(encoding="utf-8")
    assert "hunter2-secret" not in text and "[REDACTED]" in text
    assert json.loads(text)["results"][0]["name"] == "open_meteo"


def test_render_handles_results_without_optional_evidence():
    md = render_markdown([ProbeResult("geolibs", "ok", "fine")], "2026-09-30T00:00:00Z", CFG)
    assert "# Phase 0 data audit" in md
```

`tests/test_runner.py`:
```python
import requests

from aetherguard.audit import run
from aetherguard.audit.result import ProbeResult


def test_registry_contains_every_planned_probe():
    assert set(run.build_registry()) == {
        "geolibs", "disk", "earthdata_credentials", "ghcnd", "isd", "open_meteo", "power_api",
        "power_zarr", "chirps", "imd", "dem", "worldcover", "soilgrids", "osm_roads",
        "nepal_inventories", "gaolan", "lithology_search", "kerala_inventory_search",
        "manual_catalogs", "feasibility"}


def test_safe_converts_network_errors_and_bugs_into_results():
    def network(ctx):
        raise requests.ConnectionError("offline")

    def bug(ctx):
        raise KeyError("oops")

    assert run.safe("a", network, None)[0].status == "unreachable"
    res = run.safe("b", bug, None)[0]
    assert res.status == "inconclusive" and "KeyError" in res.summary


def test_safe_flattens_lists_and_passes_single_results_through():
    one = ProbeResult("x", "ok", "s")
    assert run.safe("x", lambda ctx: one, None) == [one]
    assert run.safe("x", lambda ctx: [one, one], None) == [one, one]


def test_offline_audit_still_writes_reports(monkeypatch, tmp_path, isolated_data_root):
    def offline(*args, **kwargs):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr("aetherguard.http.requests.get", offline)
    monkeypatch.setattr("aetherguard.http.requests.head", offline, raising=False)
    monkeypatch.setattr("aetherguard.http.time.sleep", lambda s: None)
    results = run.run_audit(only={"open_meteo", "power_api", "manual_catalogs", "feasibility"},
                            reports_dir=tmp_path)
    statuses = {r.name: r.status for r in results}
    assert statuses["open_meteo"] == "unreachable"
    assert statuses["power_api"] == "unreachable"
    assert statuses["feasibility"] == "ok"
    assert (tmp_path / "phase0_data_audit.md").exists()
    assert (tmp_path / "phase0_data_audit.json").exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_report.py tests/test_runner.py -v`
Expected: FAIL/ERROR — `ImportError: cannot import name 'report'`.

- [ ] **Step 3: Write the implementation**

`src/aetherguard/audit/report.py`:
```python
"""Redaction and Markdown/JSON rendering of the Phase 0 audit."""
from __future__ import annotations

import json
import netrc
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .result import ProbeResult

ATTENTION = {"needs_login", "manual_pending", "inconclusive", "fail", "unreachable"}
_MIN_SECRET_LENGTH = 4


def collect_secrets() -> list[str]:
    secrets = [os.environ.get(k, "") for k in ("EARTHDATA_USERNAME", "EARTHDATA_PASSWORD")]
    try:
        auth = netrc.netrc().authenticators("urs.earthdata.nasa.gov")
        if auth:
            secrets += [auth[0] or "", auth[2] or ""]
    except (FileNotFoundError, netrc.NetrcParseError, OSError):
        pass
    return [s for s in secrets if len(s) >= _MIN_SECRET_LENGTH]


def redact(text: str, secrets: list[str]) -> str:
    for secret in sorted(secrets, key=len, reverse=True):
        if len(secret) >= _MIN_SECRET_LENGTH:
            text = text.replace(secret, "[REDACTED]")
    return text


def _table(headers: list[str], rows: list[list]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return lines + [""]


def _by_name(results):
    return {r.name: r for r in results}


def _rain_section(results, cfg) -> list[str]:
    rows_src = [(r, row) for r in results for row in r.evidence.get("event_rows", []) if row["daily_mm"]]
    lines = ["## Rain products at the reference point", ""]
    if not rows_src:
        return lines + ["_No rain probe returned data._", ""]
    point = cfg.get("reference_point", {})
    lines += [f"Reference point: {point.get('name')} ({point.get('lat')} N, {point.get('lon')} E). "
              "Products use different definitions of a 'day' (last column); the windows do not line up "
              "exactly, so totals are indicative only.", ""]
    dates = sorted({d for _, row in rows_src for d in row["daily_mm"]})
    body = []
    for result, row in rows_src:
        values = [row["daily_mm"].get(d) for d in dates]
        total = "n/a" if any(v is None for v in values) else f"{sum(values):.0f}"
        body.append([row["label"], *["n/a" if v is None else f"{v:.0f}" for v in values], total,
                     result.day_definition or "not stated"])
    lines += _table(["source", *dates, "sum (mm)", "day definition"], body)
    gauge = cfg.get("reported_local_gauge_48h_mm")
    if gauge is not None:
        lines += [f"Reported local gauges: about {gauge} mm in 48 h to 30 Jul 2024 "
                  "(secondary source - press/papers; not yet checked against a primary source).", ""]
    return lines


def _ghcnd_section(results) -> list[str]:
    res = _by_name(results).get("ghcnd")
    lines = ["## Real fault labels (GHCN-Daily quality flags)", ""]
    if not res or "census_by_group" not in res.evidence:
        return lines + ["_Not run._", ""]
    ev = res.evidence
    lines += [f"Stations selected: {ev['n_selected']} ({ev['by_country']}). A flag means the value failed "
              "an automated NOAA check (the value is kept).", ""]
    body = [[k, v["n_stations"], v["n_valid"], v["n_flagged"],
             ", ".join(f"{f}:{n}" for f, n in v["by_flag"].items()) or "-"]
            for k, v in sorted(ev["census_by_group"].items())]
    return lines + _table(["region|elevation", "stations", "valid values", "flagged", "flags"], body)


def _catalog_section(results) -> list[str]:
    lines = ["## Landslide catalogs", ""]
    cats = [r for r in results if r.name.startswith("catalog_")]
    if not cats:
        return lines + ["_Not run._", ""]
    for r in cats:
        lines.append(f"**{r.name}** - {r.status}: {r.summary}")
        summary = r.evidence.get("summary")
        if summary:
            lines += [""] + _table(
                ["region", "total", "located", "unknown accuracy", "first", "last"],
                [[k, v["n_total"], v["n_located"], v["n_unknown_accuracy"], v["first_date"], v["last_date"]]
                 for k, v in summary.items()])
        else:
            lines.append("")
    return lines


def _feasibility_section(results, manifest_entries) -> list[str]:
    lines = ["## Ingest feasibility and volumes", ""]
    res = _by_name(results).get("feasibility")
    if res:
        lines += _table(["strategy", "points", "days", "call units", "days at free limit"],
                        [[s["name"], s["points"], s["days"], s["call_units"], s["days_at_free_limit"]]
                         for s in res.evidence["scenarios"]])
    volumes = [[r.name, r.evidence["est_total_gb"]] for r in results if "est_total_gb" in r.evidence]
    if volumes:
        lines += ["Estimated download volume for the full domain/period:", ""]
        lines += _table(["source", "GB"], volumes)
    if manifest_entries:
        groups = defaultdict(lambda: [0, 0, set()])
        for e in manifest_entries.values():
            groups[e.source][0] += 1
            groups[e.source][1] += e.size_bytes
            groups[e.source][2].add(e.licence)
        lines += ["Files downloaded so far (from the manifest):", ""]
        lines += _table(["source", "files", "MB", "licence recorded"],
                        [[s, n, f"{b / 1e6:.1f}", "; ".join(sorted(lic))] for s, (n, b, lic) in sorted(groups.items())])
    return lines


def render_markdown(results: list[ProbeResult], generated_utc: str, cfg: dict,
                    manifest_entries: dict | None = None) -> str:
    lines = ["# Phase 0 data audit", "", f"Generated: {generated_utc}", "",
             "Status meanings: ok = works as planned; partial = works with caveats; fail = does not work; "
             "unreachable = network problem; needs_login = free account required; manual_pending = you must "
             "place a file; inconclusive = the probe itself could not decide.", "",
             "## Summary", ""]
    lines += _table(["probe", "status", "summary"], [[r.name, r.status, r.summary] for r in results])
    attention = [r for r in results if r.status in ATTENTION]
    lines += ["## Needs human action", ""]
    if attention:
        lines += _table(["probe", "status", "what is needed"], [[r.name, r.status, r.summary] for r in attention])
    else:
        lines += ["_Nothing - all probes reported ok or partial._", ""]
    lines += _rain_section(results, cfg)
    lines += _ghcnd_section(results)
    lines += _catalog_section(results)
    lines += _feasibility_section(results, manifest_entries)
    return "\n".join(lines) + "\n"


def write_reports(results, out_dir, secrets, cfg, manifest_entries=None) -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    md_path, json_path = out_dir / "phase0_data_audit.md", out_dir / "phase0_data_audit.json"
    md_path.write_text(redact(render_markdown(results, generated, cfg, manifest_entries), secrets),
                       encoding="utf-8", newline="\n")
    payload = json.dumps({"generated_utc": generated, "results": [r.as_dict() for r in results]},
                         indent=2, default=str)
    json_path.write_text(redact(payload, secrets), encoding="utf-8", newline="\n")
    return md_path, json_path
```

`src/aetherguard/audit/run.py`:
```python
"""Probe registry, safe execution and the audit command line."""
from __future__ import annotations

import argparse
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import requests

from ..config import PROJECT_ROOT, data_root, load_config
from ..http import DownloadError
from ..manifest import Manifest
from . import env, feasibility, ghcnd, labels, rain, static, zenodo
from .report import collect_secrets, write_reports
from .result import ProbeResult


@dataclass
class Context:
    audit_cfg: dict
    domain_cfg: dict
    data_root: Path
    manifest: Manifest
    lat: float
    lon: float
    dates: list[str]

    @property
    def period_days(self) -> int:
        return feasibility._period_days(self.domain_cfg)


def build_registry() -> dict[str, Callable[[Context], ProbeResult | list[ProbeResult]]]:
    return {
        "geolibs": lambda c: env.probe_geolibs(),
        "disk": lambda c: env.probe_disk(c.data_root, c.audit_cfg["disk"]["min_free_gb"]),
        "earthdata_credentials": lambda c: env.probe_earthdata_credentials(),
        "ghcnd": lambda c: ghcnd.probe_ghcnd(c.data_root, c.manifest, c.audit_cfg),
        "isd": lambda c: ghcnd.probe_isd_history(c.data_root, c.manifest, c.audit_cfg),
        "open_meteo": lambda c: rain.probe_open_meteo(c.lat, c.lon, c.dates),
        "power_api": lambda c: rain.probe_power_api(c.lat, c.lon, c.dates),
        "power_zarr": lambda c: rain.probe_power_zarr(c.lat, c.lon, c.dates),
        "chirps": lambda c: rain.probe_chirps(c.dates, c.lat, c.lon, c.data_root, c.manifest, c.period_days),
        "imd": lambda c: rain.probe_imd(c.lat, c.lon, c.dates, c.data_root, c.manifest),
        "dem": lambda c: static.probe_dem(c.lat, c.lon, c.data_root, c.manifest),
        "worldcover": lambda c: static.probe_worldcover(c.lat, c.lon),
        "soilgrids": lambda c: static.probe_soilgrids(c.lat, c.lon),
        "osm_roads": lambda c: static.probe_osm_roads(),
        "nepal_inventories": lambda c: zenodo.probe_nepal_inventories(),
        "gaolan": lambda c: zenodo.probe_gaolan(),
        "lithology_search": lambda c: zenodo.probe_lithology_search(),
        "kerala_inventory_search": lambda c: zenodo.probe_kerala_inventory_search(),
        "manual_catalogs": lambda c: labels.probe_manual_catalogs(c.data_root, c.audit_cfg),
        "feasibility": lambda c: feasibility.probe_feasibility(c.domain_cfg, c.audit_cfg),
    }


def safe(name: str, fn, ctx) -> list[ProbeResult]:
    """Run one probe; a failure becomes a result and never aborts the audit."""
    try:
        out = fn(ctx)
    except (DownloadError, requests.RequestException) as exc:
        return [ProbeResult(name, "unreachable", f"network error: {exc}")]
    except Exception as exc:  # a probe bug must not abort the audit
        return [ProbeResult(name, "inconclusive", f"probe raised {type(exc).__name__}: {exc}",
                            {"traceback": traceback.format_exc(limit=5)})]
    return out if isinstance(out, list) else [out]


def run_audit(only: set[str] | None = None, reports_dir: Path | None = None) -> list[ProbeResult]:
    audit_cfg, domain_cfg = load_config("audit"), load_config("domain")
    root = data_root()
    root.mkdir(parents=True, exist_ok=True)
    manifest = Manifest(PROJECT_ROOT / "manifests" / "data_manifest.jsonl", root)
    point = audit_cfg["reference_point"]
    ctx = Context(audit_cfg, domain_cfg, root, manifest, point["lat"], point["lon"], audit_cfg["event_dates"])
    registry = build_registry()
    unknown = (only or set()) - set(registry)
    if unknown:
        raise SystemExit(f"unknown probe name(s): {sorted(unknown)}; choose from {sorted(registry)}")
    results: list[ProbeResult] = []
    for name, fn in registry.items():
        if only and name not in only:
            continue
        print(f"[audit] {name} ...", flush=True)
        results += safe(name, fn, ctx)
    out_dir = reports_dir or PROJECT_ROOT / "reports"
    md, js = write_reports(results, out_dir, collect_secrets(), audit_cfg, manifest.entries())
    problems = manifest.verify()
    print(f"[audit] wrote {md} and {js}; manifest problems: {problems or 'none'}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Phase 0 data audit.")
    parser.add_argument("--only", default="", help="comma-separated probe names (default: all)")
    parser.add_argument("--reports-dir", default=None, type=Path)
    args = parser.parse_args()
    only = {n.strip() for n in args.only.split(",") if n.strip()} or None
    for result in run_audit(only, args.reports_dir):
        print(f"{result.status:>15}  {result.name:<24} {result.summary[:90]}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_report.py tests/test_runner.py -v`
Expected: all PASS (5 report + 4 runner).
Then run the whole suite: `.venv/Scripts/python -m pytest -q`
Expected: every test passes; `tests/live` is deselected.

- [ ] **Step 5: Commit**

```bash
git add src/aetherguard/audit/report.py src/aetherguard/audit/run.py tests/test_report.py tests/test_runner.py
git commit -m "feat: audit report writer with redaction and resilient runner"
```

---

### Task 10: Run the audit against the real sources, review, and hit the gate

**Files:**
- Create (by running): `reports/phase0_data_audit.md`, `reports/phase0_data_audit.json`, `manifests/data_manifest.jsonl`
- Modify: probe code only if a probe is `inconclusive` because of a probe bug (see Step 3)

**Interfaces:**
- Consumes: `python -m aetherguard.audit.run`; the live tests in `tests/live/`.
- Produces: the committed audit report that the user reviews at the Phase 0 gate, and the list of decisions Plan 2 (Phase 1) needs.

- [ ] **Step 1: Run the live smoke tests**

Run: `.venv/Scripts/python -m pytest tests/live -m live -v`
Expected: 2 PASS. If a live test fails on a network error, retry once; if it still fails, note it and continue — the audit report records the same failure.

- [ ] **Step 2: Run the full audit**

Run: `.venv/Scripts/python -m aetherguard.audit.run`
Expected: one `[audit] <name> ...` line per probe, then a summary table; `reports/phase0_data_audit.md` and `.json` written; the last line reports `manifest problems: none`. The run downloads roughly 0.3–1 GB (station files, a few CHIRPS/DEM files, the IMD year file) into the git-ignored `data/` tree. `manual_catalogs` reporting `manual_pending` and `earthdata_credentials` reporting `needs_login` are **expected** until the user completes their two manual steps.

- [ ] **Step 3: Triage any `inconclusive` probe**

Open `reports/phase0_data_audit.md` and read "Needs human action". For each `inconclusive` probe, read the `hint` in `reports/phase0_data_audit.json`. If the cause is a probe bug (an `AttributeError`, `TypeError` or `KeyError` from `imdlib` or `xarray`), inspect the library (`.venv/Scripts/python -c "import imdlib; help(imdlib.get_data)"`), fix the probe in `src/aetherguard/audit/rain.py`, rerun only that probe (`.venv/Scripts/python -m aetherguard.audit.run --only imd`), and repeat until the result is `ok`, `partial`, `fail` or `unreachable` on real evidence. **Do not report a source as unavailable while its probe is still `inconclusive`.** After any probe edit run `.venv/Scripts/python -m pytest -q`.

- [ ] **Step 4: Verify the evidence is sane before presenting it**

Run:
```bash
.venv/Scripts/python - <<'EOF'
import json
r = {x["name"]: x for x in json.load(open("reports/phase0_data_audit.json"))["results"]}
for name in ("open_meteo", "power_api", "power_zarr", "chirps", "imd"):
    x = r.get(name)
    if x:
        print(name, x["status"], "|", x["day_definition"])
        for row in x["evidence"].get("event_rows", []):
            print("   ", row["label"], row["daily_mm"])
g = r["ghcnd"]["evidence"]
print("ghcnd stations:", g["n_selected"], g["by_country"])
print(json.dumps(g["census_by_group"], indent=1)[:900])
EOF
.venv/Scripts/python -c "from aetherguard.audit.report import collect_secrets;t=open('reports/phase0_data_audit.json',encoding='utf-8').read()+open('reports/phase0_data_audit.md',encoding='utf-8').read();print('secrets check (values, not names):', not any(s in t for s in collect_secrets()))"
```
Expected: every rain row lists its day definition; the GHCN-D census shows counts by region and elevation band; the secrets check prints `True`. Sanity-check the Wayanad numbers against the earlier hand check (ERA5 about 33 mm on 29 Jul and about 74 mm on 30 Jul; POWER about 53 and 28 mm) — a large discrepancy means a probe bug, not a finding.

- [ ] **Step 5: Commit the report and manifest, then stop at the gate**

```bash
git add reports/phase0_data_audit.md reports/phase0_data_audit.json manifests/data_manifest.jsonl
git commit -m "docs: Phase 0 data audit report and download manifest"
```

**GATE — stop here and report to the user.** Present: (a) the summary table, (b) the "Needs human action" list, (c) the rain comparison with day definitions, (d) the real-fault-label counts by region and elevation, (e) the ingest-feasibility table, (f) the recommended source set for Phase 1 (keep / replace / drop, with the reason for each). Then ask the user to (1) create the Earthdata account and (2) export the NASA landslide catalog to `data/raw/manual/nasa_glc.csv` (and the HMA catalog to `data/raw/manual/hma_ls_cat_v2.csv` once the account exists), rerun `.venv/Scripts/python -m aetherguard.audit.run --only earthdata_credentials,manual_catalogs` (a partial run writes to `reports/partial/` and does not overwrite the committed full report), and approve the source set. **Do not start Phase 1 until the user approves.**

---

## Later plans (each written at its gate, from the audit's findings)

Each phase below gets its own detailed plan once the previous gate is approved, because the earlier phase's findings decide its content. The spec (§11) fixes the deliverables and gates:

| Plan | Phase | Deliverable | Depends on from this plan |
|---|---|---|---|
| 2 | 1 — Ingest and frozen splits | Bulk ingest of the approved sources into a Parquet feature store; frozen, checksummed time- and region-blocked splits; detection-event definition frozen in `configs\` (spec §1) | `grid`, `manifest`/`http`, `ghcnd`, `landslides` readers; the audit's source decisions and feasibility numbers |
| 3 | 2 — Baselines and integrity engine | Threshold and LHASA-style baselines; the four-layer integrity engine; fault injection calibrated on the real flag census | Real-flag counts by region; Gaolan availability; `ghcnd.read_dly` |
| 4 | 3 — Hazard model and rain corrector | LightGBM landslide model with monotonic constraints and calibration; upper-quantile rain corrector; ablations; Wayanad/Kerala case studies | Frozen splits; gauge reference chosen from the audit (IMD grid or alternatives); day-definition alignment |
| 5 | 4 — Alerts, API and dashboard | Alert engine with data-confidence flag and escalation rule; FastAPI; Streamlit | Calibrated probabilities and integrity outputs |
| 6 | 5 — Final evaluation | Full report with case studies and limitations | Everything above |
