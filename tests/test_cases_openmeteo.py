import json

import numpy as np
import pandas as pd
import pytest

from aetherguard.cases import openmeteo as om
from aetherguard.grid import cell_center
from aetherguard.http import DownloadError
from aetherguard.manifest import Manifest


def hourly_payload(start="2024-07-01", end="2024-08-05", storms=None, model_key="precipitation", nulls=()):
    """A fake archive response: hourly stamps start 00:00 .. end 23:00 with the given {timestamp: mm} storms."""
    index = pd.date_range(f"{start} 00:00", f"{end} 23:00", freq="h")
    values = [float((storms or {}).get(ts.strftime("%Y-%m-%d %H:%M"), 0.0)) for ts in index]
    for i in nulls:
        values[i] = None
    return {"latitude": 11.5, "hourly": {"time": [t.strftime("%Y-%m-%dT%H:%M") for t in index], model_key: values}}


class FakeApi:
    def __init__(self, payload=None, fail_models=()):
        self.payload, self.fail_models, self.calls = payload, set(fail_models), []

    def __call__(self, url, params=None, **kwargs):
        self.calls.append((url, dict(params)))
        if params["models"] in self.fail_models:
            raise DownloadError("HTTP 400 from archive", retriable=False, status=400)
        return self.payload if self.payload is not None else hourly_payload()


@pytest.fixture
def env(tmp_path):
    manifest = Manifest(tmp_path / "manifest.jsonl", tmp_path)
    return {"directory": tmp_path / "raw" / "openmeteo", "manifest": manifest, "out_dir": tmp_path / "processed"}


def test_call_weight_follows_the_free_tier_formula():
    assert om.call_weight(36) == pytest.approx(36 / 14)
    assert om.call_weight(7) == 1.0
    assert om.call_weight(36, n_variables=20) == pytest.approx(36 / 14 * 2)
    assert om.FREE_CALLS_PER_DAY == 10_000


def test_request_asks_for_gmt_hourly_precipitation_of_one_model():
    api = FakeApi()
    env_dir = None
    params = om.request_params(11.47, 76.13, "2024-07-01", "2024-08-05", "era5")
    assert params == {"latitude": 11.47, "longitude": 76.13, "start_date": "2024-07-01", "end_date": "2024-08-05",
                      "hourly": "precipitation", "models": "era5", "timezone": "GMT"}
    assert env_dir is None and not api.calls


def test_raw_response_is_cached_with_a_manifest_row_and_never_fetched_twice(env):
    api = FakeApi()
    usage = om.Usage()
    first = om.fetch_point("Wayanad", 11.47, 76.13, "2024-07-01", "2024-08-05", "era5", usage=usage, fetch=api, **{
        k: env[k] for k in ("directory", "manifest")})
    assert usage.calls == 1 and usage.weight == pytest.approx(36 / 14) and usage.cached == 0
    url, params = api.calls[0]
    assert url == om.ARCHIVE_URL and params["timezone"] == "GMT" and params["models"] == "era5"
    files = list(env["directory"].glob("*.json"))
    assert len(files) == 1 and not list(env["directory"].glob("*.part"))
    entries = list(env["manifest"].entries().values())
    assert len(entries) == 1 and entries[0].licence == om.LICENCE and "timezone=GMT" in entries[0].url
    assert entries[0].path.endswith(files[0].name) and "key" not in entries[0].url.lower()
    again = om.fetch_point("Wayanad", 11.47, 76.13, "2024-07-01", "2024-08-05", "era5", usage=usage, fetch=api, **{
        k: env[k] for k in ("directory", "manifest")})
    assert again == first and len(api.calls) == 1 and usage.cached == 1 and usage.calls == 1


def test_parse_accepts_plain_and_model_suffixed_keys_and_turns_nulls_into_nan():
    a = om.parse_hourly(hourly_payload(), "era5")
    b = om.parse_hourly(hourly_payload(model_key="precipitation_era5_land", nulls=(3,)), "era5_land")
    assert len(a) == 36 * 24 and a.index[0] == pd.Timestamp("2024-07-01 00:00") and a.index.tz is None
    assert np.isnan(b.iloc[3]) and b.notna().sum() == len(b) - 1


