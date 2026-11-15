"""The heavy-rain warning product is off in the daily run until the user decides, and its key is the only one added."""
import yaml

from aetherguard.config import PROJECT_ROOT


def test_rain_warnings_are_off_in_the_daily_run_config():
    cfg = yaml.safe_load((PROJECT_ROOT / "configs" / "live_run.yaml").read_text(encoding="utf-8"))
    assert cfg["rain_warnings"]["enabled"] is False
    assert cfg["rain_warnings"]["calibration"].endswith("calibration_v2.json")
