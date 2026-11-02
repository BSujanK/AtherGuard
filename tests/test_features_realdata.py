"""Real frozen sample tables (run with -m realdata): integrity invariants of the Task 5a outputs."""
import pandas as pd
import pytest

from aetherguard.features.samples import (
    CASE_NAMES,
    WINDOW_NAME,
    default_inputs,
    default_out_dir,
    load_configs,
    sample_name,
    universe_name,
    verify_samples,
)

SPLITS = ("train", "validation", "test_2018")
OUT = default_out_dir()
INPUTS = default_inputs()
needs_build = pytest.mark.skipif(not (OUT / "samples_manifest.json").is_file(),
                                 reason="samples not built (python -m aetherguard.features.samples_build)")


@pytest.mark.realdata
@needs_build
def test_real_samples_verify_clean():
    assert verify_samples(OUT, INPUTS, load_configs()) == {"ok": True, "problems": []}


@pytest.mark.realdata
@needs_build
def test_real_negatives_ratio_buffer_free_and_no_split_overlap():
    positives = pd.read_parquet(INPUTS.positives)
    seen = set()
    for split in SPLITS:
        frame = pd.read_parquet(OUT / sample_name(split))
        keys = set(zip(frame["cell_id"], frame["date"]))
        assert not keys & seen
        seen |= keys
        stored = frame[frame["kind"] == "positive"]
        assert len(stored) == (positives["split"] == split).sum()
        for region in ("himalaya", "western_ghats"):
            part = frame[frame["region"] == region]
            n_pos = ((part["kind"] == "positive") & part["terrain_source"].isin(["own", "nearest_land"])).sum()
            assert (part["kind"] == "negative").sum() == 10 * n_pos


@pytest.mark.realdata
@needs_build
def test_real_universe_window_and_case_sizes():
    for split in SPLITS:
        universe = pd.read_parquet(OUT / universe_name(split))
        assert len(universe) == 200_000 and not universe.duplicated(["cell_id", "date"]).any()
        assert universe.groupby("region").size().to_dict() == {"himalaya": 100_000, "western_ghats": 100_000}
    window = pd.read_parquet(OUT / WINDOW_NAME)
    assert window["date"].nunique() == 46
    assert (window["kind"] == "window_control").sum() == 4000 * 46
    assert window.loc[window["is_window_positive_cell"], "cell_id"].nunique() == 24
    assert pd.read_parquet(OUT / CASE_NAMES["kerala_2018"])["date"].nunique() == 20
    assert pd.read_parquet(OUT / CASE_NAMES["wayanad_2024"])["date"].nunique() == 22


@pytest.mark.realdata
def test_real_cell_regions_cover_every_terrain_cell():
    path = default_out_dir().parent / "cell_regions.parquet"
    if not path.is_file():
        pytest.skip("cell regions not built (python -m aetherguard.features.regions_build)")
    regions = pd.read_parquet(path)
    terrain = pd.read_parquet(INPUTS.terrain, columns=["cell_id"])
    assert len(regions) == len(terrain) == 166_728
    assert set(regions["cell_id"]) == set(terrain["cell_id"])
    assert set(regions["region"]) == {"himalaya", "western_ghats", "out_of_scope"}


FEATURES = default_out_dir().parent
PROCESSED_RAIN = INPUTS.terrain.parent.parent / "rain"
needs_features = pytest.mark.skipif(not (FEATURES / "features_manifest.json").is_file(),
                                    reason="features not built (python -m aetherguard.features.features_build)")


@pytest.mark.realdata
@needs_features
def test_real_features_verify_clean_with_identical_rows_to_the_samples():
    from aetherguard.features import build

    assert build.verify_features(FEATURES, build.default_inputs(), build.load_configs()) == {"ok": True, "problems": []}


@pytest.mark.realdata
@needs_features
def test_real_wayanad_cell_on_2024_07_30_shows_the_imd_chirps_gap():
    from aetherguard.grid import latlon_to_cell
    from aetherguard.ingest.chirps import ChirpsStore

    cell = latlon_to_cell(11.51, 76.13)
    table = pd.read_parquet(FEATURES / "case_wayanad_2024_samples_features.parquet")
    row = table[(table["cell_id"] == cell) & (table["date"] == "2024-07-30")].iloc[0]
    utc = ChirpsStore(PROCESSED_RAIN).cell_series(cell, "2024-07-29", "2024-07-30")
    assert row["rain_source"] == "imd" and row["src_imd_acc_1"] == pytest.approx(179.24, abs=0.5)
    assert row["src_chi_acc_1"] == pytest.approx(0.875 * float(utc[0]) + 0.125 * float(utc[1]), rel=1e-4)
    assert row["src_dis_diff_1"] > 100 and row["src_dis_ratio_1"] > 2.5


@pytest.mark.realdata
@needs_features
def test_real_kerala_positive_cells_on_2018_08_15_are_wetter_than_the_median_negative():
    kerala = pd.read_parquet(FEATURES / "case_kerala_2018_samples_features.parquet")
    positives = kerala[kerala["is_positive_cell_day"] & (kerala["date"] == "2018-08-15")]
    negatives = pd.read_parquet(FEATURES / "test_2018_samples_features.parquet")
    median = negatives[(negatives["kind"] == "negative") & (negatives["region"] == "western_ghats")]["rain_acc_3"].median()
    assert len(positives) >= 1 and (positives["rain_acc_3"] > median).all()

