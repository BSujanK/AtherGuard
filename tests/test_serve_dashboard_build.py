"""Dashboard build stage: the npm steps, their order and their failures (npm is faked, nothing is built)."""
from types import SimpleNamespace

import pytest

from aetherguard.pipeline import stages
from aetherguard.serve import dashboard_build as db


def project(tmp_path, built=True):
    (tmp_path / "package.json").write_text("{}")
    if built:
        (tmp_path / "dist").mkdir()
        (tmp_path / "dist" / "index.html").write_text("<html>")
    return tmp_path


def recorder(codes=()):
    calls = []

    def run(command, cwd):
        calls.append((command, cwd))
        return SimpleNamespace(returncode=codes[len(calls) - 1] if len(codes) >= len(calls) else 0)
    return calls, run


def test_installs_cleanly_then_builds_in_the_dashboard_folder(tmp_path):
    folder = project(tmp_path)
    calls, run = recorder()
    assert db.build_dashboard(folder, run=run, which=lambda name: "NPM") == folder / "dist" / "index.html"
    assert calls == [(["NPM", "ci"], folder), (["NPM", "run", "build"], folder)]


def test_skip_install_only_builds(tmp_path):
    folder = project(tmp_path)
    calls, run = recorder()
    db.build_dashboard(folder, skip_install=True, run=run, which=lambda name: "NPM")
    assert [c for c, _ in calls] == [["NPM", "run", "build"]]


@pytest.mark.parametrize("codes, step", [((1,), "npm ci"), ((0, 2), "npm run build")])
def test_a_failing_npm_step_is_named_and_stops_the_build(tmp_path, codes, step):
    calls, run = recorder(codes)
    with pytest.raises(db.BuildError, match=step):
        db.build_dashboard(project(tmp_path), run=run, which=lambda name: "NPM")
    assert len(calls) == len(codes)


def test_missing_npm_missing_project_and_missing_output_are_clear_errors(tmp_path):
    _, run = recorder()
    with pytest.raises(db.BuildError, match="npm was not found"):
        db.build_dashboard(project(tmp_path), run=run, which=lambda name: None)
    with pytest.raises(db.BuildError, match="package.json not found"):
        db.build_dashboard(tmp_path / "empty", run=run, which=lambda name: "NPM")
    unbuilt = tmp_path / "unbuilt"
    unbuilt.mkdir()
    with pytest.raises(db.BuildError, match="without producing dist/index.html"):
        db.build_dashboard(project(unbuilt, built=False), run=run, which=lambda name: "NPM")


def test_main_reports_a_failure_on_stderr_and_returns_one(monkeypatch, capsys):
    def fail(**kwargs):
        raise db.BuildError("npm was not found on PATH")
    monkeypatch.setattr(db, "build_dashboard", fail)
    assert db.main(["--skip-install"]) == 1
    assert "npm was not found" in capsys.readouterr().err


def test_main_passes_skip_install_through_and_names_the_built_file(monkeypatch, capsys):
    seen = {}
    monkeypatch.setattr(db, "build_dashboard", lambda **kwargs: seen.update(kwargs) or db.DASHBOARD_DIR / db.INDEX)
    assert db.main(["--skip-install"]) == 0 and seen == {"skip_install": True}
    assert "built dashboard/dist/index.html" in capsys.readouterr().out


def test_the_pipeline_builds_the_dashboard_before_the_final_report_and_offline_skips_the_install():
    parsed = stages.parse_stages(stages.load_config())
    names = [s.name for s in parsed]
    stage = parsed[names.index("dashboard_build")]
    assert names.index("alerts_report") < names.index("dashboard_build") < names.index("final_report")
    assert stage.module == "aetherguard.serve.dashboard_build" and stage.network and stage.offline_args == ("--skip-install",)
    assert stage.outputs == ("dashboard/dist/index.html",) and stages.module_exists(stage.module)
