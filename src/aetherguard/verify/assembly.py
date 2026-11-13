"""Held-out assembly v2 and the added development labels (spec 2026-11-13 W1b): the W1 assembly plus the open inventories,
deduplicated across sources, counted as records, independent slides and storm clusters, and frozen.

    python -m aetherguard.verify assembly qa         # rule QA records for every admitted row of the open sources
    python -m aetherguard.verify assembly freeze     # data/processed/heldout_v2/ + labels_dev_v2/ (refuses to overwrite)
    python -m aetherguard.verify assembly report     # reports/phase8_ground_truth_expansion.{json,md} from the frozen files

No model is scored here. The held-out look on assembly v2 is `python -m aetherguard.verify heldout --assembly ...`, which
belongs to the lead (protocol v3: one look per adopted change, criterion declared first).

Inputs. The W1 assembly is rebuilt exactly as `heldout.load_event_table` builds it (2018 catalog, reported events, in-domain
`test_sparse` positives of 2019-2025); its rows keep the source names `catalog_2018`, `reported` and `catalog_sparse`. Each
open source contributes the admitted rows of its own inventory (`<source>/qa/inventory_admitted.csv`, built by
`verify.inventory` at 5 km). A new row is kept only in a scored cell (`live.backtest.universe_cell_ids`; else
`outside_scored_cells`).

Duplicates across sources follow the inventory rule (`inventory.SAME_PLACE_KM`, one day, or the same cell and day), on cell
centres, with the priority of `PRIORITY`: a lower-priority record within the rule of a kept one is dropped and the kept one
takes the earliest date of its group. Window records (none in v2) never merge with day records.

Counts (spec section 5): records; independent slides (`heldout.event_clusters`, 10 km and one day, single linkage); storm
clusters (`storm_clusters`: slides in one `tile_deg` tile whose dates fall in a fixed 5-day episode opened by the tile's first
unassigned slide). The gate is read on the storm clusters of the day-precise held-out records on panel days (June-December
2018-2025), four ways (`GATE_VIEWS`), the first deciding.
"""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .. import grid
from ..config import data_root
from ..hazard.jsonio import dump_json
from . import inventory as inv
from .geocode import _haversine_km

VERSION = 2
HELDOUT_DIR = "heldout_v2"
DEV_DIR = "labels_dev_v2"
REPORT_STEM = "phase8_ground_truth_expansion"
SOURCES = ("gfld", "bipad_nepal")
V1_SOURCES = ("catalog_2018", "reported", "catalog_sparse")
PRIORITY = (*V1_SOURCES, "gfld", "bipad_nepal")
HOW_FOUND = {"catalog_2018": "reported", "reported": "reported", "catalog_sparse": "reported", "gfld": "reported",
             "bipad_nepal": "reported"}
HELD_OUT_YEARS = tuple(range(2018, 2026))
DEV_YEARS = tuple(range(2007, 2018))
PANEL_MONTHS = tuple(range(6, 13))
EPISODE_DAYS = 5
TILE_DEG = 1.0
SENSITIVITY_TILE_DEG = 2.0
GATE = 150
GATE_VIEWS = {
    "all_sources": "every source (deciding)",
    "without_bipad": "without BIPAD Nepal (its register states no licence: a user decision)",
    "india_only": "records in Indian cells only",
    "nepal_bhutan_only": "records in Nepal and Bhutan cells only",
}
EVENT_COLUMNS = ["cell_id", "date", "source", "stratum", "how_found", "country", "region", "record_id", "latitude",
                 "longitude", "accuracy_km", "year"]


# ------------------------------------------------------------------------------------------------------------ QA

QA_COLUMNS = ("date", "place", "district", "state", "source_url", "date_ok", "place_ok", "is_landslide", "geocode_ok",
              "checked_by", "note")
SPOT_NAME = "spot_check.csv"


