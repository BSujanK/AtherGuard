"""build_splits / verify_splits: integrity invariants, freeze semantics and tamper detection."""
import json
import os
import re
import stat

import pandas as pd
import pytest
from splits_helpers import HIMALAYA, cell, event, events_frame, sample_events, write_events

from aetherguard.config import load_config
from aetherguard.manifest import sha256_file
from aetherguard.splits import freeze
from aetherguard.splits.freeze import (
    CELL_DAYS_NAME,
    MANIFEST_NAME,
    WINDOWS_NAME,
    SplitsFrozenError,
    build_splits,
    verify_splits,
)

CFG = load_config("splits")
FILES = [CELL_DAYS_NAME, WINDOWS_NAME]


@pytest.fixture
def events_path(tmp_path):
    path = tmp_path / "labels" / "events.parquet"
    write_events(sample_events(), path)
    return path


@pytest.fixture
def built(events_path, splits_out_dir):
    manifest = build_splits(events_path, splits_out_dir)
    return splits_out_dir, manifest


def writable(path):
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)


def read_only(path) -> bool:
    return not path.stat().st_mode & stat.S_IWRITE


def test_build_writes_the_three_files_and_marks_them_read_only(built):
    out, manifest = built
    for name in [*FILES, MANIFEST_NAME]:
        assert (out / name).is_file() and read_only(out / name)
    assert json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8")) == manifest
    assert manifest["frozen"] is True
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", manifest["created_utc"])
    assert manifest["config"] == CFG


def test_manifest_counts_per_split_and_region(built):
    _, manifest = built
    splits = manifest["splits"]
    assert list(splits) == ["train", "validation", "test_2018", "test_sparse"]
    assert splits["train"] == {
        "cell_days": 3, "events": 42, "min_date": "2010-07-01", "max_date": "2015-12-31",
        "regions": {"himalaya": {"cell_days": 3, "events": 42},
                    "western_ghats": {"cell_days": 0, "events": 0}}}
    assert splits["validation"]["cell_days"] == 2 and splits["validation"]["min_date"] == "2016-01-01"
    assert splits["validation"]["max_date"] == "2017-12-31"
    assert splits["test_2018"]["regions"] == {"himalaya": {"cell_days": 3, "events": 3},
                                              "western_ghats": {"cell_days": 4, "events": 4}}
    assert (splits["test_2018"]["min_date"], splits["test_2018"]["max_date"]) == ("2018-01-01", "2018-12-31")
    assert splits["test_sparse"]["regions"]["western_ghats"] == {"cell_days": 2, "events": 2}
    assert (splits["test_sparse"]["min_date"], splits["test_sparse"]["max_date"]) == ("2019-01-01", "2024-12-31")
    assert sum(s["cell_days"] for s in splits.values()) == manifest["totals"]["day_exact_cell_days"] == 16
    assert manifest["totals"]["day_exact_events"] == 55
    assert manifest["totals"]["window_cells"] == 2 and manifest["totals"]["window_events"] == 3


def test_manifest_window_test_case_studies_and_leakage(built):
    _, manifest = built
    window = manifest["window_test"]
    assert window["name"] == "test_2023_india_window"
    assert (window["cell_windows"], window["events"]) == (2, 3)
    assert (window["window_start_min"], window["window_end_max"]) == ("2023-06-16", "2023-07-31")
    assert window["regions"]["himalaya"] == {"cell_windows": 2, "events": 3}
    cases = manifest["case_studies"]
    assert cases["kerala_2018"]["cell_days"] == 3 and cases["kerala_2018"]["events"] == 3
    assert cases["wayanad_2024"] == {"region": "western_ghats", "start": "2024-07-25", "end": "2024-08-05",
                                     "cell_days": 0, "events": 0}
    assert manifest["leakage"]["per_split"]["validation"] == {"n": 2, "n_within": 1, "share": 0.5}
    assert manifest["leakage"]["per_split"]["test_2018"]["n_within"] == 0


def test_manifest_records_checksums_of_events_and_outputs(built, events_path):
    out, manifest = built
    assert manifest["events"]["sha256"] == sha256_file(events_path)
    assert manifest["events"]["path"] == "events.parquet"  # outside the project: file name only
    assert manifest["events"]["n_rows"] == len(sample_events())
    for name in FILES:
        assert manifest["files"][name]["sha256"] == sha256_file(out / name)
        assert manifest["files"][name]["size_bytes"] == (out / name).stat().st_size
    assert manifest["files"][CELL_DAYS_NAME]["n_rows"] == 16
    assert manifest["files"][WINDOWS_NAME]["n_rows"] == 2


