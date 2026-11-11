"""W3 challenger v4-int (spec 2026-11-06 sections 2-3 and its amendment): the configuration, stage 1, the two-stage decision
against v3_ranked, the lag, the tie-broken burden matching, the preflight, the one-shot held-out guard and the scoring of the
season panels with the iint group, on synthetic data."""
import copy
import hashlib
import json
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from aetherguard import grid
from aetherguard.config import PROJECT_ROOT, load_config_file
from aetherguard.features import imerg_build as B
from aetherguard.features import imerg_intensity as ii
from aetherguard.hazard import challengers as ch
from aetherguard.hazard import cv
from aetherguard.hazard import data as hd
from aetherguard.hazard import model as hm
from aetherguard.hazard import v4_int as v4
from aetherguard.live import backtest as bt
from aetherguard.live import hardening as H
from aetherguard.live import run as live_run
from aetherguard.live.early_map import IdentityMap
from aetherguard.live.sources import PERSIST, ImergSource
from aetherguard.verify import matching, scores as vscores
from aetherguard.verify import operating_point as op
from aetherguard.verify import report as vr

from hazard_helpers import COLUMN_MAP, synthetic_development, write_dev_store
from live_run_helpers import FakeStore, make_cfg, span, tiny_cells, tiny_clim

FOLDS = [[2007, 2008, 2009], [2010, 2011, 2012], [2013, 2014, 2015], [2016, 2017]]
COLUMNS = ["stat_relief", "stat_slope_mean", "stat_elev_mean", "stat_aspect_sin", "rain_acc_1", "rain_acc_3", "rain_acc_7",
           "rain_days_since_10mm"]
IINT = ii.feature_names()
SELECTED = {"hp": {"num_leaves": 4, "min_data_in_leaf": 10, "feature_fraction": 0.9, "lambda_l2": 1.0, "learning_rate": 0.2},
            "neg_mix": "matched_plus_universe", "columns": COLUMNS}
BOOT = {"n": 60, "seed": 5, "level": 0.95}


def tiny_study() -> dict:
    study = load_config_file(PROJECT_ROOT / "configs" / "hazard_v4_int.yaml")
    base = copy.deepcopy(hm.hazard_config(PROJECT_ROOT / study["base_config"]))
    base["training"].update(max_rounds=40, early_stopping_rounds=5, universe_negatives=600)
    base["cv"]["folds"] = FOLDS
    base["bootstrap"].update(n=40)
    base["ensemble"].update(members=3)
    base["groups"], base["group_stages"] = ["stat"], []          # the synthetic store has no irain / iapi / inbr files
    study["base"] = base
    return study


def add_intensity(frame: pd.DataFrame, seed: int) -> pd.DataFrame:
    """The six iint columns of the synthetic rows: bursts that rise with the day's rain."""
    rng = np.random.default_rng(seed)
    rain = frame["rain_acc_1"].to_numpy(dtype=np.float64)
    out = frame.copy()
    out["iint_max1h_1"] = rain * rng.uniform(0.2, 0.5, len(frame))
    out["iint_max3h_1"] = out["iint_max1h_1"] * rng.uniform(1.2, 2.0, len(frame))
    out["iint_max6h_1"] = out["iint_max3h_1"] * rng.uniform(1.1, 1.5, len(frame))
    out["iint_max3h_max3d"] = out["iint_max3h_1"] * rng.uniform(1.0, 1.4, len(frame))
    out["iint_max6h_max3d"] = out["iint_max6h_1"] * rng.uniform(1.0, 1.4, len(frame))
    out["iint_wet_hours_1"] = rng.uniform(1, 24, len(frame))
    return out.astype({c: np.float32 for c in IINT})


@pytest.fixture(scope="module")
def study():
    return tiny_study()


@pytest.fixture(scope="module")
def world():
    samples, universe = synthetic_development(n_pos_train=110, n_pos_validation=50, n_per_region=2500)
    samples, universe = add_intensity(samples, 1), add_intensity(universe, 2)
    column_map = {**COLUMN_MAP, **{c: "iint" for c in IINT}}
    dev = hd.build_development(samples, universe, column_map)
    return dev, cv.make_layout(dev, FOLDS)


# ------------------------------------------------------------------------------------------ configuration

def test_the_iint_group_spec_names_the_files_the_feature_build_writes(study):
    spec = study["extra_groups"]["iint"]
    assert spec["suffix"] == ii.GROUP and spec["columns_file"] == B.columns_name(ii.GROUP)
    assert spec["manifest_file"] == B.manifest_name(ii.GROUP)
    assert spec["subdir"] == "imerg" and B.table_name("train_samples", ii.GROUP) == "train_samples_iint.parquet"
    assert v4.iint_dir(study, PROJECT_ROOT / "x").as_posix().endswith("x/imerg")


def test_the_lag_selects_the_table_group_and_nothing_else(study):
    zero, one = v4.iint_spec(study, 0), v4.iint_spec(study, 1)
    assert zero == study["extra_groups"]["iint"]
    assert one == {"subdir": "imerg", "suffix": "iint_lag1", "columns_file": "iint_lag1_columns.json",
                   "manifest_file": "iint_lag1_manifest.json"}
    assert v4.extra_groups(study, 1)["iint"] == one and v4.extra_groups(study, 1).keys() == v4.extra_groups(study, 0).keys()
    with pytest.raises(ValueError, match="lag_days"):
        ii.group_name(2)


def test_v4_int_is_the_v3_inputs_plus_the_six_non_decreasing_intensity_features_and_nothing_else(study):
    candidates = v4.make_candidates(study, COLUMNS)
    c0, challenger = candidates["C0"], candidates["v4_int"]
    assert c0.columns == COLUMNS and c0.constraints == hm.configured_constraints(COLUMNS, study["base"])
    assert challenger.columns == COLUMNS + IINT                           # the config names exactly the iint group's columns
    assert challenger.constraints == c0.constraints + [1] * 6
    assert not (c0.drop_implausible or challenger.drop_implausible)
    assert list(candidates) == ["C0", "v4_int"] and study["reference"] == "C0" and study["challenger"] == "v4_int"
    assert study["candidates"]["v4_int"]["add_groups"] == [ii.GROUP]


def test_the_study_overrides_nothing_of_the_frozen_v3_configuration(study):
    assert set(study) == {"base_config", "output_dir", "seasons_dir", "report_stem", "reference", "challenger", "extra_groups",
                          "candidates", "reproduction_tolerance", "tie_seed", "preflight", "base"}
    assert set(study["candidates"]["v4_int"]) == {"description", "add_groups", "add_increasing"}
    assert study["base_config"] == "configs/hazard_v3.yaml"
    assert v4.extra_groups(study).keys() == {*study["base"]["extra_groups"], ii.GROUP}
    assert v4.groups_used(study) == [*v4.tr.extra_groups_used(study["base"]), ii.GROUP]
    assert study["base"]["model_dir"] == "model_v3_live" and v4.output_dir(study).name == "v4_int"
    assert v4.output_dir(study) != hm.configured_model_dir(study["base"])
    assert study["reproduction_tolerance"] <= 1e-12
    assert study["tie_seed"] == v4.TIE_SEED == 20261106 and study["preflight"]["straddle_tolerance"] == 0.01


def test_candidate_definitions_are_checked(study):
    broken = copy.deepcopy(study)
    broken["candidates"]["v4_int"]["add_increasing"] = ["rain_acc_1"]
    with pytest.raises(ValueError, match="already an input"):
        v4.make_candidates(broken, COLUMNS)
    broken = copy.deepcopy(study)
    broken["candidates"]["v4_int"]["add_increasing"] = ["iint_max1h_1", "iint_max1h_1"]
    with pytest.raises(ValueError, match="more than once"):
        v4.make_candidates(broken, COLUMNS)
    broken = copy.deepcopy(study)
    broken["reference"] = "C9"
    with pytest.raises(ValueError, match="reference"):
        v4.make_candidates(broken, COLUMNS)
    with pytest.raises(ValueError, match="not columns of the groups"):
        v4.make_candidates(study, COLUMNS, {**{c: "iint" for c in IINT[:-1]}, IINT[-1]: "irain"})
    assert v4.make_candidates(study, COLUMNS, {c: "iint" for c in IINT})["v4_int"].columns == COLUMNS + IINT


# --------------------------------------------------------------------------------------- stage 1 (development)

def difference(lo: float, hi: float) -> dict:
    return {"point_difference": (lo + hi) / 2, "ci_lo": lo, "ci_hi": hi, "level": 0.95, "fa_a": 0.2, "fa_b": 0.2}


@pytest.mark.parametrize("lo, hi, passed", [
    (-0.02, -0.005, True),        # the interval lies below 0: v4-int has the lower false-alarm share, it is favoured
    (-0.01, 0.02, True),          # the interval includes 0
    (-1e-12, 0.03, True),
    (0.0, 0.03, True),            # the boundary: a lower bound of exactly 0 is still "includes 0"
    (1e-9, 0.03, False),          # v4-int is significantly worse (its false-alarm share is higher)
    (0.004, 0.02, False)])
def test_stage_one_passes_when_the_lower_bound_of_v4_minus_v3_is_not_above_zero(lo, hi, passed):
    record = v4.stage_one(difference(lo, hi))
    assert record["passed"] is passed
    assert record["ci"] == [lo, hi] and record["difference"] == pytest.approx((lo + hi) / 2)
    assert "lower bound <= 0" in record["rule"] and "v4_int - C0" in record["rule"]


def degraded(frame: pd.DataFrame, seed: int = 0) -> pd.DataFrame:
    """The same rows with scores that no longer rank the positives: a much higher FA@90."""
    out = frame.copy()
    out["score"] = np.random.default_rng(seed).random(len(out))
    return out


