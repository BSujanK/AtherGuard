"""The development-year alert burden (aetherguard.live.burden): scoring of the seasons, the rules that build the alert
levels one step at a time, the grid choice and its protocol guards. Hermetic: fake IMERG stores, tiny model, toy panels."""
import itertools
from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from aetherguard.alerts import levels as lv
from aetherguard.live import backtest as bt
from aetherguard.live import burden as bu
from aetherguard.live.early_map import IdentityMap
from aetherguard.live.sources import PERSIST, ImergSource

from live_run_helpers import FakeStore, make_cfg, span, tiny_cells, tiny_clim, tiny_model

EVENT = date(2026, 8, 12)
CELLS = tiny_cells().assign(in_universe=[True, True, True, False])
T_HIM = lv.Thresholds(0.5, 0.8, 0.95, "himalaya")
T_GHATS = lv.Thresholds(0.3, 0.8, 0.95, "ghats")
THRESHOLDS = {"himalaya": T_HIM, "western_ghats": T_GHATS}


def toy_stores(tmp_path, late_heavy=()):
    cfg = make_cfg(tmp_path)
    late = FakeStore(span(EVENT - timedelta(days=300), EVENT + timedelta(days=8)), late_heavy, None)
    early = FakeStore(span(EVENT - timedelta(days=15), EVENT + timedelta(days=8)), (), None)
    return bt.Stores(cfg, ImergSource("late", late, latency_h=14.5, window_days=130),
                     ImergSource("early", early, latency_h=4.5, window_days=130, mapping=IdentityMap()),
                     tiny_clim(CELLS), lambda day, ctx: bt.TailResult(None, PERSIST, "toy"))


# ------------------------------------------------------------------------------------------------ scoring

def test_a_season_runs_from_a_week_before_june_to_the_end_of_september():
    days, first = bu.season_days(2012)
    assert days[0] == date(2012, 5, 25) and days[-1] == date(2012, 9, 30) and len(days) == 129
    assert days[first] == date(2012, 6, 1)


def test_the_bounds_are_percentiles_of_the_calibrated_members_and_ordered():
    model = tiny_model()
    rng = np.random.default_rng(1)
    rows = pd.DataFrame({"irain_acc_1": rng.uniform(0, 100, 50), "irain_acc_3": rng.uniform(0, 300, 50),
                         "irain_acc_7": rng.uniform(0, 400, 50), "iapi_90": rng.uniform(0, 200, 50),
                         "inbr_max_acc_1": rng.uniform(0, 120, 50), "stat_slope_mean": rng.uniform(5, 40, 50)})
    raw, risk, bounds = bu.ensemble_scores(model, rows)
    scored = model.score(rows)
    assert np.array_equal(raw, model.raw_score(rows)) and np.array_equal(risk, scored["risk"].to_numpy())
    members, _ = model.calibrate(model.member_raw_scores(rows), rows)
    assert np.array_equal(bounds["p90"], np.percentile(members, 90, axis=1))      # the Task 6b (pre-section-11) bound
    assert (bounds["p60"] <= bounds["p75"]).all() and (bounds["p75"] <= bounds["p90"]).all()
    assert sorted(bounds) == sorted(bu.UPPER_BOUNDS)


def test_a_season_is_scored_like_the_backtest_scores_training_style_features(tmp_path):
    stores, model = toy_stores(tmp_path, late_heavy=[EVENT - timedelta(days=1)]), tiny_model()
    days = bt.day_range(EVENT - timedelta(days=1), EVENT + timedelta(days=1))
    scores = bu.score_season(days, CELLS, model, stores)
    assert scores.risk.shape == (4, 3) and np.isfinite(scores.risk).all()
    frame = pd.concat([CELLS, bt.training_style_features(days[1], CELLS, stores)], axis=1)
    expected = model.score(frame)
    assert np.array_equal(scores.risk[:, 1], expected["risk"].to_numpy())
    assert np.array_equal(scores.upper["p90"][:, 1], expected["risk_hi"].to_numpy())
    assert np.array_equal(scores.raw[:, 1], model.raw_score(frame).astype(np.float32))
    assert scores.risk[0, 1] > scores.risk[3, 1]                     # the cell with heavy rain