@pytest.mark.parametrize("payload,match", [
    ({}, "no hourly"),
    ({"hourly": {"time": ["2024-07-01T00:00"], "temperature": [1.0]}}, "no 'precipitation'"),
    ({"hourly": {"time": [], "precipitation": []}}, "empty"),
    ({"hourly": {"time": ["2024-07-01T00:00", "2024-07-01T02:00"], "precipitation": [0.0, 0.0]}}, "consecutive"),
    ({"hourly": {"time": ["2024-07-01T00:00", "2024-07-01T01:00"], "precipitation": [0.0, -1.0]}}, "negative"),
    ({"hourly": {"time": ["2024-07-01T00:00", "2024-07-01T01:00"], "precipitation": [0.0]}}, "length"),
])
def test_parse_rejects_malformed_series(payload, match):
    with pytest.raises(ValueError, match=match):
        om.parse_hourly(payload, "era5")


def test_utc_day_uses_the_preceding_hour_convention_and_needs_24_stamps():
    series = om.parse_hourly(hourly_payload(storms={"2024-07-10 00:00": 7.0, "2024-07-10 12:00": 3.0,
                                                    "2024-07-11 00:00": 2.0}), "era5")
    utc = om.utc_day_totals(series)
    assert utc["2024-07-09"] == 7.0                         # the 00:00 stamp is the last hour of the PREVIOUS day
    assert utc["2024-07-10"] == 3.0 + 2.0
    assert np.isnan(utc["2024-08-05"])                      # the series ends at 23:00: the last UTC day is incomplete
    assert utc.index[0] == pd.Timestamp("2024-06-30") and np.isnan(utc["2024-06-30"])   # its stamp 00:00 is day 06-30
    assert utc.notna().sum() == 35


def test_exact_imd_day_d5_approximation_and_its_error_on_a_storm_after_03_utc():
    # 60 mm fell in one hour at 10:00 UTC on 2024-07-29: inside UTC day 07-29 and inside IMD day 07-30
    series = om.parse_hourly(hourly_payload(storms={"2024-07-29 11:00": 60.0}), "era5")   # stamp 11:00 = hour 10-11
    daily = om.derive_daily(series)
    assert daily.loc["2024-07-29", "utc_day_mm"] == 60.0 and daily.loc["2024-07-30", "utc_day_mm"] == 0.0
    assert daily.loc["2024-07-30", "imd_exact_mm"] == 60.0 and daily.loc["2024-07-29", "imd_exact_mm"] == 0.0
    assert daily.loc["2024-07-30", "imd_d5_mm"] == pytest.approx(0.875 * 60.0)
    assert daily.loc["2024-07-30", "d5_error_mm"] == pytest.approx(-7.5)
    assert daily.loc["2024-07-29", "d5_error_mm"] == pytest.approx(0.125 * 60.0)       # the 7.5 mm lands on the day before
    assert list(daily.columns) == ["utc_day_mm", "imd_exact_mm", "imd_d5_mm", "d5_error_mm"]


def test_a_constant_rate_makes_the_approximation_exact_and_boundary_hours_split_correctly():
    storms = {f"2024-07-{d:02d} {h:02d}:00": 1.0 for d in range(1, 31) for h in range(24)}
    daily = om.derive_daily(om.parse_hourly(hourly_payload(storms=storms), "era5"))
    inner = daily.loc["2024-07-03":"2024-07-28"]
    assert inner["imd_exact_mm"].eq(24.0).all() and inner["d5_error_mm"].abs().max() < 1e-9
    series = om.parse_hourly(hourly_payload(storms={"2024-07-14 03:00": 5.0, "2024-07-14 04:00": 9.0}), "era5")
    boundary = om.derive_daily(series)
    assert boundary.loc["2024-07-14", "imd_exact_mm"] == 5.0 and boundary.loc["2024-07-15", "imd_exact_mm"] == 9.0


def test_missing_hours_give_nan_days_never_partial_sums():
    series = om.parse_hourly(hourly_payload(storms={"2024-07-10 05:00": 4.0}, nulls=(24 * 9 + 5,)), "era5")
    daily = om.derive_daily(series)
    # the missing stamp 05:00 on 07-10 lies in UTC day 07-10 and in IMD day 07-11 (04:00 on 07-10 .. 03:00 on 07-11)
    assert np.isnan(daily.loc["2024-07-10", "utc_day_mm"]) and np.isnan(daily.loc["2024-07-11", "imd_exact_mm"])
    assert daily.loc["2024-07-10", "imd_exact_mm"] == 0.0 and daily.loc["2024-07-09", "utc_day_mm"] == 0.0
    assert np.isnan(daily.loc["2024-07-10", "imd_d5_mm"]) and np.isnan(daily.loc["2024-07-11", "imd_d5_mm"])
    assert np.isnan(daily.loc["2024-07-11", "d5_error_mm"])


