"""Forecast-rain selection and the scenario-certainty accuracy (aetherguard.live.forecast_select): the statistics, the
pre-declared decision rule and the evaluation loop on synthetic inputs (tests/live_run_helpers.py); no network."""
from datetime import date, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from aetherguard.alerts import levels as lv
from aetherguard.ingest import imerg
from aetherguard.live import forecast_choice as fc
from aetherguard.live import forecast_map as fm
from aetherguard.live import forecast_select as sel
from aetherguard.live import postrules as pr

import live_run_helpers as H
from alerts_helpers import CONFIG as ALERT_CONFIG

UTC = timezone.utc
N_PIX = imerg.ROWS * imerg.COLS


def test_candidates_are_three_sources_raw_and_bias_corrected_with_gfs_raw_as_baseline():
    assert [sel.key(c) for c in sel.CANDIDATES] == ["gfs", "gfs+map", "ecmwf_hres", "ecmwf_hres+map", "ecmwf_ens_mean",
                                                    "ecmwf_ens_mean+map"]
    assert sel.key(sel.BASELINE) == "gfs" and sel.config_of("ecmwf_hres+map") == fc.Config("ecmwf_hres", True)
    assert sel.config_of("gfs") == fc.GFS_RAW


def test_day_counts_count_pairs_agreement_and_the_watch_and_warning_splits():
    obs = np.array([0, 1, 2, 3, 0, 2])
    level = np.array([0, 1, 1, 3, 2, 2])
    both = np.array([True, True, True, True, True, False])
    counts = sel.day_counts(obs, level, both)
    assert dict(zip(sel.DAY_FIELDS, counts.tolist())) == {
        "n": 5, "same": 3, "within_one": 4, "obs_watch": 3, "hit_watch": 3, "fc_watch": 4,
        "obs_warning": 2, "hit_warning": 1, "fc_warning": 2}


def test_pooled_metrics_and_empty_input():
    rows = np.array([sel.day_counts(np.array([0, 2]), np.array([0, 2]), np.ones(2, bool)),
                     sel.day_counts(np.array([1, 3]), np.array([0, 3]), np.ones(2, bool))])
    m = sel.pooled(rows)
    assert m["pairs"] == 4 and m["agreement"] == 0.75 and m["warning_recall"] == 1.0 and m["watch_recall"] == pytest.approx(2 / 3)
    assert sel.pooled(np.zeros((0, len(sel.DAY_FIELDS)), dtype=np.int64))["agreement"] is None


def make_counts(n_days, agree_share, seed):
    rng = np.random.default_rng(seed)
    n = np.full(n_days, 1000)
    same = rng.binomial(n, agree_share)
    out = np.zeros((n_days, len(sel.DAY_FIELDS)), dtype=np.int64)
    out[:, 0], out[:, 1], out[:, 2] = n, same, n
    out[:, 6], out[:, 7] = 100, 80
    return out


def test_bootstrap_se_of_the_difference_is_small_when_candidates_move_together():
    base = make_counts(120, 0.80, 1)
    better = base.copy()
    better[:, 1] = np.minimum(base[:, 1] + 30, 1000)                     # +3 points every day
    stats = sel.bootstrap({"gfs": base, "other": better}, "gfs", 500, 7)
    assert stats["gfs"]["delta_vs_baseline"] == 0 and stats["gfs"]["delta_se"] == 0
    assert stats["other"]["delta_vs_baseline"] == pytest.approx(0.03, abs=1e-9)
    assert stats["other"]["delta_se"] < 0.001 < stats["other"]["agreement_se"] * 10
    again = sel.bootstrap({"gfs": base, "other": better}, "gfs", 500, 7)
    assert again == stats                                                # seeded


def test_bootstrap_without_days():
    empty = np.zeros((0, len(sel.DAY_FIELDS)), dtype=np.int64)
    assert sel.bootstrap({"gfs": empty}, "gfs", 10, 1)["gfs"]["delta_se"] is None


def entry(agreement, delta, se, warning_recall, mae=5.0, watch_recall=0.8):
    return {"agreement": agreement, "delta_vs_baseline": delta, "delta_se": se, "warning_recall": warning_recall,
            "watch_recall": watch_recall, "rain": {"domain": {"mae_mm": mae}}}