def test_a_day_without_its_rain_input_stays_unscored(tmp_path):
    stores = toy_stores(tmp_path)
    stores.late.store.days.discard(EVENT - timedelta(days=1))
    scores = bu.score_season([EVENT], CELLS, tiny_model(), stores)
    assert np.isnan(scores.risk).all() and np.isnan(scores.raw).all() and np.isnan(scores.upper["p75"]).all()


def test_scores_survive_a_save_and_load_and_a_scored_year_is_not_scored_again(tmp_path, monkeypatch):
    days = bt.day_range(EVENT, EVENT + timedelta(days=2))
    scores = bu.new_scores(4, 3)
    scores.raw[:], scores.risk[:] = 0.5, 0.25
    for k, name in enumerate(bu.UPPER_BOUNDS):
        scores.upper[name][:] = 0.3 + k
    path = tmp_path / "season.npz"
    bu.save_scores(path, CELLS, days, scores)
    cells, loaded_days, loaded = bu.load_scores(path)
    assert loaded_days == days and cells["cell_id"].tolist() == CELLS["cell_id"].tolist()
    assert cells["region"].tolist() == CELLS["region"].tolist() and cells["in_universe"].tolist() == [True, True, True, False]
    assert np.array_equal(loaded.risk, scores.risk) and np.array_equal(loaded.upper["p75"], scores.upper["p75"])
    assert loaded.raw.dtype == np.float32
    calls = []
    monkeypatch.setattr(bu, "score_season", lambda *args, **kwargs: calls.append(args) or scores)
    monkeypatch.setattr(bu, "season_days", lambda year: (days, 0))
    paths = bu.score_years([2010], CELLS, lambda year: None, None, tmp_path)
    assert paths == [tmp_path / "season_2010.npz"] and len(calls) == 1
    bu.score_years([2010], CELLS, lambda year: None, None, tmp_path)
    assert len(calls) == 1


def test_only_development_years_can_be_asked_for():
    assert bu.parse_years("2013-2017") == (2013, 2014, 2015, 2016, 2017) and bu.parse_years("2010") == (2010,)
    for bad in ("2018", "2016-2018", "2006-2009"):
        with pytest.raises(Exception, match="development"):
            bu.parse_years(bad)


def test_development_events_are_in_domain_positives_of_the_two_development_splits_in_the_season(tmp_path):
    def write(split, rows):
        pd.DataFrame(rows, columns=["cell_id", "date", "kind", "in_domain"]).assign(date=lambda d: pd.to_datetime(d["date"])
                                                                                   ).to_parquet(
            tmp_path / f"{split}_samples_features.parquet")
    write("train", [(1, "2010-07-01", "positive", True), (2, "2010-07-02", "positive", False),
                    (3, "2010-07-03", "negative", True), (4, "2010-05-31", "positive", True),
                    (5, "2010-10-01", "positive", True), (6, "2010-09-30", "positive", True)])
    write("validation", [(7, "2017-06-01", "positive", True), (8, "2018-06-01", "positive", True)])
    events = bu.development_events(directory=tmp_path)
    assert events["cell_id"].tolist() == [1, 6, 7] and events["split"].tolist() == ["train", "train", "validation"]
    assert bu.development_events(years=(2017,), directory=tmp_path)["cell_id"].tolist() == [7]


# ------------------------------------------------------------------------------------------------- levels

def panel(risk, upper=None, raw=None):
    risk = np.asarray(risk, dtype=np.float64)
    upper = risk.copy() if upper is None else np.asarray(upper, dtype=np.float64)
    return bu.Scores(np.zeros(risk.shape, dtype=np.float32) if raw is None else raw, risk,
                     {"p90": upper, "p75": np.minimum(upper, risk * 1.1 + 1e-12), "p60": risk})


