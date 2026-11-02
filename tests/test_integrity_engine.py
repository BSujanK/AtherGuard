import json

import numpy as np
import pandas as pd
import pytest
from integrity_helpers import make_engine_world

from aetherguard.integrity import features, model
from aetherguard.integrity.engine import OUTPUT_COLUMNS, IntegrityEngine, reference_arrays
from aetherguard.integrity.grids import GridRefs
from aetherguard.integrity.oof import truth_and_refs

PARAMS = {"num_leaves": 7, "min_child_samples": 10}


@pytest.fixture(scope="module")
def world():
    return make_engine_world()


def fit_engine(world, seed=1, **kwargs):
    train = model.assemble_rows(world["feats"], world["table"], world["splits"]["train"])
    val = model.assemble_rows(world["feats"], world["table"], world["splits"]["val"])
    truth, refs = truth_and_refs(world["feats"], world["table"], val, world["refs"])
    return IntegrityEngine.fit(train, val, truth, refs, seed, params=PARAMS, rounds=40, **kwargs)


@pytest.fixture(scope="module")
def engine(world):
    return fit_engine(world)


def test_predict_returns_one_row_per_feature_row_with_the_documented_columns(world, engine):
    out = engine.predict(world["feats"], world["obs"], world["refs"])
    assert len(out) == len(world["feats"]) and list(out.columns)[:len(OUTPUT_COLUMNS)] == OUTPUT_COLUMNS
    assert {f"p_{c}" for c in model.CLASSES} <= set(out.columns)
    observed = out["trust"].notna()
    assert observed.sum() == world["obs"].notna().to_numpy().sum()
    assert np.allclose(out.loc[observed, "trust"], 1.0 - out.loc[observed, "p_fault"])
    probs = out.loc[observed, [f"p_{c}" for c in model.CLASSES]].to_numpy()
    assert np.allclose(probs.sum(axis=1), 1.0, atol=1e-5)
    missing = ~observed
    assert missing.any() and not out.loc[missing, "flagged"].any() and out.loc[missing, "repaired"].isna().all()
    assert out.loc[missing, "p_fault"].isna().all() and (out.loc[missing, "fault_type"] == "").all()


def test_flagged_readings_are_typed_repaired_with_a_band_and_never_deleted(world, engine):
    out = engine.predict(world["feats"], world["obs"], world["refs"])
    flagged = out[out["flagged"]]
    assert len(flagged) > 0 and (flagged["fault_type"] != "").all()
    assert set(flagged["fault_type"]) <= set(model.CLASSES[1:])
    have = flagged["repaired"].notna()
    assert have.any() and (flagged.loc[have, "repaired_lo"] <= flagged.loc[have, "repaired"] + 1e-6).all()
    assert (flagged.loc[have, "repaired_hi"] >= flagged.loc[have, "repaired"] - 1e-6).all()
    assert out.loc[~out["flagged"], "repaired"].isna().all()
    assert len(out) == len(world["feats"])                       # nothing is dropped
    assert (flagged["reasons"] != "").all()


def test_a_higher_false_flag_target_flags_at_least_as_many_days(world, engine):
    counts = [int(engine.predict(world["feats"], world["obs"], world["refs"], fpr=f, use_arbiter=False)["flagged"].sum())
              for f in (0.005, 0.01, 0.02)]
    assert counts[0] <= counts[1] <= counts[2]


def test_arbiter_only_removes_flags_and_marks_them_genuine(world, engine):
    with_a = engine.predict(world["feats"], world["obs"], world["refs"])
    without = engine.predict(world["feats"], world["obs"], world["refs"], use_arbiter=False)
    assert not without["genuine_extreme"].any()
    assert (with_a["flagged"] <= without["flagged"]).all()
    retained = with_a[with_a["genuine_extreme"]]
    assert (~retained["flagged"]).all() and retained["reasons"].str.contains("corroborated_by").all()
    assert (without["flagged"] == (with_a["flagged"] | with_a["genuine_extreme"])).all()


