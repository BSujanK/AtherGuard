import json

import pandas as pd
import pytest
from events_helpers import write_raw_dir

from aetherguard.config import PROJECT_ROOT
from aetherguard.events import build as build_cli
from aetherguard.events import sources, store

BASE = "2015-07-15"  # day > 12 so the month-first GLC dates are unambiguous
LAT0, LON0 = 30.0, 79.0  # Uttarakhand, inside the Himalaya region
KM = 1 / 111.195  # degrees of latitude per km (spherical earth, R = 6371.0088 km)


def us_date(iso: str) -> str:
    if not iso:
        return ""
    year, month, day = iso.split("-")
    return f"{month}/{day}/{year} 12:00:00 AM"


def glc(ev_id, date=BASE, lat=LAT0, lon=LON0, accu="1km", trig="rain", cc="IN"):
    return {"event_id": str(ev_id), "event_date": us_date(date), "location_accuracy": accu,
            "landslide_trigger": trig, "country_code": cc, "latitude": str(lat), "longitude": str(lon)}


def report(ev_id, date=BASE, lat=LAT0, lon=LON0, accu="1km", trig="rain", cc="IN"):
    row = glc(ev_id, date, lat, lon, accu, trig, cc)
    row["event_date"] = date
    return row


def cevent(ev_id, date=BASE, lat=LAT0, lon=LON0, trig="Rain", cc="IN", before="2015-07-01", after="2015-07-30"):
    return {"event_id": str(ev_id), "event_date": date, "landslide_trigger": trig,
            "country_code": cc, "latitude": str(lat), "longitude": str(lon),
            "sat_date_before": before, "sat_date_after": after}


def hma(ev_id, date="20150715", lat=LAT0, lon=LON0, accu="1km", trig="rain", cc="IN"):
    return {"ev_id": ev_id, "ev_date": date, "loc_accu": accu, "ls_trig": trig, "ctry_code": cc,
            "latitude": lat, "longitude": lon}


def build(tmp_path, **kwargs):
    raw = write_raw_dir(tmp_path / "raw", **kwargs)
    out = tmp_path / "out"
    report_dict = store.build_events(raw, out)
    return pd.read_parquet(out / "events.parquet"), report_dict, out


def pick(df, source, event_id):
    rows = df[(df["source"] == source) & (df["event_id"] == event_id)]
    assert len(rows) == 1, f"{source}:{event_id} matched {len(rows)} rows"
    return rows.iloc[0]


def test_output_schema_and_all_input_records_are_kept_in_the_parquet(tmp_path):
    df, _, out = build(
        tmp_path,
        glc=[glc(1), glc(2, lat="")],
        reports=[report(3, date="")],
        events=[cevent(4)],
        hma=[hma(5), hma(6)], hma_deleted={1},
    )
    assert list(df.columns) == [
        "uid", "source", "event_id", "event_date", "event_date_raw", "date_basis", "date_window_start",
        "date_window_end", "latitude", "longitude", "cell_id", "accuracy_km", "trigger_raw", "trigger_class",
        "country_code", "region", "drop_reason", "not_positive_reason", "is_positive", "is_day_exact_positive"]
    assert len(df) == 5  # the deleted HMA record is not a record; everything else is present
    assert df["uid"].is_unique
    assert df["uid"].str.match(r"^(hma|coolr_reports|glc|coolr_events):\d+$").all()
    assert (out / "label_report.json").exists()


def test_drop_reasons_are_applied_in_order(tmp_path):
    df, _, _ = build(tmp_path, glc=[
        glc(1, date="", lat=""),                    # missing date wins over bad coordinates
        glc(2, lat=91.0),                           # out of range
        glc(3, lat=0.0, lon=0.0),                   # placeholder coordinates
        glc(4, lat="", lon=""),                     # blank coordinates
        glc(5, lat=20.0, lon=95.0, cc="MM"),        # Myanmar
        glc(6, cc=""),                              # inside a box with no country: never guessed
        glc(9, lat=40.0, lon=100.0, cc=""),         # no country but outside both boxes
        glc(7, lat=24.0, lon=91.0, cc="BD"),        # Bangladesh
        glc(8),                                     # kept
    ])
    reasons = {int(r.event_id): r.drop_reason for r in df.itertuples()}
    assert reasons[1] == "missing_date"
    assert reasons[2] == reasons[3] == reasons[4] == "bad_coordinates"
    assert reasons[5] == reasons[7] == reasons[9] == "out_of_scope_region"
    assert reasons[6] == "missing_country"
    assert pd.isna(reasons[8])
    assert df.loc[df["drop_reason"] == "bad_coordinates", "cell_id"].isna().all()
    assert df.loc[df["event_id"] == 8, "cell_id"].notna().all()


