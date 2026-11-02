import json

import numpy as np
import pandas as pd
import pytest

from aetherguard.cases import openmeteo as om
from aetherguard.cases import series
from aetherguard.grid import cell_center, latlon_to_cell
from aetherguard.integrity import hazard_features as hf
from aetherguard.integrity.neighbours import haversine_km

NAN = np.nan
INDEX = pd.date_range("2024-07-20", periods=14, freq="D").as_unit("ns")


def station_days(values, trust=None, flagged=None, genuine=None):
    n, m = values.shape
    coords = {"A": (11.50, 76.13), "B": (11.90, 76.13), "C": (14.0, 76.13)}
    ids = list(coords)[:m]
    return hf.StationDays(INDEX, ids, np.array([coords[s][0] for s in ids]), np.array([coords[s][1] for s in ids]),
                          np.asarray(values, float), np.full((n, m), 0.9) if trust is None else np.asarray(trust, float),
                          np.zeros((n, m), bool) if flagged is None else np.asarray(flagged, bool),
                          np.zeros((n, m), bool) if genuine is None else np.asarray(genuine, bool))


def test_nearest_station_is_the_nearest_one_observed_that_day_with_its_trust():
    value = np.full((14, 3), NAN)
    value[3] = [10.0, 20.0, 30.0]                       # all observed on day 3: A is nearest
    value[4] = [NAN, 21.0, 31.0]                        # A missing: B is nearest
    value[5] = [NAN, NAN, 32.0]                         # C only, ~277 km away: within 300 km
    trust = np.full((14, 3), 0.9)
    trust[4, 1] = 0.2
    flagged = np.zeros((14, 3), bool)
    flagged[4, 1] = True
    genuine = np.zeros((14, 3), bool)
    genuine[3, 0] = True
    sd = station_days(value, trust, flagged, genuine)
    out = series.nearest_station(sd, [11.51] * 4, [76.13] * 4, [INDEX[3], INDEX[4], INDEX[5], INDEX[6]])
    assert out["near_station"].tolist() == ["A", "B", "C", ""]
    assert out["near_value_mm"].iloc[:3].tolist() == [10.0, 21.0, 32.0] and np.isnan(out["near_value_mm"].iloc[3])
    assert out["near_dist_km"].iloc[0] == pytest.approx(float(haversine_km(11.51, 76.13, 11.50, 76.13)), rel=1e-6)
    assert out["near_dist_km"].iloc[1] == pytest.approx(float(haversine_km(11.51, 76.13, 11.90, 76.13)), rel=1e-6)
    assert out["near_trust"].iloc[1] == 0.2 and out["near_flagged"].tolist() == [False, True, False, False]
    assert out["near_genuine"].tolist() == [True, False, False, False]
    assert np.isnan(out["near_dist_km"].iloc[3]) and np.isnan(out["near_trust"].iloc[3])


def test_nearest_station_beyond_300_km_is_not_reported():
    value = np.full((14, 3), NAN)
    value[3, 2] = 5.0
    out = series.nearest_station(station_days(value), [8.0], [76.13], [INDEX[3]])        # C is ~670 km from 8 N
    assert out["near_station"].iloc[0] == "" and np.isnan(out["near_dist_km"].iloc[0])
    with pytest.raises(ValueError, match="outside"):
        series.nearest_station(station_days(value), [11.5], [76.13], ["2030-01-01"])


def daily_table(scale=1.0):
    days = pd.date_range("2024-07-01", "2024-08-05").as_unit("ns")
    return pd.DataFrame({"utc_day_mm": np.arange(len(days)) * scale, "imd_exact_mm": np.arange(len(days)) * scale + 1,
                         "imd_d5_mm": np.arange(len(days)) * scale + 2, "d5_error_mm": 1.0}, index=pd.DatetimeIndex(days, name="date"))


