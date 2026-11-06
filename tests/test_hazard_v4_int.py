"""W3 challenger v4-int (spec 2026-11-06 sections 2-3): the configuration, stage 1, the two-stage decision, the one-shot
held-out guard, the scoring of the season panels with the iint group and the burden matching, on synthetic data."""
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
                          "candidates", "base"}
    assert set(study["candidates"]["v4_int"]) == {"description", "add_groups", "add_increasing"}
    assert study["base_config"] == "configs/hazard_v3.yaml"
    assert v4.extra_groups(study).keys() == {*study["base"]["extra_groups"], ii.GROUP}
    assert v4.groups_used(study) == [*v4.tr.extra_groups_used(study["base"]), ii.GROUP]
    assert study["base"]["model_dir"] == "model_v3_live" and v4.output_dir(study).name == "v4_int"
    assert v4.output_dir(study) != hm.configured_model_dir(study["base"])


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


# ------------------------------------------------------------------------------------------ the decision

def scores(tolerant, exact) -> dict:
    """held-out scores with (v3, v4-int) independent-slide detections per level: {level: (v3, candidate)}."""
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
    exact_emergency = v4.decide(PASSED, scores(TIE, {**TIE, 3: (40, 45)}))
    assert exact_emergency["adopt"] is True


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

def test_burden_matching_gives_v4_int_the_realised_shares_of_v3_in_the_season():
    scored = np.ones((4, 5), dtype=bool)
    scored[3, :] = False
    v3 = np.zeros((4, 5), dtype=np.int8)
    v3[0, 0], v3[0, 1], v3[1, 2] = 3, 2, 1                 # 15 scored cell-days: 3/15 Watch+, 2/15 Warning+, 1/15 Emergency
    risk = np.linspace(0.0, 1.0, 20).reshape(4, 5)
    risk[3, :] = 0.99                                       # unscored cells never alert, however high their risk
    levels, shares = v4.match_burden(risk, scored, v3)
    assert shares["target"] == pytest.approx([3 / 15, 2 / 15, 1 / 15])
    assert shares["realised"] == pytest.approx(shares["target"]) and levels.dtype == np.int8
    assert (levels[3] == 0).all()
    assert levels[2, 4] == 3 and levels[2, 3] == 2 and levels[2, 2] == 1 and levels[0, 0] == 0   # ranked by v4-int's own risk


def season_panel(risk: np.ndarray, cells: pd.DataFrame, days: list, extra: int = 0) -> H.Panel:
    panel = H.new_panel(cells.assign(in_universe=True), days, 3)
    panel.values["risk"][:, :] = risk
    return panel


def test_a_v4_int_panel_must_match_the_v3_season_cells_days_and_scored_cell_days():
    cells = pd.DataFrame({"cell_id": [11, 12, 13], "region": ["himalaya"] * 3})
    days = [date(2019, 5, 30) + timedelta(days=k) for k in range(6)]
    risk = np.random.default_rng(0).random((3, 6))
    risk[1, 2] = np.nan
    part = vr.Part(cell_ids=np.array([11, 12, 13]), in_universe=np.ones(3, dtype=bool), days=days[2:], scored=np.isfinite(risk[:, 2:]),
                   acc_3=np.zeros((3, 4)), static_score=np.zeros(3), v3=np.zeros((3, 4), dtype=np.int8),
                   events=pd.DataFrame({"cell_id": [], "date": []}))
    panel = season_panel(risk, cells, days)
    levels, shares = v4.season_levels(part, panel, 2, 2019)
    assert levels.shape == (3, 4) and shares["target"] == [0.0, 0.0, 0.0]
    with pytest.raises(ValueError, match="cells"):
        v4.season_levels(part, season_panel(risk, cells.assign(cell_id=[11, 13, 12]), days), 2, 2019)
    with pytest.raises(ValueError, match="days"):
        v4.season_levels(part, season_panel(risk, cells, days[:-1] + [date(2020, 1, 1)]), 2, 2019)
    other = risk.copy()
    other[0, 3] = np.nan
    with pytest.raises(ValueError, match="scored"):
        v4.season_levels(part, season_panel(other, cells, days), 2, 2019)