def test_the_stage_one_sign_follows_fa_at_90_of_v4_int_minus_v3(world, study):
    dev, layout = world
    good = ch.oof_frame(layout, v4.cv.run_cv(dev, layout, COLUMNS, hm.configured_constraints(COLUMNS, study["base"]),
                                             SELECTED["hp"], SELECTED["neg_mix"], study["base"], "C0").oof)
    worse = v4.compare({"C0": good, "v4_int": degraded(good)}, study)
    assert worse["difference"]["point_difference"] > 0 and worse["difference"]["ci_lo"] > 0
    assert v4.stage_one(worse["difference"])["passed"] is False
    better = v4.compare({"C0": degraded(good), "v4_int": good}, study)
    assert better["difference"]["point_difference"] < 0 and better["difference"]["ci_hi"] < 0
    assert v4.stage_one(better["difference"])["passed"] is True
    same = v4.compare({"C0": good, "v4_int": good}, study)
    assert same["difference"]["point_difference"] == 0 and v4.stage_one(same["difference"])["passed"] is True
    assert set(same["metrics"]) == {"C0", "v4_int"} and "pr_auc" in same["metrics"]["C0"]


def test_the_reference_must_reproduce_the_frozen_fa_at_90_to_1e_12_and_its_tree_count():
    result = cv.CVResult("C0", COLUMNS, [], {}, "m", 315, [], None, {v4.HEADLINE: 0.19554142779163688}, [], 0.0)
    frozen = {"pooled": {v4.HEADLINE: 0.19554142779163688}, "n_trees": 315}
    assert v4.check_reproduction(result, frozen, 1e-12)["abs_difference"] == 0.0
    near = {**frozen, "pooled": {v4.HEADLINE: 0.19554142779163688 + 5e-13}}
    assert v4.check_reproduction(result, near, 1e-12)["abs_difference"] < 1e-12
    for broken in ({**frozen, "pooled": {v4.HEADLINE: 0.19554142779163688 + 1e-9}}, {**frozen, "n_trees": 314}):
        with pytest.raises(ch.ReproductionError):
            v4.check_reproduction(result, broken, 1e-12)


# ------------------------------------------------------------------------------------------ the decision

def scores(tolerant, exact) -> dict:
    """held-out scores with (v3_ranked, v4-int) independent-slide detections per level: {level: (v3, candidate)}."""
    out = {}
    for name, levels in (("tolerant", tolerant), ("cell_exact", exact)):
        out[name] = {"v3": {k: {"group_hits": v3, "groups": 87} for k, (v3, _) in levels.items()},
                     "candidate": {k: {"group_hits": c, "groups": 87} for k, (_, c) in levels.items()}}
    return out


PASSED = {"passed": True}
TIE = {2: (60, 60), 3: (40, 40), 1: (70, 70)}


def test_adoption_needs_no_loss_in_all_four_comparisons_and_a_gain_in_one():
    gain = scores({**TIE, 2: (60, 61)}, TIE)
    decision = v4.decide(PASSED, gain)
    assert decision["adopt"] is True and decision["stage"] == 2 and decision["failed"] == []
    assert [c["higher"] for c in decision["conditions"]].count(True) == 1 and len(decision["conditions"]) == 4
    assert {(c["tolerance"], c["level"]) for c in decision["conditions"]} == {
        (t, lv) for t in ("tolerant", "cell_exact") for lv in ("Warning+", "Emergency")}
    assert v4.decide(PASSED, scores(TIE, {**TIE, 3: (40, 45)}))["adopt"] is True


def test_all_ties_are_not_adopted_and_one_lost_slide_anywhere_is_not_adopted():
    tie = v4.decide(PASSED, scores(TIE, TIE))
    assert tie["adopt"] is False and tie["failed"] == ["no comparison is higher"]
    lost = v4.decide(PASSED, scores({**TIE, 2: (60, 70), 3: (40, 39)}, TIE))
    assert lost["adopt"] is False and lost["failed"] == ["tolerant: Emergency detection lower (39 against 40)"]
    lost_exact = v4.decide(PASSED, scores(TIE, {**TIE, 2: (60, 59), 3: (40, 50)}))
    assert lost_exact["adopt"] is False and lost_exact["failed"] == ["cell_exact: Warning+ detection lower (59 against 60)"]


def test_watch_plus_is_recorded_in_the_scores_but_does_not_decide():
    decision = v4.decide(PASSED, scores({**TIE, 2: (60, 61), 1: (70, 10)}, TIE))
    assert decision["adopt"] is True
    assert all(c["level"] != "Watch+" for c in decision["conditions"])


def test_a_failed_stage_one_is_final_and_needs_no_held_out_scores():
    decision = v4.decide({"passed": False, "difference": 0.01, "ci": [0.004, 0.02]})
    assert decision["adopt"] is False and decision["stage"] == 1 and decision["conditions"] == []
    assert "not evaluated on the held-out set" in decision["reason"]
    with pytest.raises(ValueError, match="held-out scores"):
        v4.decide(PASSED)


# --------------------------------------------------------------------------------------- burden matching

def ids(shape):
    """(cell ids, days) for an array of `shape`."""
    return np.arange(shape[0]) + 100, [date(2019, 6, 1) + timedelta(k) for k in range(shape[1])]


def test_burden_matching_gives_the_ranked_levels_the_realised_shares_of_v3_in_the_season():
    scored = np.ones((4, 5), dtype=bool)
    scored[3, :] = False
    v3 = np.zeros((4, 5), dtype=np.int8)
    v3[0, 0], v3[0, 1], v3[1, 2] = 3, 2, 1                 # 15 scored cell-days: 3/15 Watch+, 2/15 Warning+, 1/15 Emergency
    risk = np.linspace(0.0, 1.0, 20).reshape(4, 5)
    risk[3, :] = 0.99                                       # unscored cells never alert, however high their risk
    levels, info = v4.match_burden(risk, risk * 2, scored, v3, *ids(scored.shape))
    assert info["target"] == pytest.approx([3 / 15, 2 / 15, 1 / 15])
    assert info["realised"] == pytest.approx(info["target"]) and levels.dtype == np.int8
    assert (levels[3] == 0).all()
    assert levels[2, 4] == 3 and levels[2, 3] == 2 and levels[2, 2] == 1 and levels[0, 0] == 0   # ranked by its own risk


def test_ties_in_the_calibrated_risk_are_broken_by_the_raw_score_and_the_tie_mass_is_reported():
    scored = np.ones((2, 5), dtype=bool)
    v3 = np.zeros((2, 5), dtype=np.int8)
    v3[0, :4], v3[1, 0] = 1, 1                                          # Watch+ on 5 of 10 cell-days
    v3[0, :2] = 2                                                       # Warning+ on 2
    v3[0, 0] = 3                                                        # Emergency on 1
    risk = np.full((2, 5), 0.5)
    risk[1, 1:] = 0.1                                                   # the isotonic step: 6 cell-days tie at 0.5
    raw = np.arange(10, dtype=float).reshape(2, 5)
    levels, info = v4.match_burden(risk, raw, scored, v3, *ids(scored.shape))
    # the six cell-days at risk 0.5 are ordered by raw, highest first: (1, 0), (0, 4), (0, 3), (0, 2), (0, 1), (0, 0)
    assert levels[1, 0] == 3 and levels[0, 4] == 2 and levels[0, 3] == 1 and levels[0, 2] == 1 and levels[0, 1] == 1
    assert levels[0, 0] == 0 and (levels[1, 1:] == 0).all()
    cut = info["cuts"][1]
    assert cut["cell_days_taken"] == 5 and cut["risk_tied_cell_days"] == 6 and cut["tied_cell_days"] == 1 and cut["tied_taken"] == 1
    assert info["cuts"][3]["risk_tied_cell_days"] == 6 and info["cuts"][3]["cut_raw"] == 5.0


def test_cell_days_tied_in_both_risk_and_raw_are_reported_as_one_tie_mass():
    scored = np.ones((1, 6), dtype=bool)
    v3 = np.array([[3, 2, 1, 0, 0, 0]], dtype=np.int8)
    levels, info = v4.match_burden(np.full((1, 6), 0.3), np.full((1, 6), 7.0), scored, v3, *ids((1, 6)))
    assert (levels > 0).sum() == 3 and info["cuts"][1]["tied_cell_days"] == 6 and info["cuts"][1]["tied_taken"] == 3
    assert info["cuts"][1]["straddle"] == 3 and info["cuts"][2]["straddle"] == 4 and info["cuts"][3]["straddle"] == 5
    assert info["realised"] == info["target"]


def test_the_tie_key_depends_on_the_cell_and_the_day_only_and_is_pinned():
    a = v4.tie_keys([1, 2, 3], [10, 10, 10])
    assert a.dtype == np.uint64 and len(set(a.tolist())) == 3
    assert (v4.tie_keys([3, 1, 2], [10, 10, 10]) == a[[2, 0, 1]]).all()               # not the position in the array
    assert v4.tie_keys([1], [11])[0] != a[0] and v4.tie_keys([1], [10], seed=1)[0] != a[0]
    assert (v4.tie_keys([1, 2, 3], [10, 10, 10]) == a).all()                           # a second run is the same
    assert int(v4.tie_keys([1], [1])[0]) == 11860267419498390199                       # pinned: the same on every platform
    assert int(v4.tie_keys([123456789], [739000])[0]) == 3510536484798804842


def test_cell_days_tied_on_risk_and_raw_are_ordered_by_the_seeded_key_not_by_array_position():
    rng = np.random.default_rng(3)
    scored = np.ones((8, 6), dtype=bool)
    risk, raw = np.full((8, 6), 0.4), np.full((8, 6), 2.0)
    risk[:2] = 0.9                                                        # a clear top, everything else tied on both
    v3 = np.zeros((8, 6), dtype=np.int8)
    v3.ravel()[:20], v3.ravel()[:8], v3.ravel()[:3] = 1, 2, 3
    cells, days = ids(scored.shape)
    base, info = v4.match_burden(risk, raw, scored, v3, cells, days)
    assert (base[:2] == 3).sum() + (base[:2] == 2).sum() + (base[:2] == 1).sum() == 12      # the top rows come first
    assert 0 < (base[2:] > 0).sum() < base[2:].size
    again, _ = v4.match_burden(risk, raw, scored, v3, cells, days)
    assert np.array_equal(again, base)                                                       # two runs, identical levels
    perm = rng.permutation(8)
    shuffled, _ = v4.match_burden(risk[perm], raw[perm], scored[perm], v3[perm], cells[perm], days)
    assert np.array_equal(shuffled, base[perm])                                              # the same cell-days are taken
    columns = rng.permutation(6)
    moved, _ = v4.match_burden(risk[:, columns], raw[:, columns], scored[:, columns], v3[:, columns], cells,
                               [days[c] for c in columns])
    assert np.array_equal(moved, base[:, columns])
    other, _ = v4.match_burden(risk, raw, scored, v3, cells, days, seed=1)
    assert not np.array_equal(other, base) and (other > 0).sum() == (base > 0).sum()        # the seed decides, the burden is kept
    assert info["cuts"][1]["tied_cell_days"] == 36 and info["cuts"][1]["straddle"] > 0