def crafted_world(world):
    obs = world["obs"].copy()
    ids = world["ids"]
    imd = world["refs"].values["imd"].copy()
    chirps = world["refs"].values["chirps_aligned"].copy()
    index = obs.index
    a, b = ids[7], ids[6]

    def put(station, start, values, ref_values):
        sl = slice(start, start + len(values))
        obs.iloc[sl, obs.columns.get_loc(station)] = np.asarray(values, np.float32)
        imd.iloc[sl, imd.columns.get_loc(station)] = np.asarray(ref_values, np.float32)
        chirps.iloc[sl, chirps.columns.get_loc(station)] = np.asarray(ref_values, np.float32)
        return index[start]

    days = {"stuck_good": put(a, 100, [5.0] * 4, [5.2] * 4), "stuck_bad": put(b, 200, [6.0] * 4, [0.0] * 4),
            "bounds": put(a, 300, [2000.0], [2000.0])}
    block = [3.0, 0.0, 5.0, 2.0, 0.0, 7.0, 1.0]
    put(a, 500, block, block)
    days["dup"] = put(a, 600, block, block)
    frames = dict(world["refs"].values)
    frames["imd"], frames["chirps_aligned"] = imd, chirps
    refs = GridRefs(frames)
    clim = features.station_climatology(world["obs"])
    feats = features.build_features(obs, obs.index, world["sset"].meta, refs, world["wide"], climatology=clim)
    return obs, refs, feats, days, a, b


def row(out, station, date):
    return out[(out["station"] == station) & (out["date"] == date)].iloc[0]


def test_l1_flags_are_not_overridable_except_corroborated_stuck_streaks(world, engine):
    obs, refs, feats, days, a, b = crafted_world(world)
    out = engine.predict(feats, obs, refs)
    day = pd.Timedelta(days=1)
    good = row(out, a, days["stuck_good"] + day)
    assert good["l1_reason"] == "stuck" and good["genuine_extreme"] and not good["flagged"]
    assert "stuck_corroborated_by" in good["reasons"]
    bad = row(out, b, days["stuck_bad"] + day)
    assert bad["l1_reason"] == "stuck" and bad["flagged"] and not bad["genuine_extreme"] and bad["p_fault"] == 1.0
    assert bad["fault_type"] != ""
    over = row(out, a, days["bounds"])
    assert over["l1_reason"] == "bounds" and over["flagged"] and not over["genuine_extreme"]    # refs agree: still flagged
    dup = row(out, a, days["dup"] + 2 * day)
    assert "duplicate_block" in dup["l1_reason"] and dup["flagged"] and not dup["genuine_extreme"]
    off = engine.predict(feats, obs, refs, use_arbiter=False)
    assert row(off, a, days["stuck_good"] + day)["flagged"]


def test_model_probabilities_at_day_t_ignore_later_days(world, engine):
    clim = features.station_climatology(world["obs"])
    t = 900
    rng = np.random.default_rng(5)
    obs2 = world["obs"].copy()
    obs2.iloc[t + 1:t + 31] = rng.gamma(1.0, 40.0, (30, obs2.shape[1])).astype(np.float32)
    frames = {k: v.copy() for k, v in world["refs"].values.items()}
    for frame in frames.values():
        frame.iloc[t + 1:t + 31] = rng.random((30, obs2.shape[1])).astype(np.float32)
    refs2 = GridRefs(frames)
    meta = world["sset"].meta
    base = features.build_features(world["obs"], world["obs"].index, meta, world["refs"], world["wide"], climatology=clim)
    changed = features.build_features(obs2, obs2.index, meta, refs2, world["wide"], climatology=clim)
    a = engine.predict(base, world["obs"], world["refs"])
    b = engine.predict(changed, obs2, refs2)
    keep = a["date"] <= world["obs"].index[t]
    cols = [f"p_{c}" for c in model.CLASSES]
    pd.testing.assert_frame_equal(a.loc[keep, cols].reset_index(drop=True), b.loc[keep, cols].reset_index(drop=True))
    assert not a.loc[~keep, cols].reset_index(drop=True).equals(b.loc[~keep, cols].reset_index(drop=True))


def test_same_seed_gives_identical_predictions_and_a_different_seed_does_not(world, engine):
    again = fit_engine(world, seed=1)
    a = engine.predict(world["feats"], world["obs"], world["refs"])
    b = again.predict(world["feats"], world["obs"], world["refs"])
    pd.testing.assert_frame_equal(a, b)
    other = fit_engine(world, seed=2).predict(world["feats"], world["obs"], world["refs"])
    assert not np.array_equal(a["p_fault"].to_numpy(), other["p_fault"].to_numpy(), equal_nan=True)