def test_approximation_error_summary_numbers():
    series = om.parse_hourly(hourly_payload(storms={"2024-07-29 11:00": 60.0, "2024-07-20 02:00": 20.0}), "era5")
    summary = om.approximation_error(om.derive_daily(series))
    # 20 mm at 02:00 UTC is wholly inside IMD day 07-20 but UTC day 07-20 gives it 12.5% weight: error -17.5 mm
    assert summary["days"] > 20 and summary["max_abs_error_mm"] == pytest.approx(17.5)
    assert summary["heavy_days"] == 2 and summary["worst_days"][0] == {"date": "2024-07-20", "exact_mm": 20.0, "d5_mm": 2.5}
    assert summary["mean_abs_error_mm"] > 0 and summary["rmse_mm"] >= summary["mean_abs_error_mm"]
    assert om.approximation_error(om.derive_daily(om.parse_hourly(hourly_payload(), "era5")))["max_abs_error_mm"] == 0.0


def test_kerala_points_are_the_three_wettest_positive_cells_on_the_event_days():
    rows = pd.DataFrame({
        "cell_id": [20065137, 19965138, 20065129, 19965134, 20065129, 20305122, 20495114],
        "date": pd.to_datetime(["2018-08-16", "2018-08-16", "2018-08-16", "2018-08-15", "2018-08-15", "2018-08-16", "2018-08-10"]),
        "is_positive_cell_day": [True, True, True, True, True, False, True],
        "rain_acc_3": [396.0, 448.4, 355.8, 354.7, 300.0, 900.0, 800.0]})
    points = om.kerala_points(rows)
    assert [p["cell_id"] for p in points] == [19965138, 20065137, 20065129]
    assert points[0]["lat"] == pytest.approx(cell_center(19965138)[0]) and points[0]["lon"] == pytest.approx(cell_center(19965138)[1])
    assert points[0]["start"] == "2018-07-15" and points[0]["end"] == "2018-08-25" and points[0]["name"] == "kerala_cell_19965138"
    with pytest.raises(ValueError, match="only 2"):
        om.kerala_points(rows.iloc[:2])


def test_fetch_series_writes_daily_tables_counts_calls_and_records_unavailable_models(env):
    api = FakeApi(hourly_payload(storms={"2024-07-29 11:00": 60.0}), fail_models=("era5_land",))
    points = [om.WAYANAD, {**om.WAYANAD, "name": "second", "lat": 11.6}]
    result = om.fetch_series(points, fetch=api, **env)
    assert set(result["daily"]) == {("wayanad_mundakkai", "era5"), ("second", "era5")}
    assert set(result["unavailable"]) == {("wayanad_mundakkai", "era5_land"), ("second", "era5_land")}
    assert "HTTP 400" in result["unavailable"][("second", "era5_land")]
    usage = result["usage"]
    assert usage.calls == 4 and usage.weight == pytest.approx(4 * 36 / 14) and len(usage.failures) == 2
    assert len(list(env["directory"].glob("*.json"))) == 2          # failed requests leave no cache file
    table = pd.read_parquet(env["out_dir"] / "era5_wayanad_mundakkai_era5_daily.parquet")
    assert table.loc["2024-07-30", "imd_exact_mm"] == 60.0
    again = om.fetch_series(points, fetch=api, **env)
    assert again["usage"].cached == 2 and again["usage"].calls == 2          # only the two failed ones are asked again


def test_a_garbled_response_is_reported_not_raised(env):
    api = FakeApi({"hourly": {"time": ["2024-07-01T00:00"], "precipitation": []}})
    result = om.fetch_series([om.WAYANAD], models=("era5",), fetch=api, **env)
    assert result["daily"] == {} and "length" in next(iter(result["unavailable"].values()))
    assert json.dumps(sorted(str(k) for k in result["unavailable"]))


def test_an_all_null_series_is_reported_as_unavailable_and_writes_no_daily_table(env):
    payload = hourly_payload()
    payload["hourly"]["precipitation"] = [None] * len(payload["hourly"]["time"])
    result = om.fetch_series([om.WAYANAD], models=("era5_land",), fetch=FakeApi(payload), **env)
    assert result["daily"] == {} and "every hourly precipitation value is null" in next(iter(result["unavailable"].values()))
    assert not list(env["out_dir"].glob("*.parquet"))
    assert len(list(env["directory"].glob("*.json"))) == 1          # the raw response stays cached as evidence


def test_cache_summary_counts_responses_and_their_weight(env):
    om.fetch_series([om.WAYANAD], models=("era5",), fetch=FakeApi(), **env)
    summary = om.cache_summary(env["directory"])
    assert summary["cached_responses"] == 1 and summary["total_weight"] == pytest.approx(36 / 14)
    assert om.cache_summary(env["directory"] / "missing") == {"cached_responses": 0, "total_weight": 0.0}
