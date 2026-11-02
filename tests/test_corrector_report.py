import json

import numpy as np
import pandas as pd
import pytest
from integrity_helpers import synthetic_raw_years, write_toy_rain_store

from aetherguard.config import data_root
from aetherguard.corrector import cells, report
from aetherguard.grid import latlon_to_cell
from aetherguard.integrity.common import integrity_dir
from aetherguard.integrity.stations import load_station_set


@pytest.fixture(scope="module")
def smoke(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    tmp = tmp_path_factory.mktemp("corr")
    root = tmp / "data"
    root.mkdir()
    mp.setenv("AETHERGUARD_DATA_DIR", str(root))
    raw = synthetic_raw_years(tmp, n_stations=10)
    write_toy_rain_store(root / "processed" / "rain")
    window = load_station_set(raw, start="2007-01-01", end="2024-12-31")
    oof = pd.concat([pd.DataFrame({"station": sid, "date": window.values.index, "flagged": False})
                     for sid in window.values.columns], ignore_index=True)
    oof.to_parquet(integrity_dir() / "engine_outputs_2007_oof.parquet", index=False)
    terrain = pd.DataFrame([{"cell_id": int(latlon_to_cell(r.lat, r.lon)), "elev_mean": 300.0, "relief": 50.0, "slope_mean": 4.0,
                             "aspect_sin": 0.1, "aspect_cos": 0.9} for r in window.meta.itertuples()])
    (root / "processed" / "terrain").mkdir(parents=True)
    terrain.to_parquet(root / "processed" / "terrain" / "cell_terrain.parquet", index=False)
    features = root / "processed" / "features"
    features.mkdir(parents=True)
    n = 8
    frame = pd.DataFrame({"cell_id": np.arange(n, dtype=np.int64) + 5, "date": pd.date_range("2010-07-01", periods=n),
                          "src_chi_acc_1": np.linspace(0, 60, n), "src_chi_acc_3": np.linspace(0, 120, n), "wet_top": 0.5,
                          "wet_root": 0.5, "stat_elev_mean": 300.0, "stat_relief": 50.0, "stat_slope_mean": 4.0,
                          "stat_aspect_sin": 0.1, "stat_aspect_cos": 0.9, "src_imd_acc_1": 1.0, "src_imd_acc_3": 2.0})
    frame.to_parquet(features / "x_samples_features.parquet", index=False)
    (features / "features_manifest.json").write_text(json.dumps({"files": {"x_samples_features.parquet": {"sha256": "x"}}}),
                                                     encoding="utf-8")
    mp.setattr("aetherguard.corrector.model.QUANTILE_GRID", ({"num_leaves": 7, "min_data_in_leaf": 30},))
    mp.setattr("aetherguard.corrector.model.CLASSIFIER_GRID", ({"num_leaves": 7, "min_data_in_leaf": 20},))
    mp.setattr("aetherguard.corrector.model.MAX_ROUNDS", 40)
    out = report.build_report(raw, n_boot=15)
    md, js = report.write_reports(out, tmp / "reports")
    yield {"report": out, "md": md, "js": js, "root": root, "features": features}
    mp.undo()


def test_report_is_strict_json_with_every_section_and_variant(smoke):
    parsed = json.loads(smoke["js"].read_text(encoding="utf-8"), parse_constant=lambda c: pytest.fail(c))
    md = smoke["md"].read_text(encoding="utf-8")
    for section in ("## Data", "Pinball loss", "Coverage", "Bias on the top 1%", "Exceedance", "Wayanad check", "Verdicts",
                    "leakage-risk", "Notes and limits"):
        assert section.lower() in md.lower()
    ev = parsed["evaluation_test"]
    assert set(ev["pinball"]) == set(report.METHODS)
    for name in ("corrector", "corrector_with_imd", "linear_scaling"):
        assert set(ev["pinball"][name]) == {"0.5", "0.9", "0.99"} and "diff_ci" in ev["pinball"][name]["0.9"]
    for name in ("corrector", "corrector_with_imd"):
        assert "diff_vs_linear_ci" in ev["pinball"][name]["0.5"]
    assert set(parsed["data"]["by_split"]) == {"train", "val", "test"}
    assert len(parsed["verdicts"]) >= 15


def test_headline_corrector_excludes_imd_and_the_leakage_variant_uses_it(smoke):
    tuning = smoke["report"]["tuning"]
    assert set(tuning) == {"headline", "leakage_risk"}
    headline = json.loads((data_root() / "processed" / "corrector" / "model" / "card.json").read_text(encoding="utf-8"))
    leak = json.loads((data_root() / "processed" / "corrector" / "model" / "leakage_risk" / "card.json").read_text(encoding="utf-8"))
    assert not {"imd_1", "imd_3"} & set(headline["columns"]) and {"imd_1", "imd_3"} <= set(leak["columns"])
    assert headline["columns"] == report.cdata.PREDICTORS


def test_wayanad_case_is_reported_and_states_a_verdict(smoke):
    case = smoke["report"]["wayanad"]
    assert case["cell_id"] == int(latlon_to_cell(report.WAYANAD["lat"], report.WAYANAD["lon"]))
    assert report.WAYANAD["date"] in case["days"] and len(case["days"]) == 11
    assert isinstance(case["corrector_summary"]["gap_closed"], bool)
    assert "gap" in smoke["md"].read_text(encoding="utf-8")


def test_cell_files_were_written_frozen_with_the_documented_columns(smoke):
    out = smoke["features"] / "corrector"
    made = pd.read_parquet(out / "x_samples_corr.parquet")
    assert list(made.columns) == ["cell_id", "date"] + cells.CORR_COLUMNS and len(made) == 8
    assert cells.verify_cells(out, smoke["features"], data_root() / "processed" / "corrector" / "model")["ok"]
    assert made["corr_q50_1"].iloc[0] >= 0


def test_wayanad_gap_rule_and_constants():
    assert report.GAP_CLOSED_FRACTION == 0.5 and report.WAYANAD["imd_mm"] == pytest.approx(179.24)
    assert report.METHODS == ("raw_chirps", "linear_scaling", "corrector", "corrector_with_imd")


@pytest.mark.realdata
def test_real_corrector_outputs_are_frozen_intact_and_the_headline_beats_raw_at_q99():
    features = data_root() / "processed" / "features"
    model_dir = data_root() / "processed" / "corrector" / "model"
    result = cells.verify_cells(features / "corrector", features, model_dir)
    assert result["ok"], result["problems"]
    parsed = json.loads((report.reports_dir() / "phase3_corrector_report.json").read_text(encoding="utf-8"))
    cell = parsed["evaluation_test"]["pinball"]["corrector"]["0.99"]
    assert cell["diff_ci"][1] < 0
    assert parsed["wayanad"]["terrain_available"]
    manifest = json.loads((features / "corrector" / cells.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert len(manifest["feature_files"]) == 9
