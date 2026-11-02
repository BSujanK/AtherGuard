import sys

import pytest
import requests

from aetherguard.audit import run
from aetherguard.http import DownloadError
from aetherguard.audit.result import ProbeResult


def test_registry_contains_every_planned_probe():
    assert set(run.build_registry()) == {
        "geolibs", "disk", "earthdata_credentials", "ghcnd", "isd", "open_meteo", "power_api",
        "power_zarr", "chirps", "imd", "dem", "worldcover", "soilgrids", "osm_roads",
        "nepal_inventories", "gaolan", "lithology_search", "kerala_inventory_search",
        "manual_catalogs", "feasibility"}


def test_safe_converts_network_errors_and_bugs_into_results():
    def network(ctx):
        raise requests.ConnectionError("offline")

    def bug(ctx):
        raise KeyError("oops")

    assert run.safe("a", network, None)[0].status == "unreachable"
    res = run.safe("b", bug, None)[0]
    assert res.status == "inconclusive" and "KeyError" in res.summary


def test_safe_flattens_lists_and_passes_single_results_through():
    one = ProbeResult("x", "ok", "s")
    assert run.safe("x", lambda ctx: one, None) == [one]
    assert run.safe("x", lambda ctx: [one, one], None) == [one, one]


def _tracked_manifest_state():
    tracked = run.PROJECT_ROOT / "manifests" / "data_manifest.jsonl"
    return tracked.read_bytes() if tracked.exists() else None


def test_offline_audit_still_writes_reports(monkeypatch, tmp_path, isolated_data_root):
    # never read the developer's real credentials: point the home directory at an empty tmp dir
    home = tmp_path / "home"
    home.mkdir()
    for var in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(var, str(home))
    monkeypatch.delenv("EARTHDATA_USERNAME", raising=False)
    monkeypatch.delenv("EARTHDATA_PASSWORD", raising=False)
    tracked_before = _tracked_manifest_state()

    def offline(*args, **kwargs):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr("aetherguard.http.requests.get", offline)
    monkeypatch.setattr("aetherguard.http.requests.head", offline, raising=False)
    monkeypatch.setattr("aetherguard.http.time.sleep", lambda s: None)
    reports = tmp_path / "reports"
    results = run.run_audit(only={"open_meteo", "power_api", "manual_catalogs", "feasibility"},
                            reports_dir=reports, manifest_path=tmp_path / "manifest.jsonl")
    statuses = {r.name: r.status for r in results}
    assert statuses["open_meteo"] == "unreachable"
    assert statuses["power_api"] == "unreachable"
    assert statuses["feasibility"] == "ok"
    assert (reports / "phase0_data_audit.md").exists()
    assert (reports / "phase0_data_audit.json").exists()
    assert _tracked_manifest_state() == tracked_before  # the tracked manifest is neither created nor changed


# --- review fixes: output validation, redacted CLI output, no side effects on bad --only ---------

def test_safe_normalises_tuples_and_rejects_malformed_output():
    one = ProbeResult("x", "ok", "s")
    assert run.safe("x", lambda ctx: (one, one), None) == [one, one]
    for bad, type_name in [(None, "NoneType"), ({"a": 1}, "dict"), ("text", "str"), ([one, "junk"], "list"),
                           ((one, None), "tuple")]:
        out = run.safe("probe_name", lambda ctx, bad=bad: bad, None)
        assert len(out) == 1 and out[0].name == "probe_name" and out[0].status == "inconclusive"
        assert out[0].summary == f"probe returned {type_name} instead of ProbeResult(s)"


def test_unknown_only_name_fails_before_any_side_effect(monkeypatch, tmp_path):
    data_dir = tmp_path / "not_created_data"
    monkeypatch.setenv("AETHERGUARD_DATA_DIR", str(data_dir))

    def no_config(name):
        raise AssertionError("config must not be loaded for an unknown probe name")

    monkeypatch.setattr(run, "load_config", no_config)
    manifest = tmp_path / "m" / "manifest.jsonl"
    reports = tmp_path / "r"
    with pytest.raises(SystemExit):
        run.run_audit(only={"nope"}, reports_dir=reports, manifest_path=manifest)
    assert not data_dir.exists() and not manifest.parent.exists() and not reports.exists()