def test_save_and_load_round_trip_gives_identical_predictions_and_a_full_card(world, engine, tmp_path):
    engine.save(tmp_path / "model")
    again = IntegrityEngine.load(tmp_path / "model")
    a = engine.predict(world["feats"], world["obs"], world["refs"])
    b = again.predict(world["feats"], world["obs"], world["refs"])
    pd.testing.assert_frame_equal(a, b)
    card = json.loads((tmp_path / "model" / "card.json").read_text(encoding="utf-8"))
    assert {"features", "thresholds", "seed", "train_rows", "val_rows", "val_scores", "class_weights", "repair",
            "selected_params", "candidates"} <= set(card)
    assert card["features"] == engine.bundle.columns and card["thresholds"] == engine.bundle.tau
    assert card["train_rows"]["ok"] > 0 and (tmp_path / "model" / "model.txt").is_file()


def test_reference_arrays_use_the_idw_neighbour_mean_and_the_grids(world):
    ref = reference_arrays(world["feats"], world["refs"])
    assert set(ref) == {"imd", "chirps_aligned", "neighbours"}
    sid = world["ids"][0]
    first = (world["feats"]["station"] == sid).to_numpy()
    np.testing.assert_allclose(ref["imd"][first], world["refs"].values["imd"][sid].to_numpy(), equal_nan=True)
    np.testing.assert_allclose(ref["neighbours"], world["feats"]["nbr_idw_mean"].to_numpy(), equal_nan=True)


def test_select_tau_makes_the_combined_decision_meet_each_target_on_the_calibration_clean_days(world):
    eng = fit_engine(world)
    model_only = dict(eng.bundle.tau_model)
    val = model.assemble_rows(world["feats"], world["table"], world["splits"]["val"])
    eng.select_tau(world["feats"], world["obs"], world["refs"], val.idx, val.y == 0)
    assert eng.bundle.tau_model == model_only and eng.card["thresholds"] == eng.bundle.tau
    assert eng.card["thresholds_model_only"] == model_only
    for level in (0.005, 0.01, 0.02):
        out = eng.predict(world["feats"], world["obs"], world["refs"], fpr=level)
        assert out["flagged"].to_numpy()[val.idx][val.y == 0].mean() <= level + 1e-12
    assert eng.bundle.tau["0.005"] >= eng.bundle.tau["0.01"] >= eng.bundle.tau["0.02"]
    # a looser target must not flag fewer days
    counts = [int(eng.predict(world["feats"], world["obs"], world["refs"], fpr=f)["flagged"].sum()) for f in (0.005, 0.01, 0.02)]
    assert counts[0] <= counts[1] <= counts[2]


def test_tau_override_and_the_unreachable_target_case(world):
    eng = fit_engine(world)
    val = model.assemble_rows(world["feats"], world["table"], world["splits"]["val"])
    sub = world["feats"].iloc[val.idx].reset_index(drop=True)
    clean = np.flatnonzero(val.y == 0)
    unreachable = eng.tau_for_rate(sub, world["obs"], world["refs"], clean, [0.0])
    assert unreachable["0.0"] >= eng.tau_for_rate(sub, world["obs"], world["refs"], clean, [0.02])["0.02"]
    loose = eng.predict(world["feats"], world["obs"], world["refs"], tau=0.0)
    tight = eng.predict(world["feats"], world["obs"], world["refs"], tau=1.0)
    assert loose["flagged"].sum() > tight["flagged"].sum()
    assert tight["flagged"].sum() <= int(tight["l1_flag"].sum())          # only L1 can flag at tau = 1


def test_combined_taus_survive_save_and_load(world, tmp_path):
    eng = fit_engine(world)
    val = model.assemble_rows(world["feats"], world["table"], world["splits"]["val"])
    eng.select_tau(world["feats"], world["obs"], world["refs"], val.idx, val.y == 0)
    eng.save(tmp_path / "m")
    again = IntegrityEngine.load(tmp_path / "m")
    assert again.bundle.tau == eng.bundle.tau and again.bundle.tau_model == eng.bundle.tau_model
