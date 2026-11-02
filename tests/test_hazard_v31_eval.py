"""v3.1 challenger study, Step 4: the single test_2018 look, its adoption criterion, and the offline live replay."""
import copy
import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from aetherguard.alerts import levels as lv
from aetherguard.alerts.config import AlertConfig
from aetherguard.hazard import challengers as ch
from aetherguard.hazard import cv
from aetherguard.hazard import data as hd
from aetherguard.hazard import v31_challenger as vc
from aetherguard.hazard import v31_eval as ve
from aetherguard.live import postrules as pr

from hazard_helpers import COLUMN_MAP, synthetic_development, synthetic_samples, synthetic_universe
from test_hazard_v31_challenger import COLUMNS, FOLDS, SELECTED, tiny_study


@pytest.fixture(scope="module")
def study():
    return tiny_study()


@pytest.fixture(scope="module")
def models(study, tmp_path_factory):
    """Two small fitted models (C0 and C2) with cards, as `fit_final` writes them."""
    samples, universe = synthetic_development(n_pos_train=110, n_pos_validation=50, n_per_region=2500)
    dev = hd.build_development(samples, universe, COLUMN_MAP)
    layout = cv.make_layout(dev, FOLDS)
    candidates = vc.make_candidates(study, COLUMNS)
    empty = pd.DataFrame({"cell_id": np.array([], dtype=np.int64), "date": pd.to_datetime([])})
    out = {}
    for name in ("C0", "C2"):
        result = vc.run_candidate(candidates[name], dev, layout, SELECTED, study["base"], empty)
        out[name] = vc.fit_final(candidates[name], dev, layout, result, study["base"], empty, tmp_path_factory.mktemp(name))
    return out


@pytest.fixture(scope="module")
def test_split():
    samples = synthetic_samples("test_2018", n_pos=80, seed=11, n_out_of_domain=5)
    universe = synthetic_universe("test_2018", n_per_region=2500, seed=12)
    return hd.split_data(hd.TEST, samples, universe)


# ---------------------------------------------------------------------------------------- the 2018 look

def test_identical_models_have_zero_difference_and_are_not_recommended(models, test_split, study):
    result = ve.compare_on_split(test_split, models["C0"], models["C0"], study)
    assert result["paired_fa_at_90"]["point_difference"] == 0.0 and result["paired_fa_at_90"]["ci_lo"] == 0.0
    criterion = result["criterion"]
    assert criterion["a_fa_at_90_not_worse"] and criterion["c_warning_events_lost"] == 0
    assert not criterion["b_lower_warning_low_share"] and not criterion["recommended"]


def test_the_comparison_reports_both_models_on_the_same_rows(models, test_split, study):
    result = ve.compare_on_split(test_split, models["C0"], models["C2"], study)
    assert result["population"]["positives_in_domain"] == 80
    assert sum(result["population"]["positives_out_of_domain"].values()) == 5
    assert set(result["models"]) == {ve.V3, "candidate"}
    for name, entry in result["models"].items():
        assert 0 < entry["fa_at_90"]["value"] < 1 and entry["fa_at_90"]["lo"] <= entry["fa_at_90"]["hi"]
        watch, warning, emergency = (entry["levels"][k] for k in vc.LEVELS)
        assert watch["recall"] >= warning["recall"] >= emergency["recall"]
        assert watch["cell_days"] >= warning["cell_days"] >= emergency["cell_days"]
        assert set(entry["risk_thresholds_by_region"]["himalaya"]) >= {"watch", "warning", "emergency"}
        assert set(entry["by_region_warning"]) == {"himalaya", "western_ghats"}
    diff = result["paired_fa_at_90"]
    assert diff["fa_a"] == result["models"]["candidate"]["fa_at_90"]["value"]
    assert diff["fa_b"] == result["models"][ve.V3]["fa_at_90"]["value"]
    criterion = result["criterion"]
    warning = {n: result["models"][n]["levels"]["warning"] for n in result["models"]}
    assert criterion["c_warning_events_lost"] == warning[ve.V3]["events"] - warning["candidate"]["events"]
    assert criterion["b_lower_warning_low_share"] == (warning["candidate"]["low_share"] < warning[ve.V3]["low_share"])
    assert criterion["a_fa_at_90_not_worse"] == (diff["ci_lo"] <= 0)
    assert criterion["recommended"] == (criterion["a_fa_at_90_not_worse"] and criterion["b_lower_warning_low_share"]
                                        and criterion["c_within_allowance"])
    assert result["low_share_diff"]["value"] == pytest.approx(warning["candidate"]["low_share"] - warning[ve.V3]["low_share"])


