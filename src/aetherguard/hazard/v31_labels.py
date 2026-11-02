"""Step 1 of the v3.1 challenger study (spec section 15.2): the label audit of the positives, with no model involved.

    python -m aetherguard.hazard.v31_challenger labels

Every positive cell-day of the development period and of test_2018 (the catalog sources `hma` and `coolr_reports`) is joined
to the raw catalog records that make it a positive and to the static terrain of its cell. The catalogs carry a landslide
category, a trigger, a location accuracy, a setting and free text; only those fields and the cell terrain are read here.

A positive cell-day is PHYSICALLY IMPLAUSIBLE (the label a hillslope-susceptibility model should not learn from) when
  * its cell is low-terrain (mean slope below `low_terrain.slope_mean_below_deg` or mean elevation below
    `low_terrain.elev_mean_below_m`), AND
  * every catalog record behind it carries at least one of four flags:
      setting     the setting is an engineered or excavated slope (`engineered_settings`);
      category    the category is not a hillslope landslide (`non_hillslope_categories`);
      geocode     the record text says the coordinates are the closest match to a predicted location at least
                  `geocode_min_km` away (the position cannot be trusted at the cell scale);
      structure   the title, description, place or comments name a man-made structure failure (`structure_patterns`).
A cell-day with one plain record is plausible. The flags do not depend on any model output, so the rule is fixed before a
model is trained on it. The rule is a catalog-field screen, not a verdict on each event.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ..events import sources
from ..grid import CELL_DEG
from ..events.sources import read_dbf

CATALOG_COLUMNS = ["source", "event_id", "category", "trigger", "accuracy", "setting", "title", "description", "place",
                   "comments"]
CELL_KM = CELL_DEG * 111.195          # the 0.05 degree grid cell in km (mean meridian degree)
TEXT_COLUMNS = ("title", "description", "place", "comments")
FLAG_NAMES = ("setting", "category", "geocode", "structure")
CATALOG_SOURCES = ("hma", "coolr_reports")
TERRAIN_COLUMNS = ["stat_slope_mean", "stat_slope_p90", "stat_relief", "stat_elev_mean"]
POSITIVE_COLUMNS = ["cell_id", "date", "split", "region", "in_domain", *TERRAIN_COLUMNS]
FIELD_TABLES = ("category", "trigger", "accuracy", "setting", "source")
HMA_FIELDS = {"ev_id": "event_id", "ls_cat": "category", "ls_trig": "trigger", "loc_accu": "accuracy",
              "ls_setting": "setting", "ev_title": "title", "ev_desc": "description", "loc_desc": "place",
              "comments": "comments"}
COOLR_FIELDS = {"event_id": "event_id", "landslide_category": "category", "landslide_trigger": "trigger",
                "location_accuracy": "accuracy", "landslide_setting": "setting", "event_title": "title",
                "event_description": "description", "location_description": "place", "comments": "comments"}


@dataclass(frozen=True)
class LabelRule:
    """The pre-declared implausible-label rule and the terrain test (module doc)."""
    slope_mean_below: float
    elev_mean_below: float
    engineered_settings: frozenset
    non_hillslope_categories: frozenset
    geocode_pattern: re.Pattern
    geocode_min_km: float
    structure_pattern: re.Pattern

    @classmethod
    def from_config(cls, cfg: dict) -> "LabelRule":
        rule, terrain = cfg["label_rule"], cfg["low_terrain"]
        return cls(float(terrain["slope_mean_below_deg"]), float(terrain["elev_mean_below_m"]),
                   frozenset(rule["engineered_settings"]), frozenset(rule["non_hillslope_categories"]),
                   re.compile(rule["geocode_distance_pattern"], re.IGNORECASE), float(rule["geocode_min_km"]),
                   re.compile("|".join(f"(?:{p})" for p in rule["structure_patterns"]), re.IGNORECASE))


def low_terrain(cells: pd.DataFrame, rule: LabelRule) -> np.ndarray:
    """Per row: mean slope under the slope floor or mean elevation under the elevation floor (a missing value fails its test)."""
    with np.errstate(invalid="ignore"):
        return ((cells["stat_slope_mean"].to_numpy(dtype=np.float64) < rule.slope_mean_below)
                | (cells["stat_elev_mean"].to_numpy(dtype=np.float64) < rule.elev_mean_below))


# -------------------------------------------------------------------------------------------- the catalogs

def _clean(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame[CATALOG_COLUMNS].copy()
    out["event_id"] = pd.to_numeric(out["event_id"], errors="coerce").astype("Int64")
    for column in CATALOG_COLUMNS[2:]:
        out[column] = out[column].astype("object").where(out[column].notna(), "").astype(str).str.strip()
    return out


def read_catalog_records(raw_dir: Path) -> pd.DataFrame:
    """The raw records of the two day-exact catalogs in one schema (`CATALOG_COLUMNS`), file order, nothing dropped."""
    raw_dir = Path(raw_dir)
    hma, _ = read_dbf(raw_dir / "hma" / "HMA_LS_Cat_point_v02.0.dbf", columns=tuple(HMA_FIELDS))
    coolr = sources._read_csv(raw_dir / "coolr_reports_points.csv", tuple(COOLR_FIELDS))
    parts = [hma.rename(columns=HMA_FIELDS).assign(source="hma"), coolr.rename(columns=COOLR_FIELDS).assign(source="coolr_reports")]
    return pd.concat([_clean(p) for p in parts], ignore_index=True)


def positive_records(positives: pd.DataFrame, events: pd.DataFrame, catalog: pd.DataFrame) -> pd.DataFrame:
    """One row per catalog record behind each positive cell-day, with the cell-day's terrain.

    `positives`: POSITIVE_COLUMNS of the sample tables' positives; `events`: the label store (`cell_id`, `event_date`,
    `source`, `event_id`, `accuracy_km`, `is_positive`); `catalog`: `read_catalog_records`. A positive cell-day with no
    record, or a record whose catalog row is missing, is an error (a silently shorter table would hide it)."""
    wanted = events[events["is_positive"].astype(bool) & events["source"].isin(CATALOG_SOURCES)]
    wanted = wanted[["cell_id", "event_date", "source", "event_id", "accuracy_km"]]
    joined = positives.merge(wanted, left_on=["cell_id", "date"], right_on=["cell_id", "event_date"], how="left")
    orphan = joined["source"].isna()
    if orphan.any():
        first = joined[orphan].iloc[0]
        raise ValueError(f"{int(orphan.sum())} positive cell-day(s) have no catalog record in the label store "
                         f"(first: cell {first['cell_id']} on {first['date']:%Y-%m-%d})")
    keyed = catalog.drop_duplicates(["source", "event_id"])
    if len(keyed) != len(catalog):
        raise ValueError("the catalog has duplicate (source, event_id) keys")
    out = joined.drop(columns="event_date").merge(keyed, on=["source", "event_id"], how="left", validate="many_to_one")
    missing = out["category"].isna()
    if missing.any():
        first = out[missing].iloc[0]
        raise ValueError(f"{int(missing.sum())} positive record(s) are not in the catalog "
                         f"(first: {first['source']} event_id {first['event_id']})")
    return out.sort_values(["cell_id", "date", "source", "event_id"], kind="stable").reset_index(drop=True)


# ------------------------------------------------------------------------------------------------ flags

def _text(frame: pd.DataFrame) -> pd.Series:
    parts = [frame[c].astype("object").where(frame[c].notna(), "").astype(str) for c in TEXT_COLUMNS]
    return parts[0].str.cat(parts[1:], sep=" | ")


def _far_geocode(texts: pd.Series, rule: LabelRule) -> np.ndarray:
    def distance(text: str) -> float:
        match = rule.geocode_pattern.search(text)
        return float(match.group(1)) if match else 0.0
    return texts.map(distance).to_numpy(dtype=np.float64) >= rule.geocode_min_km


def record_flags(records: pd.DataFrame, rule: LabelRule) -> pd.DataFrame:
    """`records` plus the four boolean flags, `flag_any` and `reasons` (the fired flags, `;`-joined)."""
    texts = _text(records)
    flags = {"setting": records["setting"].isin(rule.engineered_settings).to_numpy(),
             "category": records["category"].isin(rule.non_hillslope_categories).to_numpy(),
             "geocode": _far_geocode(texts, rule),
             "structure": texts.map(lambda t: rule.structure_pattern.search(t) is not None).to_numpy(dtype=bool)}
    out = records.copy()
    for name in FLAG_NAMES:
        out[f"flag_{name}"] = flags[name]
    out["flag_any"] = np.any([flags[n] for n in FLAG_NAMES], axis=0)
    out["reasons"] = [";".join(n for n in FLAG_NAMES if flags[n][i]) for i in range(len(out))]
    return out


def _joined(values: pd.Series) -> str:
    return "|".join(dict.fromkeys(str(v) for v in values))


def cell_day_audit(records: pd.DataFrame, rule: LabelRule) -> pd.DataFrame:
    """One row per positive cell-day: its terrain, the fields of its records, `low_terrain`, `all_flagged`, `any_flagged`
    and `implausible` (low terrain and every record flagged)."""
    flagged = record_flags(records, rule)
    flagged["_text"] = _text(flagged)
    keys = ["cell_id", "date"]
    grouped = flagged.groupby(keys, sort=True, observed=True)
    table = grouped[["split", "region", "in_domain", *TERRAIN_COLUMNS]].first()
    table["n_records"] = grouped.size()
    for column, name in (("source", "sources"), ("category", "categories"), ("trigger", "triggers"),
                         ("accuracy", "accuracies"), ("setting", "settings")):
        table[name] = grouped[column].agg(_joined)
    table["text"] = grouped["_text"].agg(" || ".join)
    table["max_accuracy_km"] = grouped["accuracy_km"].max()
    table["all_flagged"] = grouped["flag_any"].all()
    table["any_flagged"] = grouped["flag_any"].any()
    fired = pd.DataFrame({name: grouped[f"flag_{name}"].any() for name in FLAG_NAMES})
    table["reasons"] = [";".join(n for n in FLAG_NAMES if row[n]) for _, row in fired.iterrows()]
    table = table.reset_index()
    table["low_terrain"] = low_terrain(table, rule)
    table["implausible"] = table["low_terrain"] & table["all_flagged"]
    return table


# ---------------------------------------------------------------------------------------------- summaries

def _counts(values: pd.Series) -> dict:
    return {str(k): int(v) for k, v in values.value_counts().sort_index().items()}


def summarise(records: pd.DataFrame, table: pd.DataFrame, rule: LabelRule) -> dict:
    """Counts of the audit: the cell-days, the low-terrain ones, the records of low-terrain and other cells by catalog field
    and by flag, and the implausible cell-days (all `int`, from the audit tables only)."""
    flagged = record_flags(records, rule)
    low = pd.Series(low_terrain(flagged, rule), index=flagged.index)
    fields = {}
    for name in FIELD_TABLES:
        fields[name] = {"low_terrain": _counts(flagged.loc[low, name]), "other": _counts(flagged.loc[~low, name])}
    accuracy_km = flagged["accuracy_km"]
    return {
        "positive_cell_days": int(len(table)), "records": int(len(flagged)),
        "low_terrain": int(table["low_terrain"].sum()), "implausible": int(table["implausible"].sum()),
        "flagged_any_record": int(table["any_flagged"].sum()), "flagged_all_records": int(table["all_flagged"].sum()),
        "flagged_all_records_not_low_terrain": int((table["all_flagged"] & ~table["low_terrain"]).sum()),
        "by_split": _counts(table["split"]), "implausible_by_split": _counts(table.loc[table["implausible"], "split"]),
        "implausible_by_region": _counts(table.loc[table["implausible"], "region"]),
        "low_terrain_by_region": _counts(table.loc[table["low_terrain"], "region"]),
        "records_by_field": fields,
        "records_flagged_by_flag": {
            "low_terrain": {n: int(flagged.loc[low, f"flag_{n}"].sum()) for n in FLAG_NAMES},
            "other": {n: int(flagged.loc[~low, f"flag_{n}"].sum()) for n in FLAG_NAMES}},
        "records_accuracy_km": {"low_terrain": _counts(accuracy_km[low]), "other": _counts(accuracy_km[~low])},
        "records_coarser_than_cell": int((accuracy_km > CELL_KM).sum()), "cell_km": CELL_KM,
        "implausible_by_reasons": _counts(table.loc[table["implausible"], "reasons"]),
        "not_in_domain": int((~table["in_domain"].astype(bool)).sum()),
        "scopes": _scopes(table),
        "low_terrain_top_cells": _top_cells(table[table["low_terrain"]]),
    }


def _scopes(table: pd.DataFrame) -> dict:
    """Counts for the populations the study uses: in-domain development positives (what the models train and are
    cross-validated on), in-domain test_2018 positives, and the positives below the slope floor (never scored or fitted)."""
    in_domain = table["in_domain"].astype(bool)
    development = table["split"].isin(["train", "validation"])
    parts = {"development_in_domain": in_domain & development, "test_2018_in_domain": in_domain & ~development,
             "out_of_domain": ~in_domain}
    return {name: {"positives": int(mask.sum()), "low_terrain": int((mask & table["low_terrain"]).sum()),
                   "implausible": int((mask & table["implausible"]).sum()),
                   "low_terrain_by_region": _counts(table.loc[mask & table["low_terrain"], "region"]),
                   "positives_by_region": _counts(table.loc[mask, "region"])} for name, mask in parts.items()}


def _top_cells(low: pd.DataFrame, n: int = 8) -> dict:
    """How concentrated the low-terrain positives are: distinct cells and the cells with the most cell-days."""
    counts = low["cell_id"].value_counts()
    return {"distinct_cells": int(len(counts)), "cell_days": int(len(low)),
            "top": [{"cell_id": int(c), "cell_days": int(k)} for c, k in counts.head(n).items()]}


def examples(table: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    """`n` low-terrain cell-days drawn with `seed` (all of them when fewer), in cell order, with their record fields and text."""
    pool = table[table["low_terrain"]].reset_index(drop=True)
    take = np.sort(np.random.default_rng(seed).choice(len(pool), size=min(n, len(pool)), replace=False))
    return pool.iloc[take].reset_index(drop=True)


# --------------------------------------------------------------------------------------------- the audit

def audit(positives: pd.DataFrame, events: pd.DataFrame, catalog: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, dict]:
    """(cell-day table, summary with the example rows) of the positives for the configuration's rule."""
    rule = LabelRule.from_config(cfg)
    records = positive_records(positives, events, catalog)
    table = cell_day_audit(records, rule)
    summary = summarise(records, table, rule)
    shown = examples(table, int(cfg["label_rule"]["example_rows"]), int(cfg["label_rule"]["example_seed"]))
    summary["examples"] = [{**{k: row[k] for k in ("cell_id", "split", "region", "sources", "categories", "triggers",
                                                   "accuracies", "settings", "reasons", "implausible", "n_records")},
                            "date": f"{row['date']:%Y-%m-%d}",
                            "slope_mean": float(row["stat_slope_mean"]), "elev_mean": float(row["stat_elev_mean"]),
                            "text": row["text"][:400]} for _, row in shown.iterrows()]
    return table, summary


def load_positives(features_dir: Path | None = None) -> pd.DataFrame:
    """The positive cell-days (in and out of the slope domain) of the train, validation and test_2018 sample tables."""
    from . import data as hd
    frames = [hd.load_features(hd.SAMPLE_NAMES[s], features_dir) for s in (*hd.DEVELOPMENT_SPLITS, hd.TEST)]
    samples = pd.concat(frames, ignore_index=True)
    return samples.loc[samples["kind"] == "positive", POSITIVE_COLUMNS].reset_index(drop=True)


def implausible_keys(table: pd.DataFrame) -> pd.DataFrame:
    """(cell_id, date) of the implausible cell-days."""
    return table.loc[table["implausible"], ["cell_id", "date"]].reset_index(drop=True)
