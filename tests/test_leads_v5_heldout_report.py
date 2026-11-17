"""The report of the v4-static leads' look is rendered from the result file only, deciding set first."""
import importlib.util
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "tools" / "leads_v5_heldout_report.py"
spec = importlib.util.spec_from_file_location("leads_v5_heldout_report", TOOL)
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


def scores(inc: int, cand: int, slides: int) -> dict:
    level = lambda hits: {"group_hits": hits, "groups": slides, "alert_cell_days": 100 + hits}   # noqa: E731
    return {"events": slides, "slides": slides, "events_outside_panel_days": 0,
            **{t: {"v3": {k: level(inc) for k in ("1", "2", "3")}, "candidate": {k: level(cand) for k in ("1", "2", "3")}}
               for t in ("tolerant", "cell_exact")}}


def result(adopt: bool) -> dict:
    rows = [{"lead": 2, "tolerance": "tolerant", "level": "Emergency", "incumbent": 2, "candidate": 3, "net_loss": -1}]
    return {"generated_utc": "t", "candidate": "s",
            "preflight": {"gate": {"passed": True, "failures": [], "rule": "gate rule"}, "gate_sha256": "abc"},
            "deciding_w1_2025": {str(l): scores(2, 3, 3) for l in (1, 2, 3)},
            "veto": {"net_all": -2, "net_ce": 0, "t_all": 13, "t_ce": 4, "triggered": not adopt, "rows": rows},
            "decision": {"adopt": adopt, "gate_passed": True, "veto_triggered": not adopt},
            "beside": {"w1_2021_2024_already_looked_at": {str(l): scores(20, 21, 22) for l in (1, 2, 3)}}}


def test_headline_and_order():
    text = report.render(result(True))
    assert "ADOPTED** by the rule of spec amendment 2" in text and "NOT ADOPTED" not in report.headline(result(True))
    assert "NET_ALL = -2 against the threshold 13" in text and "only 3 independent W1 slide(s) per lead" in text
    assert text.index("## Deciding: licence-clean W1") < text.index("### The no-harm veto") < text.index("## Development gate") \
        < text.index("## Beside it, NOT deciding")
    assert "ALREADY LOOKED AT" in text and "GFS fallback" in text
    assert "NOT ADOPTED" in report.headline(result(False))