def test_the_event_allowance_comes_from_the_study(models, test_split, study):
    strict = copy.deepcopy(study)
    strict["adoption"]["max_warning_events_lost"] = 0
    result = ve.compare_on_split(test_split, models["C0"], models["C2"], strict)
    assert result["criterion"]["c_allowed"] == 0
    assert result["criterion"]["c_within_allowance"] == (result["criterion"]["c_warning_events_lost"] <= 0)


def test_the_frozen_model_must_reproduce_its_own_test_report():
    result = {"models": {ve.V3: {"fa_at_90": {"value": 0.3064530235537835}}}}
    report = {"test": {"main": {"metrics": {"model": {vc.HEADLINE: {"value": 0.3064530235537835}}}}}}
    assert ve.check_frozen_reproduction(result, report)["abs_difference"] == 0.0
    report["test"]["main"]["metrics"]["model"][vc.HEADLINE]["value"] = 0.31
    with pytest.raises(ch.ReproductionError, match="test_2018"):
        ve.check_frozen_reproduction(result, report)


# ------------------------------------------------------------------------------ the single-look guard

def selection_file(study, tmp_path, monkeypatch, selected):
    monkeypatch.setenv("AETHERGUARD_DATA_DIR", str(tmp_path))
    out = vc.output_dir(study)
    out.mkdir(parents=True)
    (out / vc.SELECTION).write_text(json.dumps({"selected": selected, "result": selected or vc.NO_CHALLENGER}), encoding="utf-8")
    return out


def test_heldout_reads_nothing_when_no_candidate_was_selected(study, tmp_path, monkeypatch):
    out = selection_file(study, tmp_path, monkeypatch, None)
    record = ve.run_heldout(study, features_dir=tmp_path / "does-not-exist", say=lambda m: None)
    assert record["skipped"] and "not read" in record["reason"]
    assert json.loads((out / ve.HELDOUT).read_text(encoding="utf-8"))["skipped"]
    ve.run_heldout(study, features_dir=tmp_path / "does-not-exist", say=lambda m: None)    # a skipped record may be rewritten


def test_heldout_refuses_a_second_look(study, tmp_path, monkeypatch):
    out = selection_file(study, tmp_path, monkeypatch, "C2")
    (out / ve.HELDOUT).write_text(json.dumps({"skipped": False, "candidate": "C2"}), encoding="utf-8")
    with pytest.raises(ve.SingleLookError, match="not read again"):
        ve.run_heldout(study, features_dir=tmp_path, say=lambda m: None)


# ------------------------------------------------------------------------------------------ live replay

def test_replay_days_must_be_consecutive_and_stored(tmp_path):
    for day in ("2026-10-09", "2026-10-10", "2026-10-12"):
        (tmp_path / day).mkdir()
        for name in ("alerts.parquet", "features_D0.parquet"):
            (tmp_path / day / name).write_bytes(b"")
    assert ve.replay_days(tmp_path, date(2026, 10, 9), date(2026, 10, 10)) == [date(2026, 10, 9), date(2026, 10, 10)]
    with pytest.raises(ValueError, match="2026-10-11"):
        ve.replay_days(tmp_path, date(2026, 10, 9), date(2026, 10, 12))


