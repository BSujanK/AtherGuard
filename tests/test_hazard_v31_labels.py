"""v3.1 challenger study, Step 1: the label audit of the positives (catalog fields and cell terrain only, no model)."""
import numpy as np
import pandas as pd
import pytest

from aetherguard.config import PROJECT_ROOT, load_config_file
from aetherguard.hazard import v31_labels as vl

CFG = load_config_file(PROJECT_ROOT / "configs" / "hazard_v31_challenger.yaml")
RULE = vl.LabelRule.from_config(CFG)


def record(**kw) -> dict:
    base = {"source": "hma", "event_id": 1, "category": "landslide", "trigger": "rain", "accuracy": "1km",
            "setting": "unknown", "title": "Some village", "description": "Heavy rain triggered a landslide.",
            "place": "Some village", "comments": ""}
    return {**base, **kw}


def records(*rows) -> pd.DataFrame:
    return pd.DataFrame([record(**r) for r in rows])


# ------------------------------------------------------------------------------------------ the rule

def test_a_plain_natural_slope_record_is_not_flagged():
    flags = vl.record_flags(records({}), RULE)
    assert not flags["flag_any"].iloc[0]
    assert flags[["flag_setting", "flag_category", "flag_geocode", "flag_structure"]].to_numpy().sum() == 0


@pytest.mark.parametrize("setting", ["retaining_wall", "engineered_slope", "mine"])
def test_engineered_settings_are_flagged(setting):
    flags = vl.record_flags(records({"setting": setting}), RULE)
    assert flags["flag_setting"].iloc[0] and flags["flag_any"].iloc[0]


@pytest.mark.parametrize("setting", ["urban", "above_road", "natural_slope", "unknown"])
def test_urban_and_road_settings_are_not_flagged(setting):
    assert not vl.record_flags(records({"setting": setting}), RULE)["flag_any"].iloc[0]


@pytest.mark.parametrize("category", ["riverbank_collapse", "other", "unknown", "snow_avalanche"])
def test_non_hillslope_categories_are_flagged(category):
    flags = vl.record_flags(records({"category": category}), RULE)
    assert flags["flag_category"].iloc[0]


@pytest.mark.parametrize("category", ["landslide", "mudslide", "rock_fall", "debris_flow"])
def test_hillslope_categories_are_not_flagged(category):
    assert not vl.record_flags(records({"category": category}), RULE)["flag_any"].iloc[0]


def test_a_geocode_far_from_the_predicted_location_is_flagged_only_beyond_the_distance():
    far = vl.record_flags(records({"description": "closest to predicted location of Alibag (383.81 km)"}), RULE)
    near = vl.record_flags(records({"description": "closest to predicted location of Alibag (24.99 km)"}), RULE)
    edge = vl.record_flags(records({"description": "Closest to predicted location of Alibag (25.0 km)"}), RULE)
    assert far["flag_geocode"].iloc[0] and edge["flag_geocode"].iloc[0] and not near["flag_geocode"].iloc[0]


def test_structure_words_are_found_in_the_title_description_place_or_comments_case_blind():
    for column in ("title", "description", "place", "comments"):
        flags = vl.record_flags(records({column: "Wall of the Stone QUARRY collapsed"}), RULE)
        assert flags["flag_structure"].iloc[0], column
    # a building that fell as a consequence of a landslide is not a structure failure
    assert not vl.record_flags(records({"description": "A building collapsed after the landslide"}), RULE)["flag_any"].iloc[0]
    # word boundaries: "determine" does not contain the word mine
    assert not vl.record_flags(records({"description": "Officials will determine the cause"}), RULE)["flag_any"].iloc[0]


def test_missing_text_is_not_an_error():
    flags = vl.record_flags(records({"title": None, "description": np.nan, "place": None, "comments": None}), RULE)
    assert not flags["flag_any"].iloc[0]


def test_reasons_list_every_flag_that_fired():
    flags = vl.record_flags(records({"setting": "mine", "category": "other", "description": "stone quarry"}), RULE)
    assert flags["reasons"].iloc[0] == "setting;category;structure"
    assert vl.record_flags(records({}), RULE)["reasons"].iloc[0] == ""


