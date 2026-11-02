import pandas as pd
import pytest

from aetherguard.cases import openmeteo as om
from aetherguard.manifest import Manifest

pytestmark = pytest.mark.live


def test_era5_archive_returns_wayanad_hourly_precipitation_for_the_event_days(tmp_path):
    manifest = Manifest(tmp_path / "manifest.jsonl", tmp_path)
    usage = om.Usage()
    payload = om.fetch_point("wayanad_live", 11.47, 76.13, "2024-07-27", "2024-08-02", "era5",
                             directory=tmp_path / "raw", manifest=manifest, usage=usage)
    daily = om.derive_daily(om.parse_hourly(payload, "era5"))
    assert usage.calls == 1 and usage.weight == 1.0
    day = daily.loc[pd.Timestamp("2024-07-30")]
    assert day["utc_day_mm"] > 20 and day["imd_exact_mm"] > 20
    assert abs(day["imd_d5_mm"] - day["imd_exact_mm"]) < 0.5 * day["imd_exact_mm"]
    assert len(list((tmp_path / "raw").glob("*.json"))) == 1
