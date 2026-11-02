from aetherguard.audit import rain
from aetherguard.http import DownloadError

DATES = ["2024-07-28", "2024-07-29", "2024-07-30", "2024-07-31"]


def _hours(dates):
    return [f"{d}T{h:02d}:00" for d in dates for h in range(24)]


def test_daily_sums_counts_nulls_explicitly():
    out = rain.daily_sums(_hours(["2024-07-28"]), [1.0] * 22 + [None, None])
    assert out["2024-07-28"] == {"sum_mm": 22.0, "n": 24, "n_null": 2}


def _fake_open_meteo(soil_null=False):
    def fake(url, params=None, **kwargs):
        times = _hours(DATES)
        variable = params["hourly"]
        if variable == "soil_moisture_0_to_7cm":
            values = [None if soil_null else 0.3] * len(times)
        else:
            values = [1.0] * len(times)
        return {"hourly": {"time": times, variable: values}}
    return fake


def test_open_meteo_ok_states_its_day_definition(monkeypatch):
    monkeypatch.setattr(rain, "fetch_json", _fake_open_meteo())
    res = rain.probe_open_meteo(11.55, 76.13, DATES)
    assert res.status == "ok"
    assert "UTC" in res.day_definition
    rows = {r["label"]: r["daily_mm"] for r in res.evidence["event_rows"]}
    assert set(rows) == {"era5", "era5_land", "ecmwf_ifs"}
    assert rows["era5"]["2024-07-29"] == 24.0


def test_open_meteo_missing_soil_moisture_is_partial(monkeypatch):
    monkeypatch.setattr(rain, "fetch_json", _fake_open_meteo(soil_null=True))
    res = rain.probe_open_meteo(11.55, 76.13, DATES)
    assert res.status == "partial"
    assert any("soil" in p for p in res.evidence["problems"])


def test_open_meteo_network_down_is_unreachable(monkeypatch):
    def boom(*args, **kwargs):
        raise DownloadError("offline", retriable=True)
    monkeypatch.setattr(rain, "fetch_json", boom)
    res = rain.probe_open_meteo(11.55, 76.13, DATES)
    assert res.status == "unreachable"
    assert res.day_definition


def _power_payload(fill_day=None):
    precip = {"20240728": 7.6, "20240729": 52.6, "20240730": 27.5, "20240731": 19.6}
    if fill_day:
        precip[fill_day] = -999.0
    soil = {k: 0.9 for k in precip}
    return {"properties": {"parameter": {"PRECTOTCORR": precip, "GWETTOP": soil, "GWETROOT": soil}},
            "header": {"fill_value": -999.0, "time_standard": "LST"}}


def test_power_api_ok_and_uses_the_reported_time_standard(monkeypatch):
    monkeypatch.setattr(rain, "fetch_json", lambda *a, **k: _power_payload())
    res = rain.probe_power_api(11.55, 76.13, DATES)
    assert res.status == "ok"
    assert "LST" in res.day_definition
    assert res.evidence["event_rows"][0]["daily_mm"]["2024-07-29"] == 52.6


def test_power_api_fill_value_becomes_none_and_status_partial(monkeypatch):
    monkeypatch.setattr(rain, "fetch_json", lambda *a, **k: _power_payload(fill_day="20240730"))
    res = rain.probe_power_api(11.55, 76.13, DATES)
    assert res.status == "partial"
    assert res.evidence["event_rows"][0]["daily_mm"]["2024-07-30"] is None


def test_every_rain_probe_declares_a_day_definition():
    assert set(rain.DAY_DEFINITIONS) >= {"open_meteo", "chirps", "imd", "power_zarr"}
    assert all(text.strip() for text in rain.DAY_DEFINITIONS.values())


# --- review fixes -----------------------------------------------------------------------------
import gzip  # noqa: E402

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from aetherguard.manifest import Manifest  # noqa: E402


def _om_fake(era5_land_precip_null=False, short_day=None):
    def fake(url, params=None, **kwargs):
        times = _hours(DATES)
        variable = params["hourly"]
        values = [1.0] * len(times)
        if variable == "precipitation" and params["models"] == "era5_land" and era5_land_precip_null:
            values = [None] * len(times)
        if variable == "precipitation" and params["models"] == "era5" and short_day:
            keep = [i for i, t in enumerate(times) if not (t.startswith(short_day) and int(t[11:13]) >= 12)]
            times = [times[i] for i in keep]
            values = [values[i] for i in keep]
        return {"hourly": {"time": times, variable: values}}
    return fake


def test_open_meteo_summary_admits_a_fully_null_model(monkeypatch):
    monkeypatch.setattr(rain, "fetch_json", _om_fake(era5_land_precip_null=True))
    res = rain.probe_open_meteo(11.55, 76.13, DATES)
    assert res.status == "partial"
    assert "era5_land" in res.summary
    assert "2/3" in res.summary
    assert any("era5_land precipitation" in p for p in res.evidence["problems"])
    assert "3/3" not in res.summary


def test_open_meteo_truncated_day_is_none_not_a_short_sum(monkeypatch):
    monkeypatch.setattr(rain, "fetch_json", _om_fake(short_day="2024-07-30"))
    res = rain.probe_open_meteo(11.55, 76.13, DATES)
    rows = {r["label"]: r["daily_mm"] for r in res.evidence["event_rows"]}
    assert rows["era5"]["2024-07-30"] is None
    assert rows["era5"]["2024-07-29"] == 24.0
    assert res.status == "partial"
    assert any("2024-07-30" in p for p in res.evidence["problems"])