# ------------------------------------------------------------------------------------------ terrain

def test_low_terrain_is_either_test_with_strict_inequalities():
    cells = pd.DataFrame({"stat_slope_mean": [4.99, 5.0, 10.0, 10.0, 10.0], "stat_elev_mean": [500.0, 500.0, 99.9, 100.0, np.nan]})
    assert vl.low_terrain(cells, RULE).tolist() == [True, False, True, False, False]
    assert vl.low_terrain(cells.iloc[:0], RULE).tolist() == []


# --------------------------------------------------------------------------------------------- joining

def positives(**cols) -> pd.DataFrame:
    base = {"cell_id": [10, 11], "date": pd.to_datetime(["2012-07-01", "2013-07-02"]), "split": ["train", "validation"],
            "region": ["western_ghats", "himalaya"], "in_domain": [True, True],
            "stat_slope_mean": [2.0, 20.0], "stat_slope_p90": [5.0, 30.0], "stat_relief": [50.0, 900.0],
            "stat_elev_mean": [30.0, 1500.0]}
    return pd.DataFrame({**base, **cols})


def events(rows) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["cell_id", "event_date", "source", "event_id", "accuracy_km", "is_positive"])


def test_every_positive_is_joined_to_its_catalog_records():
    ev = events([(10, "2012-07-01", "hma", 1, 1.0, True), (11, "2013-07-02", "coolr_reports", 2, 5.0, True),
                 (11, "2013-07-02", "coolr_events", 3, 1.0, True), (99, "2012-07-01", "hma", 4, 1.0, True),
                 (10, "2012-07-01", "hma", 5, 1.0, False)])
    ev["event_date"] = pd.to_datetime(ev["event_date"])
    catalog = pd.concat([records({"source": "hma", "event_id": 1}), records({"source": "coolr_reports", "event_id": 2})],
                        ignore_index=True)
    joined = vl.positive_records(positives(), ev, catalog)
    assert sorted(zip(joined["cell_id"], joined["source"], joined["event_id"])) == [(10, "hma", 1), (11, "coolr_reports", 2)]
    assert {"accuracy_km", "category", "setting", "stat_slope_mean"} <= set(joined.columns)


def test_a_positive_without_a_catalog_record_is_an_error():
    ev = events([(10, "2012-07-01", "hma", 1, 1.0, True)])
    ev["event_date"] = pd.to_datetime(ev["event_date"])
    with pytest.raises(ValueError, match="no catalog record"):
        vl.positive_records(positives(), ev, records({"event_id": 1}))
    ev2 = events([(10, "2012-07-01", "hma", 1, 1.0, True), (11, "2013-07-02", "hma", 7, 1.0, True)])
    ev2["event_date"] = pd.to_datetime(ev2["event_date"])
    with pytest.raises(ValueError, match="event_id"):
        vl.positive_records(positives(), ev2, records({"event_id": 1}))


# ------------------------------------------------------------------------------- the cell-day decision

def audit_inputs():
    pos = positives(cell_id=[1, 2, 3, 4], date=pd.to_datetime(["2012-07-01"] * 4), split=["train"] * 4,
                    region=["western_ghats"] * 4, in_domain=[True] * 4,
                    stat_slope_mean=[2.0, 2.0, 20.0, 2.0], stat_slope_p90=[5.0] * 4, stat_relief=[50.0] * 4,
                    stat_elev_mean=[30.0, 30.0, 30.0, 30.0])
    # cell 1: one flagged record on low terrain -> implausible; cell 2: a flagged and a plain record -> plausible;
    # cell 3: flagged but steep terrain at 30 m elevation counts as low terrain (elevation test), so use 1500 below;
    # cell 4: a plain record on low terrain -> plausible.
    pos.loc[pos["cell_id"] == 3, "stat_elev_mean"] = 1500.0
    ev = events([(1, "2012-07-01", "hma", 1, 1.0, True), (2, "2012-07-01", "hma", 2, 1.0, True),
                 (2, "2012-07-01", "hma", 3, 1.0, True), (3, "2012-07-01", "hma", 4, 1.0, True),
                 (4, "2012-07-01", "hma", 5, 1.0, True)])
    ev["event_date"] = pd.to_datetime(ev["event_date"])
    catalog = records({"event_id": 1, "setting": "mine"}, {"event_id": 2, "setting": "mine"}, {"event_id": 3},
                      {"event_id": 4, "setting": "retaining_wall"}, {"event_id": 5})
    return vl.positive_records(pos, ev, catalog)