def test_exact_id_duplicates_keep_the_highest_priority_source(tmp_path):
    df, _, _ = build(
        tmp_path,
        hma=[hma(5, lat=30.0, lon=79.0)],
        reports=[report(5, lat=31.0, lon=80.0), report(6, lat=31.0, lon=81.0)],
        glc=[glc(5, lat=32.0, lon=79.0), glc(6, lat=32.0, lon=80.0), glc(7, lat=32.0, lon=81.0),
             glc(8, lat=33.0, lon=79.0), glc(8, lat=33.0, lon=80.0)],
        events=[cevent(5, lat=34.0, lon=79.0)],
    )
    assert pd.isna(pick(df, "hma", 5)["drop_reason"])
    assert pick(df, "coolr_reports", 5)["drop_reason"] == "duplicate_id"
    assert pick(df, "glc", 5)["drop_reason"] == "duplicate_id"
    assert pd.isna(pick(df, "coolr_reports", 6)["drop_reason"])
    assert pick(df, "glc", 6)["drop_reason"] == "duplicate_id"
    assert pd.isna(pick(df, "glc", 7)["drop_reason"])
    same_id = df[(df["source"] == "glc") & (df["event_id"] == 8)].sort_values("uid")
    assert same_id["drop_reason"].isna().tolist() == [True, False]  # first row wins within a source
    assert same_id["drop_reason"].iloc[1] == "duplicate_id"
    assert pd.isna(pick(df, "coolr_events", 5)["drop_reason"])  # different id namespace


def test_near_duplicates_same_date_within_two_km_are_dropped(tmp_path):
    df, _, _ = build(
        tmp_path,
        hma=[hma(100)],
        glc=[glc(201, lat=LAT0 + 1.0 * KM),                # 1 km, same date
             glc(202, lat=LAT0 + 2.1 * KM, lon=LON0),      # 2.1 km: kept
             glc(203, date="2015-07-16"),                   # same place, next day: kept
             glc(204, lat=LAT0 + 1.9 * KM, lon=LON0 + 0.5)],  # far away in longitude: kept
        reports=[report(301, lat=LAT0 - 1.5 * KM)],
        events=[cevent(401, lat=LAT0 + 0.5 * KM)],
    )
    assert pd.isna(pick(df, "hma", 100)["drop_reason"])
    assert pick(df, "glc", 201)["drop_reason"] == "near_duplicate"
    assert pd.isna(pick(df, "glc", 202)["drop_reason"])
    assert pd.isna(pick(df, "glc", 203)["drop_reason"])
    assert pd.isna(pick(df, "glc", 204)["drop_reason"])
    assert pick(df, "coolr_reports", 301)["drop_reason"] == "near_duplicate"
    assert pick(df, "coolr_events", 401)["drop_reason"] == "near_duplicate"


def test_near_duplicate_threshold_is_two_km(tmp_path):
    df, _, _ = build(tmp_path, hma=[hma(1)], glc=[glc(2, lat=LAT0 + 1.99 * KM), glc(3, lat=LAT0 - 2.01 * KM)])
    assert pick(df, "glc", 2)["drop_reason"] == "near_duplicate"
    assert pd.isna(pick(df, "glc", 3)["drop_reason"])


def test_same_source_neighbours_are_not_near_duplicates(tmp_path):
    df, _, _ = build(tmp_path, events=[cevent(1), cevent(2, lat=LAT0 + 0.5 * KM), cevent(3, lat=LAT0 + 1.0 * KM)])
    assert df["drop_reason"].isna().all()


def test_a_dropped_record_does_not_shadow_lower_priority_ones(tmp_path):
    # B (glc) is 1 km from A (hma) and dropped; C (coolr_events) is 1.5 km from B but 2.5 km from A.
    df, _, _ = build(
        tmp_path,
        hma=[hma(1)], glc=[glc(2, lat=LAT0 + 1.0 * KM)], events=[cevent(3, lat=LAT0 + 2.5 * KM)])
    assert pick(df, "glc", 2)["drop_reason"] == "near_duplicate"
    assert pd.isna(pick(df, "coolr_events", 3)["drop_reason"])