def test_decision_keeps_gfs_unless_a_candidate_beats_it_by_more_than_the_se_without_losing_warning_recall():
    primary = {
        "1": {"candidates": {"gfs": entry(0.80, 0.0, 0.0, 0.70),
                             "ecmwf_hres": entry(0.84, 0.04, 0.01, 0.72),                 # eligible
                             "ecmwf_hres+map": entry(0.85, 0.05, 0.01, 0.65),             # better, but Warning+ recall lower
                             "ecmwf_ens_mean": entry(0.83, 0.03, 0.02, 0.70)}},          # delta within 2 SE of nothing? 0.03 > 0.02 -> eligible
        "2": {"candidates": {"gfs": entry(0.80, 0.0, 0.0, 0.70), "ecmwf_hres": entry(0.81, 0.01, 0.02, 0.9)}},
        "3": {"candidates": {"gfs": entry(0.80, 0.0, 0.0, 0.70), "gfs+map": entry(0.83, 0.03, 0.01, 0.70),
                             "ecmwf_hres": entry(0.83, 0.03, 0.01, 0.70)}}}
    out = sel.decide(primary)
    assert out["1"]["chosen"] == "ecmwf_hres" and set(out["1"]["eligible"]) == {"ecmwf_hres", "ecmwf_ens_mean"}
    assert out["2"]["chosen"] == "gfs" and out["2"]["eligible"] == [] and "no candidate beats GFS" in out["2"]["reason"]
    assert out["3"]["chosen"] in ("gfs+map", "ecmwf_hres")                              # tie on agreement: the lower MAE, then order
    assert "bootstrap SE" in out["1"]["reason"]


def test_decision_tie_breaks_on_watch_recall_then_rain_error():
    primary = {"1": {"candidates": {"gfs": entry(0.8, 0, 0, 0.7), "a": entry(0.84, 0.04, 0.01, 0.7, mae=6.0, watch_recall=0.8),
                                    "b": entry(0.84, 0.04, 0.01, 0.7, mae=5.0, watch_recall=0.8),
                                    "c": entry(0.84, 0.04, 0.01, 0.7, mae=7.0, watch_recall=0.9)}}}
    assert sel.decide(primary)["1"]["chosen"] == "c"
    primary["1"]["candidates"]["c"]["watch_recall"] = 0.8
    assert sel.decide(primary)["1"]["chosen"] == "b"


# ------------------------------------------------------------------------------------------ certainty statistics

def test_certainty_counts_groups_and_the_observed_range():
    obs = np.array([0, 2, 3, 1])
    level = np.array([0, 2, 1, 1])
    certainty = np.array(["firm", "firm", "depends_on_forecast", None], dtype=object)
    low, high = np.array([0, 2, 0, 1]), np.array([0, 2, 3, 1])
    scored = np.array([True, True, True, False])
    out = sel.certainty_counts(obs, level, certainty, low, high, scored)
    assert out[0].tolist() == [2, 2, 2, 2, 2]                    # firm: both equal the observed level
    assert out[1].tolist() == [1, 0, 0, 1, 1]                    # depends: forecast 1 vs observed 3, inside [0, 3]
    assert out[2, 0] == 3 and out[2, 1] == 2


def test_certainty_groups_share_and_agreement():
    day = np.array([[[8, 8, 8, 8, 8], [2, 1, 2, 2, 2], [10, 9, 10, 10, 10]]] * 20)
    groups = sel.certainty_groups(day, 200, np.random.default_rng(1))
    assert groups["firm"]["agreement"] == 1.0 and groups["depends_on_forecast"]["agreement"] == 0.5
    assert groups["firm"]["share"] == pytest.approx(0.8) and groups["all"]["agreement"] == 0.9
    assert sel.certainty_groups(np.zeros((0, 3, 5), dtype=np.int64), 10, np.random.default_rng(1)) == {}


# --------------------------------------------------------------------------------------------- evaluation loop

class IdentityMaps:
    def apply(self, source, lead, field):
        return np.asarray(field, dtype=np.float32)


def write_products(rain_dir, day, gfs_mm, ecmwf_mm, spread=2.0):
    shape = (3, imerg.ROWS, imerg.COLS)
    np.savez(rain_dir / f"gfs_imdday_{day.isoformat()}.npz", days=np.full(shape, gfs_mm, np.float32), day_valid=np.ones(3, bool),
             cycle=np.array("2024-07-15T00:00:00+00:00"))
    full = np.full(shape, ecmwf_mm, np.float32)
    np.savez(rain_dir / f"ecmwf_imdday_{day.isoformat()}.npz", lead_days=np.array([1, 2, 3]), hres=full,
             hres_valid=np.ones(3, bool), hres_cycle=np.array("2024-07-14T12:00:00+00:00"), ens_mean=full, ens_p10=full * 0.5,
             ens_p50=full, ens_p90=full + spread, ens_valid=np.ones(3, bool), ens_cycle=np.array("2024-07-14T12:00:00+00:00"),
             n_members=np.array(51))