DAYS = [date(2018, 6, 1) + timedelta(days=k) for k in range(6)]


def test_each_rule_adds_one_step_to_the_levels():
    cells = CELLS.iloc[[0, 1, 2]].assign(region=["himalaya", "western_ghats", "himalaya"]).reset_index(drop=True)
    risk = [[0.0, 0.9, 0.0, 0.0, 0.0, 0.0],        # himalaya: Warning on day 1, then falls away
            [0.35, 0.35, 0.35, 0.0, 0.0, 0.0],     # ghats: 0.35 is Watch (its Watch is 0.3)
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]]
    upper = np.array(risk)
    upper[2, 3] = 0.6                              # only the upper bound reaches Watch (0.5)
    scores = panel(risk, upper)
    raw = bu.season_levels(scores, cells, DAYS, THRESHOLDS, bu.OFF, None)
    assert raw.tolist() == [[0, 2, 0, 0, 0, 0], [1, 1, 1, 0, 0, 0], [0, 0, 0, 0, 0, 0]]
    flagged = bu.season_levels(scores, cells, DAYS, THRESHOLDS, "p90", None)
    assert flagged[2].tolist() == [0, 0, 0, 1, 0, 0] and flagged[:2].tolist() == raw[:2].tolist()
    held = bu.season_levels(scores, cells, DAYS, THRESHOLDS, "p90", (0.8, 2))
    assert held[0].tolist() == [0, 2, 2, 1, 1, 0]                   # a held Warning steps down one level per two quiet days
    assert (held >= flagged).all() and held.sum() > flagged.sum()
    quick = bu.season_levels(scores, cells, DAYS, THRESHOLDS, "p90", (1.0, 1))
    assert quick[0].tolist() == [0, 2, 1, 0, 0, 0] and (quick >= flagged).all() and quick.sum() <= held.sum()


def test_a_narrower_bound_flags_fewer_cells_and_off_flags_none():
    cells = CELLS.iloc[[0]].assign(region="himalaya").reset_index(drop=True)
    risk = np.array([[0.4, 0.4]])
    scores = bu.Scores(np.zeros((1, 2), dtype=np.float32), risk,
                       {"p90": np.array([[0.6, 0.6]]), "p75": np.array([[0.55, 0.45]]), "p60": np.array([[0.45, 0.45]])})
    watch = lambda bound: bu.season_levels(scores, cells, DAYS[:2], THRESHOLDS, bound, None)[0].tolist()
    assert watch("p90") == [1, 1] and watch("p75") == [1, 0] and watch("p60") == [0, 0] and watch(bu.OFF) == [0, 0]


def test_the_current_parameters_give_the_levels_the_backtest_computes():
    cells = CELLS.iloc[[0, 1]].assign(region=["himalaya", "western_ghats"]).reset_index(drop=True)
    scores = panel([[0.0, 0.9, 0.0, 0.0, 0.0, 0.0], [0.35, 0.35, 0.35, 0.0, 0.0, 0.0]], [[0.0, 0.9, 0.0, 0.6, 0.0, 0.0],
                                                                                    [0.35, 0.35, 0.35, 0.0, 0.0, 0.0]])
    mine = bu.season_levels(scores, cells, DAYS, THRESHOLDS, "p90", (0.8, 2))
    theirs = bt.engine_levels(bt.Panel(scores.raw, scores.risk, scores.upper["p90"]), cells, DAYS, THRESHOLDS, 0.8, 2)
    assert np.array_equal(mine, theirs)


# ------------------------------------------------------------------------------------------------ metrics

def test_bootstrap_se_is_seeded_and_matches_the_binomial_scale():
    flags = np.array([True] * 40 + [False] * 10)
    assert bu.bootstrap_se(flags) == bu.bootstrap_se(flags)
    assert bu.bootstrap_se(flags) == pytest.approx(np.sqrt(0.8 * 0.2 / 50), rel=0.15)
    assert bu.bootstrap_se(np.array([True])) is None and bu.bootstrap_se(np.ones(5, dtype=bool)) == 0.0


