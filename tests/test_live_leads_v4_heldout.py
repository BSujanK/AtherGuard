"""W7 held-out look of the forecast leads: the per-lead target-day pools, burden matching, the decision rule and the guards."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from aetherguard.live import leads_v4_heldout as lh
from aetherguard.live import leads_v4_study as study


def fake_year(path, year: int, n: int = 40, seed: int = 0) -> None:
    rng = np.random.default_rng(seed + year)
    days = study.season_days(year)
    arrays = {}
    for lead in lh.LEADS:
        risk = rng.uniform(0, 1, (n, len(days)))
        scored = np.ones((n, len(days)), dtype=bool)
        scored[:, :3] = False                                  # issue days without a forecast
        level = np.digitize(risk, [0.6, 0.8, 0.95]).astype(np.int8)
        arrays.update({f"L{lead}_incumbent_level": np.where(scored, level, 0).astype(np.int8),
                       f"L{lead}_incumbent_risk": risk, f"L{lead}_incumbent_raw": risk,
                       f"L{lead}_a_risk": np.where(scored, rng.uniform(0, 1, risk.shape), np.nan),
                       f"L{lead}_a_raw": np.where(scored, rng.uniform(0, 1, risk.shape), np.nan),
                       f"L{lead}_b_risk": np.where(scored, risk, np.nan), f"L{lead}_b_raw": np.where(scored, risk, np.nan),
                       f"L{lead}_scored": scored})
    np.savez_compressed(path, cell_ids=np.arange(1000, 1000 + n), issue_days=np.array([d.toordinal() for d in days]), **arrays)


@pytest.fixture
def panels(tmp_path, monkeypatch):
    monkeypatch.setattr(lh, "out_dir", lambda: tmp_path)
    for year in lh.YEARS:
        fake_year(lh.year_path(year), year)
    return tmp_path


def test_a_lead_pool_is_indexed_by_target_day_and_burden_matched(panels):
    events = pd.DataFrame({"cell_id": [1001, 1002], "date": pd.to_datetime(["2022-07-10", "2026-01-01"]),
                           "source": ["reported", "reported"]})
    pool, seasons = lh.lead_pool(2, "a", events)
    assert pool.days[0] == date(2021, 6, 3) and pool.days[-1] == date(2024, 10, 2)        # issue day + 2
    assert len(pool.events) == 1 and pool.events_outside == 1
    for year, info in seasons.items():
        assert np.allclose(info["realised"], info["target"], atol=1e-4)
    b_pool, _ = lh.lead_pool(2, "b", events)                    # b equals the incumbent's risk here: the same levels
    assert np.array_equal(b_pool.candidate[b_pool.scored], b_pool.v3[b_pool.scored])


def test_the_decision_needs_every_row_not_lower_and_one_higher():
    def scores(inc, cand):
        return {t: {"v3": {2: {"group_hits": inc}, 3: {"group_hits": inc}},
                    "candidate": {2: {"group_hits": cand}, 3: {"group_hits": cand}}} for t in lh.TOLERANCE_NAMES}
    assert lh.decide({"1": scores(5, 5), "2": scores(5, 5), "3": scores(5, 5)})["adopt"] is False      # ties only
    assert lh.decide({"1": scores(5, 6), "2": scores(5, 5), "3": scores(5, 5)})["adopt"] is True
    assert lh.decide({"1": scores(5, 7), "2": scores(5, 4), "3": scores(5, 5)})["adopt"] is False      # one row lower
    assert len(lh.decide({"1": scores(1, 1), "2": scores(1, 1), "3": scores(1, 1)})["rows"]) == 12


def test_no_second_look_and_no_look_without_a_preflight(panels):
    with pytest.raises(FileNotFoundError, match="preflight"):
        lh.run_heldout("a")
    (panels / f"{lh.RESULT}.started").write_text("x")
    with pytest.raises(FileExistsError):
        lh.run_heldout("a")
    with pytest.raises(FileExistsError):
        lh.run_preflight("a")


def test_preflight_then_one_look_on_fake_panels(panels, monkeypatch):
    events = pd.DataFrame({"cell_id": [1001, 1005, 1010], "date": pd.to_datetime(["2022-07-10", "2023-08-01", "2024-06-20"]),
                           "source": ["reported", "catalog_sparse", "reported"]})
    monkeypatch.setattr(lh, "w1_events", lambda years=lh.YEARS: events)
    monkeypatch.setattr(lh, "v2_event_sets", lambda years=lh.YEARS: {"v2_all": events})
    preflight = lh.run_preflight("b", say=lambda *_: None)
    assert preflight["leads"]["1"]["events_on_days"] == 3 and set(preflight["panels_sha256"]) == {str(y) for y in lh.YEARS}
    with pytest.raises(ValueError, match="another candidate"):
        lh.run_heldout("a", say=lambda *_: None)
    result = lh.run_heldout("b", say=lambda *_: None)
    assert len(result["decision"]["rows"]) == 12 and result["decision"]["adopt"] is False    # b = incumbent here: ties
    assert (panels / lh.RESULT).is_file()
    with pytest.raises(FileExistsError):
        lh.run_heldout("b")
