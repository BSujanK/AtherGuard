"""Human place names for the cells the dashboard shows.

CLI: python -m aetherguard.serve.places build [--raw-dir DIR] [--out-dir DIR] [--manifest PATH] [--replay-dir DIR]
                                              [--config PATH] [--skip-download]

Every modelled cell (the candidate cells the live runner scores, `live.run.load_candidate_cells`, plus every cell that
appears in a replay-store set) gets one label: a populated place from GeoNames with its district (admin2) and state
(admin1) names, the distance from the cell centre, and the country.

Label rule. The place is the one that maximises

    log10(population + 10) - distance_km / DISTANCE_SCALE_KM          (DISTANCE_SCALE_KM = 15)

over the places of the cell's country, with the great-circle (haversine) distance from the cell centre
(`grid.cell_center`). Distance alone would pick a 300-person hamlet 1 km away over a 50,000 town 6 km away; the
population term lets the town win while a big city far away (it would need to be about 15 km further per factor 10 of
population) never beats a village next door. The search is exact: only places within `slack` kilometres of the nearest
one can win, and that bound is derived from the gazetteer's smallest and largest population.

Country. A cell takes its country from the India point-of-view mask of the base map (1 India, 2 Nepal, 3 Bhutan; see
`serve.basemap`), never from GeoNames' country code, so the claimed territory of India is India. A place is classed the
same way (by the mask at its location, else by its GeoNames code), and a cell of India, Nepal or Bhutan only takes a
place of its own country: a Nepalese town 3 km away is not the name of a cell in India. A cell outside those three
(other land, sea) takes the nearest-by-rule place of any country and that place's country.

A district or state GeoNames does not give is left out (None), never filled in.

Sources (every download recorded in the data manifest), https://download.geonames.org/export/dump/ :
  cities500.zip          populated places with population >= 500
  admin1CodesASCII.txt   state / province names
  admin2Codes.txt        district names
GeoNames data is licensed CC BY 4.0; the attribution text is `ATTRIBUTION`. The extract (countries IN, NP, BT plus
anything inside the box lat 6-37.5, lon 68-98) is stored next to the downloads as `geonames_places.parquet`.

Writes `cell_places.parquet` (cell_id, place, district, state, country, distance_km, place_lat, place_lon, population)
and `places.json` (source, licence, attribution, build date, counts) into `<data>/processed/places/`.
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import sys
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import PROJECT_ROOT, data_root
from ..grid import ID_STRIDE, cell_center, latlon_to_cell
from ..http import DownloadError, download
from ..manifest import Manifest, sha256_file
from .basemap import BHUTAN, CLASS_NAMES, INDIA, INDIA_GRID, NEPAL, OTHER, Grid

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
GEONAMES_BASE = "https://download.geonames.org/export/dump/"
GEONAMES_LICENCE = "CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)"
ATTRIBUTION = "Place names: GeoNames (CC BY 4.0)"
CITIES_ZIP, CITIES_MEMBER = "cities500.zip", "cities500.txt"
ADMIN1_FILE, ADMIN2_FILE = "admin1CodesASCII.txt", "admin2Codes.txt"
EXTRACT_NAME = "geonames_places.parquet"
TABLE_NAME, META_NAME = "cell_places.parquet", "places.json"
TABLE_COLUMNS = ["cell_id", "place", "district", "state", "country", "distance_km", "place_lat", "place_lon", "population"]

HOME_COUNTRIES = ("IN", "NP", "BT")                    # kept whole, whatever their position
BOX = {"lat_min": 6.0, "lat_max": 37.5, "lon_min": 68.0, "lon_max": 98.0}   # neighbours inside it are kept for context
COUNTRY_CLASS = {"IN": INDIA, "NP": NEPAL, "BT": BHUTAN}
COUNTRY_NAMES = {"AF": "Afghanistan", "BD": "Bangladesh", "BT": "Bhutan", "CN": "China", "IN": "India", "KG": "Kyrgyzstan",
                 "LK": "Sri Lanka", "MM": "Myanmar", "MV": "Maldives", "NP": "Nepal", "PK": "Pakistan", "TJ": "Tajikistan",
                 "TM": "Turkmenistan", "UZ": "Uzbekistan"}

DISTANCE_SCALE_KM = 15.0
POPULATION_OFFSET = 10
EARTH_RADIUS_KM = 6371.0088
FAR_KM = 25                                            # from here the place is "nearest town", not where the cell is
QUERY_CHUNK = 2000
CITY_COLUMNS = ["geonameid", "name", "asciiname", "alternatenames", "latitude", "longitude", "feature_class",
                "feature_code", "country_code", "cc2", "admin1", "admin2", "admin3", "admin4", "population",
                "elevation", "dem", "timezone", "modified"]


class PlacesError(RuntimeError):
    """The place table cannot be built or read; the message names what is wrong."""


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    dest: Path
    licence: str


def default_sources(raw_dir: Path) -> list[Source]:
    names = {CITIES_ZIP: "GeoNames cities500 (populated places with population >= 500)",
             ADMIN1_FILE: "GeoNames admin1 codes (state / province names, ASCII)",
             ADMIN2_FILE: "GeoNames admin2 codes (district names)"}
    return [Source(label, GEONAMES_BASE + file, raw_dir / file, GEONAMES_LICENCE) for file, label in names.items()]


# --- gazetteer --------------------------------------------------------------------------------------------------

def read_cities(path: Path) -> pd.DataFrame:
    """The rows of cities500.txt inside the GeoNames zip (tab separated, UTF-8, no header)."""
    try:
        with zipfile.ZipFile(path) as archive:
            raw = archive.read(CITIES_MEMBER)
    except (zipfile.BadZipFile, KeyError) as error:
        raise PlacesError(f"{path.name} is not a GeoNames cities zip holding {CITIES_MEMBER}: {error}") from None
    return pd.read_csv(io.BytesIO(raw), sep="\t", header=None, names=CITY_COLUMNS, dtype=str, keep_default_na=False,
                       quoting=3, usecols=["geonameid", "name", "asciiname", "latitude", "longitude", "country_code", "admin1",
                                           "admin2", "population"])


def read_admin_names(path: Path) -> dict[str, str]:
    """{code: ASCII name} of an admin1CodesASCII.txt / admin2Codes.txt file (`code<TAB>name<TAB>ascii name<TAB>id`)."""
    names = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 3 and parts[0]:
                names[parts[0]] = parts[2] or parts[1]
    return names


def inside_box(lat, lon, box: dict = BOX):
    return (lat >= box["lat_min"]) & (lat <= box["lat_max"]) & (lon >= box["lon_min"]) & (lon <= box["lon_max"])


def extract_places(cities: pd.DataFrame, admin1: dict[str, str], admin2: dict[str, str]) -> pd.DataFrame:
    """Places of the home countries plus those inside the context box, with district and state names (None when
    GeoNames has none). Columns: geonameid, place, district, state, country_code, lat, lon, population."""
    lat = pd.to_numeric(cities["latitude"], errors="coerce")
    lon = pd.to_numeric(cities["longitude"], errors="coerce")
    keep = (cities["country_code"].isin(HOME_COUNTRIES) | inside_box(lat, lon)) & lat.notna() & lon.notna()
    kept = cities[keep]
    code = kept["country_code"]
    state_key = code + "." + kept["admin1"]
    district_key = state_key + "." + kept["admin2"]
    frame = pd.DataFrame({
        "geonameid": pd.to_numeric(kept["geonameid"]).astype("int64"),
        "place": kept["asciiname"].where(kept["asciiname"] != "", kept["name"]).where(lambda t: t != "", None),
        "district": district_key.map(admin2).where(kept["admin2"] != ""),
        "state": state_key.map(admin1).where(kept["admin1"] != ""),
        "country_code": code,
        "lat": lat[keep].astype("float64"),
        "lon": lon[keep].astype("float64"),
        "population": pd.to_numeric(kept["population"], errors="coerce").fillna(0).astype("int64"),
    })
    frame = frame[frame["place"].notna()].sort_values("geonameid", kind="stable").reset_index(drop=True)
    return frame.astype({"district": object, "state": object}).where(frame.notna(), None)


# --- country classes --------------------------------------------------------------------------------------------

def country_classes(lat, lon, mask: np.ndarray, grid: Grid = INDIA_GRID) -> np.ndarray:
    """uint8 base-map class (0 sea or outside the grid, 1 India, 2 Nepal, 3 Bhutan, 4 other land) of each point, by
    the global grid cell it falls in, the rule `Grid.locate` uses."""
    ids = np.atleast_1d(latlon_to_cell(lat, lon)).astype(np.int64)
    row, col = ids // ID_STRIDE - grid.lat_index0, ids % ID_STRIDE - grid.lon_index0
    inside = (row >= 0) & (row < grid.rows) & (col >= 0) & (col < grid.cols)
    out = np.zeros(ids.shape, dtype=np.uint8)
    out[inside] = mask[row[inside], col[inside]]
    return out


def place_classes(gazetteer: pd.DataFrame, mask: np.ndarray, grid: Grid) -> np.ndarray:
    """Country class of each place: the base-map class where the mask says India, Nepal or Bhutan, else by GeoNames' code."""
    by_mask = country_classes(gazetteer["lat"].to_numpy(), gazetteer["lon"].to_numpy(), mask, grid)
    by_code = gazetteer["country_code"].map(COUNTRY_CLASS).fillna(OTHER).to_numpy(dtype=np.uint8)
    return np.where(np.isin(by_mask, (INDIA, NEPAL, BHUTAN)), by_mask, by_code)


