"""The operational backtest: features built exactly as the live run builds them and never from anything issued after the
11:00 IST cut-off, and its metrics against a toy store with a known answer. Hermetic: fake IMERG stores, a stub model."""
import json
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from aetherguard.alerts import levels as lv
from aetherguard.grid import neighbours
from aetherguard.live import backtest as bt
from aetherguard.live.early_map import IdentityMap
from aetherguard.live.sources import PERSIST, ImergSource
from aetherguard.ingest import imerg

from alerts_helpers import CONFIG as ALERT_CONFIG
from live_run_helpers import FakeStore, make_cfg, span, tiny_cells, tiny_clim

HUGE = 9999.0
EVENT = date(2026, 8, 12)           # the toy event day
CELLS = tiny_cells()
WAYANAD, IDUKKI, KATHMANDU, CHAMOLI = (int(c) for c in CELLS["cell_id"])


def make_stores(tmp_path, late=None, early=None, tail=None, early_heavy=(), late_heavy=()):
    """Fake Late / Early stores around the toy event day. Overrides replace the whole field of a UTC day (planted)."""
    cfg = make_cfg(tmp_path)
    late_store = FakeStore(span(EVENT - timedelta(days=300), EVENT + timedelta(days=8)), late_heavy, late)
    early_store = FakeStore(span(EVENT - timedelta(days=15), EVENT + timedelta(days=8)), early_heavy, early)
    return bt.Stores(cfg, ImergSource("late", late_store, latency_h=14.5, window_days=130),
                     ImergSource("early", early_store, latency_h=4.5, window_days=130, mapping=IdentityMap()),
                     tiny_clim(CELLS), tail or (lambda day, ctx: bt.TailResult(None, PERSIST, "toy: no GFS")))


class StubModel:
    """risk = 1-day rain / 100 mm, raw score = the 1-day rain: the known-answer model of the toy backtest."""
    columns = ["irain_acc_1"]
    card = {"alert_levels": {"watch": {"raw": 50.0, "risk": 0.5}, "warning": {"raw": 80.0, "risk": 0.8},
                             "emergency": {"raw": 95.0, "risk": 0.95}}}

    def raw_score(self, frame):
        return frame["irain_acc_1"].to_numpy(dtype=np.float64)

    def score(self, frame):
        risk = np.clip(frame["irain_acc_1"].to_numpy(dtype=np.float64) / 100.0, 0.0, 1.0)
        return pd.DataFrame({"risk": risk, "risk_lo": risk, "risk_hi": risk, "risk_per_100k": 1e5 * risk},
                            index=frame.index)


# ------------------------------------------------------------------------------- nothing after the cut-off

def test_features_at_day_d_do_not_change_when_values_after_the_cutoff_are_planted(tmp_path):
    """Late for UTC D-1 and D (published after the run), Early for UTC D (and later days) and Late of D+1 are planted
    huge; the features at D must be the unplanted ones. Early for UTC D-1 and Late for D-2 ARE inputs."""
    base = bt.operational_features(EVENT, CELLS, make_stores(tmp_path))
    assert base["irain_acc_1"].notna().all() and base["irain_acc_90"].notna().all()
    planted = bt.operational_features(EVENT, CELLS, make_stores(
        tmp_path,
        late={EVENT - timedelta(days=1): HUGE, EVENT: HUGE, EVENT + timedelta(days=1): HUGE},
        early={EVENT: HUGE, EVENT + timedelta(days=1): HUGE}))
    pd.testing.assert_frame_equal(planted, base)
    late_input = bt.operational_features(EVENT, CELLS, make_stores(tmp_path, late={EVENT - timedelta(days=2): HUGE}))
    early_input = bt.operational_features(EVENT, CELLS, make_stores(tmp_path, early={EVENT - timedelta(days=1): HUGE}))
    assert (late_input["irain_acc_3"] > base["irain_acc_3"] + 100).all()
    assert (early_input["irain_acc_1"] > base["irain_acc_1"] + 100).all()


def test_each_utc_day_comes_from_the_run_the_live_construction_names(tmp_path):
    view, tail = bt.operational_view(EVENT, make_stores(tmp_path))
    assert view.product(EVENT - timedelta(days=3)) == "late" and view.product(EVENT - timedelta(days=2)) == "late"
    assert view.product(EVENT - timedelta(days=1)) == "early"
    assert view.product(EVENT) == PERSIST and tail.product == PERSIST and view.product(EVENT + timedelta(days=1)) == "missing"
    assert view.imd_day_inputs()["D"]["product"] == "early+persist_d1"
    assert view.imd_day_inputs()["D-1"]["product"] == "late+early"