def make_setup(tmp_path, monkeypatch, days):
    monkeypatch.setattr(fm, "season_days", lambda year: days)
    cells = H.tiny_cells()
    store = H.FakeStore(H.span(days[0] - timedelta(days=140), days[-1] + timedelta(days=4)), overrides={})
    return sel.Setup(cfg={}, model=H.tiny_model(), thresholds=H.THRESHOLDS, alert_config=ALERT_CONFIG, rules=pr.NO_RULES,
                     sample=cells, clim=H.tiny_clim(cells), store=store, rain_dir=tmp_path, maps=IdentityMaps(),
                     groups={"domain": np.arange(N_PIX)}, watch_floor=0.02, seed=1)


def test_evaluate_year_scores_every_candidate_against_the_observed_features(tmp_path, monkeypatch):
    days = [date(2024, 7, 15), date(2024, 7, 16)]
    for day in days:
        write_products(tmp_path, day, gfs_mm=4.0, ecmwf_mm=H.LIGHT_MM)
    setup = make_setup(tmp_path, monkeypatch, days)
    result = sel.evaluate_year(setup, 2024)
    assert result["days"] == {1: [d.isoformat() for d in days], 2: [d.isoformat() for d in days], 3: [d.isoformat() for d in days]}
    for lead in (1, 2, 3):
        for config in sel.CANDIDATES:
            counts = result["counts"][(lead, sel.key(config))]
            assert counts.shape == (2, len(sel.DAY_FIELDS)) and (counts[:, 0] <= len(setup.sample)).all()
        rain = result["rain"][(lead, "ecmwf_hres")]["domain"].summary()
        assert rain["n"] == 2 * N_PIX
    # the observed rain of the fake store is LIGHT_MM everywhere (no heavy days): an ECMWF field of LIGHT_MM has no rain error
    assert result["rain"][(1, "ecmwf_hres")]["domain"].summary()["mae_mm"] == pytest.approx(0.0, abs=1e-4)
    assert result["rain"][(1, "gfs")]["domain"].summary()["mae_mm"] == pytest.approx(4.0 - H.LIGHT_MM, abs=1e-4)
    # the table reduces them and is complete for every candidate
    table = sel.table_of(result, 50, 3)
    assert set(table) == {"1", "2", "3"} and set(table["1"]["candidates"]) == {sel.key(c) for c in sel.CANDIDATES}
    assert table["1"]["candidates"]["gfs"]["delta_vs_baseline"] == 0


def test_an_interrupted_evaluation_resumes_with_the_same_result(tmp_path, monkeypatch):
    days = [date(2024, 7, 15), date(2024, 7, 16), date(2024, 7, 17)]
    for day in days:
        write_products(tmp_path, day, gfs_mm=4.0, ecmwf_mm=H.LIGHT_MM)
    setup = make_setup(tmp_path, monkeypatch, days)
    monkeypatch.setattr(sel, "CHECKPOINT_EVERY_DAYS", 1)
    straight = sel.evaluate_year(setup, 2024)
    ckpt = tmp_path / "year.ckpt"
    seen = []

    def stop_after_two(year, done, total):
        seen.append(done)
        if done == 2:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        sel.evaluate_year(setup, 2024, stop_after_two, ckpt)
    assert ckpt.is_file()
    resumed_days = []
    resumed = sel.evaluate_year(setup, 2024, lambda y, d, t: resumed_days.append(d), ckpt)
    assert resumed_days == [3]                                   # only the third day was computed again
    for name, rows in straight["counts"].items():
        assert np.array_equal(rows, resumed["counts"][name])
    assert straight["days"] == resumed["days"]
    for name in straight["ratios"]:
        assert np.array_equal(straight["ratios"][name], resumed["ratios"][name])
    assert resumed["rain"][(1, "gfs")]["domain"].summary()["mae_mm"] == straight["rain"][(1, "gfs")]["domain"].summary()["mae_mm"]


def test_days_a_source_lacks_are_left_out_for_every_candidate(tmp_path, monkeypatch):
    days = [date(2024, 7, 15), date(2024, 7, 16)]
    write_products(tmp_path, days[0], 4.0, 2.0)
    np.savez(tmp_path / f"gfs_imdday_{days[1].isoformat()}.npz", days=np.full((3, imerg.ROWS, imerg.COLS), 4.0, np.float32),
             day_valid=np.ones(3, bool), cycle=np.array("2024-07-16T00:00:00+00:00"))           # no ECMWF file this day
    result = sel.evaluate_year(make_setup(tmp_path, monkeypatch, days), 2024)
    assert result["days"][1] == [days[0].isoformat()]
    assert all(len(rows) == 1 for rows in result["counts"].values())