def test_cli_prints_redacted_summaries(monkeypatch, capsys, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    for var in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(var, str(home))
    monkeypatch.delenv("EARTHDATA_USERNAME", raising=False)
    monkeypatch.setenv("EARTHDATA_PASSWORD", "hunter2-secret")
    results = [ProbeResult("p1", "fail", "login failed for hunter2-secret"),
               ProbeResult("p2", "fail", "x" * 80 + "hunter2-secret")]  # secret straddles the 90-char cut
    monkeypatch.setattr(run, "run_audit", lambda *args, **kwargs: results)
    monkeypatch.setattr(sys, "argv", ["run"])
    run.main()
    out = capsys.readouterr().out
    assert "hunter2-secret" not in out and "hunt" not in out
    assert "login failed for [REDACTED]" in out


# --- final review fixes: partial runs, DownloadError classification --------------------------------

def _isolate_home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    for var in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(var, str(home))
    for var in ("EARTHDATA_USERNAME", "EARTHDATA_PASSWORD", "EARTHDATA_TOKEN"):
        monkeypatch.delenv(var, raising=False)


def _tiny_registry():
    return {"alpha": lambda c: ProbeResult("alpha", "ok", "a"),
            "beta": lambda c: ProbeResult("beta", "ok", "b")}


def test_partial_run_writes_to_partial_dir_and_leaves_full_reports_alone(
        monkeypatch, tmp_path, isolated_data_root, capsys):
    _isolate_home(monkeypatch, tmp_path)
    monkeypatch.setattr(run, "build_registry", _tiny_registry)
    full_dir = tmp_path / "reports"
    run.run_audit(only={"alpha"}, manifest_path=tmp_path / "m.jsonl", default_reports_dir=full_dir)
    partial = full_dir / "partial"
    assert (partial / "phase0_data_audit.md").exists() and (partial / "phase0_data_audit.json").exists()
    assert not (full_dir / "phase0_data_audit.md").exists()
    assert not (full_dir / "phase0_data_audit.json").exists()
    assert str(partial) in capsys.readouterr().out  # the output directory is printed


def test_full_run_writes_to_the_full_reports_dir(monkeypatch, tmp_path, isolated_data_root):
    _isolate_home(monkeypatch, tmp_path)
    monkeypatch.setattr(run, "build_registry", _tiny_registry)
    full_dir = tmp_path / "reports"
    run.run_audit(manifest_path=tmp_path / "m.jsonl", default_reports_dir=full_dir)
    assert (full_dir / "phase0_data_audit.md").exists() and (full_dir / "phase0_data_audit.json").exists()
    assert not (full_dir / "partial").exists()


def test_explicit_reports_dir_wins_even_for_partial_runs(monkeypatch, tmp_path, isolated_data_root):
    _isolate_home(monkeypatch, tmp_path)
    monkeypatch.setattr(run, "build_registry", _tiny_registry)
    explicit = tmp_path / "explicit"
    run.run_audit(only={"alpha"}, reports_dir=explicit, manifest_path=tmp_path / "m.jsonl",
                  default_reports_dir=tmp_path / "reports")
    assert (explicit / "phase0_data_audit.md").exists()
    assert not (tmp_path / "reports").exists()


def test_default_partial_dir_is_under_the_project_reports_dir():
    assert run.PARTIAL_DIR_NAME == "partial"


def test_safe_classifies_download_errors_by_retriability():
    def fatal(ctx):
        raise DownloadError("HTTP 404 from https://x", retriable=False)

    def transient(ctx):
        raise DownloadError("HTTP 503 from https://x", retriable=True)

    assert run.safe("a", fatal, None)[0].status == "fail"
    assert run.safe("a", transient, None)[0].status == "unreachable"
    assert "HTTP 404" in run.safe("a", fatal, None)[0].summary
