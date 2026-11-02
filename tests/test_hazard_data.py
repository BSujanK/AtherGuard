import numpy as np
import pandas as pd
import pytest

from aetherguard.hazard import data as d

from hazard_helpers import (COLUMN_MAP, EXTRA_GROUPS, UNIVERSE_SIZES, synthetic_development, synthetic_samples,
                            synthetic_universe, write_dev_store)


def test_model_columns_follow_the_group_map_in_store_order():
    cols = d.model_columns(["rain", "stat"], COLUMN_MAP)
    assert cols[0] == "rain_acc_1" and "stat_slope_mean" in cols
    assert all(COLUMN_MAP[c] in {"rain", "stat"} for c in cols)
    assert not any(c.startswith(("src_", "wet_")) for c in cols)


def test_meta_columns_can_never_be_model_inputs():
    with pytest.raises(ValueError, match="meta"):
        d.model_columns(["rain", "meta"], COLUMN_MAP)
    for group in ("rain", "src", "wet", "stat"):
        assert not set(d.model_columns([group], COLUMN_MAP)) & d.NEVER_INPUTS
    for name in ("lat", "lon", "cell_id", "region", "month", "rain_source", "terrain_source", "in_domain"):
        assert name not in d.model_columns(["rain", "src", "wet", "stat"], COLUMN_MAP)
        assert name in d.NEVER_INPUTS


def test_a_mislabelled_meta_column_is_refused():
    broken = {**COLUMN_MAP, "lat": "stat"}
    with pytest.raises(ValueError, match="may not be model inputs"):
        d.model_columns(["stat"], broken)


def test_unknown_group_and_empty_selection_are_refused():
    with pytest.raises(ValueError, match="unknown feature groups"):
        d.model_columns(["integ"], COLUMN_MAP)
    with pytest.raises(ValueError, match="no input columns"):
        d.model_columns(["src"], COLUMN_MAP, exclude_prefixes=("src_",))


def test_a_new_group_is_just_a_filter_over_the_map():
    extended = {**COLUMN_MAP, "integ_trust": "integ", "integ_n": "integ"}
    assert d.model_columns(["rain", "integ"], extended)[-2:] == ["integ_trust", "integ_n"]


def test_disagreement_exclusion_drops_only_those_columns():
    all_cols = d.model_columns(["rain", "src", "wet", "stat"], COLUMN_MAP)
    kept = d.model_columns(["rain", "src", "wet", "stat"], COLUMN_MAP, exclude_prefixes=("src_dis_",))
    assert set(all_cols) - set(kept) == {"src_dis_diff_1", "src_dis_ratio_1"}


def test_universe_negatives_sum_to_universe_size_and_drop_buffer_and_positives():
    universe = synthetic_universe("train", n_per_region=1000, n_buffer=40)
    negatives = d.universe_negatives(universe)
    assert len(negatives) == 2 * (1000 - 40 - 1)
    assert not negatives["in_buffer"].any() and not negatives["is_positive_cell_day"].any()
    sums = negatives.groupby("region")["weight"].sum()
    for region, size in UNIVERSE_SIZES.items():
        assert sums[region] == pytest.approx(size)
    assert (negatives["weight_drawn"] == negatives["universe_size"] / 1000).all()
    assert (negatives["label"] == 0).all()


def test_universe_negatives_with_buffer_variant_keeps_buffer_rows():
    universe = synthetic_universe("train", n_per_region=1000, n_buffer=40)
    with_buffer = d.universe_negatives(universe, include_buffer=True)
    assert len(with_buffer) == 2 * 999 and with_buffer["in_buffer"].any()
    assert with_buffer.groupby("region")["weight"].sum().sum() == pytest.approx(sum(UNIVERSE_SIZES.values()))


def test_split_data_separates_in_domain_positives_and_counts_out_of_domain():
    samples = synthetic_samples("validation", n_pos=50, n_out_of_domain=4)
    data = d.split_data("validation", samples, synthetic_universe("validation"))
    assert len(data.positives) == 50 and data.positives["in_domain"].all()
    assert sum(data.n_out_of_domain.values()) == 4
    assert (data.matched["kind"] == "negative").all()
    assert data.universe_sizes == UNIVERSE_SIZES


