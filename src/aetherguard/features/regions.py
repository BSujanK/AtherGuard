"""Country and region per 0.05-degree cell centre from Natural Earth admin-0 polygons (design D1).

Country code per polygon: `ISO_A2` when it is a real code; Natural Earth stores -99 for a few countries (France,
Norway, Kosovo ...) and then `ISO_A2_EH` is used; when that is -99 as well (Siachen Glacier, Somaliland, N. Cyprus)
the three-letter `ADM0_A3` is used, so the code is never missing for a polygon. A centre inside no polygon (open
sea, or a coastal cell the 1:50m coastline leaves just offshore) has a null country and is `out_of_scope`.
A centre on a border shared by two polygons takes the polygon listed first in the file (deterministic).

Region: `himalaya` = country in `himalaya_countries` and centre in the himalaya box and not in the ghats box;
`western_ghats` = country in `ghats_countries` and centre in the ghats box; anything else `out_of_scope`. Box
edges are half-open (`lat_min <= lat < lat_max`), exactly like `grid.region_labels`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import shapely
from shapely.geometry import shape
from shapely.strtree import STRtree

from ..grid import cell_center, regions as region_boxes
from ..http import download
from ..manifest import Manifest

OUT_OF_SCOPE = "out_of_scope"
CELL_REGION_COLUMNS = ["cell_id", "country_code", "region"]
CELL_REGIONS_NAME = "cell_regions.parquet"
CELL_REGIONS_REPORT_NAME = "cell_regions_report.json"
_NO_CODE = ("", "-99")


@dataclass(frozen=True)
class Countries:
    """Admin-0 polygons in file order with their codes and a spatial index."""
    codes: list[str]
    geometries: np.ndarray
    tree: STRtree


def country_code(properties: dict) -> str:
    for key in ("ISO_A2", "ISO_A2_EH", "ADM0_A3"):
        value = properties.get(key)
        if value is not None and str(value).strip() not in _NO_CODE:
            return str(value).strip()
    raise ValueError(f"no usable country code in properties: {properties.get('NAME', properties)}")


def load_countries(path) -> Countries:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"admin-0 boundaries not found: {path}")
    collection = json.loads(path.read_text(encoding="utf-8"))
    codes, geometries = [], []
    for feature in collection["features"]:
        codes.append(country_code(feature["properties"]))
        geometries.append(shape(feature["geometry"]))
    geometries = np.array(geometries, dtype=object)
    return Countries(codes, geometries, STRtree(geometries))


def countries_at(lat, lon, countries: Countries) -> np.ndarray:
    """Country code per point (object array, None where no polygon contains the point)."""
    points = shapely.points(np.asarray(lon, dtype=float), np.asarray(lat, dtype=float))
    point_idx, polygon_idx = countries.tree.query(points, predicate="intersects")
    order = np.lexsort((polygon_idx, point_idx))  # per point, smallest polygon index first
    point_idx, polygon_idx = point_idx[order], polygon_idx[order]
    first = np.ones(len(point_idx), dtype=bool)
    first[1:] = point_idx[1:] != point_idx[:-1]
    out = np.full(len(points), None, dtype=object)
    codes = np.array(countries.codes, dtype=object)
    out[point_idx[first]] = codes[polygon_idx[first]]
    return out


def _in_box(lat, lon, box: dict) -> np.ndarray:
    return (lat >= box["lat_min"]) & (lat < box["lat_max"]) & (lon >= box["lon_min"]) & (lon < box["lon_max"])


def region_for(country, lat, lon, cfg: dict) -> np.ndarray:
    """Region per point from its country code and centre (design D1)."""
    country = np.asarray(country, dtype=object)
    lat, lon = np.asarray(lat, dtype=float), np.asarray(lon, dtype=float)
    boxes = region_boxes()
    in_ghats_box = _in_box(lat, lon, boxes["western_ghats"])
    himalaya_ok = np.isin(country, cfg["himalaya_countries"]) & _in_box(lat, lon, boxes["himalaya"]) & ~in_ghats_box
    ghats_ok = np.isin(country, cfg["ghats_countries"]) & in_ghats_box
    out = np.full(len(lat), OUT_OF_SCOPE, dtype=object)
    out[himalaya_ok] = "himalaya"
    out[ghats_ok] = "western_ghats"
    return out


def cell_regions(cell_ids, countries: Countries, cfg: dict) -> pd.DataFrame:
    """(cell_id, country_code, region) for each cell, in the given order."""
    ids = np.asarray(cell_ids, dtype=np.int64)
    lat, lon = cell_center(ids)
    country = countries_at(lat, lon, countries)
    return pd.DataFrame({
        "cell_id": ids,
        "country_code": pd.Series(country, dtype="str"),
        "region": pd.Series(region_for(country, lat, lon, cfg), dtype="str"),
    })


def _none_if_null(value):
    return None if pd.isna(value) else str(value)


def positive_agreement(positives: pd.DataFrame, countries: Countries, cfg: dict) -> dict:
    """Compare the label store's region of each positive cell-day with the region of its cell centre.

    Disagreements (border cells) are listed per cell and counted; they are not an error.
    """
    per_cell = (positives.groupby(["cell_id", "region"]).size().rename("n_cell_days").reset_index()
                .rename(columns={"region": "label_region"}).sort_values(["cell_id", "label_region"]))
    cell_table = cell_regions(per_cell["cell_id"].to_numpy(), countries, cfg)
    per_cell = per_cell.reset_index(drop=True)
    per_cell["cell_region"] = cell_table["region"]
    per_cell["country_code"] = cell_table["country_code"]
    disagree = per_cell[per_cell["label_region"] != per_cell["cell_region"]]
    return {
        "n_cells": int(per_cell["cell_id"].nunique()),
        "n_cell_days": int(per_cell["n_cell_days"].sum()),
        "agree_cell_days": int(per_cell["n_cell_days"].sum() - disagree["n_cell_days"].sum()),
        "disagree_cell_days": int(disagree["n_cell_days"].sum()),
        "no_country_cell_days": int(per_cell.loc[per_cell["country_code"].isna(), "n_cell_days"].sum()),
        "disagree_cells": [{"cell_id": int(r.cell_id), "label_region": r.label_region, "cell_region": r.cell_region,
                            "country_code": _none_if_null(r.country_code), "n_cell_days": int(r.n_cell_days)}
                           for r in disagree.itertuples(index=False)],
    }


def region_report(table: pd.DataFrame) -> dict:
    """Cell counts per region and per country, and the number of cells with no country polygon."""
    return {
        "n_cells": len(table),
        "per_region": {k: int(v) for k, v in table["region"].value_counts().sort_index().items()},
        "per_country": {k: int(v) for k, v in table["country_code"].value_counts().sort_index().items()},
        "no_country_cells": int(table["country_code"].isna().sum()),
    }


def fetch_boundaries(root: Path, manifest: Manifest, cfg: dict) -> Path:
    """Download the Natural Earth admin-0 file into <root>/raw/boundaries (idempotent) and record it."""
    spec = cfg["boundaries"]
    dest = Path(root) / "raw" / "boundaries" / spec["file"]
    return download(spec["url"], dest, manifest, spec["source"], spec["licence"])


def build_cell_regions(terrain_path, boundaries_path, positives_path, out_dir, cfg: dict) -> dict:
    """Write cell_regions.parquet (one row per terrain cell) and cell_regions_report.json; return the report."""
    out_dir = Path(out_dir)
    countries = load_countries(boundaries_path)
    terrain = pd.read_parquet(terrain_path, columns=["cell_id", "region_box"])
    table = cell_regions(terrain["cell_id"].to_numpy(), countries, cfg)
    report = region_report(table)
    boxes = terrain["region_box"].to_numpy()
    report["terrain_cells_by_region_box"] = {
        box: {"per_region": {k: int(v) for k, v in table.loc[boxes == box, "region"].value_counts().sort_index().items()},
              "no_country_cells": int(table.loc[boxes == box, "country_code"].isna().sum())}
        for box in sorted(set(boxes))}
    report["positive_agreement"] = positive_agreement(pd.read_parquet(positives_path), countries, cfg)
    out_dir.mkdir(parents=True, exist_ok=True)
    table.to_parquet(out_dir / CELL_REGIONS_NAME, index=False)
    (out_dir / CELL_REGIONS_REPORT_NAME).write_text(json.dumps(report, indent=2, allow_nan=False) + "\n",
                                                    encoding="utf-8")
    return report