def _rule_entry(source: str, row: dict) -> dict:
    """The rule checks every admitted row of an open source passes by construction, stated per check."""
    if source == "bipad_nepal":
        note = ("rule: register field incidentOn (day); hazard Landslide (17); verified and approved; point inside its ward's "
                f"box, bound {row['accuracy_km']} km; not checked against a second report")
    else:
        note = ("rule: GFLD Day/Month/Year fields; GFLD trigger rain or unknown; polygon radius "
                f"{row['accuracy_km']} km; the cited report was not reopened")
    return {"date": row["date"], "place": row["place"], "district": row.get("district", ""), "state": row["state"],
            "source_url": row["source_url"], "date_ok": "yes", "place_ok": "yes", "is_landslide": "yes",
            "geocode_ok": "yes", "checked_by": "rule", "note": note}


def write_rule_qa(source_dir: Path, source: str) -> dict:
    """`qa/qa_results.csv` of an open source: one record per admitted row. A manual result in `qa/spot_check.csv` (same
    columns, `checked_by` "manual") replaces the rule record of its row; a manual row naming no admitted row is an error."""
    source_dir = Path(source_dir)
    admitted = pd.read_csv(source_dir / inv.QA_DIR / inv.COMBINED_NAME, dtype=str, keep_default_na=False)
    entries = {(r["date"], r["place"], r["state"]): _rule_entry(source, r) for r in admitted.to_dict("records")}
    manual = 0
    spot = source_dir / inv.QA_DIR / SPOT_NAME
    if spot.is_file():
        for row in pd.read_csv(spot, dtype=str, keep_default_na=False).to_dict("records"):
            key = (row["date"], row["place"], row["state"])
            if key not in entries:
                raise ValueError(f"{spot.name}: {key} is not an admitted row")
            entries[key] = {c: row.get(c, "") for c in QA_COLUMNS}
            manual += 1
    with (source_dir / inv.QA_DIR / inv.QA_RESULTS_NAME).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=QA_COLUMNS)
        writer.writeheader()
        writer.writerows(entries.values())
    return {"rows": len(entries), "manual": manual}


# ------------------------------------------------------------------------------------------------------- records

def source_records(source: str, admitted: pd.DataFrame) -> pd.DataFrame:
    """The admitted rows of an open source's inventory as assembly records (EVENT_COLUMNS, country and region still empty)."""
    frame = pd.DataFrame({
        "cell_id": grid.latlon_to_cell(admitted["latitude"].to_numpy(float), admitted["longitude"].to_numpy(float)),
        "date": pd.to_datetime(admitted["date"]).astype("datetime64[ns]"),
        "source": source,
        "stratum": np.where(admitted["date_basis"].fillna("stated") == "window", "window", "day"),
        "how_found": admitted["how_found"].fillna("").replace("", HOW_FOUND.get(source, "reported")),
        "country": "", "region": "",
        "record_id": admitted["record_id"].fillna("").astype(str),
        "latitude": admitted["latitude"].astype(float), "longitude": admitted["longitude"].astype(float),
        "accuracy_km": admitted["accuracy_km"].astype(float),
    })
    frame["cell_id"] = frame["cell_id"].astype(np.int64)
    frame["year"] = frame["date"].dt.year
    return frame[EVENT_COLUMNS]


def v1_records(events: pd.DataFrame) -> pd.DataFrame:
    """The W1 assembly (`heldout.load_event_table`: cell_id, date, source) as records located at their cell centres."""
    lat, lon = grid.cell_center(events["cell_id"].to_numpy(np.int64))
    frame = pd.DataFrame({
        "cell_id": events["cell_id"].to_numpy(np.int64), "date": pd.to_datetime(events["date"]).astype("datetime64[ns]"),
        "source": events["source"].to_numpy(), "stratum": "day",
        "how_found": events["source"].map(HOW_FOUND).to_numpy(), "country": "", "region": "",
        "record_id": [f"{s}:{c}:{d:%Y-%m-%d}" for s, c, d in zip(events["source"], events["cell_id"], pd.to_datetime(events["date"]))],
        "latitude": lat, "longitude": lon, "accuracy_km": np.nan,
    })
    frame["year"] = frame["date"].dt.year
    return frame[EVENT_COLUMNS]