def test_evaluation_frame_labels_and_weights():
    samples = synthetic_samples("validation", n_pos=50)
    data = d.split_data("validation", samples, synthetic_universe("validation", n_per_region=500, n_buffer=10))
    frame = d.evaluation_frame(data)
    assert frame["label"].sum() == 50
    assert (frame.loc[frame["label"] == 1, "eval_weight"] == 1.0).all()
    assert frame.loc[frame["label"] == 0, "eval_weight"].sum() == pytest.approx(sum(UNIVERSE_SIZES.values()))
    ghats = d.evaluation_frame(data, regions=["western_ghats"])
    assert set(ghats["region"]) == {"western_ghats"}
    assert ghats.loc[ghats["label"] == 0, "eval_weight"].sum() == pytest.approx(UNIVERSE_SIZES["western_ghats"])


def test_base_rates_are_positives_per_universe_cell_day():
    samples = synthetic_samples("validation", n_pos=50)
    data = d.split_data("validation", samples, synthetic_universe("validation"))
    rates = d.base_rates(data)
    assert rates["overall"]["base_rate"] == pytest.approx(50 / sum(UNIVERSE_SIZES.values()))
    assert sum(r["positives"] for r in rates["regions"].values()) == 50


def test_training_frame_matched_only():
    samples = synthetic_samples("train", n_pos=40, n_out_of_domain=3)
    frame = d.training_frame(samples, synthetic_universe("train"), "matched_only", 1000, seed=1)
    assert len(frame) == 40 + 200 and frame["in_domain"].all()
    assert (frame["sample_weight"] == 1.0).all() and set(frame["kind"]) == {"positive", "negative"}


def test_training_frame_universe_negatives_carry_equal_total_weight():
    samples = synthetic_samples("train", n_pos=40)
    universe = synthetic_universe("train", n_per_region=2000, n_buffer=50)
    frame = d.training_frame(samples, universe, "matched_plus_universe", 1000, seed=1)
    matched = frame[frame["kind"] == "negative"]
    drawn = frame[frame["kind"] == "universe"]
    allowed = universe.loc[~universe["in_buffer"] & ~universe["is_positive_cell_day"], "cell_id"]
    assert len(drawn) == 1000 and set(drawn["cell_id"]) <= set(allowed)
    assert drawn["sample_weight"].sum() == pytest.approx(matched["sample_weight"].sum())
    assert (frame.loc[frame["kind"] == "positive", "sample_weight"] == 1.0).all()
    assert (frame["label"].to_numpy()[frame["kind"] != "positive"] == 0).all()
    again = d.training_frame(samples, universe, "matched_plus_universe", 1000, seed=1)
    pd.testing.assert_frame_equal(frame, again)
    other = d.training_frame(samples, universe, "matched_plus_universe", 1000, seed=2)
    assert not frame["cell_id"].equals(other["cell_id"])


def test_training_frame_region_filter_and_bad_mix():
    samples = synthetic_samples("train", n_pos=60)
    frame = d.training_frame(samples, synthetic_universe("train"), "matched_plus_universe", 500, seed=1,
                             regions=["himalaya"])
    assert set(frame["region"]) == {"himalaya"}
    with pytest.raises(ValueError, match="neg_mix"):
        d.training_frame(samples, synthetic_universe("train"), "everything", 10, seed=1)


@pytest.mark.parametrize("split", ["test_2018", "test_sparse"])
def test_leakage_guard_rejects_test_splits(split):
    frame = d.training_frame(synthetic_samples("train", n_pos=20), synthetic_universe("train"), "matched_only", 10, 1)
    frame.loc[0, "split"] = split
    with pytest.raises(d.LeakageError, match="only"):
        d.assert_training_rows(frame)
    with pytest.raises(d.LeakageError, match="only"):
        d.assert_development_rows(frame)