def live_tables(tmp_path, model, n_days=4, n_cells=60, seed=3):
    """A tiny stored live set: D0 feature tables with the model's inputs and the published alert tables."""
    rng = np.random.default_rng(seed)
    ids = np.arange(n_cells, dtype=np.int64) + 1000
    region = np.where(np.arange(n_cells) % 3 == 0, "western_ghats", "himalaya")
    static = {"stat_relief": rng.uniform(100, 900, n_cells), "stat_slope_mean": rng.uniform(3, 30, n_cells),
              "stat_elev_mean": rng.uniform(20, 2500, n_cells), "stat_aspect_sin": rng.uniform(-1, 1, n_cells)}
    days = [date(2026, 10, 9 + k) for k in range(n_days)]
    for k, day in enumerate(days):
        acc1 = np.exp(rng.normal(1.5, 1.0, n_cells))
        frame = pd.DataFrame({"cell_id": ids, "date": pd.Timestamp(day), "lat": 10.0 + np.arange(n_cells) * 0.05,
                              "lon": 76.0 + np.arange(n_cells) * 0.05, "region": region, **static,
                              "rain_acc_1": acc1, "rain_acc_3": acc1 * 2.0, "rain_acc_7": acc1 * 4.0,
                              "rain_days_since_10mm": rng.integers(0, 10, n_cells).astype(float),
                              "irain_acc_1": acc1, "irain_acc_3": acc1 * 2.0, "irain_acc_5": acc1 * 3.0, "irain_acc_7": acc1 * 4.0})
        folder = tmp_path / day.isoformat()
        folder.mkdir(parents=True)
        frame.to_parquet(folder / "features_D0.parquet")
        pd.DataFrame({"cell_id": ids, "level": np.zeros(n_cells, dtype=np.int8), "blind": np.zeros(n_cells, dtype=bool)}) \
            .to_parquet(folder / "alerts.parquet")
    return days


RULES = pr.PostRules(agreement_min=None, rain=pr.RainRule({7: 11.5}), gated_levels=(lv.WATCH, lv.WARNING, lv.EMERGENCY),
                     hold_windows={lv.WATCH: 2, lv.WARNING: 1, lv.EMERGENCY: 1}, blind_hold_days=2, lead_uncertain_bound="unwidened")
ALERT_CONFIG = AlertConfig.from_dict({"exit_factor": 0.8, "exit_days": 2, "radius_km": 100.0, "ood_window_days": 90,
                                      "ood_multiple": 3.0, "ood_min_observed_days": 30, "engine_target_flag_rate": 0.01,
                                      "dis_ratio_lo": 0.1, "dis_ratio_hi": 10.0, "heavy_acc1_mm": 30.0, "heavy_acc3_mm": 80.0,
                                      "agree_abs_mm": 3.0, "agree_rel": 0.6})


def test_replay_levels_follow_the_live_chain(models, tmp_path):
    model = models["C0"]
    days = live_tables(tmp_path, model)
    lived = ve.LiveDays(tmp_path, days)
    run = ve.replay_levels(model, lived, RULES, ALERT_CONFIG)
    levels = run["levels"]
    assert levels.shape == (60, 4) and levels.dtype == np.int8 and levels.max() >= 1
    assert np.isfinite(run["risk"]).all()
    # day 1 (no history): the level is the raw level of the point risk with the rain cap and the blind escalation
    thresholds = ve.model_thresholds(model, np.unique(lived.region))
    risk, upper = ve.score_days(model, lived)
    raw = lv.raw_level(risk[:, 0], upper[:, 0], thresholds, lived.region)[0]
    ok = RULES.rain.passes_arrays({7: lived.rain[7][:, 0]})
    expected = np.where(ok, raw, RULES.cap_array()[raw])
    np.testing.assert_array_equal(levels[:, 0], expected)
    # a dry set of days is capped at Watch everywhere; a blind cell is raised to Watch even when dry
    dry = live_tables(tmp_path / "dry", model, seed=5)
    for day in dry:
        path = tmp_path / "dry" / day.isoformat() / "features_D0.parquet"
        frame = pd.read_parquet(path)
        frame[["irain_acc_1", "irain_acc_3", "irain_acc_5", "irain_acc_7"]] = 0.0
        frame.to_parquet(path)
    blind_path = tmp_path / "dry" / dry[0].isoformat() / "alerts.parquet"
    alerts = pd.read_parquet(blind_path)
    alerts.loc[0, "blind"] = True
    alerts.to_parquet(blind_path)
    dry_run = ve.replay_levels(model, ve.LiveDays(tmp_path / "dry", dry), RULES, ALERT_CONFIG)
    assert dry_run["levels"].max() <= lv.WATCH and dry_run["levels"][0, 0] == lv.WATCH