def label_cells(records: pd.DataFrame, regions: pd.DataFrame) -> pd.DataFrame:
    """Country and region of each record's cell from the cell table (`cell_regions.parquet`); "" for a cell it lacks."""
    table = regions.drop_duplicates("cell_id").set_index("cell_id")
    out = records.copy()
    out["country"] = table["country_code"].reindex(out["cell_id"]).fillna("").to_numpy()
    out["region"] = table["region"].reindex(out["cell_id"]).fillna("").to_numpy()
    return out


def dedupe(records: pd.DataFrame, priority=PRIORITY) -> tuple[pd.DataFrame, list[dict]]:
    """Cross-source duplicates by the inventory rule, on the records' points (cell centres for the W1 records).

    Records are taken by source priority, then date, then input order; one joins the first kept record it duplicates (same
    stratum, within a day, and the same cell or within `inventory.SAME_PLACE_KM`). A kept record takes the earliest date of
    its group. Returns the kept records and the dropped ones (with the record they duplicate)."""
    rank = {s: i for i, s in enumerate(priority)}
    order = records.assign(_rank=records["source"].map(rank).fillna(len(rank)), _pos=np.arange(len(records)))
    order = order.sort_values(["_rank", "date", "_pos"], kind="stable")
    kept_idx: list[int] = []
    by_day: dict[int, list[int]] = {}
    earliest: dict[int, pd.Timestamp] = {}
    dropped = []
    rows = order.to_dict("index")
    for idx, row in rows.items():
        day = row["date"].toordinal()
        match = None
        for offset in (0, -1, 1):
            for k in by_day.get(day + offset, []):
                other = rows[k]
                if other["stratum"] != row["stratum"]:
                    continue
                if other["cell_id"] == row["cell_id"] or float(_haversine_km(
                        row["latitude"], row["longitude"], other["latitude"], other["longitude"])) <= inv.SAME_PLACE_KM:
                    match = k
                    break
            if match is not None:
                break
        if match is None:
            kept_idx.append(idx)
            by_day.setdefault(day, []).append(idx)
            earliest[idx] = row["date"]
        else:
            earliest[match] = min(earliest[match], row["date"])
            dropped.append({"source": row["source"], "record_id": row["record_id"], "date": row["date"].date().isoformat(),
                            "duplicate_of": rows[match]["record_id"], "duplicate_source": rows[match]["source"]})
    kept = records.loc[kept_idx].copy()
    kept["date"] = [earliest[i] for i in kept_idx]
    kept["year"] = kept["date"].dt.year
    return kept.sort_values(["date", "source", "cell_id"], kind="stable").reset_index(drop=True), dropped


def storm_clusters(slide_ids: np.ndarray, cell_ids: np.ndarray, dates, tile_deg: float = TILE_DEG,
                   episode_days: int = EPISODE_DAYS) -> np.ndarray:
    """A storm-cluster label per record (spec section 5). A slide is represented by its earliest record (ties: the first
    listed); its tile is the floor of that record's cell-centre latitude and longitude over `tile_deg`. Within a tile, slides
    in date order open an episode that holds every slide dated up to `episode_days` - 1 days after the opening day; the next
    slide after it opens the next episode. Every record of a slide takes its slide's cluster."""
    slide_ids = np.asarray(slide_ids)
    frame = pd.DataFrame({"slide": slide_ids, "cell": np.asarray(cell_ids, dtype=np.int64),
                          "ordinal": [pd.Timestamp(d).toordinal() for d in pd.to_datetime(dates)]})
    if frame.empty:
        return np.zeros(0, dtype=np.int64)
    first = frame.sort_values(["slide", "ordinal"], kind="stable").drop_duplicates("slide")
    lat, lon = grid.cell_center(first["cell"].to_numpy())
    first = first.assign(tile_lat=np.floor(np.asarray(lat) / tile_deg).astype(int),
                         tile_lon=np.floor(np.asarray(lon) / tile_deg).astype(int))
    label_of, next_label = {}, 0
    for _, group in first.sort_values(["tile_lat", "tile_lon", "ordinal", "slide"], kind="stable").groupby(
            ["tile_lat", "tile_lon"], sort=False):
        opening = None
        for slide, ordinal in zip(group["slide"], group["ordinal"]):
            if opening is None or ordinal - opening >= episode_days:
                opening, next_label = ordinal, next_label + 1
            label_of[slide] = next_label - 1
    return frame["slide"].map(label_of).to_numpy(dtype=np.int64)