def test_manifest_is_strict_json_without_absolute_paths(built, tmp_path):
    out, _ = built
    text = (out / MANIFEST_NAME).read_text(encoding="utf-8")

    def reject(constant):
        raise AssertionError(f"non-strict JSON constant {constant}")

    data = json.loads(text, parse_constant=reject)
    assert str(tmp_path) not in text and str(tmp_path).replace("\\", "/") not in text

    def strings(node):
        if isinstance(node, dict):
            for key, value in node.items():
                yield key
                yield from strings(value)
        elif isinstance(node, list):
            for value in node:
                yield from strings(value)
        elif isinstance(node, str):
            yield node

    for value in strings(data):
        assert not re.match(r"^([A-Za-z]:[\\/]|/|\\\\)", value), value


def test_manifest_events_path_is_project_relative_when_inside_the_project(tmp_path):
    inside = freeze.PROJECT_ROOT / "data" / "processed" / "labels" / "events.parquet"
    assert freeze._display_path(inside) == "data/processed/labels/events.parquet"
    assert freeze._display_path(tmp_path / "x" / "events.parquet") == "events.parquet"


def test_cell_day_table_invariants(built):
    out, _ = built
    cell_days = pd.read_parquet(out / CELL_DAYS_NAME)
    windows = pd.read_parquet(out / WINDOWS_NAME)
    assert list(cell_days.columns) == ["cell_id", "event_date", "region", "country_code", "n_events",
                                       "sources", "min_accuracy_km", "max_accuracy_km", "split", "case_study"]
    assert not cell_days.duplicated(["cell_id", "event_date"]).any()  # no cell-day in two splits or twice
    assert cell_days.groupby(["cell_id", "event_date"])["split"].nunique().max() == 1
    assert cell_days["n_events"].sum() == 55 and len(cell_days) == 16  # every positive exactly once
    assert pd.MultiIndex.from_frame(cell_days[["event_date", "cell_id"]]).is_monotonic_increasing
    for name, spec in CFG["day_splits"].items():
        dates = cell_days.loc[cell_days["split"] == name, "event_date"]
        assert dates.between(pd.Timestamp(spec["start"]), pd.Timestamp(spec["end"])).all()
    assert set(cell_days.loc[cell_days["case_study"] == "kerala_2018", "split"]) == {"test_2018"}
    assert (cell_days["case_study"] == "wayanad_2024").sum() == 0
    # window positives and daily positives are disjoint populations
    assert set(windows["split"]) == {"test_2023_india_window"}
    assert "test_2023_india_window" not in set(cell_days["split"])
    assert (cell_days["event_date"] != pd.Timestamp("2023-07-01")).all()
    assert len(windows) == 2 and windows["n_events"].sum() == 3


def test_boundary_days_land_in_the_right_split(built):
    out, _ = built
    cell_days = pd.read_parquet(out / CELL_DAYS_NAME)
    far = cell(2100, 4000)
    expected = {"2015-12-31": "train", "2016-01-01": "validation", "2017-12-31": "validation",
                "2018-01-01": "test_2018", "2018-12-31": "test_2018", "2019-01-01": "test_sparse",
                "2024-12-31": "test_sparse"}
    rows = cell_days[cell_days["cell_id"] == far]
    assert dict(zip(rows["event_date"].dt.strftime("%Y-%m-%d"), rows["split"])) == expected


def test_positive_after_2024_raises_and_writes_nothing(tmp_path, splits_out_dir):
    df = events_frame([event(1, "2025-01-01", cell(*HIMALAYA))])
    path = tmp_path / "events.parquet"
    write_events(df, path)
    with pytest.raises(ValueError, match="outside every split"):
        build_splits(path, splits_out_dir)
    assert not splits_out_dir.exists() or not any(splits_out_dir.iterdir())


def test_null_window_bound_fails_the_build_without_writing(tmp_path, splits_out_dir):
    df = sample_events()
    df.loc[df["uid"] == "coolr_events:303", "date_window_end"] = pd.NaT
    path = tmp_path / "events.parquet"
    write_events(df, path)
    with pytest.raises(ValueError, match="null window bound"):
        build_splits(path, splits_out_dir)
    assert not (splits_out_dir / MANIFEST_NAME).exists()


