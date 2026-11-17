"""The v5 preflight report labels 2021-2024 as already looked at and states the power from the file."""
import importlib.util
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "tools" / "leads_v5_preflight_report.py"
spec = importlib.util.spec_from_file_location("leads_v5_preflight_report", TOOL)
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


def test_render():
    season = {"issue_days_scored": 122, "target": [0.5, 0.2, 0.08], "realised": [0.5, 0.2, 0.08],
              "cuts": {"1": {"straddle": 0}, "2": {"straddle": 0}, "3": {"straddle": 1}}}
    pre = {"candidate": "s", "deciding_years": [2025], "beside_years": [2021, 2024], "generated_utc": "t",
           "panels_sha256": {"2025": "x"}, "model_sha256": {"model.txt": "y"},
           "leads": {"1": {"days": 122, "scored_cell_days": 10, "seasons": {"2025": season}, "events_on_days": 3,
                           "events_outside_days": 0, "independent_slides_on_days": 3}},
           "beside_event_counts": {"w1_2021_2024_already_looked_at": {"1": {"events_on_days": 22, "events_outside_days": 2,
                                                                          "independent_slides_on_days": 22}}},
           "checks": [{"check": "c", "passed": True}]}
    text = report.render(pre)
    assert "ALREADY LOOKED AT" in text and "| 1 | 122 | 10 | 122 | 50.0000% / 20.0000% / 8.0000%" in text
    assert "holds 3 independent W1 slide(s) per lead" in text