def test_a_realised_share_off_its_target_is_an_error_before_any_outcome():
    scored = np.ones((1, 4), dtype=bool)
    with pytest.raises(v4.BurdenMatchError, match="differ from the target"):
        v4.match_burden(np.arange(4.0).reshape(1, 4), np.zeros((1, 4)), scored, np.array([[1, 0, 0, 0]], dtype=np.int8),
                        *ids((1, 4)), tolerance=-1.0)
    with pytest.raises(ValueError, match="finite"):
        v4.match_burden(np.array([[np.nan, 1.0]]), np.zeros((1, 2)), np.ones((1, 2), dtype=bool), np.zeros((1, 2), dtype=np.int8),
                        *ids((1, 2)))
    with pytest.raises(ValueError, match="share one shape"):
        v4.match_burden(np.zeros((1, 2)), np.zeros((1, 3)), np.ones((1, 2), dtype=bool), np.zeros((1, 2), dtype=np.int8),
                        *ids((1, 2)))
    with pytest.raises(ValueError, match="do not match"):
        v4.match_burden(np.zeros((2, 2)), np.zeros((2, 2)), np.ones((2, 2), dtype=bool), np.zeros((2, 2), dtype=np.int8),
                        np.arange(3), ids((2, 2))[1])


# -------------------------------------------------------------------------------------------- the assembly

A_CELL = int(grid.latlon_to_cell(30.025, 78.025))
REF = np.array([A_CELL, A_CELL + 1, A_CELL + 20, A_CELL + 40, A_CELL + 41, A_CELL + 60])
WARM, DAYS = 2, 6


def levels_from(order_score: np.ndarray, scored: np.ndarray, counts) -> np.ndarray:
    """Levels with exactly `counts` (Watch+, Warning+, Emergency) scored cell-days, highest `order_score` first."""
    flat = np.zeros(scored.size, dtype=np.int8)
    rows = np.flatnonzero(scored.ravel())
    order = rows[np.argsort(-order_score.ravel()[rows], kind="stable")]
    for level, k in zip((1, 2, 3), counts):
        flat[order[:k]] = level
    return flat.reshape(scored.shape)


def make_input(year=2019, seed=0, constant_v4_risk=False, drop=None, tied=False) -> v4.SeasonInput:
    rng = np.random.default_rng(seed + year)
    n, total = len(REF), WARM + DAYS
    days = [date(year, 5, 30) + timedelta(k) for k in range(total)]
    scored = np.ones((n, total), dtype=bool)
    scored[-1, 0] = False                                                # a cell-day without a score, in the warm-up
    scored[0, WARM] = False                                              # and one in the season
    v3_risk, v4_risk = rng.random((n, total)), rng.random((n, total))
    v3_raw, v4_raw = v3_risk + 1e-3 * rng.random((n, total)), v4_risk + 1e-3 * rng.random((n, total))
    if constant_v4_risk:
        v4_risk = np.full((n, total), 0.5)
        v4_raw = np.arange(n * total, dtype=float).reshape(n, total)
    if tied:                                                             # one score for every cell-day, of v3 and v4-int alike
        v3_risk, v4_risk = np.full((n, total), 0.5), np.full((n, total), 0.5)
        v3_raw, v4_raw = np.full((n, total), 1.0), np.full((n, total), 1.0)
    rules_levels = levels_from(rng.random((n, DAYS)), scored[:, WARM:], (14, 5, 2))
    nan = np.where(scored, 1.0, np.nan)
    panel = H.new_panel(pd.DataFrame({"cell_id": REF, "region": "himalaya", "in_universe": True}), days, 3)
    panel.values["risk"][:, :] = v4_risk * nan
    panel.values["raw"][:, :] = v4_raw * nan
    part = vr.Part(cell_ids=REF.copy(), in_universe=np.ones(n, dtype=bool), days=days[WARM:], scored=scored[:, WARM:].copy(),
                   acc_3=np.zeros((n, DAYS)), static_score=np.zeros(n), v3=rules_levels,
                   events=pd.DataFrame({"cell_id": [], "date": []}))
    inp = v4.SeasonInput(year, part, WARM, days, scored, v3_risk * nan, v3_raw * nan, panel, {c: 0.0 for c in IINT})
    if drop:
        drop(inp)
    return inp


EVENTS = pd.DataFrame({"cell_id": [A_CELL, A_CELL + 1, A_CELL + 20, A_CELL + 40],
                       "date": pd.to_datetime(["2019-06-02", "2019-06-02", "2020-06-03", "2019-01-01"]),
                       "source": ["reported", "catalog_sparse", "reported", "reported"]})


def assembled(years=(2019, 2020), **kwargs) -> v4.Assembly:
    return v4.assemble([make_input(y, **kwargs) for y in years], REF, EVENTS)


def test_the_assembly_gives_v4_int_and_v3_ranked_the_burden_of_v3_with_the_rules():
    assembly = assembled()
    pooled = assembly.info["pooled"]["alert_cell_days"]
    assert pooled["v3_ranked"] == pooled["v4_int"] == pooled["v3_rules"] == [28, 10, 4]       # 2 seasons x (14, 5, 2)
    for name in ("ranked", "rules"):
        pool = assembly.pools[name]
        assert pool.candidate.shape == pool.v3.shape == (len(REF), 2 * DAYS) and pool.days[0] == date(2019, 6, 1)
    ranked, rules = assembly.pools["ranked"], assembly.pools["rules"]
    assert np.array_equal(ranked.candidate, rules.candidate) and not np.array_equal(ranked.v3, rules.v3)
    season = assembly.info["seasons"]["2019"]
    assert season["v3_realised_shares"] == season["v3_ranked"]["target"] == season["v4_int"]["target"]
    assert season["scored_cell_days"] == len(REF) * DAYS - 1 and season["iint_nan_share"] == {c: 0.0 for c in IINT}
    assert set(season["v4_int"]["cuts"]) == {1, 2, 3}


def test_the_assembly_ranks_by_risk_then_raw_for_both_v4_int_and_v3_ranked():
    inp = make_input(constant_v4_risk=True)
    assembly = v4.assemble([inp], REF, EVENTS)
    levels = assembly.pools["ranked"].candidate
    raw = np.asarray(inp.v4["raw"])[:, WARM:]
    taken = np.argsort(-np.where(inp.part.scored, raw, -np.inf).ravel(), kind="stable")[:2]
    assert (levels.ravel()[taken] == [3, 3]).all() or levels.ravel()[taken[0]] == 3     # the highest raw scores hold Emergency
    ranked_v3 = assembly.pools["ranked"].v3
    risk = inp.v3_risk[:, WARM:]
    top = np.unravel_index(np.nanargmax(risk), risk.shape)
    assert ranked_v3[top] == 3                                                             # v3_ranked follows v3's own risk
    assert assembly.info["seasons"]["2019"]["v4_int"]["cuts"][1]["risk_tied_cell_days"] == int(inp.part.scored.sum())


def test_the_pooled_alert_comparison_counts_all_three_on_the_same_scored_cell_days():
    def hold(inp):
        inp.part.v3[0, 0] = 1                                            # a held level on the unscored cell-day (0, first day)

    assembly = v4.assemble([make_input(2019, drop=hold), make_input(2020)], REF, EVENTS)
    pooled = assembly.info["pooled"]
    assert pooled["alert_cell_days"]["v3_rules"][0] == 29 and pooled["alert_cell_days"]["v3_ranked"][0] == 28     # as W1 counts
    assert pooled["alert_cell_days_scored"] == {"v3_rules": [28, 10, 4], "v3_ranked": [28, 10, 4], "v4_int": [28, 10, 4]}
    study = {"preflight": expectations(assembly.info)}
    checks = v4.check_assembly(study, assembly.info, w1_of(assembly.info))
    assert all(c["passed"] for c in checks), [c for c in checks if not c["passed"]]


def test_full_ties_straddling_a_cut_are_checked_against_one_percent_of_the_alert_cell_days():
    study = {"preflight": {"straddle_tolerance": 0.01}}
    clean = v4.check_straddle(study, assembled().info)
    assert [c["passed"] for c in clean] == [True, True] and all(v["straddle"] == 0 for v in clean[0]["detail"].values())
    tied = v4.check_straddle(study, v4.assemble([make_input(2019, tied=True)], REF, EVENTS).info)
    assert tied[0]["passed"] is False and tied[0]["name"].startswith("season 2019 full ties straddling")
    numbers = tied[0]["detail"]["v4_int Warning+"]
    assert numbers["alert_cell_days"] == 5 and numbers["tied_cell_days"] == 35 and numbers["straddle"] == 30 and numbers["share"] == 6.0
    assert set(tied[0]["detail"]) == {f"{m} {lv}" for m in ("v4_int", "v3_ranked") for lv in ("Warning+", "Emergency")}

    def info_with(taken, straddle):
        cut = {"cell_days_taken": taken, "straddle": straddle, "tied_cell_days": straddle + 1, "tied_taken": 1}
        return {"seasons": {"2019": {name: {"cuts": {2: cut, 3: cut}} for name in ("v4_int", "v3_ranked")}}}

    assert v4.check_straddle(study, info_with(100, 1))[0]["passed"] is True            # exactly 1%
    assert v4.check_straddle(study, info_with(100, 2))[0]["passed"] is False
    assert v4.check_straddle(study, info_with(0, 0))[0]["passed"] is True