def test_a_day_whose_early_granule_is_not_stored_has_no_operational_features(tmp_path):
    stores = make_stores(tmp_path)
    stores.early.store.days.discard(EVENT - timedelta(days=1))
    features = bt.operational_features(EVENT, CELLS, stores)
    assert features["irain_acc_1"].isna().all() and features["irain_acc_90"].isna().all()
    assert bt.training_style_features(EVENT, CELLS, stores)["irain_acc_1"].notna().all()


def test_training_style_features_use_the_whole_late_day_d(tmp_path):
    stores = make_stores(tmp_path, late={EVENT: 80.0, EVENT - timedelta(days=1): 0.0})
    style = bt.training_style_features(EVENT, CELLS, stores)
    assert style["irain_acc_1"].to_numpy() == pytest.approx(0.125 * 80.0)
    live = bt.operational_features(EVENT, CELLS, make_stores(tmp_path, late={EVENT: 80.0}))
    assert live["irain_acc_1"].to_numpy() == pytest.approx(2.0)      # the same Late values never reach the live run


def test_the_gfs_tail_is_used_when_issued_before_the_cutoff_and_persistence_otherwise(tmp_path, monkeypatch):
    root = tmp_path / "gfs"
    path = root / "raw" / "gfs" / "archive" / f"{EVENT:%Y%m%d}00" / bt.ARCHIVE_TAIL_FILE
    cfg = make_cfg(tmp_path)
    ctx = bt.make_context(EVENT, cfg, None, True)
    grid = np.full((imerg.ROWS, imerg.COLS), 4.0, dtype=np.float32)
    monkeypatch.setattr(bt, "read_accumulation", lambda *args: grid)
    tail = bt.archive_tail(root, {"lat_min": 8.0}, 3.6)
    assert tail(EVENT, ctx).product == PERSIST and "no 00Z cycle" in tail(EVENT, ctx).note
    path.parent.mkdir(parents=True)
    path.write_bytes(b"grib")
    got = tail(EVENT, ctx)
    assert got.product == "gfs_00z_0_3h" and got.first_hours is grid
    late = bt.archive_tail(root, {"lat_min": 8.0}, 10.0)(EVENT, ctx)         # 00Z + 10 h = 10:00 UTC, after 05:30 UTC
    assert late.product == PERSIST and "after the cut-off" in late.note
    stores = make_stores(tmp_path, tail=tail)
    view, _ = bt.operational_view(EVENT, stores)
    assert view.product(EVENT) == "gfs_00z_0_3h"
    feature = bt.operational_features(EVENT, CELLS, stores)["irain_acc_1"].to_numpy()
    assert feature == pytest.approx(0.875 * 2.0 + 4.0)           # 0.875 x light Early D-1 + the 0-3 h GFS rain itself


# ------------------------------------------------------------------------------------------ levels and events

def test_engine_levels_use_the_region_threshold_hysteresis_and_uncertain_high():
    cells = pd.DataFrame({"cell_id": [1, 2, 3], "region": ["himalaya", "western_ghats", "himalaya"]})
    days = [date(2018, 6, 1) + timedelta(days=k) for k in range(6)]
    nan = np.nan
    risk = np.array([[0.0, 0.9, 0.0, 0.0, 0.0, 0.0],          # himalaya: Warning on day 1, then falls away
                     [0.35, 0.35, 0.35, 0.0, 0.0, 0.0],       # ghats: 0.35 is Watch under its own threshold (0.3)
                     [0.0, nan, 0.9, nan, 0.0, 0.0]])
    hi = risk.copy()
    hi[0, 4] = 0.6                                            # upper bound reaches Watch (0.5) with point risk below it
    panel = bt.Panel(risk.astype(np.float32), risk, hi)
    thresholds = {"himalaya": lv.Thresholds(0.5, 0.8, 0.95, "t"), "western_ghats": lv.Thresholds(0.3, 0.8, 0.95, "t")}
    levels = bt.engine_levels(panel, cells, days, thresholds, exit_factor=0.8, exit_days=2)
    assert levels[0].tolist() == [0, 2, 2, 1, 1, 1]           # Warning held one day, Watch on the uncertain_high day, held
    assert levels[1].tolist() == [1, 1, 1, 1, 0, 0]           # 0.35 is Watch under the ghats threshold 0.3
    assert levels[2].tolist() == [0, 0, 2, 2, 2, 1]           # a day without a score never steps a level down
    pooled = bt.engine_levels(panel, cells, days, {"*": thresholds["himalaya"]}, 0.8, 2)
    assert pooled[1].tolist() == [0, 0, 0, 0, 0, 0] and pooled[0].tolist() == levels[0].tolist()


