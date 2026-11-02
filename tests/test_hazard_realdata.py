"""Real frozen feature store and the trained v2 model (run with -m realdata). Never opens test_2018 scores."""
import json

import numpy as np
import pytest

from aetherguard.hazard import data as hd
from aetherguard.hazard import model as hm
from aetherguard.hazard.train import extra_groups_used, input_checksums

FEATURES = hd.features_dir()
MODEL = hm.default_model_dir()
CFG = hm.hazard_config()
needs_store = pytest.mark.skipif(not (FEATURES / "feature_columns.json").is_file(), reason="feature store not built")
needs_model = pytest.mark.skipif(not (MODEL / "card.json").is_file(),
                                 reason="model not trained (python -m aetherguard.hazard.train)")


@pytest.fixture(scope="module")
def dev():
    return hd.load_development(FEATURES, CFG["extra_groups"], extra_groups_used(CFG), CFG["meta_columns"])


@pytest.mark.realdata
@needs_store
def test_real_group_map_never_exposes_meta_or_station_presence_columns(dev):
    columns = hd.model_columns(["rain", "src", "wet", "stat", "integ", "corr"], dev.column_map)
    assert not set(columns) & hd.NEVER_INPUTS
    assert not set(columns) & set(CFG["meta_columns"])
    assert {"integ_trw_rain_1", "integ_frac_trusted_100km", "corr_p_exceed99"} <= set(columns)
    assert len([c for c in columns if c.startswith(("rain_", "src_", "wet_", "stat_"))]) == 43


@pytest.mark.realdata
@needs_store
def test_real_development_counts_and_year_weights(dev):
    assert len(dev.positives) == 789 and sum(dev.n_out_of_domain.values()) == 35
    negatives = dev.negatives
    sums = negatives.groupby(["split", "region"])["weight"].sum()
    sizes = dev.universe.groupby(["split", "region"])["universe_size"].first()
    for key, total in sums.items():
        assert total == pytest.approx(sizes[key])
    assert (negatives.groupby(["year", "region"])["weight"].nunique() == 1).all()
    assert set(negatives["year"]) == set(range(2007, 2018))
    assert not negatives["in_buffer"].any() and not negatives["is_positive_cell_day"].any()


@pytest.mark.realdata
@needs_store
def test_real_extra_groups_join_with_verified_keys(dev):
    for group in extra_groups_used(CFG):
        assert group in set(dev.column_map.values())
    assert dev.samples["integ_trw_rain_1"].notna().any() and dev.universe["corr_p_exceed99"].notna().any()
    assert len(dev.samples) == 9064 and len(dev.universe) == 400000


@pytest.mark.realdata
@needs_store
def test_real_test_window_and_case_tables_are_refused_by_the_guard():
    for name in (hd.SAMPLE_NAMES[hd.TEST], hd.UNIVERSE_NAMES[hd.TEST], hd.WINDOW_NAME, "case_kerala_2018_samples"):
        with pytest.raises(hd.LeakageError):
            hd.assert_development_rows(hd.load_features(name))


@pytest.mark.realdata
@needs_store
@needs_model
def test_real_model_scores_development_rows_and_card_is_consistent(dev):
    scored = hm.score_frame(dev.positives.head(50), MODEL)
    assert list(scored.columns) == ["risk", "risk_lo", "risk_hi", "risk_per_100k"]
    assert np.isfinite(scored.to_numpy()).all() and (scored["risk_lo"] <= scored["risk_hi"]).all()
    card = json.loads((MODEL / "card.json").read_text())
    assert card["inputs"] == json.loads(json.dumps(input_checksums(FEATURES, CFG))), "model is stale versus the inputs"
    assert card["folds"] == CFG["cv"]["folds"] and card["monotonicity_all_hold"]
    assert not set(card["columns"]) & set(CFG["meta_columns"]) and not set(card["columns"]) & hd.NEVER_INPUTS
    levels = card["alert_levels"]
    assert levels["watch"]["raw"] < levels["warning"]["raw"] < levels["emergency"]["raw"]
    assert levels["watch"]["oof_recall"] >= 0.9
    assert np.isfinite(card["oof_pooled"]["fa_at_recall_0.9"]["value"])


@pytest.mark.realdata
@needs_model
def test_real_model_matches_its_freeze_record():
    from aetherguard.hazard.freeze import verify_freeze
    record = verify_freeze(MODEL)
    assert record["created_utc"].endswith("Z") and "card.json" in record["sha256"]
    assert len([k for k in record["sha256"] if k.startswith("ensemble/")]) == 20
