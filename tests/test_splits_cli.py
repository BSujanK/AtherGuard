"""CLI entry points: python -m aetherguard.splits.build / verify."""
import os
import stat

import pandas as pd
import pytest
from splits_helpers import cell, event, events_frame, sample_events, write_events

from aetherguard.config import data_root
from aetherguard.splits import build, freeze, verify


@pytest.fixture
def events_path(tmp_path):
    path = tmp_path / "events.parquet"
    write_events(sample_events(), path)
    return path


def test_build_cli_prints_the_count_tables(events_path, splits_out_dir, capsys):
    assert build.main(["--events", str(events_path), "--out-dir", str(splits_out_dir)]) == 0
    out = capsys.readouterr().out
    for expected in ("himalaya", "western_ghats", "train", "validation", "test_2018", "test_sparse",
                     "test_2023_india_window: 2 cell-windows / 3 events",
                     "case study kerala_2018", "case study wayanad_2024",
                     "0 cell-days / 0 events  <- NO POSITIVES", "leakage", "validation", "all checked"):
        assert expected in out
    assert (splits_out_dir / freeze.MANIFEST_NAME).is_file()


def test_build_cli_refuses_a_frozen_directory_without_force(events_path, splits_out_dir, capsys):
    assert build.main(["--events", str(events_path), "--out-dir", str(splits_out_dir)]) == 0
    capsys.readouterr()
    assert build.main(["--events", str(events_path), "--out-dir", str(splits_out_dir)]) == 1
    captured = capsys.readouterr()
    assert "frozen" in captured.err and captured.out == ""
    assert build.main(["--events", str(events_path), "--out-dir", str(splits_out_dir), "--force"]) == 0


def test_build_cli_uses_default_paths_under_the_data_root(isolated_data_root, capsys):
    events = data_root() / "processed" / "labels" / "events.parquet"
    write_events(sample_events(), events)
    assert build.main([]) == 0
    capsys.readouterr()
    splits_dir = data_root() / "processed" / "splits"
    try:
        assert (splits_dir / freeze.MANIFEST_NAME).is_file()
        assert verify.main(["--events", str(events)]) == 0
    finally:
        for path in splits_dir.iterdir():
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)


def test_verify_cli_exit_codes(events_path, splits_out_dir, capsys):
    assert verify.main(["--out-dir", str(splits_out_dir)]) == 1  # nothing built yet
    assert "splits_manifest.json" in capsys.readouterr().err

    build.main(["--events", str(events_path), "--out-dir", str(splits_out_dir)])
    capsys.readouterr()
    assert verify.main(["--out-dir", str(splits_out_dir), "--events", str(events_path)]) == 0
    assert "OK" in capsys.readouterr().out

    changed = pd.concat([sample_events(), events_frame([event(900, "2011-05-05", cell(2200, 4200))])],
                        ignore_index=True)
    write_events(changed, events_path)
    assert verify.main(["--out-dir", str(splits_out_dir), "--events", str(events_path)]) == 1
    out = capsys.readouterr().out
    assert "PROBLEMS" in out and "events checksum mismatch" in out
