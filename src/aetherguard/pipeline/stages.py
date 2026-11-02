"""Stage definitions of the pipeline (parsed from configs/pipeline.yaml), selection and the reuse / status checks."""
from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..config import PROJECT_ROOT, data_root
from ..manifest import sha256_file

CONFIG_PATH = PROJECT_ROOT / "configs" / "pipeline.yaml"
_STAGE_KEYS = {"name", "module", "args", "steps", "verify", "frozen_manifest", "marker", "outputs", "network",
               "offline_args", "default", "optional"}


class PipelineConfigError(ValueError):
    """The pipeline configuration is malformed (names the offending stage)."""


@dataclass(frozen=True)
class Step:
    module: str
    args: tuple[str, ...] = ()


@dataclass(frozen=True)
class Stage:
    name: str
    steps: tuple[Step, ...]
    verify: Step | None = None
    frozen_manifest: dict | None = None
    marker: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    network: bool = False
    offline_args: tuple[str, ...] = ()
    default: bool = True
    optional: bool = False

    @property
    def module(self) -> str:
        return self.steps[0].module


def load_config(path=None) -> dict:
    with Path(path or CONFIG_PATH).open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _step(spec, where: str) -> Step:
    if not isinstance(spec, dict) or not isinstance(spec.get("module"), str):
        raise PipelineConfigError(f"{where}: a step needs a `module` string")
    args = spec.get("args") or []
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise PipelineConfigError(f"{where}: `args` must be a list of strings")
    return Step(spec["module"], tuple(args))


def parse_stages(cfg: dict) -> list[Stage]:
    raw = cfg.get("stages")
    if not isinstance(raw, list) or not raw:
        raise PipelineConfigError("the configuration has no `stages` list")
    stages, seen = [], set()
    for spec in raw:
        name = spec.get("name") if isinstance(spec, dict) else None
        if not isinstance(name, str) or not name:
            raise PipelineConfigError(f"every stage needs a `name`: {spec!r}")
        if name in seen:
            raise PipelineConfigError(f"duplicate stage name {name!r}")
        seen.add(name)
        unknown = set(spec) - _STAGE_KEYS
        if unknown:
            raise PipelineConfigError(f"stage {name}: unknown keys {sorted(unknown)}")
        if "steps" in spec:
            steps = tuple(_step(s, f"stage {name}") for s in spec["steps"])
        elif "module" in spec:
            steps = (_step(spec, f"stage {name}"),)
        else:
            steps = ()
        if not steps:
            raise PipelineConfigError(f"stage {name}: needs `module` (and `args`) or a non-empty `steps` list")
        manifest = spec.get("frozen_manifest")
        if manifest is not None and not (isinstance(manifest, dict) and {"path", "dir"} <= set(manifest)):
            raise PipelineConfigError(f"stage {name}: `frozen_manifest` needs `path` and `dir`")
        stages.append(Stage(name=name, steps=steps, verify=_step(spec["verify"], f"stage {name} verify") if spec.get("verify") else None,
                            frozen_manifest=manifest, marker=tuple(spec.get("marker") or ()),
                            outputs=tuple(spec.get("outputs") or ()), network=bool(spec.get("network", False)),
                            offline_args=tuple(spec.get("offline_args") or ()), default=bool(spec.get("default", True)),
                            optional=bool(spec.get("optional", False))))
    return stages


def resolve_path(template: str, data: Path, reports: Path, root: Path) -> Path:
    path = Path(template.replace("{data}", str(data)).replace("{reports}", str(reports)))
    return path if path.is_absolute() else root / path


def select_stages(stages: list[Stage], start: str | None = None, end: str | None = None,
                  only: list[str] | None = None, include: list[str] | None = None) -> list[Stage]:
    """Stages to consider, in configured order. `only` wins over `start`/`end`; stages with default: false run only when
    named in `only` or `include`."""
    names = [s.name for s in stages]
    for label, given in (("--from", [start] if start else []), ("--to", [end] if end else []),
                         ("--only", only or []), ("--include", include or [])):
        unknown = [g for g in given if g not in names]
        if unknown:
            raise PipelineConfigError(f"{label}: unknown stage {unknown[0]!r} (stages: {', '.join(names)})")
    if only:
        return [s for s in stages if s.name in only]
    first = names.index(start) if start else 0
    last = names.index(end) if end else len(stages) - 1
    if first > last:
        raise PipelineConfigError(f"--from {start} comes after --to {end}")
    chosen = set(include or [])
    return [s for s in stages[first:last + 1] if s.default or s.name in chosen]


def module_exists(module: str, extra_paths: list[Path] | None = None) -> bool:
    """True when `python -m module` can find its code: importable, or present under one of `extra_paths`."""
    try:
        if importlib.util.find_spec(module) is not None:
            return True
    except (ImportError, ValueError):
        pass
    relative = Path(*module.split("."))
    for base in [*(extra_paths or []), *map(Path, sys.path)]:
        if (base / relative).with_suffix(".py").is_file() or (base / relative / "__init__.py").is_file():
            return True
    return False


def verify_manifest(manifest_path: Path, directory: Path) -> dict:
    """Checksum check of a frozen manifest ({files: {name: {sha256}}}) against the files in `directory`.

    Returns {"state": "ok" | "fail" | "missing", "problems": [...], "checked": n}."""
    if not manifest_path.is_file():
        return {"state": "missing", "problems": [f"{manifest_path.name} not found"], "checked": 0}
    try:
        files = json.loads(manifest_path.read_text(encoding="utf-8"))["files"]
    except (ValueError, KeyError, TypeError) as exc:
        return {"state": "fail", "problems": [f"manifest unreadable: {exc}"], "checked": 0}
    problems = []
    for name, entry in files.items():
        path = directory / name
        if not path.is_file():
            problems.append(f"missing: {name}")
        elif "sha256" in entry and sha256_file(path) != entry["sha256"]:
            problems.append(f"checksum mismatch: {name}")
    return {"state": "fail" if problems else "ok", "problems": problems, "checked": len(files)}


@dataclass
class Paths:
    root: Path
    data: Path
    reports: Path

    @classmethod
    def default(cls) -> "Paths":
        return cls(PROJECT_ROOT, data_root(), PROJECT_ROOT / "reports")

    def resolve(self, template: str) -> Path:
        return resolve_path(template, self.data, self.reports, self.root)


def manifest_state(stage: Stage, paths: Paths) -> dict | None:
    if stage.frozen_manifest is None:
        return None
    return verify_manifest(paths.resolve(stage.frozen_manifest["path"]), paths.resolve(stage.frozen_manifest["dir"]))


def cheap_reusable(stage: Stage, paths: Paths) -> tuple[bool, str]:
    """Reuse test that needs no subprocess: a verified frozen manifest, or all marker outputs present."""
    state = manifest_state(stage, paths)
    if state is not None:
        return state["state"] == "ok", f"frozen manifest {state['state']}"
    if stage.marker:
        missing = [m for m in stage.marker if not paths.resolve(m).exists()]
        return (not missing), ("outputs present" if not missing else f"missing {Path(missing[0]).name}")
    return False, "no reuse test"


@dataclass
class StageStatus:
    name: str
    outputs_present: int
    outputs_total: int
    manifest: str            # "ok" | "FAIL (n problems)" | "no manifest" | "n/a"
    last_run: str | None
    last_state: str | None
    module_found: bool
    notes: list[str] = field(default_factory=list)