def test_era5_columns_are_filled_only_on_the_focus_cell_and_missing_models_stay_nan():
    table = pd.DataFrame({"cell_id": [1, 1, 2, 2], "date": pd.to_datetime(["2024-07-10", "2024-07-11"] * 2)})
    out = series.attach_era5(table, [{"name": "wayanad", "cell_id": 1}], {("wayanad", "era5"): daily_table()})
    assert out["focus_point"].tolist() == ["wayanad", "wayanad", "", ""]
    assert out["era5_utc_mm"].iloc[:2].tolist() == [9.0, 10.0] and out["era5_imd_exact_mm"].iloc[0] == 10.0
    assert out["era5_imd_d5_mm"].iloc[1] == 12.0 and out["era5_utc_mm"].iloc[2:].isna().all()
    assert out[["era5_land_utc_mm", "era5_land_imd_exact_mm", "era5_land_imd_d5_mm"]].isna().all().all()
    assert list(out.columns)[2:] == series.ERA5_COLUMNS


def test_focus_cell_is_the_cell_containing_the_point_or_the_nearest_case_cell():
    exact = int(latlon_to_cell(11.47, 76.13))
    frame = pd.DataFrame({"cell_id": [exact, exact + 1, exact + 10000]})
    assert series.focus_cell(frame, 11.47, 76.13)[0] == exact
    cell_id, distance = series.focus_cell(frame.iloc[1:], 11.47, 76.13)
    assert cell_id == exact + 1 and distance == pytest.approx(float(haversine_km(11.47, 76.13, *cell_center(exact + 1))))


def inputs_fixture():
    days = pd.date_range("2024-07-24", "2024-08-03")
    rows = []
    for c in (7, 8):
        for i, d in enumerate(days):
            rows.append({"cell_id": c, "date": d, "src_imd_acc_1": 10.0 + i, "src_chi_acc_1": 5.0 + i, "corr_q50_1": 1.0,
                         "corr_q90_1": 2.0, "corr_q99_1": 3.0, "corr_p_exceed99": 0.1, "integ_trw_rain_1": 9.0,
                         "near_station": "A", "near_dist_km": 12.0, "near_value_mm": 8.0, "near_trust": 0.9,
                         "near_flagged": False, "near_genuine": False})
    return pd.DataFrame(rows)


def test_focus_table_lines_up_every_source_for_the_focus_window():
    inputs = inputs_fixture()
    chirps_utc = pd.Series(np.arange(11) * 3.0, index=pd.date_range("2024-07-24", "2024-08-03").as_unit("ns"))
    table = series.focus_table(inputs, 7, {("wayanad", "era5"): daily_table()}, "wayanad", chirps_utc)
    assert list(table.index) == list(pd.date_range("2024-07-25", "2024-08-02"))
    assert table.loc["2024-07-30", "imd_mm"] == 10.0 + 6 and table.loc["2024-07-30", "chirps_aligned_mm"] == 5.0 + 6
    assert table.loc["2024-07-30", "chirps_utc_mm"] == 18.0 and table.loc["2024-07-30", "era5_utc_mm"] == 29.0
    assert table.loc["2024-07-30", "era5_imd_exact_mm"] == 30.0 and table.loc["2024-07-30", "era5_imd_d5_mm"] == 31.0
    assert table["era5_land_utc_mm"].isna().all()                              # no ERA5-Land series was available
    assert table["near_station"].eq("A").all() and table["corr_q90_1"].eq(2.0).all()
    assert {"era5_land_imd_exact_mm", "integ_trw_rain_1", "near_trust"} <= set(table.columns)