def stats_for(levels, events, universe=None, days=None):
    levels = np.asarray(levels, dtype=np.int8)
    days = days or [date(2018, 6, 1) + timedelta(days=k) for k in range(levels.shape[1])]
    return bu.season_stats(levels, np.ones(levels.shape, dtype=bool),
                           np.ones(len(levels), dtype=bool) if universe is None else np.asarray(universe),
                           np.arange(1, len(levels) + 1), days, events, 3)


def test_season_stats_count_shares_over_universe_cells_and_events_over_all_cells():
    levels = [[0, 1, 2, 3], [0, 0, 0, 1], [1, 1, 1, 1]]
    events = pd.DataFrame({"cell_id": [1, 3], "date": pd.to_datetime(["2018-06-04", "2018-06-02"]), "split": ["train", "validation"]})
    stats = stats_for(levels, events, universe=[True, True, False])
    assert stats["cell_days"] == 8 and stats["watch"] == 4 and stats["warning"] == 2 and stats["emergency"] == 1
    assert [e["own_detected"] for e in stats["events"]] == [True, True]            # the non-universe cell is still an event cell
    assert [e["split"] for e in stats["events"]] == ["train", "validation"]


def test_combined_seasons_add_up_and_report_detection_with_its_standard_error():
    events = lambda day: pd.DataFrame({"cell_id": [1], "date": pd.to_datetime([day]), "split": ["train"]})
    by_year = {2008: stats_for([[0, 0, 1], [0, 0, 0]], events("2018-06-03")),
               2007: stats_for([[1, 1, 1], [0, 2, 0]], events("2018-06-02"))}
    out = bu.combine_seasons(by_year)
    assert out["cell_days"] == 12 and out["watch_plus_share"] == pytest.approx(5 / 12)
    assert out["warning_plus_share"] == pytest.approx(1 / 12) and out["emergency_share"] == 0.0
    assert out["watch_plus_share_by_year"] == {2007: pytest.approx(4 / 6), 2008: pytest.approx(1 / 6)}
    assert out["n_events"] == 2 and out["own_day"]["hits"] == 2 and out["own_day"]["se"] == 0.0
    assert out["median_lead_days"] == 0.5 and out["own_day_by_split"]["train"]["n"] == 2
    assert out["flapping"]["n_flaps"] == 0 and out["flapping"]["n_changes"] == 3


def test_a_set_without_events_still_reports_the_burden():
    out = bu.combine_seasons({2007: stats_for([[1, 0]], pd.DataFrame({"cell_id": [], "date": pd.to_datetime([])}))})
    assert out["n_events"] == 0 and out["own_day"] is None and out["watch_plus_share"] == 0.5


# ------------------------------------------------------------------------------------------ grid and choice

def test_the_grid_is_small_starts_with_the_current_parameters_and_has_no_duplicates():
    grid = bu.grid_configs((0.8, 2))
    assert len(grid) == 24 <= bu.MAX_COMBINATIONS and grid[0]["key"] == "p90|0.8|2"
    assert len({c["key"] for c in grid}) == len(grid)
    assert {c["bound"] for c in grid} == {"p90", "p75", "p60", "off"}
    with pytest.raises(ValueError, match="not on the grid"):
        bu.grid_configs((0.7, 2))


def test_the_decomposition_runs_from_the_point_rule_to_the_full_levels():
    steps = bu.decomposition_configs((0.8, 2))
    assert [c["key"] for c in steps] == ["off|none", "p90|none", "p90|1|2", "p90|0.8|2", "off|0.8|2"]
    assert bu.hysteresis_of(steps[0]) is None and bu.hysteresis_of(steps[3]) == (0.8, 2)


def result(key, share, hits, lead=7.0):
    return {"config": {"key": key}, "watch_plus_share": share, "own_day": {"hits": hits}, "median_lead_days": lead}


