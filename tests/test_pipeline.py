import hashlib
import json
import sys
import textwrap

import pytest
import yaml

from aetherguard.pipeline import cli, runner, stages
from aetherguard.pipeline.stages import PipelineConfigError, Paths

FAKE_OK = textwrap.dedent('''
    import argparse, pathlib, sys
    p = argparse.ArgumentParser()
    p.add_argument("--name", required=True)
    p.add_argument("--out", default=None)
    p.add_argument("--order", default=None)
    p.add_argument("--offline-flag", action="store_true")
    p.add_argument("--skip-download", action="store_true")
    a = p.parse_args()
    print("running", a.name, "skip" if a.skip_download else "")
    if a.order:
        with open(a.order, "a") as h:
            h.write(a.name + (" skip-download" if a.skip_download else "") + "\\n")
    if a.out:
        pathlib.Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(a.out).write_text("x")
''')
FAKE_FAIL = "import sys\nprint('about to fail', file=sys.stderr)\nsys.exit(3)\n"
FAKE_NOOP = "print('did nothing')\n"
FAKE_VERIFY_OK = "import sys\nprint('intact')\nsys.exit(0)\n"
FAKE_VERIFY_BAD = "import sys\nprint('damaged')\nsys.exit(1)\n"


@pytest.fixture
def world(tmp_path, monkeypatch):
    fakes = tmp_path / "fakes"
    fakes.mkdir()
    for name, body in (("fake_ok", FAKE_OK), ("fake_fail", FAKE_FAIL), ("fake_noop", FAKE_NOOP),
                       ("fake_verify_ok", FAKE_VERIFY_OK), ("fake_verify_bad", FAKE_VERIFY_BAD)):
        (fakes / f"{name}.py").write_text(body, encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("AETHERGUARD_DATA_DIR", str(data))
    order = tmp_path / "order.txt"

    def stage(name, module="fake_ok", out=True, **extra):
        spec = {"name": name, "module": module, "args": ["--name", name, "--order", str(order)]}
        if out:
            spec["args"] += ["--out", "{data}/" + f"{name}.out"]
            spec["marker"] = ["{data}/" + f"{name}.out"]
            spec["outputs"] = list(spec["marker"])
        spec.update(extra)
        return spec

    def build(specs):
        for spec in specs:                               # {data} is not expanded inside args: resolve here
            spec["args"] = [a.replace("{data}", str(data)) for a in spec["args"]]
        return {"python": sys.executable, "pythonpath": [str(fakes)], "log_dir": "logs/pipeline", "stages": specs}

    paths = Paths(tmp_path, data, tmp_path / "reports")
    return {"tmp": tmp_path, "data": data, "order": order, "stage": stage, "build": build, "paths": paths}


def run(world, specs, **kwargs):
    cfg = world["build"](specs)
    parsed = stages.parse_stages(cfg)
    chosen = stages.select_stages(parsed, kwargs.pop("start", None), kwargs.pop("end", None), kwargs.pop("only", None),
                                  kwargs.pop("include", None))
    messages = []
    results, code = runner.run_pipeline(cfg, chosen, world["paths"], out=messages.append, **kwargs)
    return results, code, messages, cfg


def order(world):
    return world["order"].read_text().split() if world["order"].exists() else []


# --------------------------------------------------------------------------------------------- configuration

def test_config_validation_names_the_offending_stage():
    good = {"stages": [{"name": "a", "module": "m", "args": ["--x"]}]}
    assert stages.parse_stages(good)[0].steps == (stages.Step("m", ("--x",)),)
    for bad, text in (({"stages": []}, "no `stages`"),
                      ({"stages": [{"name": "a", "module": "m"}, {"name": "a", "module": "n"}]}, "duplicate"),
                      ({"stages": [{"name": "a"}]}, "needs `module`"),
                      ({"stages": [{"name": "a", "module": "m", "bogus": 1}]}, "unknown keys"),
                      ({"stages": [{"name": "a", "module": "m", "args": [1]}]}, "list of strings"),
                      ({"stages": [{"name": "a", "module": "m", "frozen_manifest": {"path": "x"}}]}, "frozen_manifest")):
        with pytest.raises(PipelineConfigError, match=text):
            stages.parse_stages(bad)


def test_selection_from_to_only_include_and_default_false():
    cfg = {"stages": [{"name": n, "module": "m", **({"default": False} if n == "audit" else {})}
                      for n in ("audit", "a", "b", "c", "d")]}
    parsed = stages.parse_stages(cfg)
    names = lambda sel: [s.name for s in sel]  # noqa: E731
    assert names(stages.select_stages(parsed)) == ["a", "b", "c", "d"]
    assert names(stages.select_stages(parsed, start="b")) == ["b", "c", "d"]
    assert names(stages.select_stages(parsed, end="b")) == ["a", "b"]
    assert names(stages.select_stages(parsed, start="b", end="c")) == ["b", "c"]
    assert names(stages.select_stages(parsed, only=["d", "a"])) == ["a", "d"]
    assert names(stages.select_stages(parsed, only=["audit"])) == ["audit"]
    assert names(stages.select_stages(parsed, include=["audit"])) == ["audit", "a", "b", "c", "d"]
    for kwargs, text in (({"start": "zz"}, "unknown stage 'zz'"), ({"only": ["nope"]}, "--only"),
                         ({"start": "c", "end": "a"}, "comes after")):
        with pytest.raises(PipelineConfigError, match=text):
            stages.select_stages(parsed, **kwargs)


def test_the_real_configuration_parses_lists_the_required_stages_in_order_and_uses_existing_modules():
    parsed = stages.parse_stages(stages.load_config())
    names = [s.name for s in parsed]
    required = ["audit", "labels", "splits", "imd", "chirps", "power", "terrain", "regions", "samples", "features",
                "integrity_2a", "engine_data", "integrity_engine", "integ_features", "corrector", "hazard_train",
                "hazard_report", "cases", "alerts_report", "final_report"]
    assert [n for n in names if n in required] == required
    assert next(s for s in parsed if s.name == "audit").default is False
    for stage in parsed:
        if not stage.optional:
            assert all(stages.module_exists(step.module) for step in stage.steps), stage.name
    for name in ("splits", "samples", "features"):
        assert next(s for s in parsed if s.name == name).verify is not None


# ----------------------------------------------------------------------------------------------- running

def test_stages_run_in_configured_order_and_every_run_is_logged(world):
    specs = [world["stage"](n) for n in ("one", "two", "three")]
    results, code, messages, cfg = run(world, specs)
    assert code == 0 and [r.name for r in results] == ["one", "two", "three"] and order(world) == ["one", "two", "three"]
    assert all(r.status == "ran" and r.exit_code == 0 and r.duration_s >= 0 for r in results)
    for name in ("one", "two", "three"):
        text = (world["tmp"] / "logs" / "pipeline" / f"{name}.log").read_text(encoding="utf-8")
        assert f"running {name}" in text and "[exit code 0]" in text and text.startswith("$ ")
        assert str(sys.executable) not in text.splitlines()[0]          # the interpreter path is not written absolute
    record = json.loads(next((world["tmp"] / "logs" / "pipeline").glob("run_*.json")).read_text(encoding="utf-8"))
    assert record["finished"] is True and record["exit_code"] == 0 and record["python"] == sys.executable
    assert [s["name"] for s in record["stages"]] == ["one", "two", "three"]
    assert {"started", "ended", "duration_s", "exit_code", "log", "commands", "status"} <= set(record["stages"][0])
    assert record["stages"][0]["log"] == "logs/pipeline/one.log"
    assert any("[two] ran" in m for m in messages)


def test_from_to_only_through_the_cli(world):
    specs = [world["stage"](n) for n in ("one", "two", "three", "four")]
    cfg_path = world["tmp"] / "pipeline.yaml"
    cfg_path.write_text(yaml.safe_dump(world["build"](specs)), encoding="utf-8")
    base = ["--config", str(cfg_path), "--root", str(world["tmp"]), "run", "--force"]
    assert cli.main(base + ["--from", "two", "--to", "three"]) == 0
    assert order(world) == ["two", "three"]
    world["order"].unlink()
    assert cli.main(base + ["--only", "four,one"]) == 0
    assert order(world) == ["one", "four"]
    assert cli.main(base + ["--only", "nope"]) == 2


def test_the_first_failure_stops_the_run_with_a_clear_message_and_a_resume_hint(world):
    specs = [world["stage"]("one"), world["stage"]("boom", module="fake_fail", out=False), world["stage"]("three")]
    results, code, messages, cfg = run(world, specs)
    assert code == 1 and [r.name for r in results] == ["one", "boom"] and order(world) == ["one"]
    assert results[1].status == "failed" and results[1].exit_code == 3
    text = "\n".join(messages)
    assert "stage 'boom' failed" in text and "logs/pipeline/boom.log" in text and "--from boom" in text
    assert "about to fail" in (world["tmp"] / "logs" / "pipeline" / "boom.log").read_text(encoding="utf-8")
    record = json.loads(next((world["tmp"] / "logs" / "pipeline").glob("run_*.json")).read_text(encoding="utf-8"))
    assert record["exit_code"] == 1 and record["finished"] is True and record["stages"][-1]["status"] == "failed"
    assert not (world["data"] / "three.out").exists()


def test_exit_code_zero_without_the_promised_output_is_a_failure(world):
    spec = world["stage"]("quiet", module="fake_noop")
    spec["marker"] = ["{data}/quiet.out"]
    results, code, messages, _ = run(world, [spec])
    assert code == 1 and results[0].status == "failed" and "without producing quiet.out" in results[0].detail


def test_marker_outputs_are_reused_unless_forced(world):
    specs = [world["stage"]("one"), world["stage"]("two")]
    run(world, specs)
    world["order"].unlink()
    results, code, _, _ = run(world, specs)
    assert [r.status for r in results] == ["reused", "reused"] and order(world) == []
    assert results[0].detail == "outputs present"
    forced, _, _, _ = run(world, specs, force=True)
    assert [r.status for r in forced] == ["ran", "ran"] and order(world) == ["one", "two"]
    (world["data"] / "two.out").unlink()
    again, _, _, _ = run(world, specs)
    assert [r.status for r in again] == ["reused", "ran"]


def frozen_stage(world, name="frozen"):
    folder = world["data"] / name
    folder.mkdir(exist_ok=True)
    payload = folder / "table.parquet"
    payload.write_bytes(b"frozen data")
    manifest = folder / "manifest.json"
    manifest.write_text(json.dumps({"files": {"table.parquet": {"sha256": hashlib.sha256(b"frozen data").hexdigest()}}}),
                        encoding="utf-8")
    spec = world["stage"](name, out=False, frozen_manifest={"path": "{data}/" + f"{name}/manifest.json", "dir": "{data}/" + name})
    return spec, payload


def test_a_verified_frozen_manifest_means_reused_and_tampering_means_rerun(world):
    spec, payload = frozen_stage(world)
    results, _, _, _ = run(world, [spec])
    assert results[0].status == "reused" and "frozen manifest ok" in results[0].detail and order(world) == []
    payload.write_bytes(b"tampered")
    results, _, _, _ = run(world, [spec])
    assert results[0].status == "ran" and order(world) == ["frozen"]


def test_a_stage_verify_cli_decides_reuse(world):
    ok = world["stage"]("ok", verify={"module": "fake_verify_ok", "args": []})
    bad = world["stage"]("bad", verify={"module": "fake_verify_bad", "args": []})
    results, _, _, _ = run(world, [ok, bad])
    assert [r.status for r in results] == ["reused", "ran"] and order(world) == ["bad"]
    assert "verify exit code 0" in results[0].detail
    assert "intact" in (world["tmp"] / "logs" / "pipeline" / "ok.log").read_text(encoding="utf-8")
    assert "damaged" in (world["tmp"] / "logs" / "pipeline" / "bad.log").read_text(encoding="utf-8")


def test_offline_skips_network_stages_unless_reusable_and_uses_offline_args(world):
    net = world["stage"]("net", network=True)
    net_reusable = world["stage"]("have", network=True)
    (world["data"] / "have.out").write_text("x")
    local = world["stage"]("local")
    with_flag = world["stage"]("flagged", network=True, offline_args=["--skip-download"])
    results, code, _, _ = run(world, [net, net_reusable, local, with_flag], offline=True)
    assert code == 0
    assert [(r.name, r.status) for r in results] == [("net", "skipped"), ("have", "reused"), ("local", "ran"), ("flagged", "ran")]
    assert "--offline" in results[0].detail and results[1].detail == "outputs present"
    assert order(world) == ["local", "flagged", "skip-download"]
    assert results[3].commands[0].endswith("--skip-download")


def test_an_optional_missing_module_is_skipped_but_a_required_one_fails(world):
    optional = world["stage"]("opt", module="no_such_module_xyz", out=False, optional=True)
    results, code, _, _ = run(world, [optional, world["stage"]("after")])
    assert code == 0 and results[0].status == "skipped" and "module not found" in results[0].detail
    assert results[1].status == "ran"
    required = world["stage"]("req", module="no_such_module_xyz", out=False)
    results, code, _, _ = run(world, [required])
    assert code == 1 and results[0].status == "failed"
    assert "No module named" in (world["tmp"] / "logs" / "pipeline" / "req.log").read_text(encoding="utf-8")


def test_dry_run_executes_nothing_and_writes_no_logs(world):
    spec, _ = frozen_stage(world)
    optional = world["stage"]("opt", module="no_such_module_xyz", out=False, optional=True)
    results, code, messages, _ = run(world, [world["stage"]("new"), spec, optional], dry_run=True)
    assert code == 0 and order(world) == [] and not (world["tmp"] / "logs").exists()
    assert [(r.name, r.status) for r in results] == [("new", "would-run"), ("frozen", "would-reuse"), ("opt", "would-skip")]
    assert any("fake_ok" in m and "--name new" in m for m in messages)
    assert not any(str(world["tmp"]) in m.split("--")[0] for m in messages)         # the interpreter is not shown absolute


def test_default_false_stage_runs_only_when_included(world):
    specs = [world["stage"]("audit", default=False), world["stage"]("one")]
    results, _, _, _ = run(world, specs)
    assert [r.name for r in results] == ["one"]
    results, _, _, _ = run(world, specs, include=["audit"], force=True)
    assert [r.name for r in results] == ["audit", "one"]


# -------------------------------------------------------------------------------------------------- status

def test_status_reports_outputs_manifest_verification_and_the_last_run(world):
    spec, payload = frozen_stage(world)
    specs = [world["stage"]("one"), spec, world["stage"]("opt", module="no_such_module_xyz", out=False, optional=True,
                                                         default=False, network=True)]
    cfg = world["build"](specs)
    parsed = stages.parse_stages(cfg)
    rows = {r.name: r for r in runner.stage_statuses(cfg, parsed, world["paths"])}
    assert rows["one"].outputs_present == 0 and rows["one"].last_run is None and rows["one"].manifest == "n/a"
    assert rows["frozen"].manifest == "OK" and not rows["opt"].module_found
    assert "skipped by default" in rows["opt"].notes and "network" in rows["opt"].notes
    runner.run_pipeline(cfg, parsed[:2], world["paths"], out=lambda m: None)
    payload.write_bytes(b"damaged")
    rows = {r.name: r for r in runner.stage_statuses(cfg, parsed, world["paths"])}
    assert rows["one"].outputs_present == 1 and rows["one"].last_state == "ran" and rows["one"].last_run
    assert rows["frozen"].manifest.startswith("FAIL") and rows["frozen"].last_state == "reused"
    text = runner.format_status(list(rows.values()))
    assert "one" in text and "FAIL (1 problems)" in text and "never" in text and "module not found" in text


def test_status_through_the_cli_prints_every_real_stage(capsys):
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    for name in ("labels", "splits", "features", "integrity_engine", "corrector", "final_report"):
        assert name in out
    assert "C:\\" not in out and "/Users/" not in out


def test_manifest_verification_states(tmp_path):
    assert stages.verify_manifest(tmp_path / "nope.json", tmp_path)["state"] == "missing"
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    assert stages.verify_manifest(tmp_path / "bad.json", tmp_path)["state"] == "fail"
    (tmp_path / "m.json").write_text(json.dumps({"files": {"a.txt": {"sha256": "0" * 64}, "b.txt": {}}}), encoding="utf-8")
    (tmp_path / "a.txt").write_text("a")
    result = stages.verify_manifest(tmp_path / "m.json", tmp_path)
    assert result["state"] == "fail" and result["checked"] == 2
    assert result["problems"] == ["checksum mismatch: a.txt", "missing: b.txt"]