# ---------------------------------------------------------------------------- the single held-out look

A_CELL = int(grid.latlon_to_cell(30.025, 78.025))
CELLS = np.array([A_CELL, A_CELL + 1, A_CELL + 20])


def pool() -> op.HeldOut:
    days = [date(2019, 7, 1) + timedelta(days=k) for k in range(5)]
    v3 = np.zeros((3, 5), dtype=np.int8)
    v3[0, 1], v3[1, 1], v3[2, 3], v3[0, 3] = 2, 2, 3, 1
    candidate = np.zeros((3, 5), dtype=np.int8)
    candidate[0, 1], candidate[2, 3] = 2, 3
    events = pd.DataFrame({"cell_id": [A_CELL, A_CELL + 1, A_CELL + 20],
                           "date": pd.to_datetime(["2019-07-02", "2019-07-02", "2019-07-04"])})
    return op.HeldOut(CELLS, days, np.ones((3, 5), dtype=bool), v3, candidate, events, 1)


def test_the_look_scores_slides_with_the_w1_assembly_and_decides_on_them(tmp_path):
    result = v4.evaluate_once(tmp_path / "heldout.json", tmp_path / "report.json", lambda: (pool(), {"seasons": {}}), BOOT,
                              None, {"stage_one": PASSED})
    scores_ = result["scores"]
    assert scores_["slides"] == 2 and scores_["events"] == 3
    for tolerance in ("tolerant", "cell_exact"):
        assert scores_[tolerance]["v3"][2]["group_hits"] == 2 and scores_[tolerance]["candidate"][2]["group_hits"] == 2
    assert result["decision"]["adopt"] is False and result["decision"]["failed"] == ["no comparison is higher"]
    stored = json.loads((tmp_path / "heldout.json").read_text(encoding="utf-8"))
    assert stored["decision"]["adopt"] is False and stored["seasons"] == {} and stored["stage_one"] == PASSED


def test_the_second_look_is_refused_before_anything_is_loaded(tmp_path):
    built = []

    def build():
        built.append(1)
        return pool(), {}

    path, report = tmp_path / "heldout.json", tmp_path / "report.json"
    v4.evaluate_once(path, report, build, BOOT, None, {"stage_one": PASSED})
    stored = path.read_text(encoding="utf-8")
    with pytest.raises(FileExistsError, match="heldout.json"):
        v4.evaluate_once(path, report, build, BOOT, None, {"stage_one": PASSED})
    assert built == [1] and path.read_text(encoding="utf-8") == stored


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
        v4.evaluate_once(path, report, lambda: (pool(), {}), BOOT, wrong, {"stage_one": PASSED})
    assert not path.exists()
    assert v4.evaluate_once(path, report, lambda: (pool(), {}), BOOT, None, {"stage_one": PASSED})["scores"]["slides"] == 2


# ---------------------------------------------------- the season panels scored with the iint group

YEAR = 2026
SEASON_CELLS = tiny_cells().iloc[::-1].reset_index(drop=True)
HEAVY = [date(YEAR, 8, 10), date(YEAR, 8, 11), date(YEAR, 8, 12), date(YEAR, 9, 20)]


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


def write_season_iint(directory, study, year=YEAR, burst_day=HEAVY[2], tamper=False, cells=SEASON_CELLS):
    """The frozen season table of the iint group (cell-major cells x days, as features.imerg_intensity writes it)."""
    days = bt.day_range(date(year, 6, 1) - timedelta(days=bt.WARMUP_DAYS), date(year, 12, 31))
    frame = ii.panel_frame(cells["cell_id"].to_numpy(dtype=np.int64), days)
    wayanad = int(tiny_cells().query("region == 'western_ghats'")["cell_id"].iloc[0])
    hot = ((frame["cell_id"] == wayanad) & (frame["date"] == pd.Timestamp(burst_day))).to_numpy()
    for name in IINT:
        frame[name] = np.where(hot, 80.0, 1.0).astype(np.float32)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ii.season_name(year)
    frame.to_parquet(path, index=False)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    (directory / B.manifest_name(ii.GROUP)).write_text(
        json.dumps({"files": {path.name: {"sha256": digest, "n_rows": len(frame)}}}), encoding="utf-8")
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


