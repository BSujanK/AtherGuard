"""Held-out season panels (verify.seasons): the cells, order and levels of a scored season on a toy store."""
import argparse
import json
import runpy
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from aetherguard.alerts import levels as lv
from aetherguard.live import backtest as bt
from aetherguard.live import hardening as H
from aetherguard.live import hardening_dev as D
from aetherguard.live import run as live_run
from aetherguard.live.early_map import IdentityMap
from aetherguard.live.sources import PERSIST, ImergSource
from aetherguard.verify import seasons

from alerts_helpers import CONFIG
from live_run_helpers import THRESHOLDS, FakeStore, make_cfg, span, tiny_cells, tiny_clim

YEAR = 2026
CELLS = tiny_cells().iloc[::-1].reset_index(drop=True)           # not in cell_id order: the panel must keep this order
HEAVY = [date(YEAR, 8, 10), date(YEAR, 8, 11), date(YEAR, 8, 12), date(YEAR, 9, 20)]
CARD_SHA = "ab" * 32


def _stub_score_rows(model, rows):
    """risk = 1-day rain / 100 mm; every other field a plain function of the rain."""
    rain = rows["irain_acc_1"].to_numpy(dtype=np.float64)
    risk = np.clip(rain / 100.0, 0.0, 1.0)
    out = {name: np.full(len(rows), np.nan) for name in H.FLOAT_FIELDS + H.RISK_FIELDS}
    out.update({name: np.zeros(len(rows), dtype=np.uint8) for name in H.COUNT_FIELDS})
    out["top3_terrain"] = np.zeros(len(rows), dtype=bool)
    out.update(raw=rain, risk=risk, new_lo=risk, new_hi=risk, old_lo=risk, old_hi=risk, median_risk=risk,
               **{f"acc_{w}": rows[f"irain_acc_{w}"].to_numpy(dtype=np.float64) for w in H.RAIN_WINDOWS})
    return out


class _Model:
    members = [None, None, None]
    card = {"alert_levels": {name: {"raw": 1.0, "risk": getattr(THRESHOLDS, name)} for name in lv.THRESHOLD_NAMES}}


@pytest.fixture
def toy(tmp_path, monkeypatch):
    """A toy store with heavy Late rain near Wayanad on `HEAVY`, the stub scoring, and a record of the set asked for."""
    cfg = make_cfg(tmp_path)
    late = FakeStore(span(date(YEAR, 1, 1), date(YEAR + 1, 1, 5)), HEAVY)
    stores = bt.Stores(cfg, ImergSource("late", late, latency_h=14.5, window_days=130),
                       ImergSource("early", FakeStore([]), latency_h=4.5, window_days=130, mapping=IdentityMap()),
                       tiny_clim(CELLS), lambda day, ctx: bt.TailResult(None, PERSIST, "toy"))
    asked = {}

    def load_set(name, start=None, end=None, cfg=None):
        asked.update(name=name, start=start, end=end)
        return bt.BacktestSet(name, start, end, CELLS, None, "season")

    monkeypatch.setattr(live_run, "load_run_config", lambda: cfg)
    monkeypatch.setattr(live_run, "load_live_model", lambda cfg: _Model())
    monkeypatch.setattr(bt, "load_set", load_set)
    monkeypatch.setattr(bt, "build_stores", lambda cells, cfg=None, root=None: stores)
    monkeypatch.setattr(H, "score_rows", _stub_score_rows)
    monkeypatch.setattr(seasons, "model_card_sha", lambda cfg: CARD_SHA)
    return asked


def test_score_season_keeps_the_candidate_cells_in_order_and_the_season_window(toy, tmp_path):
    path = seasons.score_season(YEAR, tmp_path / "out", say=lambda m: None)
    assert path == tmp_path / "out" / f"season_{YEAR}_training.npz"
    assert toy == {"name": f"season_{YEAR}", "start": date(YEAR, 6, 1), "end": date(YEAR, 12, 31)}
    panel = H.load_panel(path)
    assert panel.cells["cell_id"].tolist() == CELLS["cell_id"].tolist()
    assert panel.cells["region"].tolist() == CELLS["region"].tolist() and panel.cells["in_universe"].all()
    assert panel.days[0] == date(YEAR, 6, 1) - timedelta(days=bt.WARMUP_DAYS) and panel.days[-1] == date(YEAR, 12, 31)
    wayanad = CELLS.index[CELLS["cell_id"] == int(tiny_cells()["cell_id"].iloc[0])][0]
    assert panel["risk"][wayanad, panel.days.index(HEAVY[2])] > THRESHOLDS.watch
    assert panel["risk"][wayanad, panel.days.index(date(YEAR, 7, 1))] < 0.1