def test_the_choice_is_the_smallest_burden_that_loses_no_detection_and_no_lead():
    results = [result("now", 0.50, 100), result("fewer-hits", 0.30, 99), result("shorter-lead", 0.35, 100, 5.0),
               result("better", 0.45, 101), result("best", 0.40, 100), result("tie", 0.40, 100)]
    assert bu.choose(results, "now")["config"]["key"] == "best"
    assert bu.choose(results[:3], "now")["config"]["key"] == "now"                 # nothing admissible beats the current
    assert bu.choose([result("now", 0.5, 10, None), result("x", 0.4, 10, None)], "now")["config"]["key"] == "x"
    assert bu.choose([result("now", 0.5, 10, 3.0), result("x", 0.4, 10, None)], "now")["config"]["key"] == "now"


def test_the_grid_search_space_never_exceeds_the_protocol_even_with_every_option():
    assert len(list(itertools.product(*bu.GRID.values()))) <= bu.MAX_COMBINATIONS


# --------------------------------------------------------------------------------------------- the config

def fake_result(key, bound, factor, days, share, hits):
    return {"config": {"key": key, "bound": bound, "exit_factor": factor, "exit_days": days}, "watch_plus_share": share,
            "warning_plus_share": share / 2, "emergency_share": share / 4, "n_events": 100,
            "own_day": {"hits": hits, "value": hits / 100, "se": 0.03}, "median_lead_days": 7.0,
            "flapping": {"flaps_per_1000_cell_days": 5.0}}


def test_the_v3_config_takes_the_chosen_exit_rule_and_keeps_the_rederived_data_values():
    from alerts_helpers import CONFIG
    now, best = fake_result("p90|0.8|2", "p90", 0.8, 2, 0.6, 90), fake_result("p90|0.9|1", "p90", 0.9, 1, 0.5, 91)
    analysis = {"protocol": {"period": "dev"}, "selection": {"chosen_key": best["config"]["key"]}, "grid_spec": {"exit_days": [1, 2]},
                "current": now, "chosen": best, "grid": [now, best]}
    derived = (replace(CONFIG, dis_ratio_hi=CONFIG.dis_ratio_hi), {"n_universe_rows": 5, "created_utc": "x"})
    config, record = bu.v3_alert_config(analysis, CONFIG, derived)
    assert (config.exit_factor, config.exit_days) == (0.9, 1)
    assert {k: getattr(config, k) for k in bu.DATA_DERIVED} == {k: getattr(CONFIG, k) for k in bu.DATA_DERIVED}
    rederivation = record["structural_rederivation"]
    assert rederivation["previous"] == {"exit_factor": 0.8, "exit_days": 2, "uncertain_percentile": 90.0}
    assert rederivation["chosen"] == {"exit_factor": 0.9, "exit_days": 1, "uncertain_percentile": 90.0}
    assert rederivation["development_after"]["own_day_hits"] == 91 and len(rederivation["all_combinations"]) == 2
    assert all(rederivation["data_derived_values_equal_to_previous"].values()) and record["n_universe_rows"] == 5
    changed = bu.v3_alert_config(analysis, CONFIG, (replace(CONFIG, heavy_acc1_mm=50.0), {}))[1]
    assert changed["structural_rederivation"]["data_derived_values_equal_to_previous"]["heavy_acc1_mm"] is False


# ------------------------------------------------------------------------------------- out-of-fold scoring

@pytest.fixture(scope="module")
def tiny_world(tmp_path_factory):
    from aetherguard.hazard import train as tr
    from hazard_helpers import synthetic_development, write_dev_store
    from test_hazard_train import tiny_cfg
    root = tmp_path_factory.mktemp("oof")
    samples, universe = synthetic_development(n_pos_train=110, n_pos_validation=50, n_per_region=2500)
    store = write_dev_store(root / "features", samples, universe)
    cfg = tiny_cfg()
    return tr.train(store, root / "model", cfg, report_dir=root / "reports"), cfg, store