def test_a_season_is_scored_with_the_training_style_features_joined_to_its_iint_table(toy, tmp_path, study):
    features = tmp_path / "features" / "imerg"
    _, days = write_season_iint(features, study)
    path = v4.score_season(IintModel(), "ab" * 32, study, YEAR, tmp_path / "features", tmp_path / "panels", say=lambda m: None)
    assert path == tmp_path / "panels" / f"season_{YEAR}_v4_int.npz"
    panel = H.load_panel(path)
    assert panel.cells["cell_id"].tolist() == SEASON_CELLS["cell_id"].tolist() and panel.days == days
    wayanad = SEASON_CELLS.index[SEASON_CELLS["cell_id"] == int(tiny_cells().query("region == 'western_ghats'")["cell_id"].iloc[0])][0]
    assert panel["risk"][wayanad, days.index(HEAVY[2])] == pytest.approx(0.8)         # the iint value reached the model
    assert panel["risk"][wayanad, days.index(date(YEAR, 7, 1))] == pytest.approx(0.01)
    sidecar = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    assert sidecar["features"] == "training_style+iint" and sidecar["model_card_sha256"] == "ab" * 32
    assert sidecar["n_cells"] == len(SEASON_CELLS) and sidecar["first_day"] == days[0].isoformat()


def test_an_existing_season_panel_is_kept_unless_forced(toy, tmp_path, study):
    features = tmp_path / "features" / "imerg"
    write_season_iint(features, study)
    args = (IintModel(), "ab" * 32, study, YEAR, tmp_path / "features", tmp_path / "panels")
    path = v4.score_season(*args, say=lambda m: None)
    path.write_bytes(b"kept")
    assert v4.score_season(*args, say=lambda m: None).read_bytes() == b"kept"
    assert v4.score_season(*args, say=lambda m: None, force=True).read_bytes() != b"kept"


def test_the_iint_season_table_is_verified_against_its_manifest_cells_and_days(tmp_path, study):
    features = tmp_path / "imerg"
    _, days = write_season_iint(features, study)
    ids = SEASON_CELLS["cell_id"].to_numpy(dtype=np.int64)
    values = v4.season_iint(study, features, YEAR, ids, days)
    assert values.shape == (len(ids), len(days), 6) and values.dtype == np.float32
    with pytest.raises(v4.IintTableError, match="cells"):
        v4.season_iint(study, features, YEAR, ids[::-1], days)
    with pytest.raises(v4.IintTableError, match="days"):
        v4.season_iint(study, features, YEAR, ids, days[1:])
    write_season_iint(features, study, tamper=True)
    with pytest.raises(v4.IintTableError, match="checksum"):
        v4.season_iint(study, features, YEAR, ids, days)
    with pytest.raises(FileNotFoundError, match="iint"):
        v4.season_iint(study, tmp_path / "missing", YEAR, ids, days)


# ------------------------------------------------------------------------ the stages on a synthetic store

def write_iint_store(directory, tables: dict, seed: int = 7) -> None:
    sub = directory / "imerg"
    sub.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, frame in tables.items():
        extra = add_intensity(frame, seed + len(name))[["cell_id", "date", *IINT]]
        path = sub / B.table_name(name, ii.GROUP)
        extra.to_parquet(path)
        files[path.name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "n_rows": len(extra)}
    (sub / B.columns_name(ii.GROUP)).write_text(json.dumps({c: ii.GROUP for c in IINT}), encoding="utf-8")
    (sub / B.manifest_name(ii.GROUP)).write_text(json.dumps({"files": files}), encoding="utf-8")


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    samples, universe = synthetic_development(n_pos_train=110, n_pos_validation=50, n_per_region=2500)
    directory = write_dev_store(tmp_path_factory.mktemp("features"), samples, universe, extras=False)
    tables = {n: pd.read_parquet(directory / f"{n}_features.parquet") for n in
              ("train_samples", "validation_samples", "universe_train", "universe_validation")}
    write_iint_store(directory, tables)
    return directory


