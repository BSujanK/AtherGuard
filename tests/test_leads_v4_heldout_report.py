"""The report of the leads' held-out look is rendered from the result file only."""
import importlib.util
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "tools" / "leads_v4_heldout_report.py"
spec = importlib.util.spec_from_file_location("leads_v4_heldout_report", TOOL)
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


def scores(inc: int, cand: int, slides: int = 5) -> dict:
    level = lambda hits: {"group_hits": hits, "groups": slides, "alert_cell_days": 1000 + hits}   # noqa: E731
    return {"events": slides, "slides": slides, "events_outside_panel_days": 1,
            **{t: {"v3": {k: level(inc) for k in ("1", "2", "3")}, "candidate": {k: level(cand) for k in ("1", "2", "3")}}
               for t in report.TOLERANCES}}


def result(adopt: bool, lower: bool) -> dict:
    rows = [{"lead": l, "tolerance": t, "level": v, "incumbent": 5, "candidate": 4 if (lower and l == 2 and t == "tolerant") else 6,
             "not_lower": not (lower and l == 2 and t == "tolerant"), "higher": not (lower and l == 2 and t == "tolerant")}
            for l in (1, 2, 3) for t in report.TOLERANCES for v in ("Warning", "Emergency")]
    return {"generated_utc": "2026-11-16T16:58:00+00:00", "candidate": "a", "decision": {"adopt": adopt, "rows": rows},
            "deciding_w1": {str(l): scores(5, 6) for l in (1, 2, 3)},
            "beside_v2": {"v2_all": {str(l): scores(50, 51, 60) for l in (1, 2, 3)}}}


def test_headline_states_the_verdict_and_the_lower_rows():
    text = report.headline(result(False, True))
    assert "NOT ADOPTED" in text and "10 of 12 rows are higher and 2 are lower" in text
    assert "lead 2 tolerant Warning+ 5 -> 4" in text and "not changed after the look" in text
    assert "ADOPTED" in report.headline(result(True, False)) and "NOT" not in report.headline(result(True, False))


def test_the_deciding_table_comes_before_the_v2_sets_which_are_labelled_not_deciding():
    text = report.render(result(False, True))
    assert text.index("## Deciding: licence-clean W1") < text.index("## Beside it, NOT deciding")
    assert "BIPAD Nepal register has no stated licence" in text and "rows local only" in text
    assert "| 1 | tolerant | Warning+ | 5 | 6 | 5 | 1,005 | 1,006 |" in text
    assert "| 2 | tolerant | Warning+ | 5 | 4 | NO | no |" in text
    assert "Low power: 5, 5, 5 independent W1 slides" in text
