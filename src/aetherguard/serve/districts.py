"""District boundaries for India, Nepal and Bhutan, the cell-to-district table, and the district level rule.

CLI: python -m aetherguard.serve.districts build [--raw-dir DIR] [--out-dir DIR] [--skip-download]

Why. A warning is issued to an administrative area, not to a 5 km cell. `cell_places` gives each cell the district of its
label place (GeoNames admin2), which is the district of a nearby town, not the district the cell lies in. This module
uses district polygons instead.

Sources: geoBoundaries gbOpen (https://www.geoboundaries.org), the district level of each country:

  India   ADM2 "District", 736 units, Pathways Data / lgdirectory.gov.in, 2021: Open Data Commons Open Database License 1.0
  Nepal   ADM2 "Districts", 75 units, Wikimedia Commons, 2006: Public Domain (the 75 districts before 2015; Nawalparasi
          and Rukum were split since, so the table has 75, not 77)
  Bhutan  ADM1 "Dzongdeys", 20 units (the dzongkhags, Bhutan's districts; its ADM2 are the 205 gewogs), 2010:
          Creative Commons Attribution 3.0

The licence of each file is copied from the geoBoundaries API record (`boundaryLicense`) into `districts.json`, never
typed here. The boundary files and the table stay under `data/` (never committed); the India table is a derived database
under ODbL, so it may be shared only under ODbL with attribution.

Cell rule. A cell takes the district whose polygon holds its centre (`grid.cell_center`). Where polygons of two
countries overlap (contested borders), the polygon of the cell's own country wins; the country is the one of
`cell_places` (the India point-of-view mask of the base map). A centre inside no polygon (a coastline or border sliver)
takes the nearest district of its own country within `MAX_NEAREST_KM`; beyond that it has none. `how` records which.

District level rule (`DistrictRule`, `district_levels`): a district is at level L on a day when at least `cells` of its
cells, or at least the `share` of its scored cells of the day, are at L or above; its level is the highest such L.

Writes `cell_districts.parquet` (cell_id, country, district_id, district, how) and `districts.json` (sources, licences,
counts) into `<data>/processed/districts/`.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import shapely
from shapely.geometry import shape

from ..config import data_root
from ..grid import cell_center
from ..http import download
from ..manifest import Manifest, sha256_file

API = "https://www.geoboundaries.org/api/current/gbOpen/{iso}/{level}/"
SOURCES = {"India": ("IND", "ADM2"), "Nepal": ("NPL", "ADM2"), "Bhutan": ("BTN", "ADM1")}
MAX_NEAREST_KM = 5.0
KM_PER_DEG = 111.2


def raw_dir() -> Path:
    return data_root() / "raw" / "boundaries" / "geoboundaries"


def out_dir() -> Path:
    return data_root() / "processed" / "districts"


# ------------------------------------------------------------------------------------------------ download

def fetch(directory: Path, manifest: Manifest) -> dict[str, dict]:
    """Per country: the geoBoundaries API record (stored as `<ISO>_<LEVEL>_meta.json`) and its GeoJSON, downloaded."""
    directory.mkdir(parents=True, exist_ok=True)
    out = {}
    for country, (iso, level) in SOURCES.items():
        response = requests.get(API.format(iso=iso, level=level), timeout=60)
        response.raise_for_status()
        meta = response.json()
        (directory / f"{iso}_{level}_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        path = directory / f"geoBoundaries-{iso}-{level}.geojson"
        download(meta["gjDownloadURL"], path, manifest, source=f"geoBoundaries gbOpen {iso} {level}",
                 licence=meta["boundaryLicense"])
        out[country] = meta
    return out


def stored_meta(directory: Path) -> dict[str, dict]:
    return {country: json.loads((directory / f"{iso}_{level}_meta.json").read_text(encoding="utf-8"))
            for country, (iso, level) in SOURCES.items()}


# --------------------------------------------------------------------------------------------- polygons

def read_polygons(path: Path, country: str) -> pd.DataFrame:
    """country, district_id, district, geometry of every feature of a geoBoundaries GeoJSON file."""
    features = json.loads(Path(path).read_text(encoding="utf-8"))["features"]
    rows = [{"country": country, "district_id": str(f["properties"]["shapeID"]),
             "district": str(f["properties"]["shapeName"]), "geometry": shapely.make_valid(shape(f["geometry"]))}
            for f in features]
    return pd.DataFrame(rows, columns=["country", "district_id", "district", "geometry"])


def all_polygons(directory: Path) -> pd.DataFrame:
    return pd.concat([read_polygons(directory / f"geoBoundaries-{iso}-{level}.geojson", country)
                      for country, (iso, level) in SOURCES.items()], ignore_index=True)


def _km(lat: float, lon: float, polygon) -> float:
    """Approximate distance (km) from a point to a polygon, longitudes scaled by cos(latitude)."""
    scale = np.cos(np.radians(lat))
    scaled = shapely.affinity.scale(polygon, xfact=scale, yfact=1.0, origin=(0.0, 0.0))
    return float(scaled.distance(shapely.Point(lon * scale, lat))) * KM_PER_DEG


def cell_districts(cells: pd.DataFrame, polygons: pd.DataFrame, max_nearest_km: float = MAX_NEAREST_KM) -> pd.DataFrame:
    """The district of every cell of `cells` (cell_id, country) under the cell rule of the module doc."""
    import shapely.affinity  # noqa: F401  (used by _km)
    lat, lon = cell_center(cells["cell_id"].to_numpy(dtype=np.int64))
    points = shapely.points(lon, lat)
    geoms = polygons["geometry"].to_numpy()
    tree = shapely.STRtree(geoms)
    hit_point, hit_poly = tree.query(points, predicate="intersects")
    country = cells["country"].to_numpy(dtype=object)
    poly_country = polygons["country"].to_numpy(dtype=object)
    chosen = np.full(len(cells), -1, dtype=np.int64)
    how = np.full(len(cells), "none", dtype=object)
    for i, j in zip(hit_point, hit_poly):
        if chosen[i] < 0 or (poly_country[j] == country[i] and poly_country[chosen[i]] != country[i]):
            chosen[i], how[i] = j, "inside"
    reach_deg = max_nearest_km / KM_PER_DEG / max(np.cos(np.radians(np.nanmax(np.abs(lat)) if len(lat) else 0.0)), 0.1)
    for i in np.flatnonzero(chosen < 0):
        own = np.flatnonzero(poly_country == country[i])
        near = [j for j in tree.query(points[i].buffer(reach_deg)) if j in set(own)]
        if not near:
            continue
        distances = [_km(lat[i], lon[i], geoms[j]) for j in near]
        best = int(np.argmin(distances))
        if distances[best] <= max_nearest_km:
            chosen[i], how[i] = near[best], "nearest"
    found = chosen >= 0
    district_id = np.full(len(cells), None, dtype=object)
    district = np.full(len(cells), None, dtype=object)
    district_id[found] = polygons["district_id"].to_numpy(dtype=object)[chosen[found]]
    district[found] = polygons["district"].to_numpy(dtype=object)[chosen[found]]
    return pd.DataFrame({"cell_id": cells["cell_id"].to_numpy(dtype=np.int64), "country": country,
                         "district_id": district_id, "district": district, "how": how})


# ---------------------------------------------------------------------------------------- the level rule

@dataclass(frozen=True)
class DistrictRule:
    """A district is at level L when at least `cells` of its cells, or at least `share` of its scored cells, are at L
    or above (either part may be None, not both)."""
    cells: int | None
    share: float | None

    def __post_init__(self) -> None:
        if self.cells is None and self.share is None:
            raise ValueError("a district rule needs a cell count, a share, or both")

    @property
    def name(self) -> str:
        parts = ([f"{self.cells} cell{'s' if self.cells != 1 else ''}"] if self.cells is not None else []) + \
                ([f"{self.share:.0%} of cells"] if self.share is not None else [])
        return " or ".join(parts)

    def to_dict(self) -> dict:
        return {"cells": self.cells, "share": self.share, "name": self.name}


def district_levels(levels: np.ndarray, scored: np.ndarray, district: np.ndarray, n_districts: int,
                    rule: DistrictRule) -> np.ndarray:
    """(districts, days) levels from cell levels (cells, days): `district` holds each cell's district index (-1: none,
    left out), `scored` the cell-days with a score (the denominator of the share)."""
    levels, scored, district = np.asarray(levels), np.asarray(scored, dtype=bool), np.asarray(district, dtype=np.int64)
    keep = district >= 0
    order = np.argsort(district[keep], kind="stable")
    groups = district[keep][order]
    starts = np.searchsorted(groups, np.arange(n_districts))
    present = np.isin(np.arange(n_districts), groups)

    def per_district(mask: np.ndarray) -> np.ndarray:
        total = np.zeros((n_districts, mask.shape[1]), dtype=np.int64)
        if len(groups):
            sums = np.add.reduceat(mask[keep][order].astype(np.int64), starts[present], axis=0)
            total[present] = sums
        return total

    n_scored = per_district(scored)
    out = np.zeros((n_districts, levels.shape[1]), dtype=np.int8)
    for level in (1, 2, 3):
        count = per_district((levels >= level) & scored)
        reached = np.zeros(count.shape, dtype=bool)
        if rule.cells is not None:
            reached |= count >= rule.cells
        if rule.share is not None:
            with np.errstate(invalid="ignore", divide="ignore"):
                reached |= (count > 0) & (count >= rule.share * n_scored)
        out[reached] = level
    return out


# ------------------------------------------------------------------------------------------------- build

def build(raw: Path, out: Path, skip_download: bool, say=print) -> dict:
    manifest = Manifest(raw / "manifest.jsonl", data_root())
    meta = stored_meta(raw) if skip_download else fetch(raw, manifest)
    polygons = all_polygons(raw)
    cells = pd.read_parquet(data_root() / "processed" / "places" / "cell_places.parquet", columns=["cell_id", "country"])
    table = cell_districts(cells, polygons)
    out.mkdir(parents=True, exist_ok=True)
    table.to_parquet(out / "cell_districts.parquet", index=False)
    sources = {country: {"iso": SOURCES[country][0], "level": SOURCES[country][1],
                         "canonical": m["boundaryCanonical"], "units": int(m["admUnitCount"]),
                         "licence": m["boundaryLicense"], "licence_detail": m.get("licenseDetail"),
                         "licence_source": m.get("licenseSource"), "source": m["boundarySource"],
                         "year": m["boundaryYearRepresented"], "url": m["gjDownloadURL"],
                         "sha256": sha256_file(raw / f"geoBoundaries-{SOURCES[country][0]}-{SOURCES[country][1]}.geojson")}
               for country, m in meta.items()}
    counts = {"cells": int(len(table)), "by_how": table["how"].value_counts().to_dict(),
              "by_country": table["country"].value_counts().to_dict(),
              "districts_with_cells": int(table["district_id"].nunique()),
              "cells_without_district_by_country": table[table["district_id"].isna()]["country"].value_counts().to_dict()}
    record = {"name": "cell_districts", "built_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "rule": f"centre inside the polygon (own country first where two overlap), else the nearest district of "
                      f"the own country within {MAX_NEAREST_KM} km, else none",
              "sources": sources, "counts": counts,
              "note": "boundary files and this table stay under data/ (not committed); the India part is a derived "
                      "database of an ODbL 1.0 source"}
    (out / "districts.json").write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    say(json.dumps(counts, ensure_ascii=False))
    return record


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aetherguard.serve.districts", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("build", help="download the boundaries and write the cell-to-district table")
    cmd.add_argument("--raw-dir", type=Path, default=None)
    cmd.add_argument("--out-dir", type=Path, default=None)
    cmd.add_argument("--skip-download", action="store_true")
    args = parser.parse_args(argv)
    build(args.raw_dir or raw_dir(), args.out_dir or out_dir(), args.skip_download)
    return 0


if __name__ == "__main__":
    sys.exit(main())