def test_positive_and_not_positive_reasons_on_kept_records(tmp_path):
    lon = lambda i: LON0 + i  # noqa: E731  (keeps the records far apart)
    df, _, _ = build(tmp_path, glc=[
        glc(1, lon=lon(0.0)),                                   # positive
        glc(2, lon=lon(0.1), trig="unknown"),                   # unknown trigger
        glc(3, lon=lon(0.2), trig="earthquake"),                # non rain
        glc(4, lon=lon(0.3), accu="25km"),                      # poor accuracy
        glc(5, lon=lon(0.4), accu="unknown"),                   # unknown accuracy
        glc(6, lon=lon(0.5), date="2006-12-31"),                # before the period
        glc(7, lon=lon(0.6), date="2025-01-15"),                # after the period
        glc(8, lon=lon(0.7), date="2007-01-15", accu="5km"),    # positive at the 5 km edge
        glc(9, lat=11.55, lon=76.13),                           # Western Ghats positive
    ])
    by_id = {int(r.event_id): r for r in df.itertuples()}
    assert by_id[1].is_positive and pd.isna(by_id[1].not_positive_reason)
    assert by_id[8].is_positive and by_id[9].is_positive and by_id[9].region == "western_ghats"
    expected = {2: "unknown_trigger", 3: "non_rain_trigger", 4: "poor_accuracy",
                5: "unknown_accuracy", 6: "outside_period", 7: "outside_period"}
    for event_id, reason in expected.items():
        assert not by_id[event_id].is_positive
        assert by_id[event_id].not_positive_reason == reason
        assert pd.isna(by_id[event_id].drop_reason)  # still in the store: defines the exclusion buffer
    assert df["trigger_class"].tolist()[1] == "unknown"


def test_dropped_records_are_never_positive_and_carry_no_not_positive_reason(tmp_path):
    df, _, _ = build(tmp_path, glc=[glc(1, cc="MM", lat=20.0, lon=95.0), glc(2)])
    dropped = df[df["drop_reason"].notna()]
    assert len(dropped) == 1
    assert not dropped["is_positive"].any() and dropped["not_positive_reason"].isna().all()
    assert df["is_positive"].dtype == bool


def test_report_counts_reconcile_and_are_strict_json(tmp_path):
    _, report_dict, out = build(
        tmp_path,
        glc=[glc(1), glc(2, date="", lat=""), glc(3, cc="MM", lat=20.0, lon=95.0), glc(4, trig="unknown", lon=80.0)],
        reports=[report(1, lon=81.0), report(5, lat="", date="2015-07-15")],
        events=[cevent(9, lon=82.0)],
        hma=[hma(1, lon=83.0), hma(7, lon=84.0), hma(8)], hma_deleted={2},
    )
    text = (out / "label_report.json").read_text(encoding="utf-8")

    def reject(constant):
        raise AssertionError(f"non-strict JSON constant {constant}")

    parsed = json.loads(text, parse_constant=reject)
    assert parsed == json.loads(json.dumps(report_dict))
    for name, counts in parsed["sources"].items():
        assert counts["n_input"] == sum(counts["n_dropped"].values()) + counts["n_kept"], name
        assert set(counts["n_dropped"]) == set(store.DROP_REASONS)
    glc_counts = parsed["sources"]["glc"]
    assert glc_counts["n_input"] == 4 and glc_counts["n_dropped"]["missing_date"] == 1
    assert glc_counts["n_dropped"]["out_of_scope_region"] == 1 and glc_counts["n_dropped"]["duplicate_id"] == 1
    assert glc_counts["n_kept"] == 1 and glc_counts["n_positive"] == 0
    assert glc_counts["not_positive_reasons"] == {"unknown_trigger": 1}
    assert parsed["sources"]["hma"]["n_input"] == 2 and parsed["sources"]["hma"]["n_positive"] == 2
    hma_input = next(entry for entry in parsed["inputs"] if entry["source"] == "hma")
    assert hma_input["n_rows"] == 2 and hma_input["n_deleted_records"] == 1
    assert [e["source"] for e in parsed["inputs"]] == ["hma", "coolr_reports", "glc", "coolr_events"]
    assert parsed["id_overlaps"] == {"hma|coolr_reports": 1, "hma|glc": 1, "coolr_reports|glc": 1}
    assert parsed["positives_per_region_per_year"] == {"himalaya": {"2015": 3}, "western_ghats": {}}


def test_reconciliation_violation_raises():
    bad = {"glc": {"n_input": 5, "n_dropped": {"missing_date": 1}, "n_kept": 3}}
    with pytest.raises(RuntimeError, match="glc"):
        store.assert_reconciled(bad)
    store.assert_reconciled({"glc": {"n_input": 4, "n_dropped": {"missing_date": 1}, "n_kept": 3}})


def test_build_events_does_not_mutate_inputs_and_is_deterministic(tmp_path):
    raw = write_raw_dir(tmp_path / "raw", glc=[glc(1), glc(2, lon=80.0)], hma=[hma(3, lon=81.0)])
    before = {p: p.read_bytes() for p in raw.rglob("*") if p.is_file()}
    store.build_events(raw, tmp_path / "a")
    store.build_events(raw, tmp_path / "b")
    assert before == {p: p.read_bytes() for p in raw.rglob("*") if p.is_file()}
    pd.testing.assert_frame_equal(pd.read_parquet(tmp_path / "a" / "events.parquet"),
                                  pd.read_parquet(tmp_path / "b" / "events.parquet"))