def test_validation_rows_are_development_rows_in_v2():
    frame = d.training_frame(synthetic_samples("validation", n_pos=20), synthetic_universe("validation"),
                             "matched_only", 10, 1)
    d.assert_training_rows(frame)


def test_leakage_guard_rejects_case_window_and_out_of_domain_rows():
    frame = d.training_frame(synthetic_samples("train", n_pos=20), synthetic_universe("train"), "matched_only", 10, 1)
    for kind in ("case_kerala_2018", "window_cell", "window_control"):
        bad = frame.copy()
        bad.loc[0, "kind"] = kind
        with pytest.raises(d.LeakageError, match="never fitted"):
            d.assert_training_rows(bad)
    bad = frame.copy()
    bad.loc[0, "in_domain"] = False
    with pytest.raises(d.LeakageError, match="out-of-domain"):
        d.assert_training_rows(bad)
    with pytest.raises(d.LeakageError, match="`split` column"):
        d.assert_training_rows(frame.drop(columns="split"))


def test_load_features_reports_missing_store(tmp_path):
    with pytest.raises(FileNotFoundError, match="feature store"):
        d.load_features("train_samples", tmp_path)
    with pytest.raises(FileNotFoundError):
        d.load_column_map(tmp_path)


def test_load_split_round_trip_from_parquet(tmp_path):
    synthetic_samples("validation", n_pos=30).to_parquet(tmp_path / "validation_samples_features.parquet")
    synthetic_universe("validation").to_parquet(tmp_path / "universe_validation_features.parquet")
    data = d.load_split("validation", tmp_path)
    assert len(data.positives) == 30
    with pytest.raises(ValueError):
        d.load_split("test_sparse", tmp_path)
    assert np.isfinite(d.base_rates(data)["overall"]["base_rate"])


# ------------------------------------------------------------------------------------------- development

def _dev():
    samples, universe = synthetic_development()
    return d.build_development(samples, universe, COLUMN_MAP), samples, universe


def test_year_weights_sum_to_the_split_region_size_and_follow_the_days_of_each_year():
    dev, _, universe = _dev()
    negatives = dev.negatives
    per_split = negatives.groupby(["split", "region"])["weight"].sum()
    for (split, region), total in per_split.items():
        assert total == pytest.approx(UNIVERSE_SIZES[region])
    days = universe[universe["split"] == "validation"].assign(year=lambda f: f["date"].dt.year)
    days = days.groupby("year")["date"].nunique()
    per_year = negatives[(negatives["split"] == "validation") & (negatives["region"] == "himalaya")]
    per_year = per_year.groupby("year")["weight"].sum()
    for year in (2016, 2017):
        assert per_year[year] == pytest.approx(UNIVERSE_SIZES["himalaya"] * days[year] / days.sum())
    assert not negatives["in_buffer"].any() and not negatives["is_positive_cell_day"].any()
    assert (negatives["weight_drawn"] == negatives["universe_size"] / 3000).all()


def test_year_weights_are_constant_within_a_year_region():
    dev, _, _ = _dev()
    spread = dev.negatives.groupby(["year", "region"])["weight"].nunique()
    assert (spread == 1).all()


def test_year_weights_buffer_variant_counts_buffer_rows():
    dev, _, universe = _dev()
    with_buffer = d.year_weighted_negatives(universe, include_buffer=True)
    assert with_buffer["in_buffer"].any() and len(with_buffer) > len(dev.negatives)
    assert with_buffer.groupby(["split", "region"])["weight"].sum().sum() == pytest.approx(
        sum(UNIVERSE_SIZES.values()) * 2)


def test_year_weights_fail_when_a_year_has_no_negatives():
    _, _, universe = _dev()
    gone = universe[~((universe["date"].dt.year == 2012) & (universe["region"] == "himalaya"))]
    with pytest.raises(ValueError, match="no negative universe rows"):
        d.year_weighted_negatives(gone)