@pytest.fixture(scope="module")
def frozen(world, study):
    """The 'frozen' v3 reference, taken from a first CV of C0 so that the refit reproduces it."""
    dev, layout = world
    reference = cv.run_cv(dev, layout, COLUMNS, hm.configured_constraints(COLUMNS, study["base"]), SELECTED["hp"],
                          SELECTED["neg_mix"], study["base"], "C0")
    return {**SELECTED, "pooled": {v4.HEADLINE: reference.pooled[v4.HEADLINE]}, "n_trees": reference.n_trees}


@pytest.fixture
def stage_env(isolated_data_root, monkeypatch, tmp_path, study, frozen):
    """run_dev on the synthetic store in an isolated data root; the committed report path is a temporary one."""
    monkeypatch.setattr(v4, "frozen_selection", lambda s: frozen)
    monkeypatch.setattr(v4, "report_path", lambda s: tmp_path / "reports" / "phase7_rain_intensity.json")
    return study


def test_dev_reproduces_v3_runs_both_cvs_and_applies_stage_one(stage_env, store):
    study = stage_env
    payload = v4.run_dev(study, store, say=lambda m: None)
    out = v4.output_dir(study)
    assert payload["reproduction"]["abs_difference"] == pytest.approx(0.0, abs=1e-9)
    assert payload["candidates"]["v4_int"]["columns"] == COLUMNS + IINT and payload["candidates"]["C0"]["columns"] == COLUMNS
    assert payload["candidates"]["v4_int"]["constraints"]["iint_max6h_max3d"] == 1
    assert payload["comparison"]["difference"]["n_boot"] == 40
    stage = payload["stage_one"]
    assert stage["passed"] == (payload["comparison"]["difference"]["ci_lo"] <= 0)
    assert json.loads((out / v4.DEV_RESULTS).read_text(encoding="utf-8"))["stage_one"] == stage
    assert (out / "oof" / "oof_C0.parquet").is_file() and (out / "oof" / "oof_v4_int.parquet").is_file()
    assert (out / v4.MODEL_SUBDIR / "v4_int" / hm.CARD_FILE).is_file() == stage["passed"]
    if stage["passed"]:
        model = hm.HazardModel.load(out / v4.MODEL_SUBDIR / "v4_int")
        assert model.columns == COLUMNS + IINT and model.constraints[-6:] == [1] * 6
        assert model.card["candidate"] == "v4_int" and "W3" in model.card["protocol"]
        assert model.region_calibrator is not None and len(model.members) == 3


def test_dev_fails_when_the_reference_does_not_reproduce_v3(stage_env, store, frozen, monkeypatch):
    monkeypatch.setattr(v4, "frozen_selection", lambda s: {**frozen, "pooled": {v4.HEADLINE: frozen["pooled"][v4.HEADLINE] + 0.01}})
    with pytest.raises(ch.ReproductionError):
        v4.run_dev(stage_env, store, say=lambda m: None)
    assert not (v4.output_dir(stage_env) / v4.DEV_RESULTS).exists()


def force_stage_one(monkeypatch, passed: bool) -> None:
    monkeypatch.setattr(v4, "stage_one", lambda diff: {"passed": passed, "difference": diff["point_difference"],
                                                       "ci": [diff["ci_lo"], diff["ci_hi"]], "rule": "forced",
                                                       "verdict": "forced"})