def test_event_outcomes_report_own_cell_footprint_lead_and_unscored_events():
    days = [date(2018, 8, 1) + timedelta(days=k) for k in range(12)]
    own, neighbour, quiet = 24165144, neighbours(24165144)[0], 24175140
    cell_ids = np.array([own, neighbour, quiet])
    levels = np.zeros((3, 12), dtype=np.int8)
    levels[0, 5:9] = 1                                         # own cell: Watch+ on days 5..8
    levels[1, 10] = 1                                          # neighbour only, on the second event's day
    scored = np.ones((3, 12), dtype=bool)
    scored[2, 8] = False
    events = pd.DataFrame({"cell_id": [own, own, quiet, quiet], "date": pd.to_datetime(
        ["2018-08-09", "2018-08-11", "2018-08-09", "2018-08-05"])})
    table = bt.event_outcomes(levels, scored, cell_ids, days, events)
    first, second, unscored, quiet_row = table.to_dict("records")
    assert first["own_detected"] and first["own_lead_days"] == 3 and first["own_alert_days_before"] == 3
    assert not second["own_detected"] and second["footprint_detected"] and second["scored"]
    assert second["own_lead_days"] == 5 and second["own_alert_days_before"] == 0
    assert not unscored["scored"] and not unscored["own_detected"] and quiet_row["scored"]
    summary = bt.summarize_events(table)
    assert summary["n_events"] == 4 and summary["n_unscored"] == 1
    assert summary["own"]["detected_of_all_events"]["hits"] == 1 and summary["own"]["detected_of_all_events"]["n"] == 4
    assert summary["own"]["detected_of_scored_events"]["n"] == 3
    assert summary["footprint"]["detected_of_all_events"]["hits"] == 2


def test_alert_share_counts_only_scored_cells_and_mean_ci_is_a_seeded_bootstrap():
    levels = np.array([[1, 0, 2], [0, 0, 3], [1, 1, 0], [0, 0, 0]], dtype=np.int8)
    scored = np.array([[1, 1, 1], [1, 1, 1], [1, 1, 0], [0, 0, 0]], dtype=bool)
    share = bt.alert_share(levels, scored)
    assert share.tolist() == [2 / 3, 1 / 3, 1.0]
    assert np.isnan(bt.alert_share(np.zeros((2, 1), dtype=np.int8), np.zeros((2, 1), dtype=bool))[0])
    assert bt.alert_share(levels, scored, 2).tolist() == [0, 0, 1.0]
    a, b = bt.mean_ci(share), bt.mean_ci(share)
    assert a == b and a["lo"] <= a["value"] <= a["hi"] and a["n_days"] == 3 and bt.mean_ci(np.array([np.nan]))["value"] is None


# ----------------------------------------------------------------------------------- the toy backtest

def toy_spec(kind="season", events=True, window_frame=None, focus=None):
    pairs = [(WAYANAD, EVENT), (IDUKKI, EVENT)] if events else []
    return bt.BacktestSet("toy", EVENT - timedelta(days=2), EVENT + timedelta(days=5), CELLS,
                          pd.DataFrame({"cell_id": [c for c, _ in pairs], "date": pd.to_datetime([d for _, d in pairs])})
                          if events else None, kind, window_frame=window_frame, focus=focus)


@pytest.fixture(scope="module")
def toy(tmp_path_factory):
    """Heavy rain near Wayanad on UTC day EVENT-1 in the Early run only; the Late run (training-style) saw none."""
    stores = make_stores(tmp_path_factory.mktemp("toy"), early_heavy=[EVENT - timedelta(days=1)])
    return bt.run_set(toy_spec(), StubModel(), stores, ALERT_CONFIG)