def test_missing_source_file_fails_loudly(tmp_path):
    raw = write_raw_dir(tmp_path / "raw")
    (raw / "nasa_glc.csv").unlink()
    with pytest.raises(FileNotFoundError, match="nasa_glc.csv"):
        store.build_events(raw, tmp_path / "out")


def test_cli_builds_and_prints_a_per_source_summary(tmp_path, capsys):
    raw = write_raw_dir(tmp_path / "raw", glc=[glc(1)], hma=[hma(2, lon=81.0)])
    out = tmp_path / "out"
    assert build_cli.main(["--raw-dir", str(raw), "--out-dir", str(out)]) == 0
    printed = capsys.readouterr().out
    assert (out / "events.parquet").exists() and (out / "label_report.json").exists()
    for source in ("hma", "coolr_reports", "glc", "coolr_events"):
        assert source in printed
    assert "positive" in printed


def test_cli_defaults_follow_the_data_root(isolated_data_root, capsys):
    write_raw_dir(isolated_data_root / "raw" / "manual", glc=[glc(1)])
    assert build_cli.main([]) == 0
    assert (isolated_data_root / "processed" / "labels" / "events.parquet").exists()
    capsys.readouterr()


@pytest.mark.realdata
def test_real_data_build_is_sane(tmp_path, capsys):
    raw = PROJECT_ROOT / "data" / "raw" / "manual"
    if not (raw / "nasa_glc.csv").exists():
        pytest.skip("real label files not present")
    report_dict = store.build_events(raw, tmp_path)
    df = pd.read_parquet(tmp_path / "events.parquet")
    store.assert_reconciled(report_dict["sources"])
    assert len(df) == sum(c["n_input"] for c in report_dict["sources"].values())
    overlaps = report_dict["id_overlaps"]
    assert overlaps["hma|coolr_reports"] > 0 and overlaps["hma|glc"] > 0 and overlaps["coolr_reports|glc"] > 0
    kept = df[df["drop_reason"].isna()]
    assert set(kept.loc[kept["is_positive"], "region"]) == {"himalaya", "western_ghats"}
    assert not kept["country_code"].isin(["MM", "BD", "PK", "CN"]).any()
    assert set(kept["region"]) <= {"himalaya", "western_ghats"}
    # Pinned facts of the delivered files (Phase 1 gate numbers).
    assert int(df["is_positive"].sum()) == 1132
    assert int(df["is_day_exact_positive"].sum()) == 956
    positives = df[df["is_positive"]]
    assert positives.groupby("region").size().to_dict() == {"himalaya": 956, "western_ghats": 176}
    in_2023 = positives[positives["event_date"].dt.year == 2023]
    assert len(in_2023) == 176 and (in_2023["date_basis"] == "inventory_window").all()
    assert not in_2023["is_day_exact_positive"].any()
    assert (in_2023["date_window_start"] == pd.Timestamp("2023-06-16")).all()
    assert (in_2023["date_window_end"] == pd.Timestamp("2023-07-31")).all()
    assert set(positives.loc[positives["date_basis"] == "event_day", "source"]) == {"hma", "coolr_reports"}
    drops = {name: c["n_dropped"] for name, c in report_dict["sources"].items()}
    assert {n: d["missing_country"] for n, d in drops.items()} == {
        "hma": 0, "coolr_reports": 1, "glc": 346, "coolr_events": 0}
    assert report_dict["id_conflicts"]["hma|coolr_reports"]["date_differs"] == 0
    assert report_dict["id_conflicts"]["hma|glc"]["date_differs"] == 3
    assert report_dict["id_conflicts"]["coolr_reports|glc"]["date_differs"] == 4
    assert [e["path"] for e in report_dict["inputs"]] == [
        "data/raw/manual/hma/HMA_LS_Cat_point_v02.0.dbf", "data/raw/manual/coolr_reports_points.csv",
        "data/raw/manual/nasa_glc.csv", "data/raw/manual/coolr_events_points.csv"]

    dbf = raw / "hma" / "HMA_LS_Cat_point_v02.0.dbf"
    table, n_deleted = sources.read_dbf(dbf, columns=["latitude", "longitude"])
    geometry = sources.read_shp_points(dbf.with_suffix(".shp"))
    shx_records = (dbf.with_suffix(".shx").stat().st_size - 100) // 8
    assert len(table) + n_deleted == len(geometry) == shx_records
    assert table["latitude"].to_numpy() == pytest.approx(geometry.loc[table.index, "latitude"].to_numpy(), abs=1e-7)
    assert table["longitude"].to_numpy() == pytest.approx(geometry.loc[table.index, "longitude"].to_numpy(), abs=1e-7)

    with capsys.disabled():
        print("\nREAL-DATA COUNTS")
        print(json.dumps(report_dict["sources"], indent=1))
        print("id_overlaps", report_dict["id_overlaps"])
        print("inventory_windows", report_dict["inventory_windows"])