def write_case_files(directory, case="kerala_2018"):
    spec = series.CASES[case]
    base = pd.DataFrame({"cell_id": np.array([5, 5, 6, 6, 7, 7], dtype=np.int64),
                         "date": pd.to_datetime(["2018-08-14", "2018-08-15"] * 3),
                         "region": "western_ghats", "lat": np.float32(10.0), "lon": np.float32(76.0), "rain_source": "imd",
                         "is_positive_cell_day": [False, True, False, True, False, True],
                         "rain_acc_1": np.float32([1, 2, 3, 4, 5, 6]),
                         "rain_acc_3": np.float32([5, 6, 7, 8, 9, 10]), "rain_acc_7": np.float32([9, 10, 11, 12, 13, 14]),
                         **{f"src_imd_acc_{n}": np.float32(n) for n in (1, 3, 7)},
                         **{f"src_chi_acc_{n}": np.float32(n + 1) for n in (1, 3, 7)},
                         **{c: np.float32(0.5) for c in ("wet_top", "wet_root", "wet_top_chg3", "wet_top_chg7", "wet_root_chg3", "wet_root_chg7")}})
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "integ").mkdir(exist_ok=True)
    (directory / "corrector").mkdir(exist_ok=True)
    base.to_parquet(directory / f"{spec['features']}_features.parquet", index=False)
    integ = base[["cell_id", "date"]].assign(**{c: np.float32(1.0) for c in hf.COLUMNS})
    integ.to_parquet(directory / "integ" / f"{spec['features']}_integ.parquet", index=False)
    corr = base[["cell_id", "date"]].assign(corr_q50_1=np.float32(1), corr_q90_1=np.float32(2), corr_q99_1=np.float32(3),
                                            corr_p_exceed99=np.float32(0.1))
    corr.to_parquet(directory / "corrector" / f"{spec['features']}_corr.parquet", index=False)
    return base


def test_case_frame_joins_integ_and_corr_columns_by_identical_keys(tmp_path):
    base = write_case_files(tmp_path)
    frame = series.load_case_frame("kerala_2018", tmp_path)
    assert len(frame) == len(base) and "integ_trw_rain_1" in frame.columns and "corr_q90_1" in frame.columns
    assert list(frame.columns[:len(base.columns)]) == list(base.columns)
    corr_path = tmp_path / "corrector" / "case_kerala_2018_samples_corr.parquet"
    pd.read_parquet(corr_path).iloc[::-1].to_parquet(corr_path, index=False)
    with pytest.raises(ValueError, match="keys / row order"):
        series.load_case_frame("kerala_2018", tmp_path)


def test_case_inputs_table_has_the_documented_columns_and_nearest_observations(tmp_path):
    write_case_files(tmp_path)
    days = pd.date_range("2018-08-10", periods=10).as_unit("ns")
    value = np.full((10, 2), NAN)
    value[4:6] = [[12.0, 30.0]] * 2
    sd = hf.StationDays(days, ["A", "B"], np.array([10.05, 10.5]), np.array([76.0, 76.0]), value, np.full((10, 2), 0.8),
                        np.zeros((10, 2), bool), np.zeros((10, 2), bool))
    table = series.case_inputs("kerala_2018", sd, [{"name": "p", "cell_id": 5}], {("p", "era5"): daily_table()}, tmp_path)
    assert list(table.columns) == [c for c in series.KEY_COLUMNS] + series.INPUT_COLUMNS + series.NEAREST_COLUMNS + series.ERA5_COLUMNS
    assert table["near_station"].eq("A").all() and table["near_value_mm"].eq(12.0).all() and table["near_trust"].eq(0.8).all()
    assert table["focus_point"].tolist() == ["p", "p", "", "", "", ""] and table["era5_utc_mm"].iloc[2:].isna().all()
    assert table["is_positive_cell_day"].tolist() == [False, True] * 3


