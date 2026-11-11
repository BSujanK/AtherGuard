"""Fixes from the 2026-11-11 audit: the manifest lock on Windows, the health path, the stream's watch list, the daily task."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aetherguard import manifest as mf
from aetherguard.serve import api, dash_api

ROOT = Path(__file__).resolve().parents[1]


def test_the_lock_waits_when_windows_denies_access_to_a_lock_file_that_is_being_deleted(tmp_path, monkeypatch):
    """Another process deleting the lock makes `os.open` raise PermissionError on Windows, not FileExistsError."""
    real_open, calls = os.open, {"n": 0}

    def flaky_open(path, flags, *args, **kwargs):
        if str(path).endswith(".lock"):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise PermissionError(13, "Access is denied", str(path))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(mf.os, "open", flaky_open)
    with mf._process_lock(tmp_path / "manifest.jsonl"):
        assert (tmp_path / "manifest.jsonl.lock").exists()
    assert calls["n"] == 3 and not (tmp_path / "manifest.jsonl.lock").exists()


def test_a_lock_that_is_denied_for_longer_than_the_timeout_still_gives_up(tmp_path, monkeypatch):
    def denied(path, flags, *args, **kwargs):
        raise PermissionError(13, "Access is denied", str(path))

    monkeypatch.setattr(mf.os, "open", denied)
    with pytest.raises(TimeoutError):
        with mf._process_lock(tmp_path / "manifest.jsonl", timeout_s=0.2):
            pass


def test_health_names_the_store_without_this_machines_absolute_path(tmp_path):
    body = TestClient(api.create_app(tmp_path / "nothing", dist_dir=tmp_path / "no-dist")).get("/health").json()
    assert body["replay_store"] == "nothing"
    assert str(tmp_path) not in body["replay_store"] and ":" not in body["replay_store"]


def test_the_stream_watches_only_the_newest_run_days(tmp_path):
    live = tmp_path / "live"
    for day in range(1, 31):
        folder = live / f"2026-10-{day:02d}"
        folder.mkdir(parents=True)
        (folder / "alerts.parquet").write_bytes(b"x")
    from aetherguard.alerts.store import ReplayStore
    runs, _, _ = dash_api._snapshot(ReplayStore(tmp_path / "no-store"), live)
    assert len(runs) == dash_api.WATCHED_RUN_DAYS + 1                 # the newest days, plus how many days there are
    assert runs[0] == 30 and str(runs[-1][0]).endswith(os.path.join("2026-10-30", "alerts.parquet"))


def test_the_daily_task_wakes_the_laptop_and_tries_again_every_hour():
    shell = shutil.which("powershell") or shutil.which("pwsh")
    if shell is None:
        pytest.skip("PowerShell is not available")
    out = subprocess.run([shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                          str(ROOT / "scripts" / "install_daily_task.ps1"), "-DryRun"],
                         capture_output=True, text=True, timeout=60, check=True).stdout
    for needle in ("WakeToRun", "every hour from 13:00 to 23:00"):
        assert needle in out, needle
