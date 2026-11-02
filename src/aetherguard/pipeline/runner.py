"""Run the pipeline stages as subprocesses, log them, reuse verified frozen outputs and report the outcome."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .stages import Paths, Stage, StageStatus, Step, cheap_reusable, manifest_state, module_exists


@dataclass
class StageResult:
    name: str
    status: str                  # ran | reused | skipped | failed | would-run | would-reuse | would-skip
    detail: str = ""
    commands: list[str] | None = None
    started: str | None = None
    ended: str | None = None
    duration_s: float | None = None
    exit_code: int | None = None
    log: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def python_executable(cfg: dict, root: Path) -> str:
    configured = cfg.get("python")
    if configured:
        path = Path(configured)
        path = path if path.is_absolute() else root / path
        if path.is_file():
            return str(path)
    return sys.executable


def extra_paths(cfg: dict, root: Path) -> list[Path]:
    return [p if p.is_absolute() else root / p for p in map(Path, cfg.get("pythonpath") or [])]


def command_for(python: str, step: Step, extra_args: tuple[str, ...] = ()) -> list[str]:
    return [python, "-m", step.module, *step.args, *extra_args]


def display_command(command: list[str], root: Path) -> str:
    """The command with the interpreter shown relative to the project root when it lives there (no absolute paths in logs)."""
    first = Path(command[0])
    try:
        shown = first.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        shown = first.name
    return " ".join([shown, *command[1:]])


def _environment(cfg: dict, root: Path) -> dict:
    env = dict(os.environ)
    paths = [str(p) for p in extra_paths(cfg, root)]
    if paths:
        env["PYTHONPATH"] = os.pathsep.join([*paths, env["PYTHONPATH"]] if env.get("PYTHONPATH") else paths)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _run(command: list[str], log, cfg: dict, root: Path) -> int:
    log.write(f"$ {display_command(command, root)}\n")
    log.flush()
    completed = subprocess.run(command, cwd=root, env=_environment(cfg, root), stdout=log, stderr=subprocess.STDOUT)
    log.write(f"\n[exit code {completed.returncode}]\n")
    log.flush()
    return completed.returncode


def _reuse_decision(stage: Stage, paths: Paths, cfg: dict, python: str, log, dry_run: bool) -> tuple[bool, str]:
    """(reusable, why). A stage's own verify CLI decides when it has one (it is never executed in a dry run)."""
    if stage.verify is not None and not dry_run:
        code = _run(command_for(python, stage.verify), log, cfg, paths.root)
        return code == 0, f"verify exit code {code}"
    reusable, why = cheap_reusable(stage, paths)
    if stage.verify is not None and stage.frozen_manifest is None:
        why = "verify CLI not executed in a dry run"
    return reusable, why