def test_build_all_writes_tables_focus_table_and_a_report_with_a_hermetic_fake_api(tmp_path, isolated_data_root, monkeypatch):
    features = isolated_data_root / "processed" / "features"
    write_case_files(features, "kerala_2018")
    wayanad = pd.DataFrame({"cell_id": np.repeat(np.array([int(latlon_to_cell(11.47, 76.13)), 20295123], dtype=np.int64), 22),
                            "date": np.tile(pd.date_range("2024-07-15", "2024-08-05"), 2), "region": "western_ghats",
                            "lat": np.float32(11.47), "lon": np.float32(76.13), "rain_source": "imd", "is_positive_cell_day": False})
    for column in series.INPUT_COLUMNS[:-6]:
        wayanad[column] = np.float32(1.0)
    for column in series.INPUT_COLUMNS[-6:]:
        wayanad[column] = np.float32(0.5)
    wayanad = wayanad.drop(columns=[c for c in wayanad.columns if c.startswith(("corr_", "integ_"))])
    wayanad.to_parquet(features / "case_wayanad_2024_samples_features.parquet", index=False)
    (features / "integ").mkdir(exist_ok=True)
    (features / "corrector").mkdir(exist_ok=True)
    keys = wayanad[["cell_id", "date"]]
    keys.assign(**{c: np.float32(1.0) for c in hf.COLUMNS}).to_parquet(features / "integ" / "case_wayanad_2024_samples_integ.parquet", index=False)
    keys.assign(corr_q50_1=np.float32(1), corr_q90_1=np.float32(2), corr_q99_1=np.float32(3), corr_p_exceed99=np.float32(0.1)
                ).to_parquet(features / "corrector" / "case_wayanad_2024_samples_corr.parquet", index=False)
    days = pd.date_range("2018-07-01", "2024-12-31").as_unit("ns")
    value = np.full((len(days), 1), 2.0)
    sd = hf.StationDays(days, ["A"], np.array([11.5]), np.array([76.1]), value, np.full(value.shape, 0.9),
                        np.zeros(value.shape, bool), np.zeros(value.shape, bool))

    def fake_fetch(url, params=None, **kwargs):
        start, end = pd.Timestamp(params["start_date"]), pd.Timestamp(params["end_date"])
        index = pd.date_range(f"{start.date()} 00:00", f"{end.date()} 23:00", freq="h")
        rain = [1.0 if params["models"] == "era5" else None for _ in index]
        return {"hourly": {"time": [t.strftime("%Y-%m-%dT%H:%M") for t in index], "precipitation": rain}}

    from aetherguard.manifest import Manifest
    manifest = Manifest(tmp_path / "m.jsonl", isolated_data_root)
    result = series.build_all(station_data=(None, sd), fetch_fn=fake_fetch, manifest=manifest,
                              chirps_series=pd.Series(np.arange(9) * 1.0, index=pd.date_range("2024-07-25", "2024-08-02").as_unit("ns")))
    assert result["usage"]["calls"] == 8 and result["usage"]["weight"] > 8
    assert len(result["unavailable"]) == 4 and all("null" in v for v in result["unavailable"].values())
    cases = isolated_data_root / "processed" / "cases"
    for name in ("kerala_2018_inputs.parquet", "wayanad_2024_inputs.parquet", "wayanad_2024_focus_table.parquet"):
        assert (cases / name).is_file()
    focus = pd.read_parquet(cases / "wayanad_2024_focus_table.parquet")
    assert len(focus) == 9 and focus["era5_utc_mm"].notna().all() and focus["near_station"].eq("A").all()
    report = series.build_report(result)
    md, js = series.write_report(report, tmp_path / "reports")
    parsed = json.loads(js.read_text(encoding="utf-8"), parse_constant=lambda c: pytest.fail(c))
    assert parsed["usage"]["calls"] == 8 and len(parsed["era5_wayanad"]) == 3 and len(parsed["focus_table"]) == 9
    text = md.read_text(encoding="utf-8")
    assert "D5 approximation error" in text and "Wayanad focus cell" in text and "API use" in text


@pytest.mark.realdata
def test_real_case_input_tables_have_the_frozen_row_counts_and_the_wayanad_gap():
    from aetherguard.config import data_root
    cases = data_root() / "processed" / "cases"
    kerala = pd.read_parquet(cases / "kerala_2018_inputs.parquet")
    wayanad = pd.read_parquet(cases / "wayanad_2024_inputs.parquet")
    assert len(kerala) == 160960 and len(wayanad) == 3080 and kerala["is_positive_cell_day"].sum() == 23
    assert kerala["focus_point"].ne("").sum() == 3 * 20 and wayanad["focus_point"].ne("").sum() == 22
    for column in series.INPUT_COLUMNS + series.NEAREST_COLUMNS + series.ERA5_COLUMNS:
        assert column in kerala.columns and column in wayanad.columns
    focus = pd.read_parquet(cases / "wayanad_2024_focus_table.parquet")
    row = focus.loc["2024-07-30"]
    assert row["imd_mm"] == pytest.approx(179.2, abs=0.5) and row["chirps_utc_mm"] < 5.0
    assert row["era5_imd_exact_mm"] > row["era5_utc_mm"]                      # the IMD day holds the afternoon-to-morning rain