def on_panel_days(dates) -> np.ndarray:
    """Whether each date is a held-out panel day (June-December of 2018-2025)."""
    stamps = pd.to_datetime(dates)
    return (stamps.dt.year.isin(HELD_OUT_YEARS) & stamps.dt.month.isin(PANEL_MONTHS)).to_numpy()


def counts(events: pd.DataFrame) -> dict:
    """Records, slides and storm clusters (1- and 2-degree tiles) of an assembly frame that carries the cluster columns."""
    return {"records": int(len(events)), "slides": int(events["slide_id"].nunique()),
            "storm_clusters": int(events["storm_id"].nunique()),
            "storm_clusters_2deg": int(events["storm_id_2deg"].nunique())}


def gate_views(gate_set: pd.DataFrame, gate: int = GATE) -> dict:
    """The gate verdict per view of `GATE_VIEWS` on the storm clusters of the gate set (the first view decides). Slides and
    storm clusters are recomputed within a view, so a view never borrows another country's records."""
    views = {
        "all_sources": gate_set,
        "without_bipad": gate_set[gate_set["source"] != "bipad_nepal"],
        "india_only": gate_set[gate_set["country"] == "IN"],
        "nepal_bhutan_only": gate_set[gate_set["country"].isin(["NP", "BT"])],
    }
    out = {}
    for name, frame in views.items():
        frame = with_clusters(frame.reset_index(drop=True))
        c = counts(frame)
        met = c["storm_clusters"] >= gate
        out[name] = {**c, "note": GATE_VIEWS[name], "met": met,
                     "verdict": (f"MET, {c['storm_clusters'] - gate} over" if met
                                 else f"NOT MET, {gate - c['storm_clusters']} short")}
    return out


def with_clusters(events: pd.DataFrame) -> pd.DataFrame:
    """`events` with `slide_id` (heldout.event_clusters) and `storm_id` / `storm_id_2deg` (`storm_clusters`)."""
    from .heldout import event_clusters                 # late: heldout pulls in the whole scoring stack
    out = events.copy()
    if out.empty:
        return out.assign(slide_id=np.zeros(0, np.int64), storm_id=np.zeros(0, np.int64), storm_id_2deg=np.zeros(0, np.int64))
    out["slide_id"] = event_clusters(out[["cell_id", "date"]])
    out["storm_id"] = storm_clusters(out["slide_id"], out["cell_id"], out["date"], TILE_DEG)
    out["storm_id_2deg"] = storm_clusters(out["slide_id"], out["cell_id"], out["date"], SENSITIVITY_TILE_DEG)
    return out


# ------------------------------------------------------------------------------------------------------- freezing

