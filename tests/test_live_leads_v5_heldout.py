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
    monkeypatch.setattr(l5, "e1_path", lambda: tmp_path / "e1.json")
    (tmp_path / "e1.json").write_text(json.dumps({**gate_e1(0.71, 1.0), "model_sha256": DIGESTS,
                                                  "gate": {"passed": True, "failures": [], "rule": "r"}}))
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
    assert result["veto"]["net_all"] == 0 and result["decision"] == {"adopt": True, "gate_passed": True, "veto_triggered": False}
    assert set(result["beside"]) == {"w1_2021_2024_already_looked_at", "v2_all_2025"}
    with pytest.raises(FileExistsError):
        l5.run_heldout()
    with pytest.raises(FileExistsError):
        l5.run_preflight()


# ------------------------------------------------------------------------------------------- amendment 2

def scores_of(rows: dict) -> dict:
    """{lead: score_heldout-like dict} from {(lead, tolerance, level): (incumbent hits, candidate hits)}."""
    out = {}
    for (lead, tol, level), (inc, cand) in rows.items():
        entry = out.setdefault(str(lead), {}).setdefault(tol, {"v3": {}, "candidate": {}})
        entry["v3"][level] = {"group_hits": inc}
        entry["candidate"][level] = {"group_hits": cand}
    return out


def all_rows(inc: int, cand: int, override=None) -> dict:
    rows = {(l, t, k): (inc, cand) for l in (1, 2, 3) for t in ("tolerant", "cell_exact") for k in (2, 3)}
    rows.update(override or {})
    return scores_of(rows)


def test_the_veto_pools_the_net_loss():
    assert l5.veto(all_rows(3, 3))["triggered"] is False
    one_short = l5.veto(all_rows(3, 2))                              # 12 rows each one slide lower: NET_ALL 12
    assert one_short["net_all"] == 12 and one_short["triggered"] is False
    assert l5.veto(all_rows(3, 2, {(1, "tolerant", 2): (3, 1)}))["triggered"] is True              # NET_ALL 13
    ce = {(l, "cell_exact", 3): (3, 1) for l in (1, 2)}                                           # NET_CE 4
    result = l5.veto(all_rows(3, 3, ce))
    assert result["net_ce"] == 4 and result["net_all"] == 4 and result["triggered"] is True


def gate_e1(recall_s: float, burden_s: float) -> dict:
    ref = {"normal": 0.6, "watch": 0.25, "warning": 0.1, "emergency": 0.05}
    entry = lambda recall, scale: {"warning_plus_recall": recall, "burden_reference": ref,                  # noqa: E731
                                   "burden_forecast": {k: v * scale for k, v in ref.items()}}
    return {"results": {str(l): {"c": {"vs_v4_reference": entry(0.70, 2.0)}, "s": {"vs_v4_reference": entry(recall_s, burden_s)}}
                        for l in (1, 2, 3)}}


def test_the_gate():
    assert l5.gate_verdict(gate_e1(0.70, 1.2))["passed"] is True              # equal recall, burden +20%
    assert l5.gate_verdict(gate_e1(0.69, 1.0))["passed"] is False             # recall below the incumbent's
    failed = l5.gate_verdict(gate_e1(0.80, 1.25))
    assert failed["passed"] is False and len(failed["failures"]) == 9           # three levels at three leads


def test_the_adoption_needs_the_gate_and_no_veto():
    assert l5.adoption(True, {"triggered": False}) is True
    assert l5.adoption(False, {"triggered": False}) is False
    assert l5.adoption(True, {"triggered": True}) is False


def test_no_look_when_the_gate_failed(panels):
    (panels / "e1.json").write_text(json.dumps({**gate_e1(0.5, 1.0), "model_sha256": DIGESTS,
                                                "gate": {"passed": False, "failures": ["x"], "rule": "r"}}))
    l5.run_preflight(say=lambda *_: None)
    with pytest.raises(ValueError, match="gate failed"):
        l5.run_heldout(say=lambda *_: None)
    assert not (panels / f"{l5.RESULT}.started").exists()