def test_a_failed_stage_one_writes_no_model_and_no_held_out_look_happens(stage_env, store, monkeypatch):
    force_stage_one(monkeypatch, False)
    payload = v4.run_dev(stage_env, store, say=lambda m: None)
    out = v4.output_dir(stage_env)
    assert payload["model_dir"] is None and not (out / v4.MODEL_SUBDIR).exists()
    assert payload["decision"]["adopt"] is False and payload["decision"]["stage"] == 1
    built = []
    with pytest.raises(v4.StageOneError, match="not passed"):
        v4.run_heldout(stage_env, say=lambda m: None, build=lambda s, say: built.append(1))
    assert built == [] and not (out / v4.HELDOUT).exists()


def test_heldout_needs_the_development_results(isolated_data_root, study, monkeypatch, tmp_path):
    monkeypatch.setattr(v4, "report_path", lambda s: tmp_path / "reports" / "phase7_rain_intensity.json")
    with pytest.raises(FileNotFoundError, match="dev"):
        v4.run_heldout(study, say=lambda m: None, build=lambda s, say: None)


def test_the_heldout_stage_stores_one_result_and_refuses_a_second_look(stage_env, store, monkeypatch, tmp_path):
    force_stage_one(monkeypatch, True)
    v4.run_dev(stage_env, store, say=lambda m: None)
    monkeypatch.setattr(v4, "published_v3_numbers", lambda: None)
    built = []

    def build(study, say):
        built.append(1)
        return pool(), {"seasons": {"2019": {"target": [0.1, 0.05, 0.01], "realised": [0.1, 0.05, 0.01]}}}

    result = v4.run_heldout(stage_env, say=lambda m: None, build=build)
    assert result["stage_one"]["passed"] is True and result["decision"]["stage"] == 2
    assert result["decision"]["adopt"] in (True, False) and set(result["seasons"]) == {"2019"}
    path = v4.output_dir(stage_env) / v4.HELDOUT
    assert path.is_file()
    with pytest.raises(FileExistsError):
        v4.run_heldout(stage_env, say=lambda m: None, build=build)
    assert built == [1]


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
    assert result["heldout"] is None and result["decision"]["adopt"] is False
    text = (tmp_path / "reports" / "phase7_rain_intensity.md").read_text(encoding="utf-8")
    assert "not evaluated on the held-out set" in text and "v4-int is not adopted" in text.replace("**", "")
    stored = json.loads((tmp_path / "reports" / "phase7_rain_intensity.json").read_text(encoding="utf-8"))
    assert stored["stage_one"]["passed"] is False
    with pytest.raises(FileExistsError):                          # the committed report now also blocks any look
        v4.evaluate_once(v4.output_dir(stage_env) / v4.HELDOUT, tmp_path / "reports" / "phase7_rain_intensity.json",
                         lambda: (pool(), {}), BOOT, None, {})


def test_the_report_of_a_look_lists_the_four_comparisons_and_the_burden_matching(stage_env, store, monkeypatch, tmp_path):
    force_stage_one(monkeypatch, True)
    v4.run_dev(stage_env, store, say=lambda m: None)
    monkeypatch.setattr(v4, "published_v3_numbers", lambda: None)
    seasons_info = {"2019": {"target": [0.1, 0.05, 0.01], "realised": [0.1, 0.05, 0.01]}}
    v4.run_heldout(stage_env, say=lambda m: None, build=lambda s, say: (pool(), {"seasons": seasons_info}))
    result = v4.write_report(stage_env, tmp_path / "reports", say=lambda m: None)
    text = (tmp_path / "reports" / "phase7_rain_intensity.md").read_text(encoding="utf-8")
    for needle in ("Warning+", "Emergency", "cell_exact", "tolerant", "independent slides", "burden", "2019", "C0", "v4_int"):
        assert needle in text, needle
    assert result["heldout"]["decision"]["stage"] == 2 and result["decision"] == result["heldout"]["decision"]
    json.loads((tmp_path / "reports" / "phase7_rain_intensity.json").read_text(encoding="utf-8"))