def run_pipeline(cfg: dict, stages: list[Stage], paths: Paths, *, dry_run: bool = False, offline: bool = False,
                 force: bool = False, out=print) -> tuple[list[StageResult], int]:
    """Run `stages` in order; stop at the first failure. Returns (results, exit code 0 / 1).

    Per stage (in this order): offline + network stage -> reused when reusable, else skipped; optional stage whose module
    does not exist -> skipped; reusable (verify CLI, frozen manifest or marker outputs) and not `force` -> reused;
    otherwise the steps run. Logs go to <log_dir>/<stage>.log, the run record to <log_dir>/run_<timestamp>.json."""
    python = python_executable(cfg, paths.root)
    log_dir = paths.root / cfg.get("log_dir", "logs/pipeline")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    record_path = log_dir / f"run_{stamp}.json"
    results: list[StageResult] = []
    paths_extra = extra_paths(cfg, paths.root)
    if not dry_run:
        log_dir.mkdir(parents=True, exist_ok=True)

    def save(exit_code=None, finished=False):
        if dry_run:
            return
        record_path.write_text(json.dumps({"started": results[0].started if results else _now(), "finished": finished,
                                           "exit_code": exit_code, "offline": offline, "force": force,
                                           "python": python, "stages": [asdict(r) for r in results]}, indent=2) + "\n",
                               encoding="utf-8")

    for stage in stages:
        extra = stage.offline_args if offline else ()
        commands = [display_command(command_for(python, s, extra if i == 0 else ()), paths.root)
                    for i, s in enumerate(stage.steps)]
        result = StageResult(stage.name, "ran", commands=commands)
        log_path = log_dir / f"{stage.name}.log"
        if dry_run:
            reusable, why = (False, "forced") if force else _reuse_decision(stage, paths, cfg, python, None, True)
            if stage.optional and not module_exists(stage.module, paths_extra):
                result.status, result.detail = "would-skip", f"module not found: {stage.module}"
            elif offline and stage.network and not stage.offline_args and not cheap_reusable(stage, paths)[0]:
                result.status, result.detail = "would-skip", "network stage, --offline"
            elif reusable or (offline and stage.network and cheap_reusable(stage, paths)[0]):
                result.status, result.detail = "would-reuse", why
            else:
                result.status, result.detail = "would-run", " && ".join(commands)
            results.append(result)
            out(f"[{stage.name}] {result.status}: {result.detail}")
            continue
        result.started = _now()
        started = time.monotonic()
        with log_path.open("w", encoding="utf-8") as log:
            result.log = log_path.relative_to(paths.root).as_posix()
            if stage.optional and not module_exists(stage.module, paths_extra):
                result.status, result.detail = "skipped", f"module not found: {stage.module}"
            elif offline and stage.network and not stage.offline_args and not cheap_reusable(stage, paths)[0]:
                result.status, result.detail = "skipped", "needs the network (--offline) and nothing to reuse"
            else:
                reusable, why = (False, "forced rerun") if force else _reuse_decision(stage, paths, cfg, python, log, False)
                if not reusable and offline and stage.network and cheap_reusable(stage, paths)[0] and not force:
                    reusable, why = True, "offline: outputs present"
                if reusable:
                    result.status, result.detail = "reused", why
                else:
                    for i, step in enumerate(stage.steps):
                        code = _run(command_for(python, step, extra if i == 0 else ()), log, cfg, paths.root)
                        result.exit_code = code
                        if code != 0:
                            result.status, result.detail = "failed", f"{step.module} exited with code {code}"
                            break
                    else:
                        missing = [m for m in stage.marker if not paths.resolve(m).exists()]
                        if missing:  # exit code 0 but the stage did not produce what it promises (e.g. a module without a CLI)
                            result.status, result.detail = "failed", f"finished without producing {Path(missing[0]).name}"
                            result.exit_code = result.exit_code if result.exit_code is not None else 0
        result.ended = _now()
        result.duration_s = round(time.monotonic() - started, 2)
        results.append(result)
        save()
        out(f"[{stage.name}] {result.status}" + (f": {result.detail}" if result.detail else "")
            + (f" ({result.duration_s}s)" if result.status in ("ran", "failed") else ""))
        if result.status == "failed":
            out(f"error: stage {stage.name!r} failed ({result.detail}); see {result.log}; "
                f"fix it and resume with: python -m aetherguard.pipeline run --from {stage.name}")
            save(exit_code=1, finished=True)
            return results, 1
    save(exit_code=0, finished=True)
    return results, 0


def last_runs(log_dir: Path) -> dict[str, tuple[str, str]]:
    """{stage: (time, status)} of the most recent run record in which the stage ran, was reused or failed."""
    latest: dict[str, tuple[str, str]] = {}
    for path in sorted(log_dir.glob("run_*.json")) if log_dir.is_dir() else []:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for stage in record.get("stages", []):
            if stage.get("status") in ("ran", "reused", "failed"):
                latest[stage["name"]] = (stage.get("ended") or stage.get("started") or path.stem[4:], stage["status"])
    return latest


def stage_statuses(cfg: dict, stages: list[Stage], paths: Paths) -> list[StageStatus]:
    log_dir = paths.root / cfg.get("log_dir", "logs/pipeline")
    runs = last_runs(log_dir)
    extras = extra_paths(cfg, paths.root)
    out = []
    for stage in stages:
        present = sum(paths.resolve(o).exists() for o in stage.outputs)
        state = manifest_state(stage, paths)
        if state is None:
            manifest = "n/a"
        elif state["state"] == "ok":
            manifest = "OK"
        elif state["state"] == "missing":
            manifest = "no manifest"
        else:
            manifest = f"FAIL ({len(state['problems'])} problems)"
        when, last = runs.get(stage.name, (None, None))
        notes = []
        found = module_exists(stage.module, extras)
        if not found:
            notes.append(f"module not found: {stage.module}")
        if not stage.default:
            notes.append("skipped by default")
        if stage.network:
            notes.append("network")
        out.append(StageStatus(stage.name, present, len(stage.outputs), manifest, when, last, found, notes))
    return out


def format_status(rows: list[StageStatus]) -> str:
    header = f"{'stage':<18} {'outputs':<9} {'manifest':<18} {'last run':<22} notes"
    lines = [header, "-" * len(header)]
    for r in rows:
        last = f"{r.last_run} ({r.last_state})" if r.last_run else "never"
        lines.append(f"{r.name:<18} {r.outputs_present}/{r.outputs_total:<7} {r.manifest:<18} {last:<22} {'; '.join(r.notes)}")
    return "\n".join(lines)
