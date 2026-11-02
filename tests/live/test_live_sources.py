import pytest

from aetherguard.audit import rain

pytestmark = pytest.mark.live
DATES = ["2024-07-28", "2024-07-29", "2024-07-30", "2024-07-31"]


def test_open_meteo_live():
    res = rain.probe_open_meteo(11.55, 76.13, DATES)
    assert res.status in ("ok", "partial"), res.summary


def test_power_api_live():
    res = rain.probe_power_api(11.55, 76.13, DATES)
    assert res.status in ("ok", "partial"), res.summary
