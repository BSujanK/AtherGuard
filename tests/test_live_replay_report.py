"""The replay comparison report renders every set and day it finds and sums them."""
import json

from aetherguard.live import replay_report as rr


def entry(high, emergency):
    return {"levels": {"Normal": 90 - emergency, "Watch": 6, "Warning": 4, "Emergency": emergency},
            "confidence": {"High": high, "Degraded": 100 - high, "Insufficient": 0}, "confidence_causes": {"imd_missing": 100 - high},
            "n_blind_escalated": 1, "lead1_levels": {"Normal": 99, "Watch": 1, "Warning": 0, "Emergency": 0}, "audit": 0,
            "second_opinion": {"check_day": "2026-11-12"}}


def test_sets_and_totals(tmp_path):
    for name, high in (("before", 0), ("after", 90)):
        (tmp_path / name).mkdir()
        (tmp_path / name / "replay_summary.json").write_text(json.dumps({"2026-11-13": entry(high, 2)}), encoding="utf-8")
    result = rr.build(tmp_path)
    assert list(result["sets"]) == ["before", "after"] and result["days"] == ["2026-11-13"]
    assert result["totals"]["after"]["confidence"]["High"] == 90 and result["totals"]["before"]["levels"]["Emergency"] == 2
    text = rr.markdown(result)
    assert "before (dc93f98)" in text and "| 2026-11-13 | after, v4, alert_config_v3 | 90 |" in text