def test_a_cell_day_is_implausible_only_when_every_record_is_flagged_and_the_terrain_is_low():
    table = vl.cell_day_audit(audit_inputs(), RULE).set_index("cell_id")
    assert table["implausible"].to_dict() == {1: True, 2: False, 3: False, 4: False}
    assert table["any_flagged"].to_dict() == {1: True, 2: True, 3: True, 4: False}
    assert table["all_flagged"].to_dict() == {1: True, 2: False, 3: True, 4: False}
    assert table["low_terrain"].to_dict() == {1: True, 2: True, 3: False, 4: True}
    assert table["n_records"].to_dict() == {1: 1, 2: 2, 3: 1, 4: 1}
    assert len(table) == 4


def test_the_audit_table_keeps_the_texts_and_fields_of_the_records():
    table = vl.cell_day_audit(audit_inputs(), RULE).set_index("cell_id")
    assert table.loc[2, "settings"] == "mine|unknown"
    assert table.loc[1, "text"].startswith("Some village")
    assert table.loc[1, "reasons"] == "setting"
    assert table.loc[1, "sources"] == "hma"


# ------------------------------------------------------------------------------------------- summaries

def test_low_terrain_tabulation_counts_by_field_and_flag():
    inputs = audit_inputs()
    table = vl.cell_day_audit(inputs, RULE)
    summary = vl.summarise(inputs, table, RULE)
    assert summary["positive_cell_days"] == 4 and summary["records"] == 5
    assert summary["low_terrain"] == 3 and summary["implausible"] == 1
    assert summary["flagged_any_record"] == 3 and summary["flagged_all_records"] == 2
    assert summary["flagged_all_records_not_low_terrain"] == 1
    # records of the three low-terrain cells (cells 1, 2, 4): ids 1, 2, 3 and 5; the steep cell 3 holds record 4
    assert summary["records_by_field"]["setting"]["low_terrain"] == {"mine": 2, "unknown": 2}
    assert summary["records_by_field"]["setting"]["other"] == {"retaining_wall": 1}
    assert summary["records_by_field"]["source"]["low_terrain"] == {"hma": 4}
    assert summary["records_flagged_by_flag"]["low_terrain"] == {"setting": 2, "category": 0, "geocode": 0, "structure": 0}
    assert summary["records_flagged_by_flag"]["other"]["setting"] == 1
    assert summary["by_split"] == {"train": 4} and summary["implausible_by_split"] == {"train": 1}
    assert summary["implausible_by_reasons"] == {"setting": 1}
    assert summary["records_coarser_than_cell"] == 0 and summary["not_in_domain"] == 0


def test_examples_are_a_seeded_sample_of_the_low_terrain_rows_with_their_text():
    base = audit_inputs()
    many = pd.concat([base.assign(cell_id=base["cell_id"] + 100 * k, event_id=base["event_id"] + 100 * k)
                      for k in range(10)], ignore_index=True)
    table = vl.cell_day_audit(many, RULE)
    first = vl.examples(table, 5, seed=1)
    again = vl.examples(table, 5, seed=1)
    other = vl.examples(table, 5, seed=2)
    assert len(first) == 5 and first.equals(again) and not first["cell_id"].tolist() == other["cell_id"].tolist()
    assert first["low_terrain"].all() and {"text", "categories", "triggers", "accuracies", "settings"} <= set(first.columns)
    assert len(vl.examples(table, 500, seed=1)) == int(table["low_terrain"].sum())
