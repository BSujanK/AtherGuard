"""W7b held-out look of the forecast leads on v4-static: the fresh 2025 decision, 2021-2024 beside it, the guards."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from aetherguard.live import leads_v4_heldout as lh
from aetherguard.live import leads_v4_study as study
from aetherguard.live import leads_v5_heldout as l5

DIGESTS = {"model.txt": "abc"}


def fake_year(path, year: int, n: int = 30, digests=DIGESTS) -> None:
    rng = np.random.default_rng(year)
    days = study.season_days(year)
    arrays = {}
    for lead in lh.LEADS:
        risk = rng.uniform(0, 1, (n, len(days)))
        scored = np.ones_like(risk, dtype=bool)
        level = np.digitize(risk, [0.6, 0.8, 0.95]).astype(np.int8)
        arrays.update({f"L{lead}_incumbent_level": level, f"L{lead}_incumbent_risk": risk, f"L{lead}_incumbent_raw": risk,
                       f"L{lead}_s_risk": risk, f"L{lead}_s_raw": risk, f"L{lead}_scored": scored})
    np.savez_compressed(path, cell_ids=np.arange(500, 500 + n), issue_days=np.array([d.toordinal() for d in days]),
                        model_sha256=np.array(json.dumps(digests)), **arrays)


@pytest.fixture
def panels(tmp_path, monkeypatch):
    monkeypatch.setattr(l5, "out_dir", lambda: tmp_path)
    monkeypatch.setattr(l5, "model_digests", lambda: DIGESTS)
    events = pd.DataFrame({"cell_id": [501, 502, 503], "date": pd.to_datetime(["2025-06-10", "2025-08-01", "2023-07-01"]),
                           "source": ["reported"] * 3})
    monkeypatch.setattr(lh, "w1_events", lambda years=lh.YEARS: events[events["date"].dt.year.isin(years)])
    monkeypatch.setattr(lh, "v2_event_sets", lambda years=lh.YEARS: {"v2_all": events[events["date"].dt.year.isin(years)]})
    for year in l5.ALL_YEARS:
        fake_year(l5.year_path(year), year)
    return tmp_path


def test_the_deciding_pools_hold_2025_only(panels):
    by_lead = l5.pools(lh.w1_events(l5.DECIDING_YEARS), l5.DECIDING_YEARS)
    pool, seasons = by_lead["2"]
    assert set(seasons) == {"2025"} and pool.days[0].year == 2025 and len(pool.events) == 2


def test_preflight_refuses_panels_scored_with_another_model(panels):
    fake_year(l5.year_path(2023), 2023, digests={"model.txt": "other"})
    with pytest.raises(ValueError, match="other v4-static files"):
        l5.run_preflight(say=lambda *_: None)


def test_preflight_then_one_look_and_never_a_second(panels):
    pre = l5.run_preflight(say=lambda *_: None)
    assert pre["deciding_years"] == [2025] and pre["leads"]["1"]["events_on_days"] == 2
    assert pre["beside_event_counts"]["w1_2021_2024_already_looked_at"]["1"]["events_on_days"] == 1
    result = l5.run_heldout(say=lambda *_: None)
    assert len(result["decision"]["rows"]) == 12 and result["decision"]["adopt"] is False      # identical risks: ties
    assert set(result["beside"]) == {"w1_2021_2024_already_looked_at", "v2_all_2025"}
    with pytest.raises(FileExistsError):
        l5.run_heldout()
    with pytest.raises(FileExistsError):
        l5.run_preflight()