def test_toy_inputs_record_the_product_behind_every_day_and_the_persistence_share(toy):
    inputs = toy["inputs"]
    assert inputs["days"] == 8 and inputs["persist_d1_days"] == 8 and inputs["persist_d1_share"] == 1.0
    assert inputs["tail_products"] == {PERSIST: 8} and inputs["utc_d-1_products"] == {"early": 8}
    assert inputs["days_without_operational_scores"] == 0
    assert [d["date"] for d in toy["days"]][0] == (EVENT - timedelta(days=2)).isoformat()
    assert toy["days"][2]["input_D"]["product"] == "early+persist_d1"
    assert toy["days"][2]["scored_cells"] == {"operational": 4, "training_style": 4}


def test_toy_operational_alert_levels_and_shares_have_the_known_values(toy):
    engine = toy["variants"]["operational"]["region"]["engine"]
    # Wayanad: 90 mm on the event day only -> risk 0.9, Warning; hysteresis: Warning 2 days, Watch 2 days, then Normal
    assert engine["alert_share_watch_plus"]["mean_daily_share"]["value"] == pytest.approx(4 * 0.25 / 8)
    assert engine["alert_share_watch_plus"]["max_daily_share"] == 0.25
    assert engine["alert_share_warning_plus"]["mean_daily_share"]["value"] == pytest.approx(2 * 0.25 / 8)
    assert engine["alert_share_emergency"]["mean_daily_share"]["value"] == 0.0
    assert engine["alert_share_by_region"] == {"himalaya": 0.0, "western_ghats": pytest.approx(4 * 0.5 / 8)}
    raw = toy["variants"]["operational"]["region"]["raw_watch"]
    assert raw["alert_share_watch_plus"]["mean_daily_share"]["value"] == pytest.approx(0.25 / 8)
    for rule in ("raw_watch", "engine"):
        assert toy["variants"]["training_style"]["region"][rule]["alert_share_watch_plus"]["max_daily_share"] == 0.0


def test_toy_event_detection_and_lead_time_have_the_known_values(toy):
    for rule in ("raw_watch", "engine"):
        events = toy["variants"]["operational"]["region"][rule]["events"]
        assert events["n_events"] == 2 and events["n_scored"] == 2
        assert events["own"]["detected_of_all_events"]["hits"] == 1 and events["own"]["median_lead_days"] == 0.0
        by_cell = {e["cell_id"]: e for e in toy["variants"]["operational"]["region"][rule]["event_table"]}
        assert by_cell[WAYANAD]["own_detected"] and by_cell[WAYANAD]["own_lead_days"] == 0
        assert not by_cell[IDUKKI]["own_detected"] and not by_cell[IDUKKI]["footprint_detected"]
        training = toy["variants"]["training_style"]["region"][rule]["events"]
        assert training["own"]["detected_of_all_events"]["hits"] == 0
        assert toy["gap"]["modes"]["region"][rule]["paired_events_own"] == {
            "both": 0, "only_operational": 1, "only_training_style": 0, "neither": 1}


def test_toy_gap_is_operational_minus_training_style(toy):
    gap = toy["gap"]["modes"]["region"]
    assert gap["engine"]["alert_share_difference"]["value"] == pytest.approx(4 * 0.25 / 8)
    assert gap["raw_watch"]["alert_share_difference"]["value"] == pytest.approx(0.25 / 8)
    assert gap["raw_watch"]["watch_set_agreement_jaccard"] == pytest.approx(0.0)
    assert toy["gap"]["mean_abs_diff_irain_acc_1_mm"] > 0
    assert toy["gap"]["modes"]["pooled"]["engine"]["alert_share_difference"]["value"] == pytest.approx(4 * 0.25 / 8)


def test_a_gfs_tail_day_is_not_counted_as_persisted(tmp_path):
    grid = np.zeros((imerg.ROWS, imerg.COLS), dtype=np.float32)
    stores = make_stores(tmp_path, early_heavy=[EVENT - timedelta(days=1)], tail=lambda day, ctx: (
        bt.TailResult(grid, "gfs_00z_0_3h") if day >= EVENT else bt.TailResult(None, PERSIST, "toy")))
    result = bt.run_set(toy_spec(), StubModel(), stores, ALERT_CONFIG)
    assert result["inputs"]["persist_d1_days"] == 2 and result["inputs"]["persist_d1_share"] == 0.25
    assert result["inputs"]["tail_products"] == {PERSIST: 2, "gfs_00z_0_3h": 6}
    # a zero GFS tail removes the persisted heavy 0-3 h rain: acc_1 = 0.875 x 90 = 78.75 -> risk 0.7875, below Warning (0.8)
    engine = result["variants"]["operational"]["region"]["engine"]["event_table"]
    assert next(e for e in engine if e["cell_id"] == WAYANAD)["own_level"] == 1