def place_countries(gazetteer: pd.DataFrame, classes: np.ndarray) -> np.ndarray:
    names = gazetteer["country_code"].map(lambda code: COUNTRY_NAMES.get(code, code)).to_numpy(dtype=object)
    for cls in (INDIA, NEPAL, BHUTAN):
        names[classes == cls] = CLASS_NAMES[cls]
    return names


# --- the label rule ---------------------------------------------------------------------------------------------

def place_score(population, distance_km):
    """The quantity the label maximises: log10(population + 10) - distance_km / 15."""
    return np.log10(np.asarray(population, dtype=np.float64) + POPULATION_OFFSET) - np.asarray(distance_km) / DISTANCE_SCALE_KM


class _Pool:
    """The places of one country (or all) in a haversine ball tree, answering "best place by the rule" exactly."""

    def __init__(self, gazetteer: pd.DataFrame, positions: np.ndarray) -> None:
        from sklearn.neighbors import BallTree
        self.positions = positions
        part = gazetteer.iloc[positions]
        self.tree = BallTree(np.radians(part[["lat", "lon"]].to_numpy()), metric="haversine")
        self.log_population = np.log10(part["population"].to_numpy(dtype=np.float64) + POPULATION_OFFSET)
        # A place further than the nearest one by more than this cannot out-score it, whatever its population.
        self.slack_km = DISTANCE_SCALE_KM * float(self.log_population.max() - self.log_population.min())

    def best(self, lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(gazetteer position, distance in km) of the highest scoring place for each point."""
        points = np.radians(np.column_stack([lat, lon]))
        nearest = self.tree.query(points, k=1)[0][:, 0]
        found, dists = self.tree.query_radius(points, r=nearest + self.slack_km / EARTH_RADIUS_KM + 1e-9, return_distance=True)
        chosen, distance = np.empty(len(points), dtype=np.int64), np.empty(len(points))
        for i, (ids, d) in enumerate(zip(found, dists)):
            km = d * EARTH_RADIUS_KM
            top = int(np.argmax(self.log_population[ids] - km / DISTANCE_SCALE_KM))
            chosen[i], distance[i] = self.positions[ids[top]], km[top]
        return chosen, distance


def label_cells(cell_ids, gazetteer: pd.DataFrame, mask: np.ndarray, grid: Grid = INDIA_GRID) -> pd.DataFrame:
    """The label table (TABLE_COLUMNS) of `cell_ids`, one row per distinct cell, sorted by cell_id."""
    ids = np.unique(np.asarray(cell_ids, dtype=np.int64))
    if not len(ids):
        raise PlacesError("no cells to label")
    if gazetteer.empty:
        raise PlacesError("the gazetteer holds no places")
    lat, lon = cell_center(ids)
    cell_class = country_classes(lat, lon, mask, grid)
    classes = place_classes(gazetteer, mask, grid)
    countries = place_countries(gazetteer, classes)
    everything = _Pool(gazetteer, np.arange(len(gazetteer)))
    pools = {cls: _Pool(gazetteer, np.flatnonzero(classes == cls)) for cls in (INDIA, NEPAL, BHUTAN) if (classes == cls).any()}
    chosen, distance = np.empty(len(ids), dtype=np.int64), np.empty(len(ids))
    for cls in np.unique(cell_class):
        pool = pools.get(int(cls), everything)
        rows = np.flatnonzero(cell_class == cls)
        for start in range(0, len(rows), QUERY_CHUNK):
            part = rows[start:start + QUERY_CHUNK]
            chosen[part], distance[part] = pool.best(lat[part], lon[part])
    picked = gazetteer.iloc[chosen]
    country = np.where(np.isin(cell_class, (INDIA, NEPAL, BHUTAN)),
                       np.array([CLASS_NAMES.get(int(c), "") for c in cell_class], dtype=object), countries[chosen])
    table = pd.DataFrame({
        "cell_id": ids, "place": picked["place"].to_numpy(), "district": picked["district"].to_numpy(),
        "state": picked["state"].to_numpy(), "country": country, "distance_km": np.rint(distance).astype(np.int32),
        "place_lat": picked["lat"].round(4).to_numpy(), "place_lon": picked["lon"].round(4).to_numpy(),
        "population": picked["population"].to_numpy(dtype=np.int64)})
    return table[TABLE_COLUMNS]


# --- which cells -----------------------------------------------------------------------------------------------

def replay_cell_ids(replay_dir: Path) -> np.ndarray:
    """Every cell id in the alert tables of every set of the replay store at `replay_dir` (empty when there is none)."""
    from ..alerts.store import ALERTS_DIR, ReplayStore, StoreError
    store = ReplayStore(replay_dir)
    if not store.available:
        return np.empty(0, dtype=np.int64)
    found = []
    try:
        sets = store.manifest["sets"]
    except (StoreError, ValueError, KeyError) as error:
        raise PlacesError(f"replay store {replay_dir} cannot be read: {error}") from None
    for name, entry in sets.items():
        for day in entry["dates"]:
            path = replay_dir / name / ALERTS_DIR / f"{day}.parquet"
            found.append(np.unique(pd.read_parquet(path, columns=["cell_id"])["cell_id"].to_numpy(dtype=np.int64)))
    return np.unique(np.concatenate(found)) if found else np.empty(0, dtype=np.int64)


def modelled_cell_ids(cfg: dict, replay_dir: Path) -> tuple[np.ndarray, dict]:
    """(sorted distinct cell ids, counts) of the live runner's candidate cells and the cells of the replay store sets."""
    from ..live import run as live_run
    candidates = live_run.load_candidate_cells(cfg)[0]["cell_id"].to_numpy(dtype=np.int64)
    replay = replay_cell_ids(replay_dir)
    both = np.unique(np.concatenate([candidates, replay]))
    return both, {"candidate_cells": int(len(candidates)), "replay_cells": int(len(replay)), "cells": int(len(both))}


# --- reading and showing the table -----------------------------------------------------------------------------

def read_table(path: Path) -> pd.DataFrame:
    """The label table at `path`, sorted by cell_id; PlacesError when it is absent or not a label table."""
    try:
        table = pd.read_parquet(path)
    except (OSError, ValueError) as error:
        raise PlacesError(f"{path.name} cannot be read: {error}") from None
    missing = [c for c in TABLE_COLUMNS if c not in table.columns]
    if missing:
        raise PlacesError(f"{path.name} lacks the columns {missing}")
    return table[TABLE_COLUMNS].sort_values("cell_id", kind="stable").reset_index(drop=True)


def _text(value) -> str | None:
    return None if value is None or (isinstance(value, float) and np.isnan(value)) or value == "" else str(value)


def place_record(row) -> dict:
    """The label of one table row as a JSON-ready dict (missing district / state are None)."""
    return {"place": _text(row["place"]), "district": _text(row["district"]), "state": _text(row["state"]),
            "country": _text(row["country"]), "distance_km": int(row["distance_km"]),
            "place_lat": float(row["place_lat"]), "place_lon": float(row["place_lon"]), "population": int(row["population"])}


def place_name(record: dict) -> str:
    """"Mananthavady, Wayanad, Kerala": place, district, state without a part that repeats the one before, and the
    country when it is not India. At FAR_KM or more the distance follows in brackets, since the cell is then not in
    the place."""
    parts: list[str] = []
    for part in (record["place"], record["district"], record["state"]):
        if part and (not parts or parts[-1] != part):
            parts.append(part)
    if record["country"] and record["country"] != CLASS_NAMES[INDIA]:
        parts.append(record["country"])
    name = ", ".join(parts)
    return f"{name} ({record['distance_km']} km)" if record["distance_km"] >= FAR_KM else name


# --- build -----------------------------------------------------------------------------------------------------

def _write_atomic(path: Path, write: Callable) -> None:
    partial = path.with_name(path.name + ".tmp")
    try:
        write(partial)
        partial.replace(path)
    finally:
        partial.unlink(missing_ok=True)


def build_places(sources: list[Source], cfg: dict, replay_dir: Path, out_dir: Path, manifest: Manifest,
                 basemap_npz: Path, fetch: Callable = download, skip_download: bool = False) -> dict:
    """Fetch any source that is not current in the manifest, extract the gazetteer, label the cells and write the
    table and its json into `out_dir`; returns the json."""
    by_name = {s.dest.name: s for s in sources}
    for source in sources:
        if manifest.is_current(source.dest):
            continue
        if skip_download:
            raise PlacesError(f"{source.dest} is missing or differs from its manifest entry (run without --skip-download)")
        fetch(source.url, source.dest, manifest, source.name, source.licence)
    try:
        with np.load(basemap_npz) as stored:
            mask = stored["mask"]
            grid = Grid(lat0=float(stored["lat0"]), lon0=float(stored["lon0"]), rows=mask.shape[0], cols=mask.shape[1])
    except (OSError, KeyError, ValueError) as error:
        raise PlacesError(f"the base map {basemap_npz} cannot be read ({error}); build it (python -m aetherguard.serve.basemap build)") from None

    cities_source = by_name[CITIES_ZIP]
    gazetteer = extract_places(read_cities(cities_source.dest), read_admin_names(by_name[ADMIN1_FILE].dest),
                               read_admin_names(by_name[ADMIN2_FILE].dest))
    extract_path = cities_source.dest.with_name(EXTRACT_NAME)
    _write_atomic(extract_path, lambda p: gazetteer.to_parquet(p, index=False))
    if not manifest.is_current(extract_path):
        manifest.add(extract_path, "GeoNames extract: countries IN, NP, BT and places inside lat 6-37.5, lon 68-98",
                     f"derived: {GEONAMES_BASE}{CITIES_ZIP}, {ADMIN1_FILE}, {ADMIN2_FILE}", GEONAMES_LICENCE)

    ids, cell_counts = modelled_cell_ids(cfg, replay_dir)
    table = label_cells(ids, gazetteer, mask, grid)
    entries = manifest.entries()
    recorded = [{"name": s.name, "url": entries[manifest.relpath(s.dest)].url, "licence": s.licence,
                 "path": manifest.relpath(s.dest), "size_bytes": entries[manifest.relpath(s.dest)].size_bytes,
                 "sha256": entries[manifest.relpath(s.dest)].sha256} for s in sources]
    out_dir.mkdir(parents=True, exist_ok=True)
    table_path = out_dir / TABLE_NAME
    _write_atomic(table_path, lambda p: table.to_parquet(p, index=False))
    distance = table["distance_km"].to_numpy()
    meta = {
        "schema_version": SCHEMA_VERSION, "name": "cell_places", "source": "GeoNames", "licence": GEONAMES_LICENCE,
        "attribution": ATTRIBUTION, "build_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "rule": f"maximise log10(population + {POPULATION_OFFSET}) - distance_km / {DISTANCE_SCALE_KM:g} over the places of the "
                "cell's country (base-map mask: India, Nepal, Bhutan; any place for other land); great-circle distance from the "
                "cell centre; a district or state GeoNames does not give is left out",
        "counts": {
            **cell_counts, "gazetteer_places": int(len(gazetteer)),
            "labelled_places": int(table["place"].nunique()),
            "without_district": int(table["district"].isna().sum()), "without_state": int(table["state"].isna().sum()),
            "far_cells": int((distance >= FAR_KM).sum()),
            "by_country": {k: int(v) for k, v in table["country"].value_counts().items()},
            "distance_km": {"median": float(np.median(distance)), "p90": float(np.percentile(distance, 90)),
                            "max": int(distance.max())},
        },
        "sources": recorded,
        "files": {TABLE_NAME: {"size_bytes": table_path.stat().st_size, "sha256": sha256_file(table_path)}},
    }
    _write_atomic(out_dir / META_NAME, lambda p: p.write_text(json.dumps(meta, indent=1), encoding="utf-8"))
    return meta


def format_summary(meta: dict, out_dir: Path, seconds: float) -> str:
    counts = meta["counts"]
    countries = ", ".join(f"{k} {v}" for k, v in counts["by_country"].items())
    return "\n".join([
        f"places: {counts['cells']} cells labelled ({counts['candidate_cells']} candidate, {counts['replay_cells']} replay) "
        f"-> {out_dir} in {seconds:.0f} s",
        f"  gazetteer {counts['gazetteer_places']} places, {counts['labelled_places']} used; countries: {countries}",
        f"  distance to the place: median {counts['distance_km']['median']:g} km, p90 {counts['distance_km']['p90']:g} km, "
        f"max {counts['distance_km']['max']} km; {counts['far_cells']} cells at {FAR_KM} km or more",
        f"  without district {counts['without_district']}, without state {counts['without_state']}; {meta['attribution']}",
    ])


def main(argv: list[str] | None = None, fetch: Callable = download) -> int:
    parser = argparse.ArgumentParser(description="Build the place names of the modelled cells (GeoNames).")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="download the sources (idempotent) and write the place table")
    build.add_argument("--raw-dir", type=Path, help="default: <data>/raw/geonames")
    build.add_argument("--out-dir", type=Path, help="default: <data>/processed/places")
    build.add_argument("--manifest", type=Path, help="default: <project>/manifests/data_manifest.jsonl")
    build.add_argument("--replay-dir", type=Path, help="default: <data>/processed/alerts/replay")
    build.add_argument("--config", type=Path, help="live runner config naming the candidate cells (default configs/live_run.yaml)")
    build.add_argument("--basemap", type=Path, help="default: <data>/processed/basemap/india_basemap.npz")
    build.add_argument("--skip-download", action="store_true", help="build from the files already on disk")
    args = parser.parse_args(argv)
    from ..live import run as live_run
    raw_dir = args.raw_dir or data_root() / "raw" / "geonames"
    out_dir = args.out_dir or data_root() / "processed" / "places"
    manifest = Manifest(args.manifest or PROJECT_ROOT / "manifests" / "data_manifest.jsonl", data_root())
    started = time.perf_counter()
    try:
        meta = build_places(default_sources(raw_dir), live_run.load_run_config(args.config), args.replay_dir or data_root() / "processed" / "alerts" / "replay",
                            out_dir, manifest, args.basemap or data_root() / "processed" / "basemap" / "india_basemap.npz",
                            fetch=fetch, skip_download=args.skip_download)
    except (PlacesError, DownloadError, ValueError, OSError) as exc:
        print(f"places: error: {exc}", file=sys.stderr)
        return 1
    print(format_summary(meta, out_dir, time.perf_counter() - started))
    return 0


if __name__ == "__main__":
    sys.exit(main())