def test_development_properties():
    dev, samples, _ = _dev()
    assert (dev.samples["year"] == dev.samples["date"].dt.year).all()
    assert len(dev.positives) == 130 and dev.positives["in_domain"].all()
    assert sum(dev.n_out_of_domain.values()) == 6
    assert dev.universe_sizes == {r: 2 * s for r, s in UNIVERSE_SIZES.items()}


def test_development_refuses_test_window_and_case_rows():
    samples, universe = synthetic_development()
    for column, value in (("split", "test_2018"), ("kind", "window_cell"), ("kind", "case_kerala_2018")):
        bad = samples.copy()
        bad.loc[0, column] = value
        with pytest.raises(d.LeakageError):
            d.build_development(bad, universe, COLUMN_MAP)
        bad_u = universe.copy()
        bad_u.loc[0, column] = value
        with pytest.raises(d.LeakageError):
            d.build_development(samples, bad_u, COLUMN_MAP)


def test_load_development_with_extras_joins_columns_and_applies_meta_columns(tmp_path):
    samples, universe = synthetic_development()
    store = write_dev_store(tmp_path / "store", samples, universe)
    dev = d.load_development(store, EXTRA_GROUPS, ["integ", "corr"], ["integ_n_st_100km"])
    assert {"integ_trw_rain_1", "corr_q50_1", "integ_n_st_100km"} <= set(dev.universe.columns)
    columns = d.model_columns(["rain", "integ", "corr"], dev.column_map)
    assert "integ_trw_rain_1" in columns and "corr_p_exceed99" in columns
    assert "integ_n_st_100km" not in columns and dev.column_map["integ_n_st_100km"] == "meta"
    plain = d.load_development(store)
    assert "integ_trw_rain_1" not in plain.samples.columns and len(plain.samples) == len(dev.samples)


def test_extra_group_key_row_and_checksum_verification(tmp_path):
    samples, universe = synthetic_development()
    store = write_dev_store(tmp_path / "store", samples, universe)
    path = store / "integ" / "train_samples_integ.parquet"
    original = pd.read_parquet(path)

    shuffled = original.sample(frac=1.0, random_state=0).reset_index(drop=True)
    shuffled.to_parquet(path)
    with pytest.raises(d.ExtraGroupError, match="checksum"):
        d.load_table("train_samples", store, EXTRA_GROUPS, ["integ"])

    import hashlib
    import json
    manifest_path = store / "integ" / "integ_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][path.name]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(d.ExtraGroupError, match="keys"):
        d.load_table("train_samples", store, EXTRA_GROUPS, ["integ"])

    original.head(10).to_parquet(path)
    manifest["files"][path.name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "n_rows": 10}
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(d.ExtraGroupError, match="rows"):
        d.load_table("train_samples", store, EXTRA_GROUPS, ["integ"])


def test_extra_group_errors_for_missing_config_and_files(tmp_path):
    samples, universe = synthetic_development()
    store = write_dev_store(tmp_path / "store", samples, universe, extras=False)
    with pytest.raises(ValueError, match="not configured"):
        d.load_table("train_samples", store, EXTRA_GROUPS, ["nope"])
    with pytest.raises(FileNotFoundError):
        d.load_table("train_samples", store, EXTRA_GROUPS, ["integ"])
    with pytest.raises(FileNotFoundError):
        d.load_column_map(store, EXTRA_GROUPS, ["integ"])


def test_meta_columns_of_groups_that_are_not_loaded_are_ignored(tmp_path):
    samples, universe = synthetic_development()
    store = write_dev_store(tmp_path / "store", samples, universe)
    mapping = d.load_column_map(store, EXTRA_GROUPS, ["corr"], ["integ_n_st_100km"])
    assert "integ_n_st_100km" not in mapping and mapping["corr_q50_1"] == "corr"
    mapping = d.load_column_map(store, EXTRA_GROUPS, ["integ"], ["integ_n_st_100km"])
    assert mapping["integ_n_st_100km"] == "meta" and mapping["integ_trw_rain_1"] == "integ"