def test_the_assembly_checks_the_cells_days_scored_cell_days_and_finite_scores():
    def other_cells(inp):
        inp.v4.cells["cell_id"] = inp.v4.cells["cell_id"].to_numpy()[::-1]

    def other_days(inp):
        inp.v4.days[-1] = date(2030, 1, 1)

    def other_scored(inp):
        inp.v4.values["risk"][1, 4] = np.nan

    def not_finite(inp):
        inp.v3_raw[1, 4] = np.inf

    for drop, message in ((other_cells, "cells"), (other_days, "days"), (other_scored, "scored"), (not_finite, "finite")):
        with pytest.raises(ValueError, match=message):
            v4.assemble([make_input(drop=drop)], REF, EVENTS)
    with pytest.raises(ValueError, match="cells"):
        v4.assemble([make_input()], REF[::-1], EVENTS)
    with pytest.raises(ValueError, match="no season"):
        v4.assemble([], REF, EVENTS)


def test_the_assembly_never_joins_an_event_with_a_level(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("an outcome was computed")

    monkeypatch.setattr(op, "score_heldout", forbidden)
    monkeypatch.setattr(op, "match", forbidden)
    monkeypatch.setattr(op, "grouped_pod", forbidden)
    monkeypatch.setattr(matching, "match", forbidden)
    monkeypatch.setattr(vscores, "grouped_pod", forbidden)
    monkeypatch.setattr(v4.vh, "match", forbidden, raising=False)
    info = assembled().info
    assert info["events"] == {"events": 3, "outside_panel_days": 1, "distinct_slides": 2,
                              "by_source": {"catalog_sparse": 1, "reported": 2}}


def test_the_events_digest_is_order_free_and_changes_with_any_row():
    shuffled = EVENTS.sample(frac=1.0, random_state=1).reset_index(drop=True)
    assert v4.events_digest(shuffled) == v4.events_digest(EVENTS)
    changed = EVENTS.assign(source=["reported", "reported", "reported", "reported"])
    assert v4.events_digest(changed) != v4.events_digest(EVENTS)
    assert assembled().info["events_sha256"] == v4.events_digest(EVENTS.iloc[:3])      # the event off the panel days is not frozen


def test_the_nan_share_of_each_intensity_input_is_counted_on_scored_cell_days_only():
    values = np.zeros((2, 3, 6), dtype=np.float32)
    values[0, 0, 1] = np.nan                                  # scored: counts
    values[1, 2, 1] = np.nan                                  # not scored: does not
    scored = np.array([[True, True, False], [True, True, False]])
    share = v4.iint_nan_share(values, scored)
    assert share["iint_max3h_1"] == pytest.approx(1 / 4) and share["iint_max1h_1"] == 0.0 and set(share) == set(IINT)


# ---------------------------------------------------------------------------- the single held-out look

def pool() -> op.HeldOut:
    days = [date(2019, 7, 1) + timedelta(days=k) for k in range(5)]
    cells = np.array([A_CELL, A_CELL + 1, A_CELL + 20])
    v3 = np.zeros((3, 5), dtype=np.int8)
    v3[0, 1], v3[1, 1], v3[2, 3], v3[0, 3] = 2, 2, 3, 1
    candidate = np.zeros((3, 5), dtype=np.int8)
    candidate[0, 1], candidate[2, 3] = 2, 3
    events = pd.DataFrame({"cell_id": [A_CELL, A_CELL + 1, A_CELL + 20],
                           "date": pd.to_datetime(["2019-07-02", "2019-07-02", "2019-07-04"])})
    return op.HeldOut(cells, days, np.ones((3, 5), dtype=bool), v3, candidate, events, 1)


def pools(info=None):
    return {"ranked": pool(), "rules": pool()}, info or {"seasons": {}}


def test_the_look_decides_on_v3_ranked_and_reports_v3_with_the_rules_beside_it(tmp_path):
    result = v4.evaluate_once(tmp_path / "heldout.json", tmp_path / "report.json", pools, BOOT, None, {"stage_one": PASSED})
    deciding, beside = result["scores"], result["scores_v3_rules"]
    assert deciding["slides"] == beside["slides"] == 2 and deciding["events"] == 3
    for tolerance in ("tolerant", "cell_exact"):
        assert deciding[tolerance]["v3"][2]["group_hits"] == 2 and deciding[tolerance]["candidate"][2]["group_hits"] == 2
    assert result["decision"]["adopt"] is False and result["decision"]["failed"] == ["no comparison is higher"]
    assert "v3_ranked" in result["labels"]["scores"] and "section 11" in result["labels"]["scores_v3_rules"]
    stored = json.loads((tmp_path / "heldout.json").read_text(encoding="utf-8"))
    assert stored["decision"]["adopt"] is False and stored["seasons"] == {} and stored["stage_one"] == PASSED


def test_the_decision_uses_the_ranked_pool_and_not_the_rules_pool(tmp_path):
    better = pool()
    better.v3 = np.zeros_like(better.v3)                       # the ranked v3 detects nothing: v4-int is higher
    result = v4.evaluate_once(tmp_path / "heldout.json", tmp_path / "report.json",
                              lambda: ({"ranked": better, "rules": pool()}, {}), BOOT, None, {"stage_one": PASSED})
    assert result["decision"]["adopt"] is True
    assert result["scores_v3_rules"]["tolerant"]["v3"][2]["group_hits"] == 2          # beside it, v3 with rules ties


def test_the_second_look_is_refused_before_anything_is_loaded(tmp_path):
    built = []

    def build():
        built.append(1)
        return pools()

    path, report = tmp_path / "heldout.json", tmp_path / "report.json"
    v4.evaluate_once(path, report, build, BOOT, None, {"stage_one": PASSED})
    stored = path.read_text(encoding="utf-8")
    with pytest.raises(FileExistsError, match="heldout.json"):
        v4.evaluate_once(path, report, build, BOOT, None, {"stage_one": PASSED})
    assert built == [1] and path.read_text(encoding="utf-8") == stored


def test_the_started_marker_is_written_after_v3_reproduced_and_before_any_candidate_outcome(tmp_path, monkeypatch):
    path, marker = tmp_path / "heldout.json", tmp_path / "heldout.started"
    built = pools({"events_sha256": "e"})
    seen = []
    real = op.match

    def spy(levels, *args, **kwargs):
        seen.append(("candidate" if levels is built[0]["rules"].candidate else "v3" if levels is built[0]["rules"].v3 else "ranked",
                     marker.exists()))
        return real(levels, *args, **kwargs)

    monkeypatch.setattr(op, "match", spy)
    v4.evaluate_once(path, tmp_path / "report.json", lambda: built, BOOT, None, {"stage_one": PASSED, "lag_days": 1})
    assert seen[0] == ("v3", False) and ("candidate", True) in seen and all(flag for kind, flag in seen if kind == "candidate")
    record = json.loads(marker.read_text(encoding="utf-8"))
    assert record["events_sha256"] == "e" and record["lag_days"] == 1 and record["stage_one"] == PASSED
    assert record["started_utc"].endswith("Z")


def test_a_look_that_died_after_the_marker_is_not_rerun_and_needs_a_human(tmp_path, monkeypatch):
    path, marker, report = tmp_path / "heldout.json", tmp_path / "heldout.started", tmp_path / "report.json"
    built = pools()
    real = op.match

    def dies(levels, *args, **kwargs):
        if levels is built[0]["rules"].candidate:
            raise RuntimeError("out of memory")
        return real(levels, *args, **kwargs)

    monkeypatch.setattr(op, "match", dies)
    with pytest.raises(RuntimeError, match="out of memory"):
        v4.evaluate_once(path, report, lambda: built, BOOT, None, {"stage_one": PASSED})
    assert marker.is_file() and not path.exists()
    monkeypatch.setattr(op, "match", real)
    loaded = []
    with pytest.raises(v4.LookStartedError, match="started and not completed.*human decision"):
        v4.evaluate_once(path, report, lambda: loaded.append(1) or built, BOOT, None, {"stage_one": PASSED})
    assert loaded == [] and not path.exists()


def test_no_marker_is_left_by_a_look_that_failed_the_published_check(tmp_path):
    wrong = {"tolerant": {2: {"hits": 9, "alert_cell_days": 3, "group_hits": 2, "groups": 2}}}
    with pytest.raises(ValueError, match="published"):
        v4.evaluate_once(tmp_path / "heldout.json", tmp_path / "report.json", pools, BOOT, wrong, {"stage_one": PASSED})
    assert not (tmp_path / "heldout.started").exists()


def test_a_committed_report_alone_also_blocks_the_look(tmp_path):
    report = tmp_path / "phase7_rain_intensity.json"
    report.write_text("{}", encoding="utf-8")
    built = []
    with pytest.raises(FileExistsError, match="phase7_rain_intensity.json"):
        v4.evaluate_once(tmp_path / "heldout.json", report, lambda: built.append(1), BOOT, None, {})
    assert built == [] and not (tmp_path / "heldout.json").exists()


def test_a_failed_look_leaves_no_result_and_may_be_repeated(tmp_path):
    path, report = tmp_path / "heldout.json", tmp_path / "report.json"
    wrong = {"tolerant": {2: {"hits": 9, "alert_cell_days": 3, "group_hits": 2, "groups": 2}}}
    with pytest.raises(ValueError, match="published"):
        v4.evaluate_once(path, report, pools, BOOT, wrong, {"stage_one": PASSED})
    assert not path.exists()
    assert v4.evaluate_once(path, report, pools, BOOT, None, {"stage_one": PASSED})["scores"]["slides"] == 2


def test_the_look_is_not_taken_when_the_events_differ_from_the_frozen_digest(tmp_path):
    path = tmp_path / "heldout.json"
    with pytest.raises(ValueError, match="events_sha256"):
        v4.evaluate_once(path, tmp_path / "report.json", lambda: pools({"events_sha256": "b"}), BOOT, None,
                         {"stage_one": PASSED}, {"events_sha256": "a"})
    assert not path.exists()
    v4.evaluate_once(path, tmp_path / "report.json", lambda: pools({"events_sha256": "a"}), BOOT, None, {"stage_one": PASSED},
                     {"events_sha256": "a"})
    assert path.is_file()


# ---------------------------------------------------- the season panels scored with the iint group

YEAR = 2026
SEASON_CELLS = tiny_cells().iloc[::-1].reset_index(drop=True)
HEAVY = [date(YEAR, 8, 10), date(YEAR, 8, 11), date(YEAR, 8, 12), date(YEAR, 9, 20)]
WAYANAD = int(tiny_cells().query("region == 'western_ghats'")["cell_id"].iloc[0])


class IintModel:
    """Stand-in for the v4-int model: the scoring stub reads the intensity columns the frame must carry."""
    members = [None, None, None]
    columns = COLUMNS + IINT


def stub_score_rows(model, rows):
    missing = [c for c in IINT if c not in rows.columns]
    assert not missing, f"the frame given to the model lacks {missing}"
    burst = rows["iint_max3h_1"].to_numpy(dtype=np.float64)
    risk = np.clip(burst / 100.0, 0.0, 1.0)
    out = {name: np.full(len(rows), np.nan) for name in H.FLOAT_FIELDS + H.RISK_FIELDS}
    out.update({name: np.zeros(len(rows), dtype=np.uint8) for name in H.COUNT_FIELDS})
    out["top3_terrain"] = np.zeros(len(rows), dtype=bool)
    out.update(raw=burst, risk=risk, new_lo=risk, new_hi=risk, old_lo=risk, old_hi=risk, median_risk=risk,
               **{f"acc_{w}": rows[f"irain_acc_{w}"].to_numpy(dtype=np.float64) for w in H.RAIN_WINDOWS})
    return out


def write_season_iint(directory, year=YEAR, burst_day=HEAVY[2], tamper=False, cells=SEASON_CELLS, lag=0):
    """The frozen season table of the iint group at `lag` (cell-major cells x days, as features.imerg_intensity writes it)."""
    days = bt.day_range(date(year, 6, 1) - timedelta(days=bt.WARMUP_DAYS), date(year, 12, 31))
    frame = ii.panel_frame(cells["cell_id"].to_numpy(dtype=np.int64), days)
    hot = ((frame["cell_id"] == WAYANAD) & (frame["date"] == pd.Timestamp(burst_day))).to_numpy()
    for name in IINT:
        frame[name] = np.where(hot, 80.0, 1.0).astype(np.float32)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ii.season_name(year, lag)
    frame.to_parquet(path, index=False)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    (directory / B.manifest_name(ii.group_name(lag))).write_text(
        json.dumps({"lag_days": lag, "files": {path.name: {"sha256": digest, "n_rows": len(frame)}}}), encoding="utf-8")
    if tamper:
        frame[IINT[0]] = np.float32(5.0)
        frame.to_parquet(path, index=False)
    return path, days


@pytest.fixture
def toy(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    late = FakeStore(span(date(YEAR, 1, 1), date(YEAR + 1, 1, 5)), HEAVY)
    stores = bt.Stores(cfg, ImergSource("late", late, latency_h=14.5, window_days=130),
                       ImergSource("early", FakeStore([]), latency_h=4.5, window_days=130, mapping=IdentityMap()),
                       tiny_clim(SEASON_CELLS), lambda day, ctx: bt.TailResult(None, PERSIST, "toy"))
    monkeypatch.setattr(live_run, "load_run_config", lambda: cfg)
    monkeypatch.setattr(bt, "load_set", lambda name, start=None, end=None, cfg=None: bt.BacktestSet(
        name, start, end, SEASON_CELLS, None, "season"))
    monkeypatch.setattr(bt, "build_stores", lambda cells, cfg=None, root=None: stores)
    monkeypatch.setattr(H, "score_rows", stub_score_rows)


@pytest.mark.parametrize("lag", [0, 1])
def test_a_season_is_scored_with_the_training_style_features_joined_to_its_iint_table(toy, tmp_path, study, lag):
    features = tmp_path / "features" / "imerg"
    _, days = write_season_iint(features, lag=lag)
    path = v4.score_season(IintModel(), "ab" * 32, study, YEAR, tmp_path / "features", tmp_path / "panels", say=lambda m: None,
                           lag_days=lag)
    assert path == tmp_path / "panels" / f"season_{YEAR}_v4_int.npz"
    panel = H.load_panel(path)
    assert panel.cells["cell_id"].tolist() == SEASON_CELLS["cell_id"].tolist() and panel.days == days
    wayanad = SEASON_CELLS.index[SEASON_CELLS["cell_id"] == WAYANAD][0]
    assert panel["risk"][wayanad, days.index(HEAVY[2])] == pytest.approx(0.8)         # the iint value reached the model
    assert panel["risk"][wayanad, days.index(date(YEAR, 7, 1))] == pytest.approx(0.01)
    sidecar = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    assert sidecar["features"] == "training_style+iint" and sidecar["model_card_sha256"] == "ab" * 32 and sidecar["lag_days"] == lag
    assert sidecar["n_cells"] == len(SEASON_CELLS) and sidecar["first_day"] == days[0].isoformat()


def test_a_season_table_of_the_wrong_lag_is_not_used(toy, tmp_path, study):
    features = tmp_path / "features" / "imerg"
    write_season_iint(features, lag=1)
    with pytest.raises(FileNotFoundError, match="iint"):
        v4.score_season(IintModel(), "ab" * 32, study, YEAR, tmp_path / "features", tmp_path / "panels", say=lambda m: None, lag_days=0)
    _, days = write_season_iint(features, lag=0)
    manifest = features / "iint_manifest.json"
    manifest.write_text(manifest.read_text(encoding="utf-8").replace('"lag_days": 0', '"lag_days": 1'), encoding="utf-8")
    ids = SEASON_CELLS["cell_id"].to_numpy(dtype=np.int64)
    with pytest.raises(v4.IintTableError, match="lag"):
        v4.season_iint(study, features, YEAR, ids, days, 0)


def test_an_existing_season_panel_is_kept_unless_forced(toy, tmp_path, study):
    features = tmp_path / "features" / "imerg"
    write_season_iint(features)
    args = (IintModel(), "ab" * 32, study, YEAR, tmp_path / "features", tmp_path / "panels")
    path = v4.score_season(*args, say=lambda m: None)
    path.write_bytes(b"kept")
    assert v4.score_season(*args, say=lambda m: None).read_bytes() == b"kept"
    assert v4.score_season(*args, say=lambda m: None, force=True).read_bytes() != b"kept"


def test_the_iint_season_table_is_verified_against_its_manifest_cells_and_days(tmp_path, study):
    features = tmp_path / "imerg"
    _, days = write_season_iint(features)
    ids = SEASON_CELLS["cell_id"].to_numpy(dtype=np.int64)
    values = v4.season_iint(study, features, YEAR, ids, days)
    assert values.shape == (len(ids), len(days), 6) and values.dtype == np.float32
    with pytest.raises(v4.IintTableError, match="cells"):
        v4.season_iint(study, features, YEAR, ids[::-1], days)
    with pytest.raises(v4.IintTableError, match="days"):
        v4.season_iint(study, features, YEAR, ids, days[1:])
    write_season_iint(features, tamper=True)
    with pytest.raises(v4.IintTableError, match="checksum"):
        v4.season_iint(study, features, YEAR, ids, days)
    with pytest.raises(FileNotFoundError, match="iint"):
        v4.season_iint(study, tmp_path / "missing", YEAR, ids, days)


# ------------------------------------------------------------------------ the stages on a synthetic store

def write_iint_store(directory, tables: dict, lag: int = 0, seed: int = 7) -> None:
    sub = directory / "imerg"
    sub.mkdir(parents=True, exist_ok=True)
    group, files = ii.group_name(lag), {}
    for name, frame in tables.items():
        extra = add_intensity(frame, seed + len(name))[["cell_id", "date", *IINT]]
        path = sub / B.table_name(name, group)
        extra.to_parquet(path)
        files[path.name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "n_rows": len(extra)}
    (sub / B.columns_name(group)).write_text(json.dumps({c: ii.GROUP for c in IINT}), encoding="utf-8")
    (sub / B.manifest_name(group)).write_text(json.dumps({"lag_days": lag, "files": files}), encoding="utf-8")


def make_store(directory, lag=0):
    samples, universe = synthetic_development(n_pos_train=110, n_pos_validation=50, n_per_region=2500)
    directory = write_dev_store(directory, samples, universe, extras=False)
    tables = {n: pd.read_parquet(directory / f"{n}_features.parquet") for n in
              ("train_samples", "validation_samples", "universe_train", "universe_validation")}
    write_iint_store(directory, tables, lag)
    return directory


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    return make_store(tmp_path_factory.mktemp("features"))


@pytest.fixture(scope="module")
def frozen(world, study):
    """The 'frozen' v3 reference, taken from a first CV of C0 so that the refit reproduces it."""
    dev, layout = world
    reference = cv.run_cv(dev, layout, COLUMNS, hm.configured_constraints(COLUMNS, study["base"]), SELECTED["hp"],
                          SELECTED["neg_mix"], study["base"], "C0")
    return {**SELECTED, "pooled": {v4.HEADLINE: reference.pooled[v4.HEADLINE]}, "n_trees": reference.n_trees}


@pytest.fixture
def stage_env(isolated_data_root, monkeypatch, tmp_path, study, frozen):
    """The stages in an isolated data root: lag 0, a temporary committed-report path and the gap report 'present'."""
    monkeypatch.setattr(v4, "frozen_selection", lambda s: frozen)
    monkeypatch.setattr(v4, "report_path", lambda s: tmp_path / "reports" / "phase7_rain_intensity.json")
    monkeypatch.setattr(v4, "declared_lag", lambda: 0)
    return study


def force_stage_one(monkeypatch, passed: bool) -> None:
    monkeypatch.setattr(v4, "stage_one", lambda diff: {"passed": passed, "difference": diff["point_difference"],
                                                       "ci": [diff["ci_lo"], diff["ci_hi"]], "rule": "forced",
                                                       "verdict": "forced"})


def test_dev_reproduces_v3_runs_both_cvs_and_applies_stage_one(stage_env, store, monkeypatch):
    force_stage_one(monkeypatch, True)
    study = stage_env
    payload = v4.run_dev(study, store, say=lambda m: None)
    out = v4.output_dir(study)
    assert payload["reproduction"]["abs_difference"] <= 1e-12 and payload["lag_days"] == 0 and payload["intensity_group"] == "iint"
    assert payload["candidates"]["v4_int"]["columns"] == COLUMNS + IINT and payload["candidates"]["C0"]["columns"] == COLUMNS
    assert payload["candidates"]["v4_int"]["constraints"]["iint_max6h_max3d"] == 1
    assert payload["comparison"]["difference"]["n_boot"] == 40
    assert json.loads((out / v4.DEV_RESULTS).read_text(encoding="utf-8"))["stage_one"] == payload["stage_one"]
    assert (out / "oof" / "oof_C0.parquet").is_file() and (out / "oof" / "oof_v4_int.parquet").is_file()
    model = hm.HazardModel.load(out / v4.MODEL_SUBDIR / "v4_int")
    assert model.columns == COLUMNS + IINT and model.constraints[-6:] == [1] * 6
    assert model.card["candidate"] == "v4_int" and "W3" in model.card["protocol"]
    assert model.region_calibrator is not None and len(model.members) == 3
    assert model.card["monotone_assumptions"]["increasing"][-6:] == IINT
    assert model.card["monotone_assumptions"]["increasing"][:-6] == study["base"]["monotone"]["increasing"]
    assert model.card["monotone_assumptions"]["decreasing"] == study["base"]["monotone"]["decreasing"]
    assert model.card["intensity"] == {"group": "iint", "lag_days": 0, "inputs": IINT}


def test_dev_with_a_declared_lag_of_one_reads_the_lag_one_tables_and_records_the_lag(stage_env, tmp_path, monkeypatch):
    force_stage_one(monkeypatch, False)
    monkeypatch.setattr(v4, "declared_lag", lambda: 1)
    lagged = make_store(tmp_path / "lag1_features", lag=1)
    payload = v4.run_dev(stage_env, lagged, say=lambda m: None)
    assert payload["lag_days"] == 1 and payload["intensity_group"] == "iint_lag1"
    assert payload["candidates"]["v4_int"]["columns"] == COLUMNS + IINT
    monkeypatch.setattr(v4, "declared_lag", lambda: 0)
    with pytest.raises(ValueError, match="rerun `dev --force`"):
        v4.current_lag(payload)


def test_dev_refuses_without_the_gap_report_and_a_lag_zero_store_is_not_read_at_lag_one(stage_env, store, monkeypatch, tmp_path):
    monkeypatch.undo()  # this also drops the isolated data root, so the output directory is pinned to tmp again
    monkeypatch.setattr(v4, "output_dir", lambda s: tmp_path / "out")
    monkeypatch.setattr(v4, "gap_report_path", lambda: tmp_path / "missing_gap.json")
    with pytest.raises(FileNotFoundError, match="gap"):
        v4.declared_lag()
    monkeypatch.setattr(v4, "frozen_selection", lambda s: {})
    with pytest.raises(FileNotFoundError, match="gap"):
        v4.run_dev(stage_env, store, say=lambda m: None)
    monkeypatch.setattr(v4, "declared_lag", lambda: 1)
    with pytest.raises(FileNotFoundError, match="iint_lag1"):
        v4.run_dev(stage_env, store, say=lambda m: None)


def test_dev_fails_when_the_reference_does_not_reproduce_v3(stage_env, store, frozen, monkeypatch):
    monkeypatch.setattr(v4, "frozen_selection", lambda s: {**frozen, "pooled": {v4.HEADLINE: frozen["pooled"][v4.HEADLINE] + 1e-9}})
    with pytest.raises(ch.ReproductionError):
        v4.run_dev(stage_env, store, say=lambda m: None)
    assert not (v4.output_dir(stage_env) / v4.DEV_RESULTS).exists()


def test_dev_does_not_overwrite_earlier_results_unless_forced_and_never_after_the_look(stage_env, store, monkeypatch):
    force_stage_one(monkeypatch, False)
    first = v4.run_dev(stage_env, store, say=lambda m: None)
    out = v4.output_dir(stage_env)
    stored = (out / v4.DEV_RESULTS).read_text(encoding="utf-8")
    with pytest.raises(FileExistsError, match="--force"):
        v4.run_dev(stage_env, store, say=lambda m: None)
    assert (out / v4.DEV_RESULTS).read_text(encoding="utf-8") == stored
    again = v4.run_dev(stage_env, store, say=lambda m: None, force=True)
    assert again["comparison"]["difference"]["point_difference"] == first["comparison"]["difference"]["point_difference"]
    (out / v4.HELDOUT).write_text("{}", encoding="utf-8")
    with pytest.raises(FileExistsError, match="look has been taken"):
        v4.run_dev(stage_env, store, say=lambda m: None, force=True)
    (out / v4.HELDOUT).unlink()
    (out / v4.STARTED).write_text("{}", encoding="utf-8")
    with pytest.raises(FileExistsError, match="heldout.started"):
        v4.run_dev(stage_env, store, say=lambda m: None, force=True)


def test_a_failed_stage_one_writes_no_model_and_no_held_out_look_happens(stage_env, store, monkeypatch):
    force_stage_one(monkeypatch, False)
    payload = v4.run_dev(stage_env, store, say=lambda m: None)
    out = v4.output_dir(stage_env)
    assert payload["model_dir"] is None and not (out / v4.MODEL_SUBDIR).exists()
    assert payload["decision"]["adopt"] is False and payload["decision"]["stage"] == 1
    built = []
    with pytest.raises(v4.StageOneError, match="not passed"):
        v4.run_heldout(stage_env, say=lambda m: None, build=lambda *a: built.append(1))
    assert built == [] and not (out / v4.HELDOUT).exists()
    with pytest.raises(v4.StageOneError, match="stage 1"):
        v4.load_model(stage_env)


def test_heldout_needs_the_development_results(stage_env):
    with pytest.raises(FileNotFoundError, match="dev"):
        v4.run_heldout(stage_env, say=lambda m: None, build=lambda *a: None)


# --------------------------------------------------------------------------------------------- preflight

def expectations(info: dict) -> dict:
    """The study's `preflight` section as the W1 facts of the synthetic assembly."""
    pooled, events = info["pooled"], info["events"]
    return {"burden_tolerance": 1e-4, "pooled_alert_tolerance": 5e-4, "straddle_tolerance": 0.01, "cells": pooled["cells"], "days": pooled["days"],
            "v3_alert_cell_days": pooled["alert_cell_days"]["v3_rules"], "events": events["events"],
            "events_outside_panel_days": events["outside_panel_days"], "distinct_slides": events["distinct_slides"],
            "events_by_source": events["by_source"]}


def w1_of(info: dict) -> dict:
    return {"seasons": {y: {"cells": s["cells"], "days": s["days"], "scored_cell_days": s["scored_cell_days"],
                            "v3_realised_shares": s["v3_realised_shares"]} for y, s in info["seasons"].items()}}


def test_the_assembly_checks_pass_against_matching_w1_facts_and_name_what_differs(study):
    info = assembled().info
    study = {**study, "preflight": expectations(info)}
    assert all(c["passed"] for c in v4.check_assembly(study, info, w1_of(info)))
    other = w1_of(info)
    other["seasons"]["2019"]["v3_realised_shares"] = [0.4, 0.2, 0.1]
    failed = [c["name"] for c in v4.check_assembly(study, info, other) if not c["passed"]]
    assert failed == ["season 2019 v3 burden equals W1"]
    off = {**study, "preflight": {**study["preflight"], "v3_alert_cell_days": [28, 10, 5], "events_by_source": {"reported": 3}}}
    failed = [c["name"] for c in v4.check_assembly(off, info, w1_of(info)) if not c["passed"]]
    assert "pooled v3 alert cell-days equal W1" in failed and any(n.startswith("events:") for n in failed)


def test_the_guard_checks_name_the_state_of_the_look(stage_env, tmp_path):
    out = v4.output_dir(stage_env)
    out.mkdir(parents=True)
    dev = {"stage_one": {"passed": True, "verdict": "includes zero"}, "lag_days": 1}
    checks = {c["name"]: c["passed"] for c in v4.check_guard(stage_env, dev, 1)}
    assert all(checks.values()) and len(checks) == 5 and "no look-started marker" in checks
    (out / v4.HELDOUT).write_text("{}", encoding="utf-8")
    (out / v4.STARTED).write_text("{}", encoding="utf-8")
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "phase7_rain_intensity.json").write_text("{}", encoding="utf-8")
    checks = {c["name"]: c["passed"] for c in v4.check_guard(stage_env, {**dev, "stage_one": {"passed": False, "verdict": "x"}}, 0)}
    assert not any(checks.values())


def test_provenance_checks_each_season_sidecar_against_the_current_card(stage_env, isolated_data_root):
    base_dir = hm.configured_model_dir(stage_env["base"])
    base_dir.mkdir(parents=True)
    (base_dir / hm.CARD_FILE).write_text(json.dumps({"n_members": 3}), encoding="utf-8")
    directory = v4.seasons_dir(stage_env)
    directory.mkdir(parents=True)
    prov = {"card_sha256": "c" * 64}
    for year in bt.SEASON_YEARS:
        (directory / f"season_{year}_v4_int.json").write_text(json.dumps({
            "model_card_sha256": "c" * 64, "features": "training_style+iint", "n_members": 3, "lag_days": 1}), encoding="utf-8")
    assert all(c["passed"] for c in v4.check_provenance(stage_env, 1, prov))
    (directory / "season_2021_v4_int.json").write_text(json.dumps({
        "model_card_sha256": "d" * 64, "features": "training_style+iint", "n_members": 3, "lag_days": 1}), encoding="utf-8")
    (directory / "season_2022_v4_int.json").write_text(json.dumps({
        "model_card_sha256": "c" * 64, "features": "training_style", "n_members": 3, "lag_days": 1}), encoding="utf-8")
    (directory / "season_2023_v4_int.json").write_text(json.dumps({
        "model_card_sha256": "c" * 64, "features": "training_style+iint", "n_members": 20, "lag_days": 1}), encoding="utf-8")
    (directory / "season_2024_v4_int.json").write_text(json.dumps({
        "model_card_sha256": "c" * 64, "features": "training_style+iint", "n_members": 3, "lag_days": 0}), encoding="utf-8")
    failed = [c["name"] for c in v4.check_provenance(stage_env, 1, prov) if not c["passed"]]
    assert failed == [f"season {y} provenance" for y in (2021, 2022, 2023, 2024)]


def test_the_iint_table_checks_read_the_manifest_and_the_current_v3_panels(stage_env, tmp_path, monkeypatch):
    features, panels = tmp_path / "f", tmp_path / "panels"
    (features / "imerg").mkdir(parents=True)
    panels.mkdir()
    shas = {}
    for year in range(2018, 2026):
        path = panels / f"season_{year}_training.npz"
        path.write_bytes(str(year).encode())
        shas[str(year)] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    manifest = {"frozen": True, "allow_missing": False, "required_days_missing": 0, "lag_days": 1,
                "inputs": {"season_panels": shas}, "created_utc": "x"}
    (features / "imerg" / "iint_lag1_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(ii, "verify_iint_tables", lambda *a, **k: {"ok": True, "problems": []})
    assert all(c["passed"] for c in v4.check_iint_tables(stage_env, features, 1, panels))
    bad = {**manifest, "frozen": False, "allow_missing": True, "required_days_missing": 3, "lag_days": 0}
    (features / "imerg" / "iint_lag1_manifest.json").write_text(json.dumps(bad), encoding="utf-8")
    (panels / "season_2019_training.npz").write_bytes(b"changed")
    failed = {c["name"] for c in v4.check_iint_tables(stage_env, features, 1, panels) if not c["passed"]}
    assert failed == {"iint tables frozen", "iint tables built without --allow-missing", "no required Late day missing",
                      "iint tables built at this lag", "iint tables built from the current v3 season panels"}
    monkeypatch.setattr(ii, "verify_iint_tables", lambda *a, **k: {"ok": False, "problems": ["checksum mismatch: x"]})
    assert "iint tables intact" in {c["name"] for c in v4.check_iint_tables(stage_env, features, 1, panels) if not c["passed"]}


PROV = {"lag_days": 0, "card_sha256": "c" * 64, "v4_panel_sha256": {"2019": "1"}, "v3_panel_sha256": {"2019": "2"},
        "iint_manifest_sha256": "m"}


@pytest.fixture
def preflight_env(stage_env, store, monkeypatch):
    """A development stage that passed, with the file-level checks replaced by their verdicts (tested above)."""
    force_stage_one(monkeypatch, True)
    v4.run_dev(stage_env, store, say=lambda m: None)
    info = assembled().info
    study = {**stage_env, "preflight": expectations(info)}
    monkeypatch.setattr(v4, "provenance", lambda study_, lag, features: PROV)
    monkeypatch.setattr(v4, "check_provenance", lambda *a: [v4._check("provenance", True, "")])
    monkeypatch.setattr(v4, "check_iint_tables", lambda *a: [v4._check("tables", True, "")])
    monkeypatch.setattr(v4, "w1_report", lambda: w1_of(info))
    return study, store


def test_a_preflight_that_passes_computes_no_outcome_and_freezes_the_events_and_checksums(preflight_env, monkeypatch):
    study, store = preflight_env

    def forbidden(*args, **kwargs):
        raise AssertionError("an outcome was computed")

    for target in (op, matching, vscores):
        for name in ("score_heldout", "match", "grouped_pod"):
            if hasattr(target, name):
                monkeypatch.setattr(target, name, forbidden)
    record = v4.run_preflight(study, store, say=lambda m: None, load=lambda *a: assembled())
    assert record["passed"] is True and record["outcome_computed"] is False and record["lag_days"] == 0
    assert record["events_sha256"] == assembled().info["events_sha256"] and record["provenance"] == PROV
    assert record["peak_memory_mb"] > 0 and set(record["seasons"]) == {"2019", "2020"}
    names = {c["name"] for c in record["checks"]}
    assert {"no held-out result in data/", "stage 1 passed", "assembly (alignment, burden matching)",
            "JSON serialisable without NaN", "provenance", "tables"} <= names
    stored = json.loads((v4.output_dir(study) / v4.PREFLIGHT).read_text(encoding="utf-8"))
    assert stored["passed"] is True and stored["outcome_computed"] is False
    assert not (v4.output_dir(study) / v4.HELDOUT).exists()


def test_a_preflight_that_finds_a_problem_fails_and_says_which(preflight_env):
    study, store = preflight_env
    wrong = {**study, "preflight": {**study["preflight"], "events": 99}}
    record = v4.run_preflight(wrong, store, say=lambda m: None, load=lambda *a: assembled())
    assert record["passed"] is False and record["outcome_computed"] is False
    assert [c["name"] for c in record["checks"] if not c["passed"]][0].startswith("events:")

    def broken(*args):
        return v4.assemble([make_input(drop=lambda inp: inp.v4.values["risk"].__setitem__((1, 4), np.nan))], REF, EVENTS)

    record = v4.run_preflight(study, store, say=lambda m: None, load=broken)
    failed = [c for c in record["checks"] if not c["passed"]]
    assert record["passed"] is False and failed[0]["name"] == "assembly (alignment, burden matching)" and "scored" in failed[0]["detail"]


def test_a_nan_anywhere_in_the_preflight_record_fails_it(preflight_env):
    study, store = preflight_env

    def with_nan(*args):
        assembly = assembled()
        assembly.info["seasons"]["2019"]["iint_nan_share"]["iint_max1h_1"] = float("nan")
        return assembly

    record = v4.run_preflight(study, store, say=lambda m: None, load=with_nan)
    assert record["passed"] is False
    assert [c["name"] for c in record["checks"] if not c["passed"]] == ["JSON serialisable without NaN"]


def test_a_preflight_after_the_look_or_on_a_failed_stage_one_does_not_pass(stage_env, store, monkeypatch):
    force_stage_one(monkeypatch, False)
    v4.run_dev(stage_env, store, say=lambda m: None)
    record = v4.run_preflight(stage_env, store, say=lambda m: None, load=lambda *a: pytest.fail("assembled"))
    assert record["passed"] is False and [c["name"] for c in record["checks"] if not c["passed"]] == ["stage 1 passed"]
    (v4.output_dir(stage_env) / v4.HELDOUT).write_text("{}", encoding="utf-8")
    with pytest.raises(FileExistsError, match="look has been taken"):
        v4.run_preflight(stage_env, store, say=lambda m: None)
    (v4.output_dir(stage_env) / v4.HELDOUT).unlink()
    (v4.output_dir(stage_env) / v4.STARTED).write_text("{}", encoding="utf-8")
    with pytest.raises(FileExistsError, match="heldout.started"):
        v4.run_preflight(stage_env, store, say=lambda m: None)


def test_the_provenance_hashes_the_card_the_panels_the_lag_and_the_iint_manifest(stage_env, isolated_data_root, tmp_path):
    directory = v4.output_dir(stage_env) / v4.MODEL_SUBDIR / "v4_int"
    directory.mkdir(parents=True)
    (directory / hm.CARD_FILE).write_text("card", encoding="utf-8")
    seasons_ = v4.seasons_dir(stage_env)
    seasons_.mkdir(parents=True)
    v3_dir = H.alerts_dir("heldout_seasons")
    v3_dir.mkdir(parents=True)
    for year in bt.SEASON_YEARS:
        (seasons_ / f"season_{year}_v4_int.npz").write_bytes(b"v4%d" % year)
        (v3_dir / f"season_{year}_training.npz").write_bytes(b"v3%d" % year)
    (tmp_path / "f" / "imerg").mkdir(parents=True)
    (tmp_path / "f" / "imerg" / "iint_lag1_manifest.json").write_text("m", encoding="utf-8")
    prov = v4.provenance(stage_env, 1, tmp_path / "f")
    assert prov["lag_days"] == 1 and prov["card_sha256"] == hashlib.sha256(b"card").hexdigest()
    assert prov["v4_panel_sha256"]["2019"] == hashlib.sha256(b"v42019").hexdigest()
    assert prov["v3_panel_sha256"]["2025"] == hashlib.sha256(b"v32025").hexdigest()
    assert prov["iint_manifest_sha256"] == hashlib.sha256(b"m").hexdigest() and set(prov["v4_panel_sha256"]) == {str(y) for y in bt.SEASON_YEARS}
    (seasons_ / "season_2019_v4_int.npz").write_bytes(b"changed")
    assert v4.provenance(stage_env, 1, tmp_path / "f") != prov


def test_the_peak_memory_and_the_non_finite_finder():
    assert v4.peak_memory_mb() > 10
    assert v4.non_finite({"a": [1.0, float("nan")], "b": {"c": np.inf}, "d": "x"}) == ["$.a[1]", "$.b.c"]
    assert v4.non_finite({"a": [1.0, 2], "b": None}) == []


# ----------------------------------------------------------------- the stages around the single look

def write_preflight(study, passed=True, prov=PROV, sha="s", outcome_computed=False):
    out = v4.output_dir(study)
    out.mkdir(parents=True, exist_ok=True)
    (out / v4.PREFLIGHT).write_text(json.dumps({"passed": passed, "outcome_computed": outcome_computed, "provenance": prov,
                                                "events_sha256": sha, "checks": [], "peak_memory_mb": 1.0}), encoding="utf-8")


def look_env(stage_env, store, monkeypatch):
    force_stage_one(monkeypatch, True)
    v4.run_dev(stage_env, store, say=lambda m: None)
    monkeypatch.setattr(v4, "published_v3_numbers", lambda: None)
    monkeypatch.setattr(v4, "provenance", lambda study, lag, features: PROV)


def test_the_look_needs_a_current_passed_preflight(stage_env, store, monkeypatch):
    look_env(stage_env, store, monkeypatch)
    built = []

    def build(study, say, lag, features):
        built.append(1)
        return pools({"events_sha256": "s"})

    with pytest.raises(v4.PreflightError, match="not found"):
        v4.run_heldout(stage_env, say=lambda m: None, build=build, features_dir=store)
    for kwargs, message in (({"passed": False}, "did not pass"), ({"outcome_computed": True}, "did not pass"),
                            ({"prov": {**PROV, "card_sha256": "other"}}, "different card")):
        write_preflight(stage_env, **kwargs)
        with pytest.raises(v4.PreflightError, match=message):
            v4.run_heldout(stage_env, say=lambda m: None, build=build, features_dir=store)
    assert built == [] and not (v4.output_dir(stage_env) / v4.HELDOUT).exists()


def test_the_heldout_stage_stores_one_result_with_the_lag_and_provenance_and_refuses_a_second_look(stage_env, store, monkeypatch):
    look_env(stage_env, store, monkeypatch)
    write_preflight(stage_env)
    built = []

    def build(study, say, lag, features):
        built.append((lag, features))
        return pools({"seasons": {"2019": {}}, "events_sha256": "s"})

    result = v4.run_heldout(stage_env, say=lambda m: None, build=build, features_dir=store)
    assert built == [(0, store)] and result["lag_days"] == 0 and result["provenance"] == PROV
    assert result["stage_one"]["passed"] is True and result["decision"]["stage"] == 2
    assert (v4.output_dir(stage_env) / v4.HELDOUT).is_file()
    with pytest.raises(FileExistsError):
        v4.run_heldout(stage_env, say=lambda m: None, build=build, features_dir=store)
    assert len(built) == 1


def test_the_heldout_stage_refuses_a_started_look_and_names_the_human_decision(stage_env, store, monkeypatch):
    look_env(stage_env, store, monkeypatch)
    write_preflight(stage_env)
    (v4.output_dir(stage_env) / v4.STARTED).write_text("{}", encoding="utf-8")
    built = []
    with pytest.raises(v4.LookStartedError, match="human decision"):
        v4.run_heldout(stage_env, say=lambda m: None, build=lambda *a: built.append(1), features_dir=store)
    assert built == [] and not (v4.output_dir(stage_env) / v4.HELDOUT).exists()


def test_the_look_is_refused_when_the_events_changed_after_the_preflight(stage_env, store, monkeypatch):
    look_env(stage_env, store, monkeypatch)
    write_preflight(stage_env, sha="frozen")
    with pytest.raises(ValueError, match="events_sha256"):
        v4.run_heldout(stage_env, say=lambda m: None, build=lambda *a: pools({"events_sha256": "changed"}), features_dir=store)
    assert not (v4.output_dir(stage_env) / v4.HELDOUT).exists()


def test_the_look_is_refused_when_the_gap_report_changed_the_lag_after_dev(stage_env, store, monkeypatch):
    look_env(stage_env, store, monkeypatch)
    write_preflight(stage_env)
    monkeypatch.setattr(v4, "declared_lag", lambda: 1)
    with pytest.raises(ValueError, match="rerun `dev --force`"):
        v4.run_heldout(stage_env, say=lambda m: None, build=lambda *a: pools(), features_dir=store)


# --------------------------------------------------------------------------------------------- the report

def test_the_report_waits_for_the_look_when_stage_one_passed(stage_env, store, monkeypatch, tmp_path):
    force_stage_one(monkeypatch, True)
    v4.run_dev(stage_env, store, say=lambda m: None)
    with pytest.raises(v4.StageOneError, match="held-out look"):
        v4.write_report(stage_env, tmp_path / "reports", say=lambda m: None)
    assert not (tmp_path / "reports").exists()                    # a report must never be what blocks the unseen look


def test_the_report_of_a_failed_stage_one_says_the_held_out_set_was_not_read(stage_env, store, monkeypatch, tmp_path):
    force_stage_one(monkeypatch, False)
    v4.run_dev(stage_env, store, say=lambda m: None)
    result = v4.write_report(stage_env, tmp_path / "reports", say=lambda m: None)
    assert result["heldout"] is None and result["decision"]["adopt"] is False and result["dev"]["lag_days"] == 0
    text = (tmp_path / "reports" / "phase7_rain_intensity.md").read_text(encoding="utf-8")
    assert "not evaluated on the held-out set" in text and "v4-int is not adopted" in text.replace("**", "")
    stored = json.loads((tmp_path / "reports" / "phase7_rain_intensity.json").read_text(encoding="utf-8"))
    assert stored["stage_one"]["passed"] is False
    with pytest.raises(FileExistsError):                          # the committed report now also blocks any look
        v4.evaluate_once(v4.output_dir(stage_env) / v4.HELDOUT, tmp_path / "reports" / "phase7_rain_intensity.json",
                         pools, BOOT, None, {})


def test_the_report_of_a_look_lists_the_comparisons_the_ties_and_the_lag(stage_env, store, monkeypatch, tmp_path):
    look_env(stage_env, store, monkeypatch)
    write_preflight(stage_env, sha=assembled().info["events_sha256"])
    v4.run_heldout(stage_env, say=lambda m: None, build=lambda *a: (assembled().pools, assembled().info), features_dir=store)
    result = v4.write_report(stage_env, tmp_path / "reports", say=lambda m: None)
    text = (tmp_path / "reports" / "phase7_rain_intensity.md").read_text(encoding="utf-8")
    for needle in ("Warning+", "Emergency", "cell_exact", "tolerant", "independent slides", "burden", "2019", "2020", "C0", "v4_int",
                   "v3_ranked", "with rules", "v3_ranked ties at the cuts", "v4-int ties at the cuts", "straddled tie", "NaN intensity", "lag the target day by 0", "iint_max6h_max3d"):
        assert needle in text, needle
    assert result["heldout"]["decision"]["stage"] == 2 and result["decision"] == result["heldout"]["decision"]
    assert result["preflight"]["passed"] is True and result["heldout"]["lag_days"] == 0
    json.loads((tmp_path / "reports" / "phase7_rain_intensity.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------------- the combined study (W6)

@pytest.fixture
def combined():
    return v4.load_study(PROJECT_ROOT / "configs" / "hazard_v4.yaml")


def test_v4_is_the_v3_inputs_plus_the_intensity_and_the_nine_physical_static_inputs(combined, study):
    static = v4.static_inputs(combined)
    challenger = v4.make_candidates(combined, COLUMNS, {c: "iint" for c in IINT})["v4"]
    assert static == v4.sw.HAZARD_COLUMNS and len(static) == 9 and not set(v4.sw.EXPOSURE_COLUMNS) & set(static)
    assert challenger.columns == COLUMNS + IINT + static
    assert challenger.constraints[len(COLUMNS):] == [1] * 6 + [0] * 9
    assert v4.pool_names(combined) == ("v4_int_ranked", "v4") and combined["tie_seed"] == study["tie_seed"]
    assert combined["preflight"] == study["preflight"]                    # the W1 facts and tolerances of the W3 look
    assert v4.static_inputs(study) == [] and v4.pool_names(study) == ("v3_ranked", "v4_int") and v4.check_requires(study) == []
    broken = copy.deepcopy(combined)
    broken["candidates"]["v4"]["add_static"] = ["lc_built"]
    with pytest.raises(ValueError, match="physical columns"):
        v4.make_candidates(broken, COLUMNS)


def test_the_assembly_and_the_decision_use_the_names_of_the_study():
    assembly = v4.assemble([make_input(2019)], REF, EVENTS, names=("v4_int_ranked", "v4"))
    assert set(assembly.info["pooled"]["alert_cell_days"]) == {"v3_rules", "v4_int_ranked", "v4"}
    assert {"v4_int_ranked", "v4"} <= set(assembly.info["seasons"]["2019"])
    assert "v4_int_ranked's" in v4.decide(PASSED, scores({**TIE, 2: (60, 61)}, TIE), "v4_int_ranked")["reason"]


def test_a_combined_study_requires_an_adopted_incumbent_and_a_passed_static_stage(combined, isolated_data_root):
    def passed():
        return [c["passed"] for c in v4.check_requires(combined)]
    assert passed() == [False, False]
    with pytest.raises(v4.StageOneError, match="requirements"):
        v4.run_dev(combined, say=lambda m: None)
    root = isolated_data_root / "processed" / "hazard"
    (root / "v4_int").mkdir(parents=True)
    (root / "v4_static").mkdir()
    (root / "v4_int" / v4.HELDOUT).write_text(json.dumps({"decision": {"adopt": True}}), encoding="utf-8")
    record = {"stage_one": {"passed": True}, "candidates": {"v4_static": {"columns": v4.static_inputs(combined)[:-1]}}}
    (root / "v4_static" / v4.DEV_RESULTS).write_text(json.dumps(record), encoding="utf-8")
    assert passed() == [True, False]                                      # one static input was never tested in that stage
    record["candidates"]["v4_static"]["columns"] = v4.static_inputs(combined)
    (root / "v4_static" / v4.DEV_RESULTS).write_text(json.dumps(record), encoding="utf-8")
    assert passed() == [True, True]


def test_the_combined_report_renders_from_a_stored_result():
    from aetherguard.hazard import v4_combined

    result = json.loads((PROJECT_ROOT / "reports" / "phase7_rain_intensity.json").read_text(encoding="utf-8"))
    result["dev"]["static_inputs"] = ["lc_tree"]
    stage = {"stage_one": result["stage_one"], "candidates": result["dev"]["candidates"], "comparison": result["comparison"]}
    text = v4_combined.markdown(result, {"nine": stage, "eleven": stage}, ("v3_ranked", "v4_int"))
    for needle in ("v4 is adopted", "all eleven columns", "the nine physical columns", "v3_ranked slides detected", "`lc_tree`"):
        assert needle in text