def test_live_days_reject_different_cells(models, tmp_path):
    days = live_tables(tmp_path, models["C0"], n_days=2)
    path = tmp_path / days[1].isoformat() / "alerts.parquet"
    alerts = pd.read_parquet(path)
    alerts.loc[0, "cell_id"] += 1
    alerts.to_parquet(path)
    with pytest.raises(ValueError, match="differ"):
        ve.LiveDays(tmp_path, days)


def test_area_helpers():
    last = pd.DataFrame({"lat": [9.5, 10.0, 11.0], "lon": [77.0, 77.5, 77.0], "cell_id": [1, 2, 3]})
    mask = ve.box_mask(last, (9.0, 10.5), (76.8, 77.6))
    assert mask.tolist() == [True, True, False]
    levels = {"published": np.array([[1, 2], [0, 3], [0, 0]], dtype=np.int8), ve.V3: np.array([[1, 2], [0, 1], [0, 0]], dtype=np.int8)}
    summary = ve.area_summary(mask, levels)
    assert summary["published"] == {"Normal": 0, "Watch": 0, "Warning": 1, "Emergency": 1}
    assert summary[ve.V3] == {"Normal": 0, "Watch": 1, "Warning": 1, "Emergency": 0}
    assert ve.count_levels(levels["published"])[1] == {"Normal": 1, "Watch": 0, "Warning": 1, "Emergency": 1}


def test_lead_replay_widens_the_upper_bound_and_caps_on_the_leads_own_rain(models, tmp_path):
    model = models["C0"]
    days = live_tables(tmp_path, model, n_days=1)
    n = 60
    frame = pd.read_parquet(tmp_path / days[0].isoformat() / "features_D0.parquet")
    frame.to_parquet(tmp_path / days[0].isoformat() / "features_D1.parquet")
    scorable = np.ones(n, dtype=bool)
    plain, risk = ve.lead_replay(model, tmp_path, days[0], 1, scorable, RULES, None)
    wide, same_risk = ve.lead_replay(model, tmp_path, days[0], 1, scorable, RULES, (0.2, 50.0))
    np.testing.assert_array_equal(risk, same_risk)
    assert (wide >= plain).all() and (wide > plain).any()               # widening only raises the uncertain_high level
    point_only = pr.PostRules(agreement_min=None, rain=RULES.rain, gated_levels=RULES.gated_levels, hold_windows=RULES.hold_windows,
                              blind_hold_days=2, lead_uncertain_bound="none")
    flat, _ = ve.lead_replay(model, tmp_path, days[0], 1, scorable, point_only, (0.2, 50.0))
    assert (flat <= wide).all()                                         # the point-only bound ignores the widening
    unscored, nan_risk = ve.lead_replay(model, tmp_path, days[0], 1, np.zeros(n, dtype=bool), RULES, None)
    assert (unscored == lv.NORMAL).all() and np.isnan(nan_risk).all()
    dry = frame.assign(irain_acc_7=0.0)
    dry.to_parquet(tmp_path / days[0].isoformat() / "features_D1.parquet")
    capped, _ = ve.lead_replay(model, tmp_path, days[0], 1, scorable, RULES, (0.2, 50.0))
    assert capped.max() <= lv.WATCH