def test_fold_models_reproduce_the_out_of_fold_recall_the_card_reports(tiny_world):
    model, cfg, store = tiny_world
    models, check = bu.fold_models(model, cfg, store)
    assert sorted(models) == list(range(2007, 2018))
    assert check["oof_recall_at_watch"] == check["card_oof_recall_at_watch"] and check["positives"] > 100
    assert models[2007] is models[2008] and models[2007] is not models[2009]              # one model per fold
    assert models[2016].calibrator is model.calibrator and models[2016].card == model.card
    assert models[2016].best_iteration == model.best_iteration and len(models[2016].members) == len(model.members)


def test_fold_models_do_not_score_their_own_fold_like_the_final_model(tiny_world):
    model, cfg, store = tiny_world
    models, _ = bu.fold_models(model, cfg, store)
    positives = bu.hd.load_development(store, cfg["extra_groups"], bu.extra_groups_used(cfg), cfg["meta_columns"]).positives
    held = positives[positives["year"] == 2016]
    assert not np.array_equal(models[2016].raw_score(held), model.raw_score(held))
    assert np.mean(model.raw_score(held)) > np.mean(models[2016].raw_score(held)) - 1e-9        # in-sample is not lower


def test_the_out_of_fold_cells_are_the_event_cells_plus_a_seeded_universe_sample():
    cells = tiny_cells().iloc[[0, 1, 2, 3]].assign(in_universe=[True, True, True, False])
    events = pd.DataFrame({"cell_id": [int(cells["cell_id"].iloc[3])]})
    first = bu.sample_cells(events, cells, 1, seed=3)
    assert first["cell_id"].tolist() == bu.sample_cells(events, cells, 1, seed=3)["cell_id"].tolist()
    assert len(first) == 2 and int(cells["cell_id"].iloc[3]) in first["cell_id"].tolist()
    assert first["in_universe"].sum() == 1 and not first.loc[first["cell_id"] == events["cell_id"].iloc[0], "in_universe"].any()
    everything = bu.sample_cells(events, cells, 99, seed=3)
    assert sorted(everything["cell_id"]) == sorted(cells["cell_id"]) and everything["in_universe"].tolist().count(True) == 3


def test_a_loss_tolerance_widens_only_the_costed_alternative():
    results = [result("now", 0.50, 100), result("lose-two", 0.40, 98), result("lose-five", 0.30, 95)]
    assert bu.choose(results, "now")["config"]["key"] == "now"
    assert bu.choose(results, "now", allowed_loss=2)["config"]["key"] == "lose-two"
    assert bu.choose(results, "now", allowed_loss=5)["config"]["key"] == "lose-five"


def test_the_bound_names_map_to_the_ensemble_percentile_of_the_config():
    from alerts_helpers import CONFIG
    assert bu.bound_percentile("p75") == 75.0 and bu.bound_percentile("p90") == 90.0 and bu.bound_percentile("off") is None
    analysis = {"protocol": {}, "selection": {}, "grid_spec": {}, "current": fake_result("p90|0.8|2", "p90", 0.8, 2, 0.6, 90),
                "chosen": fake_result("p90|0.8|2", "p90", 0.8, 2, 0.6, 90),
                "alternative": fake_result("p60|1|2", "p60", 1.0, 2, 0.5, 88), "grid": []}
    config, record = bu.v3_alert_config(analysis, CONFIG, (CONFIG, {}), "alternative")
    assert (config.exit_factor, config.exit_days, config.uncertain_percentile) == (1.0, 2, 60.0)
    assert record["structural_rederivation"]["chosen"]["uncertain_percentile"] == 60.0
    off = dict(analysis, alternative=fake_result("off|1|1", "off", 1.0, 1, 0.5, 88))
    assert bu.v3_alert_config(off, CONFIG, (CONFIG, {}), "alternative")[0].uncertain_percentile is None