def test_frozen_directory_refuses_to_rebuild_without_force(built, events_path):
    out, manifest = built
    before = {name: (out / name).read_bytes() for name in [*FILES, MANIFEST_NAME]}
    changed = pd.concat([sample_events(), events_frame([event(900, "2011-05-05", cell(2200, 4200))])],
                        ignore_index=True)
    write_events(changed, events_path)
    with pytest.raises(SplitsFrozenError, match="frozen"):
        build_splits(events_path, out)
    assert {name: (out / name).read_bytes() for name in before} == before


def test_force_rebuilds_everything_and_refreezes(built, events_path):
    out, manifest = built
    changed = pd.concat([sample_events(), events_frame([event(900, "2011-05-05", cell(2200, 4200))])],
                        ignore_index=True)
    write_events(changed, events_path)
    rebuilt = build_splits(events_path, out, force=True)
    assert rebuilt["totals"]["day_exact_cell_days"] == 17
    assert rebuilt["events"]["sha256"] == sha256_file(events_path) != manifest["events"]["sha256"]
    assert len(pd.read_parquet(out / CELL_DAYS_NAME)) == 17
    assert all(read_only(out / name) for name in [*FILES, MANIFEST_NAME])
    assert verify_splits(out, events_path)["ok"]


def test_build_is_deterministic(events_path, tmp_path):
    first = build_splits(events_path, tmp_path / "a")
    second = build_splits(events_path, tmp_path / "b")
    try:
        for name in FILES:
            assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()
        assert first["files"] == second["files"]
        assert first["splits"] == second["splits"] and first["leakage"] == second["leakage"]
    finally:
        for directory in (tmp_path / "a", tmp_path / "b"):
            for path in directory.iterdir():
                writable(path)


def test_verify_passes_on_an_untouched_build(built, events_path):
    out, _ = built
    assert verify_splits(out) == {"ok": True, "problems": []}
    assert verify_splits(out, events_path) == {"ok": True, "problems": []}


def test_verify_missing_manifest_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match=MANIFEST_NAME):
        verify_splits(tmp_path / "nothing")


def test_verify_detects_a_modified_parquet_byte(built):
    out, _ = built
    target = out / CELL_DAYS_NAME
    writable(target)
    data = bytearray(target.read_bytes())
    data[len(data) // 2] ^= 0x01
    target.write_bytes(bytes(data))
    result = verify_splits(out)
    assert not result["ok"]
    assert any("checksum mismatch" in p and CELL_DAYS_NAME in p for p in result["problems"])


def test_verify_detects_a_deleted_file(built):
    out, _ = built
    writable(out / WINDOWS_NAME)
    (out / WINDOWS_NAME).unlink()
    result = verify_splits(out)
    assert not result["ok"]
    assert any("missing" in p and WINDOWS_NAME in p for p in result["problems"])


def test_verify_detects_a_changed_events_file(built, events_path):
    out, _ = built
    changed = pd.concat([sample_events(), events_frame([event(900, "2011-05-05", cell(2200, 4200))])],
                        ignore_index=True)
    write_events(changed, events_path)
    result = verify_splits(out, events_path)
    assert not result["ok"]
    assert any("events" in p and "checksum mismatch" in p for p in result["problems"])
    assert any("reproduce" in p for p in result["problems"])


def test_verify_detects_a_missing_events_file(built, events_path):
    out, _ = built
    events_path.unlink()
    result = verify_splits(out, events_path)
    assert not result["ok"] and any("events" in p and "missing" in p for p in result["problems"])


def test_verify_detects_stored_tables_that_no_longer_follow_from_the_events(built, events_path):
    # events changed AND the manifest's events hash rewritten to match: only the recomputation can tell.
    out, _ = built
    changed = pd.concat([sample_events(), events_frame([event(900, "2011-05-05", cell(2200, 4200))])],
                        ignore_index=True)
    write_events(changed, events_path)
    manifest_path = out / MANIFEST_NAME
    writable(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["events"]["sha256"] = sha256_file(events_path)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    result = verify_splits(out, events_path)
    assert not result["ok"]
    assert [p for p in result["problems"] if "checksum" in p] == []
    assert any("reproduce" in p for p in result["problems"])


def test_verify_detects_manifest_edited_to_not_frozen(built):
    out, _ = built
    manifest_path = out / MANIFEST_NAME
    writable(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["frozen"] = False
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    result = verify_splits(out)
    assert not result["ok"] and any("not frozen" in p for p in result["problems"])


def test_verify_reports_an_unreadable_manifest_as_a_problem(built):
    out, _ = built
    manifest_path = out / MANIFEST_NAME
    writable(manifest_path)
    manifest_path.write_text("{not json", encoding="utf-8")
    result = verify_splits(out)
    assert not result["ok"] and any("manifest" in p for p in result["problems"])