def test_window_set_scores_the_window_positive_cells_by_their_neighbourhood_maximum(tmp_path):
    frame = pd.DataFrame({"cell_id": np.repeat(CELLS["cell_id"].to_numpy(), 8),
                          "date": np.tile(pd.date_range(EVENT - timedelta(days=2), periods=8), 4),
                          "kind": np.repeat(["window_cell", "window_control", "window_control", "window_control"], 8),
                          "is_window_positive_cell": np.repeat([True, False, False, False], 8)})
    stores = make_stores(tmp_path, early_heavy=[EVENT - timedelta(days=1)])
    result = bt.run_set(toy_spec("window", events=False, window_frame=frame), StubModel(), stores, ALERT_CONFIG)
    test = result["variants"]["operational"]["region"]["raw_watch"]["window_test"]
    assert test["positive_cells"] == 1 and test["detection"]["hits"] == 1 and test["control_cells"] == 3
    assert test["control_any_alert"]["hits"] == 0 and test["threshold"] == 50.0
    assert result["variants"]["training_style"]["region"]["raw_watch"]["window_test"]["detection"]["hits"] == 0
    assert result["variants"]["operational"]["region"]["engine"]["window_test"]["threshold"] == 1.0


def test_case_series_set_reports_the_first_watch_day_of_the_focus_cell(tmp_path):
    stores = make_stores(tmp_path, early_heavy=[EVENT - timedelta(days=1)])
    focus = (11.55, 76.15)
    result = bt.run_set(toy_spec("case_series", events=False, focus=focus), StubModel(), stores, ALERT_CONFIG)
    metrics = result["variants"]["operational"]["region"]["engine"]["series"]["metrics"]
    assert metrics["first_watch_plus"]["focus"] == EVENT.isoformat() and metrics["first_warning_plus"]["focus"] == EVENT.isoformat()
    training = result["variants"]["training_style"]["region"]["engine"]["series"]["metrics"]
    assert training["first_watch_plus"]["focus"] is None


def test_run_backtest_takes_the_set_stores_and_model_it_is_given(tmp_path):
    stores = make_stores(tmp_path, early_heavy=[EVENT - timedelta(days=1)])
    spec = toy_spec()
    result = bt.run_backtest(spec.start, spec.end, spec=spec, stores=stores, model=StubModel(), alert_config=ALERT_CONFIG,
                             cfg=make_cfg(tmp_path))
    assert result["set"] == "toy" and result["n_cells"] == 4 and result["n_days"] == 8 and result["warmup_days"] == bt.WARMUP_DAYS


def test_load_set_rejects_an_unknown_name():
    with pytest.raises(ValueError, match="unknown backtest set"):
        bt.load_set("season_2026")


# ----------------------------------------------------------------------------------------------- report

def test_reports_are_strict_json_and_markdown_states_the_gap_and_the_persistence_share(toy, tmp_path):
    from aetherguard.live import backtest_report as br
    results = {"toy": toy}
    meta = {"model_dir": "model_v3_live", "created_utc": "2026-10-15T00:00:00Z", "model_card_sha256": "0" * 64}
    json_path, md_path = br.write_reports(results, meta, tmp_path, "toy_backtest")
    json.loads(json_path.read_text(), parse_constant=lambda c: pytest.fail(f"non-strict constant {c}"))
    text = md_path.read_text(encoding="utf-8")
    assert "persist_d1" in text and "100.0%" in text and "operational" in text and "training-style" in text
    assert "train/live gap" in text.lower()
    saved = json.loads(json_path.read_text())
    assert saved["sets"]["toy"]["inputs"]["persist_d1_share"] == 1.0
    assert saved["sets"]["toy"]["gap"]["modes"]["region"]["engine"]["alert_share_difference"]["value"] == pytest.approx(0.125)