def test_open_meteo_day_definition_states_the_preceding_hour_window():
    text = rain.DAY_DEFINITIONS["open_meteo"]
    assert "UTC" in text and "preceding" in text.lower()


def test_power_api_missing_requested_date_is_none_and_partial(monkeypatch):
    payload = _power_payload()
    payload["properties"]["parameter"]["PRECTOTCORR"].pop("20240731")
    payload["properties"]["parameter"]["PRECTOTCORR"]["20240801"] = 3.0  # extra day, ignored
    monkeypatch.setattr(rain, "fetch_json", lambda *a, **k: payload)
    res = rain.probe_power_api(11.55, 76.13, DATES)
    daily = res.evidence["event_rows"][0]["daily_mm"]
    assert list(daily) == DATES
    assert daily["2024-07-31"] is None
    assert res.status == "partial"
    assert any("missing dates" in p and "2024-07-31" in p for p in res.evidence["problems"])


def _fake_zarr(monkeypatch, days):
    import xarray as xr

    times = np.array(days, dtype="datetime64[ns]")
    ds = xr.Dataset(
        {"PRECTOTCORR": (("time", "lat", "lon"), np.arange(len(days), dtype=float).reshape(-1, 1, 1) + 1.0)},
        coords={"time": times, "lat": [11.5], "lon": [76.25]})
    monkeypatch.setattr(xr, "open_zarr", lambda *a, **k: ds)


def test_power_zarr_complete_dataset_is_ok(monkeypatch):
    _fake_zarr(monkeypatch, ["2024-07-27"] + DATES + ["2024-08-01"])
    res = rain.probe_power_zarr(11.55, 76.13, DATES)
    daily = res.evidence["event_rows"][0]["daily_mm"]
    assert list(daily) == DATES and all(v is not None for v in daily.values())
    assert res.status == "ok"


def test_power_zarr_missing_requested_date_is_partial(monkeypatch):
    _fake_zarr(monkeypatch, ["2024-07-28", "2024-07-29", "2024-07-31"])
    res = rain.probe_power_zarr(11.55, 76.13, DATES)
    daily = res.evidence["event_rows"][0]["daily_mm"]
    assert list(daily) == DATES and daily["2024-07-30"] is None
    assert res.status == "partial"
    assert any("missing dates" in p and "2024-07-30" in p for p in res.evidence["problems"])


def _write_gz_geotiff(dest, tmp_path):
    import rasterio
    from affine import Affine

    tif = tmp_path / "src.tif"
    data = np.zeros((6, 6), dtype="float32")
    data[3, 2] = 42.5  # the pixel containing 11.55N 76.13E
    with rasterio.open(tif, "w", driver="GTiff", height=6, width=6, count=1, dtype="float32",
                       crs="EPSG:4326", transform=Affine(0.05, 0.0, 76.025, 0.0, -0.05, 11.725),
                       nodata=-9999.0) as out:
        out.write(data, 1)
    with tif.open("rb") as source, gzip.open(dest, "wb") as target:
        target.write(source.read())


def test_chirps_survives_a_corrupt_file_and_reads_the_good_one(monkeypatch, tmp_path):
    def fake_download(url, dest, manifest, source, licence, **kwargs):
        dest.parent.mkdir(parents=True, exist_ok=True)
        if "2024.07.28" in dest.name:
            dest.write_bytes(b"<html>not a gzip</html>")
        else:
            _write_gz_geotiff(dest, tmp_path)
        return dest

    monkeypatch.setattr(rain, "download", fake_download)
    manifest = Manifest(tmp_path / "manifest.jsonl", tmp_path)
    res = rain.probe_chirps(["2024-07-28", "2024-07-29"], 11.55, 76.13, tmp_path, manifest, 10)
    daily = res.evidence["event_rows"][0]["daily_mm"]
    assert daily["2024-07-28"] is None
    assert daily["2024-07-29"] == 42.5
    assert res.status == "partial"
    assert any("2024-07-28" in p for p in res.evidence["problems"])
    assert any("grid" in p for p in res.evidence["problems"])
    assert "problem" in res.summary
    folder = tmp_path / "raw" / "audit" / "chirps"
    leftovers = [p.name for p in folder.iterdir() if "07.28" in p.name and not p.name.endswith(".gz")]
    assert leftovers == []
    assert res.evidence["est_total_gb"] is not None


def test_chirps_all_dates_corrupt_is_inconclusive_not_a_crash(monkeypatch, tmp_path):
    def fake_download(url, dest, manifest, source, licence, **kwargs):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"garbage")
        return dest

    monkeypatch.setattr(rain, "download", fake_download)
    res = rain.probe_chirps(["2024-07-28"], 11.55, 76.13, tmp_path, None, 10)
    assert res.status == "inconclusive"
    assert res.evidence["problems"]


def test_chirps_all_downloads_failing_is_unreachable(monkeypatch, tmp_path):
    def boom(*args, **kwargs):
        raise DownloadError("offline", retriable=True)

    monkeypatch.setattr(rain, "download", boom)
    res = rain.probe_chirps(["2024-07-28"], 11.55, 76.13, tmp_path, None, 10)
    assert res.status == "unreachable"
    assert res.evidence["problems"]