def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _rel(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(data_root().resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


def assemble(v1_events: pd.DataFrame, sources: dict[str, pd.DataFrame], universe: np.ndarray,
             regions: pd.DataFrame) -> dict:
    """Every frame of assembly v2 from its inputs (pure; `freeze` writes them). `sources` maps a source name to its
    inventory's admitted rows."""
    universe = set(np.asarray(universe, dtype=np.int64).tolist())
    parts, rejected = [v1_records(v1_events)], []
    for name, admitted in sources.items():
        records = source_records(name, admitted)
        inside = records["cell_id"].isin(universe).to_numpy()
        for row in records[~inside].to_dict("records"):
            rejected.append({"source": name, "record_id": row["record_id"], "date": row["date"].date().isoformat(),
                             "reason": "outside_scored_cells"})
        parts.append(records[inside])
    records = label_cells(pd.concat(parts, ignore_index=True), regions)
    kept, dropped = dedupe(records)
    held = kept[kept["year"].isin(HELD_OUT_YEARS)].reset_index(drop=True)
    day = with_clusters(held[held["stratum"] == "day"].reset_index(drop=True))
    day["on_panel_day"] = on_panel_days(day["date"])
    window = held[held["stratum"] == "window"].reset_index(drop=True)
    dev = kept[kept["year"].isin(DEV_YEARS) & kept["source"].isin(SOURCES)].reset_index(drop=True)
    return {"records": records, "kept": kept, "dropped": dropped, "rejected": rejected, "heldout_day": day,
            "heldout_window": window, "dev_added": dev}


def dev_against_existing(dev: pd.DataFrame, positives: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """The added development records that do not repeat an existing development positive (train or validation split of
    `positive_cell_days`) by the inventory rule on cell centres."""
    existing = positives[positives["split"].isin(["train", "validation"])]
    base = pd.DataFrame({"cell_id": existing["cell_id"].to_numpy(np.int64),
                         "date": pd.to_datetime(existing["event_date"]).astype("datetime64[ns]"),
                         "source": "existing_dev", "stratum": "day", "record_id": "existing", "how_found": "reported"})
    base["latitude"], base["longitude"] = grid.cell_center(base["cell_id"].to_numpy())
    both = pd.concat([base, dev], ignore_index=True)
    kept, dropped = dedupe(both, priority=("existing_dev", *SOURCES))
    return kept[kept["source"] != "existing_dev"].reset_index(drop=True), dropped


def _write_frozen(directory: Path, frames: dict[str, pd.DataFrame], manifest: dict) -> None:
    directory = Path(directory)
    if (directory / "FROZEN.json").exists():
        raise FileExistsError(f"{directory} is frozen; a new assembly needs a new version directory")
    directory.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, frame in frames.items():
        path = directory / f"{name}.parquet"
        frame.to_parquet(path, index=False)
        files[path.name] = {"sha256": _sha256(path), "rows": int(len(frame))}
    dump_json(directory / "MANIFEST.json", {**manifest, "files": files})
    dump_json(directory / "FROZEN.json", {"frozen": True, "version": VERSION,
                                          "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                          "manifest_sha256": _sha256(directory / "MANIFEST.json"),
                                          "files": {k: v["sha256"] for k, v in files.items()}})


def freeze(say=print) -> dict:
    """Assemble v2 from the data tree and write `data/processed/heldout_v2/` and `data/processed/labels_dev_v2/`."""
    from ..live import backtest as bt
    from ..live import run as live_run
    from .heldout import load_event_table
    cfg = live_run.load_run_config()
    v1 = load_event_table(cfg)
    inputs, sources = {}, {}
    for name in SOURCES:
        path = data_root() / "raw" / "manual" / name / inv.QA_DIR / inv.COMBINED_NAME
        sources[name] = pd.read_csv(path, dtype={"record_id": str, "window_end": str, "date_basis": str, "how_found": str},
                                    keep_default_na=False, na_values={"latitude": [""], "longitude": [""]})
        inputs[name] = {"path": _rel(path), "sha256": _sha256(path), "rows": int(len(sources[name]))}
    regions = pd.read_parquet(bt.features_dir() / "cell_regions.parquet")
    built = assemble(v1, sources, bt.universe_cell_ids(), regions)
    positives_path = data_root() / "processed" / "splits" / "positive_cell_days.parquet"
    positives = pd.read_parquet(positives_path, columns=["cell_id", "event_date", "split"])
    dev, dev_dropped = dev_against_existing(built["dev_added"], positives)
    rules = {"spec": "docs/superpowers/specs/2026-11-13-aetherguard-w1b-ground-truth.md", "max_accuracy_km_new": 5.0,
             "same_place_km": inv.SAME_PLACE_KM, "max_window_days": inv.MAX_WINDOW_DAYS, "priority": list(PRIORITY),
             "slide_rule": "10 km and 1 day, single linkage (heldout.event_clusters)",
             "storm_rule": f"{TILE_DEG:g}-degree tile, fixed {EPISODE_DAYS}-day episodes (sensitivity {SENSITIVITY_TILE_DEG:g})",
             "gate": GATE, "gate_basis": "storm clusters of the day-precise held-out records on panel days, all sources"}
    common = {"version": VERSION, "rules": rules,
              "inputs": {**inputs, "v1": "heldout.load_event_table (test_2018 positives, reported_events, test_sparse)",
                         "positive_cell_days": {"path": _rel(positives_path), "sha256": _sha256(positives_path)}}}
    held_dir, dev_dir = data_root() / "processed" / HELDOUT_DIR, data_root() / "processed" / DEV_DIR
    _write_frozen(held_dir, {"events": built["heldout_day"], "window_events": built["heldout_window"]},
                  {**common, "dropped_duplicates": built["dropped"], "rejected": built["rejected"]})
    _write_frozen(dev_dir, {"added_positives": dev}, {**common, "dropped_as_existing_or_duplicate": dev_dropped})
    say(f"froze {held_dir} ({len(built['heldout_day'])} day records, {len(built['heldout_window'])} window) and "
        f"{dev_dir} ({len(dev)} added development records)")
    return {"heldout": held_dir, "dev": dev_dir}


# --------------------------------------------------------------------------------------------------------- report

def _check_frozen(directory: Path) -> dict:
    frozen = json.loads((Path(directory) / "FROZEN.json").read_text(encoding="utf-8"))
    for name, digest in frozen["files"].items():
        if _sha256(Path(directory) / name) != digest:
            raise ValueError(f"{directory / name} does not match its FROZEN.json hash")
    return frozen


def _table(frame: pd.DataFrame, by: list[str]) -> list[dict]:
    if frame.empty:
        return []
    out = []
    for key, group in frame.groupby(by, sort=True):
        key = key if isinstance(key, tuple) else (key,)
        out.append({**dict(zip(by, [str(k) for k in key])), "records": int(len(group)),
                    "slides": int(group["slide_id"].nunique()), "storm_clusters": int(group["storm_id"].nunique())})
    return out


def summarise(heldout: pd.DataFrame, window: pd.DataFrame, dev: pd.DataFrame, manifests: dict) -> dict:
    gate_set = heldout[heldout["on_panel_day"]].reset_index(drop=True)
    v1 = with_clusters(gate_set[gate_set["source"].isin(V1_SOURCES)].reset_index(drop=True))
    return {
        "version": VERSION,
        "rules": manifests["heldout"]["rules"],
        "heldout": {
            "all_dates": counts(heldout), "panel_days": counts(gate_set),
            "outside_panel_days": int((~heldout["on_panel_day"]).sum()),
            "v1_part_on_panel_days": counts(v1),
            "by_source": _table(gate_set, ["source"]), "by_year": _table(gate_set, ["year"]),
            "by_region": _table(gate_set, ["region"]), "by_country": _table(gate_set, ["country"]),
            "by_how_found": _table(gate_set, ["how_found"]),
            "by_date_precision": [{"date_precision": "day", **counts(gate_set)},
                                  {"date_precision": "window (<= 7 days)", "records": int(len(window))}],
            "accuracy_km_new_sources": {} if gate_set[gate_set["source"].isin(SOURCES)].empty else {
                f"p{q}": float(np.nanpercentile(gate_set.loc[gate_set["source"].isin(SOURCES), "accuracy_km"], q))
                for q in (25, 50, 75, 100)},
            "dropped_duplicates": len(manifests["heldout"]["dropped_duplicates"]),
            "dropped_by_pair": _pairs(manifests["heldout"]["dropped_duplicates"]),
            "rejected_outside_scored_cells": len(manifests["heldout"]["rejected"]),
        },
        "gate": gate_views(gate_set),
        "dev_added": {"records": int(len(dev)),
                      "by_source": {str(k): int(v) for k, v in dev.groupby("source").size().items()} if len(dev) else {},
                      "by_year": {str(k): int(v) for k, v in dev.groupby("year").size().items()} if len(dev) else {},
                      "by_region": {str(k): int(v) for k, v in dev.groupby("region").size().items()} if len(dev) else {},
                      "by_country": {str(k): int(v) for k, v in dev.groupby("country").size().items()} if len(dev) else {},
                      "dropped_as_existing_or_duplicate": len(manifests["dev"]["dropped_as_existing_or_duplicate"])},
        "frozen": {name: {"dir": _rel(path), "manifest_sha256": frozen["manifest_sha256"], "files": frozen["files"]}
                   for name, (path, frozen) in manifests["frozen"].items()},
    }


def _pairs(dropped: list[dict]) -> dict:
    out: dict[str, int] = {}
    for d in dropped:
        key = f"{d['source']} -> {d['duplicate_source']}"
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))


def heldout_command() -> str:
    return (f"python -m aetherguard.verify heldout --assembly data/processed/{HELDOUT_DIR} --stem phase8_heldout_v2")


def markdown(result: dict) -> str:
    h, gate = result["heldout"], result["gate"]
    deciding = gate["all_sources"]
    row = lambda e, key: f"| {e[key]} | {e['records']:,} | {e['slides']:,} | {e['storm_clusters']:,} |"
    table = lambda entries, key, title: [f"| {title} | records | slides | storm clusters |", "|---|---|---|---|",
                                         *[row(e, key) for e in entries], ""]
    gate_rows = [f"| {name} | {v['note']} | {v['records']:,} | {v['slides']:,} | {v['storm_clusters']:,} | "
                 f"{v['storm_clusters_2deg']:,} | {v['verdict']} |" for name, v in gate.items()]
    acc = h["accuracy_km_new_sources"]
    lines = [
        "# Ground-truth expansion W1b: held-out assembly v2 (phase 8)",
        "",
        f"**Gate (storm clusters, all sources, deciding): {deciding['storm_clusters']:,} storm clusters of "
        f"{deciding['slides']:,} independent slides ({deciding['records']:,} records) against the {GATE}-event gate: "
        f"{deciding['verdict']}.** No model was scored on any v2 event; this report only counts.",
        "",
        "Rules (pre-declared in `docs/superpowers/specs/2026-11-13-aetherguard-w1b-ground-truth.md`): new records are dated to "
        "the day (no window record qualified), located to 5 km or better, in a scored cell, rain-triggered or cause unknown, "
        "deduplicated within and across sources (one day and 5 km, or the same cell and day). Independent slides merge "
        "records within 10 km and a day; storm clusters merge slides of one 1-degree tile within a fixed 5-day episode.",
        "",
        "## Reading this report",
        "",
        "- Every record in v2 was found by people reporting a slide (police, agencies, news, NASA catalogs built from news). "
        "None was mapped from imagery, so the set follows roads and settlements; an alert in an empty valley that verifies "
        "nothing is not shown to be false.",
        "- BIPAD Nepal dominates the new records. Its location is the reporting ward (the incident point is a per-ward point), "
        "bounded by the ward's box; the 5 km bound keeps the small wards of hills and towns, which strengthens the "
        "settlement bias. Its register states no licence; the view without BIPAD is printed for that decision.",
        "- A pass carried by Nepal records says nothing about skill in India. The India-only view is printed beside it, and "
        "any G1-G4 claim must be broken down by country.",
        "- Ground truth stays very incomplete: precision on these records is relative (between models at matched burden), "
        "never an absolute false-alarm rate. Tolerant matching has a high chance floor at Watch+ and Warning+.",
        "",
        "## Gate views (held-out records on panel days, June-December 2018-2025)",
        "",
        "| view | what | records | slides | storm clusters | storm clusters (2-degree tiles) | verdict |",
        "|---|---|---|---|---|---|---|",
        *gate_rows,
        "",
        f"The W1 part alone (2018 catalog, W1 reported, test_sparse) on panel days: {h['v1_part_on_panel_days']['records']} "
        f"records, {h['v1_part_on_panel_days']['slides']} slides, {h['v1_part_on_panel_days']['storm_clusters']} storm clusters. "
        f"{h['outside_panel_days']} held-out records fall outside the panel days (January-May) and are counted, not scored.",
        "",
        "## Held-out records on panel days",
        "",
        *table(h["by_source"], "source", "source"),
        *table(h["by_year"], "year", "year"),
        *table(h["by_region"], "region", "region"),
        *table(h["by_country"], "country", "country"),
        *table(h["by_how_found"], "how_found", "how found"),
        "| date precision | records |",
        "|---|---|",
        *[f"| {e['date_precision']} | {e['records']:,} |" for e in h["by_date_precision"]],
        "",
        ("Location bound of the new records (km): " + ", ".join(f"{k} {v:.2f}" for k, v in acc.items()) + ".") if acc else "",
        "",
        f"Cross-source duplicates dropped: {h['dropped_duplicates']} ("
        + (", ".join(f"{k} {v}" for k, v in h["dropped_by_pair"].items()) or "none") + "). "
        f"New records outside the scored cells: {h['rejected_outside_scored_cells']}.",
        "",
        "## Development labels added (2007-2017)",
        "",
        f"{result['dev_added']['records']:,} records not repeating an existing development positive "
        f"({result['dev_added']['dropped_as_existing_or_duplicate']:,} dropped as repeats or duplicates). By source: "
        + ", ".join(f"{k} {v:,}" for k, v in result["dev_added"]["by_source"].items()) + "; by country: "
        + ", ".join(f"{k} {v:,}" for k, v in result["dev_added"]["by_country"].items()) + "; by year: "
        + ", ".join(f"{k} {v}" for k, v in result["dev_added"]["by_year"].items()) + ". Nothing was retrained; using them is "
        "a separate, declared step.",
        "",
        "## Frozen files",
        "",
        *[f"- `{v['dir']}`: manifest sha256 `{v['manifest_sha256']}`; "
          + ", ".join(f"`{k}` `{d[:16]}`" for k, d in v["files"].items()) for v in result["frozen"].values()],
        "",
        "## Next step (the lead's)",
        "",
        ("READY FOR HELD-OUT LOOK. " if deciding["met"] else "The gate is not met by the deciding count. ")
        + f"The W1 held-out report re-run on assembly v2 (writes `reports/phase8_heldout_v2.{{json,md}}`, never the phase 7 "
        f"report): `{heldout_command()}`. It is a held-out look and follows the one-look-per-adopted-change rule.",
        "",
    ]
    return "\n".join(lines)


def write_report(out: Path, say=print) -> dict:
    held_dir, dev_dir = data_root() / "processed" / HELDOUT_DIR, data_root() / "processed" / DEV_DIR
    frozen = {"heldout": (held_dir, _check_frozen(held_dir)), "dev": (dev_dir, _check_frozen(dev_dir))}
    manifests = {"heldout": json.loads((held_dir / "MANIFEST.json").read_text(encoding="utf-8")),
                 "dev": json.loads((dev_dir / "MANIFEST.json").read_text(encoding="utf-8")), "frozen": frozen}
    result = summarise(pd.read_parquet(held_dir / "events.parquet"), pd.read_parquet(held_dir / "window_events.parquet"),
                       pd.read_parquet(dev_dir / "added_positives.parquet"), manifests)
    result["heldout_command"] = heldout_command()
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    dump_json(out / f"{REPORT_STEM}.json", result)
    (out / f"{REPORT_STEM}.md").write_text(markdown(result), encoding="utf-8")
    say(f"wrote {out / REPORT_STEM}.{{json,md}}: gate {result['gate']['all_sources']['verdict']}")
    return result


def write_all_qa(say=print) -> None:
    for name in SOURCES:
        directory = data_root() / "raw" / "manual" / name
        done = write_rule_qa(directory, name)
        say(f"{name}: {done['rows']} QA records ({done['manual']} manual)")