def test_score_season_levels_match_a_direct_computation_on_the_panel(toy, tmp_path):
    panel = H.load_panel(seasons.score_season(YEAR, tmp_path, say=lambda m: None))
    thresholds = lv.card_region_thresholds(_Model.card, panel.cells["region"])
    season = D.Season(YEAR, panel, panel.days.index(date(YEAR, 6, 1)), pd.DataFrame(), thresholds)
    got = D.season_levels(season, "risk", CONFIG)
    assert got.max() >= 1
    stamps = pd.DatetimeIndex(pd.to_datetime(panel.days))
    for i, region in enumerate(panel.cells["region"]):
        risk = panel["risk"][i]
        raw = lv.raw_level(risk, risk, thresholds[region])[0]
        direct = lv.apply_hysteresis(np.full(len(risk), panel.cells["cell_id"][i]), stamps, raw, risk,
                                     thresholds[region], CONFIG.exit_factor, CONFIG.exit_days)
        assert got[i].tolist() == direct.tolist()


def test_score_season_writes_a_sidecar_with_the_scored_share_and_the_card_sha(toy, tmp_path):
    path = seasons.score_season(YEAR, tmp_path, say=lambda m: None)
    side = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    panel = H.load_panel(path)
    assert side["year"] == YEAR and side["n_days"] == len(panel.days) and side["n_cells"] == len(CELLS)
    assert side["first_day"] == panel.days[0].isoformat() and side["last_day"] == f"{YEAR}-12-31"
    assert side["model_card_sha256"] == CARD_SHA and side["features"] == "training_style" and side["seconds"] >= 0
    share = side["scored_share_per_day"]
    assert share["min"] == share["mean"] == share["max"] == 1.0 and share["days_below_half"] == 0
    assert set(share["mean_by_month"]) == {f"{YEAR}-{m:02d}" for m in range(5, 13)}


def test_an_existing_season_is_skipped_unless_forced(toy, tmp_path):
    said = []
    first = seasons.score_season(YEAR, tmp_path, say=said.append)
    stamp = first.stat().st_mtime_ns
    toy.clear()
    assert seasons.score_season(YEAR, tmp_path, say=said.append) == first
    assert toy == {} and first.stat().st_mtime_ns == stamp and any("exists" in m for m in said)
    seasons.score_season(YEAR, tmp_path, say=said.append, force=True)
    assert toy["name"] == f"season_{YEAR}" and first.stat().st_mtime_ns != stamp


def test_the_default_directory_is_under_the_data_root(isolated_data_root):
    expected = isolated_data_root / "processed" / "alerts" / "heldout_seasons" / "season_2021_training.npz"
    assert seasons.season_path(None, 2021) == expected


def test_years_parse_as_a_range_within_the_season_years():
    assert seasons.parse_years("2018-2020") == (2018, 2019, 2020) and seasons.parse_years("2023") == (2023,)
    for text in ("2017-2019", "2024-2026", "2020-2019"):
        with pytest.raises(argparse.ArgumentTypeError):
            seasons.parse_years(text)


def test_the_cli_scores_each_year_in_turn(monkeypatch):
    calls = []
    monkeypatch.setattr(seasons, "score_season", lambda year, out_dir=None, say=print, force=False: calls.append((year, force)))
    monkeypatch.setattr(sys, "argv", ["aetherguard.verify", "seasons", "--years", "2018-2019", "--force"])
    with pytest.raises(SystemExit) as stop:
        runpy.run_module("aetherguard.verify", run_name="__main__")
    assert stop.value.code == 0 and calls == [(2018, True), (2019, True)]


def test_load_set_knows_the_season_years_only():
    for name in ("season_2017", "season_2026", "season_x"):
        with pytest.raises(ValueError, match="unknown backtest set"):
            bt.load_set(name)
    assert [bt.season_year(f"season_{y}") for y in (2018, 2025)] == [2018, 2025] and bt.season_year("window_2023") is None