def test_published_level_applies_the_rain_cap(tmp_path, monkeypatch):
    setup = make_setup(tmp_path, monkeypatch, [date(2024, 7, 15)])
    frame = pd.DataFrame({"cell_id": [1, 2], "region": ["western_ghats", "himalaya"], "irain_acc_1": [90.0, 90.0],
                          "irain_acc_3": [270.0, 270.0], "irain_acc_7": [400.0, 5.0], "iapi_90": [200.0, 200.0],
                          "inbr_max_acc_1": [95.0, 95.0], "stat_slope_mean": [20.0, 20.0]}).astype(
        {c: np.float32 for c in H.MODEL_COLUMNS})
    free = sel.published(setup, frame)[1]
    setup.rules = pr.PostRules(agreement_min=None, rain=pr.RainRule({7: 11.5}), gated_levels=(lv.WATCH, lv.WARNING, lv.EMERGENCY))
    capped = sel.published(setup, frame)[1]
    assert free[0] == capped[0] and capped[1] < free[1] == free[0]       # the dry-week cell is lowered, the wet one is not


def test_scenario_evaluation_reports_firm_cells_against_depends_cells(tmp_path, monkeypatch):
    """Heavy HRES rain near Wayanad makes that cell depend on the forecast; the calm cells stay firm."""
    days = [date(2024, 7, 15)]
    rows, cols = np.indices((imerg.ROWS, imerg.COLS))
    write_products(tmp_path, days[0], gfs_mm=4.0, ecmwf_mm=4.0)
    with np.load(tmp_path / f"ecmwf_imdday_{days[0].isoformat()}.npz") as data:
        arrays = dict(data)
    arrays["hres"][:, H.heavy_mask(rows, cols)] = H.HEAVY_MM
    np.savez(tmp_path / f"ecmwf_imdday_{days[0].isoformat()}.npz", **arrays)
    setup = make_setup(tmp_path, monkeypatch, days)
    choice = fc.ForecastChoice({k: fc.Config("ecmwf_hres") for k in fc.LEADS})
    products = fc.load_product_days(tmp_path, days[0])
    field = fc.resolve_lead(products, choice, setup.maps, 2)
    scenes = fc.scenario_fields(field, 3.0)
    levels = {name: sel.forecast_side(setup, days[0], 2, scenes[name]) for name in scenes}
    certainty, low, high = pr.scenario_certainty(levels["forecast"][1], levels["dry"][1], levels["wet"][1], levels["forecast"][2])
    wayanad = H.wayanad_row(setup.sample.assign(i=range(len(setup.sample))))["i"]
    assert certainty[wayanad] == pr.CERTAINTY_DEPENDS and low[wayanad] == 0 and high[wayanad] >= levels["forecast"][1][wayanad] > 0
    assert (certainty[np.arange(len(certainty)) != wayanad] == pr.CERTAINTY_FIRM).all()


def test_markdown_reports_name_every_decision_and_the_gefs_reason():
    block = {"days": 3, "candidates": {"gfs": {**entry(0.8, 0.0, 0.0, 0.7), "pairs": 10, "agreement_se": 0.01, "within_one": 0.9,
                                               "watch_recall": 0.8, "warning_precision": 0.6,
                                               "rain": {"domain": {"mae_mm": 5.0, "hit_rate_50": 0.1, "false_alarm_ratio_50": 0.6}}}}}
    payload = {"cells": 2536, "seed": 1, "model": "m", "gefs": "not used: test reason",
               "tables": {"2024": {"1": block}, "2023": {"1": block}},
               "decision": {"1": {"chosen": "gfs", "eligible": [], "reason": "none"}, "2": {"chosen": "gfs", "eligible": [], "reason": "r"},
                            "3": {"chosen": "gfs", "eligible": [], "reason": "r"}},
               "widening": {"chosen": {"leads": {k: {"n": 5, "lo": 0.2, "hi": 4.0} for k in "123"}},
                            "gfs_raw_2024": {"leads": {k: {"n": 5, "lo": 0.2, "hi": 4.0} for k in "123"}}}}
    text = "\n".join(sel.selection_markdown(payload))
    assert "not used: test reason" in text and "| D+1 | gfs | none | none |" in text and "### Lead D+1 (3 issue days)" in text