def test_real_stores_are_built_from_local_files_with_a_cached_climatology(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    stores = bt.build_stores(CELLS, cfg, root=tmp_path / "data")
    assert stores.late.run == "late" and stores.early.run == "early" and isinstance(stores.early.mapping, IdentityMap)
    cache = tmp_path / "data" / "processed" / "live_backtest" / "imerg_climatology.npz"
    assert cache.is_file() and len(stores.clim.pix) == len(np.unique(bt.F.cell_pixels(CELLS["cell_id"].to_numpy())))
    monkeypatch.setattr(bt.F, "imerg_climatology", lambda *args, **kwargs: pytest.fail("climatology was recomputed"))
    again = bt.build_stores(CELLS, cfg, root=tmp_path / "data")
    assert np.array_equal(again.clim.pix, stores.clim.pix) and np.array_equal(again.clim.values, stores.clim.values,
                                                                              equal_nan=True)
    assert stores.tail(EVENT, bt.make_context(EVENT, cfg, None, True)).product == PERSIST      # no GFS archive under tmp


def test_chance_rate_is_the_share_of_cell_days_with_a_watch_day_in_the_last_week():
    levels = np.zeros((2, 10), dtype=np.int8)
    levels[0, 3] = 1
    scored = np.ones((2, 10), dtype=bool)
    # three 8-day spans (ending on days 7, 8, 9) x two cells; cell 0's Watch day 3 lies in all three, cell 1 has none
    assert bt.chance_alert_within(levels, scored) == pytest.approx(3 / 6)
    assert bt.chance_alert_within(levels[:, :7], scored[:, :7]) is None
    assert bt.chance_alert_within(levels, np.zeros_like(scored)) == 0.0


def test_toy_report_carries_the_chance_rate(toy):
    entry = toy["variants"]["operational"]["region"]["engine"]
    assert entry["chance_watch_within_7d"] is not None and 0 <= entry["chance_watch_within_7d"] <= 1


def test_matrix_flapping_agrees_with_the_alert_table_flapping_and_ignores_unscored_days():
    from aetherguard.alerts import evaluate as alert_eval
    rng = np.random.default_rng(5)
    levels = rng.choice([0, 0, 1, 2, 3], size=(40, 30)).astype(np.int8)
    scored = np.ones(levels.shape, dtype=bool)
    table = pd.DataFrame({"cell_id": np.repeat(np.arange(40), 30), "date": np.tile(pd.date_range("2018-06-01", periods=30), 40),
                          "level": levels.ravel()})
    expected = alert_eval.flapping(table, "level", 3)
    got = bt.flapping(levels, scored, 3)
    assert got["n_changes"] == expected["n_changes"] and got["n_flaps"] == expected["n_flaps"] and got["cell_days"] == 1200
    assert got["flaps_per_1000_cell_days"] == pytest.approx(expected["flaps_per_1000_cell_days"])
    # on, off, off, on is one flap; an unscored day inside the gap means the gap is unknown and no flap is counted
    one = np.array([[1, 0, 0, 1, 1]], dtype=np.int8)
    assert bt.flapping(one, np.ones_like(one, dtype=bool), 3)["n_flaps"] == 1
    assert bt.flapping(one, np.array([[1, 0, 1, 1, 1]], dtype=bool), 3)["n_flaps"] == 0
    assert bt.flapping(one, np.ones_like(one, dtype=bool), 1)["n_flaps"] == 0              # the gap is longer than the window
    assert bt.flapping(np.zeros((2, 1), dtype=np.int8), np.ones((2, 1), dtype=bool), 3)["n_flaps"] == 0


def test_toy_report_carries_flapping(toy):
    entry = toy["variants"]["operational"]["region"]["engine"]["flapping"]
    assert entry["cell_days"] == 4 * 8 and entry["n_flaps"] == 0 and entry["n_changes"] > 0


def test_one_scoring_pass_can_be_evaluated_under_two_alert_configurations(tmp_path):
    from dataclasses import replace
    stores = make_stores(tmp_path, early_heavy=[EVENT - timedelta(days=1)])
    spec = toy_spec()
    scored = bt.score_days(bt.set_days(spec), spec.cells, StubModel(), stores)
    slow = bt.run_set(spec, StubModel(), stores, ALERT_CONFIG, scored=scored)
    quick = bt.run_set(spec, StubModel(), stores, replace(ALERT_CONFIG, exit_days=1), scored=scored)
    share = lambda r: r["variants"]["operational"]["region"]["engine"]["alert_share_watch_plus"]["mean_daily_share"]["value"]
    assert share(slow) == pytest.approx(4 * 0.25 / 8) and share(quick) == pytest.approx(2 * 0.25 / 8)   # Warning 1 day, Watch 1 day
    raw = lambda r: r["variants"]["operational"]["region"]["raw_watch"]["alert_share_watch_plus"]["mean_daily_share"]["value"]
    assert slow["days"] == quick["days"] and raw(slow) == raw(quick)             # the raw rule does not depend on the config
    assert share(bt.run_set(spec, StubModel(), stores, ALERT_CONFIG)) == share(slow)


# ------------------------------------------------------------------------------------ the uncertain_high bound

class BoundModel(StubModel):
    """The stub with an ensemble: the p-th percentile of a cell's risk is risk x (1 + p / 100)."""

    def ensemble_percentile(self, frame, percentile):
        return self.score(frame)["risk"].to_numpy() * (1 + percentile / 100.0)


def test_panels_keep_the_requested_ensemble_percentiles(tmp_path):
    panel = bt.new_panel(4, 1, percentiles=(75.0,))
    frame = pd.concat([CELLS, pd.DataFrame({"irain_acc_1": [20.0, 40.0, np.nan, 80.0], "irain_acc_3": [1.0, 1.0, np.nan, 1.0]})],
                      axis=1)
    assert bt.score_into(panel, 0, BoundModel(), frame, percentiles=(75.0,)) == 3
    assert panel.upper[75.0][:, 0][[0, 1, 3]].tolist() == pytest.approx([0.35, 0.7, 1.4])
    assert np.isnan(panel.upper[75.0][2, 0]) and bt.new_panel(4, 1).upper == {}


def test_engine_levels_flag_uncertain_high_against_the_bound_they_are_given():
    cells = pd.DataFrame({"cell_id": [1], "region": ["himalaya"]})
    days = [date(2018, 6, 1) + timedelta(days=k) for k in range(2)]
    risk = np.array([[0.4, 0.4]])
    panel = bt.Panel(risk.astype(np.float32), risk, risk.copy())
    thresholds = {"himalaya": lv.Thresholds(0.5, 0.8, 0.95, "t")}
    assert bt.engine_levels(panel, cells, days, thresholds, 0.8, 2)[0].tolist() == [0, 0]
    assert bt.engine_levels(panel, cells, days, thresholds, 0.8, 2, upper=np.array([[0.6, 0.45]]))[0].tolist() == [1, 1]


def test_the_alert_configuration_names_the_bound_the_levels_use():
    from dataclasses import replace
    cells = pd.DataFrame({"cell_id": [1], "region": ["himalaya"]})
    days = [date(2018, 6, 1), date(2018, 6, 2)]
    risk = np.array([[0.4, 0.4]])
    panel = bt.Panel(risk.astype(np.float32), risk, np.array([[0.6, 0.6]]), {75.0: np.array([[0.45, 0.6]])})
    model = StubModel()
    model.card = {"alert_levels": {k: {"raw": 1.0, "risk": v} for k, v in (("watch", 0.5), ("warning", 0.8), ("emergency", 0.95))}}
    engine = lambda **change: bt.rule_levels(panel, cells, days, model, replace(ALERT_CONFIG, **change), "pooled")["engine"][0].tolist()
    assert engine() == [1, 1]                                          # the 90th percentile (risk_hi) reaches Watch
    assert engine(uncertain_percentile=75.0, exit_days=1) == [0, 1]
    assert engine(uncertain_percentile=None) == [0, 0]
    with pytest.raises(ValueError, match="75"):
        bt.rule_levels(bt.Panel(risk.astype(np.float32), risk, risk.copy()), cells, days, model,
                       replace(ALERT_CONFIG, uncertain_percentile=75.0), "pooled")


def test_a_scoring_pass_serves_every_configuration_whose_percentile_it_holds(tmp_path):
    from dataclasses import replace
    stores = make_stores(tmp_path, early_heavy=[EVENT - timedelta(days=1)])
    spec = toy_spec()
    narrow = replace(ALERT_CONFIG, uncertain_percentile=75.0)
    scored = bt.score_days(bt.set_days(spec), spec.cells, BoundModel(), stores, percentiles=(75.0,))
    assert bt.run_set(spec, BoundModel(), stores, narrow, scored=scored)["n_days"] == 8
    plain = bt.score_days(bt.set_days(spec), spec.cells, BoundModel(), stores)
    with pytest.raises(ValueError, match="75"):
        bt.run_set(spec, BoundModel(), stores, narrow, scored=plain)
    assert bt.run_set(spec, BoundModel(), stores, narrow)["n_days"] == 8          # scored on demand when not handed in
