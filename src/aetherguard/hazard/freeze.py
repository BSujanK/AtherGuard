"""Freeze record of the trained hazard model (protocol v2).

    python -m aetherguard.hazard.freeze [--config configs/hazard.yaml] [--model data/processed/hazard/model]

`FROZEN.json` stores the SHA-256 of every model file (model.txt, ensemble members, calibrator, the per-region
calibrator when the model has one, card, cv_results), the configuration file and the stage-1 CV report, with a
timestamp. `--config` freezes a model trained from another configuration (v3); its model directory and CV report
stem come from that configuration unless `--model` is given. `verify_freeze` recomputes them and raises
`FrozenMismatchError` on any difference, so the single test evaluation can only run against the exact frozen model.

A freeze is never rewritten silently: an existing `FROZEN.json` is refused unless `--force` is given, and `--force` is
refused once a test evaluation is recorded for the model (the frozen state is then what the test result is about). A
forced re-freeze keeps the record it replaces under `superseded`.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from ..config import PROJECT_ROOT
from ..manifest import sha256_file
from . import model as hm
from .jsonio import dump_json

FROZEN_NAME = "FROZEN.json"
EVALUATION_RECORD = "TEST_EVALUATION.json"
MODEL_FILES = (hm.MODEL_FILE, hm.CALIBRATOR_FILE, hm.CARD_FILE, "cv_results.json")


class FrozenMismatchError(RuntimeError):
    """The model directory does not match its freeze record (or has none)."""


def default_external_files(config_path: Path | None = None) -> dict[str, Path]:
    """Files outside the model directory that are part of the frozen state, keyed by a stable label: the
    configuration (default configs/hazard.yaml) and the stage-1 CV report it names."""
    config_path = Path(config_path) if config_path else PROJECT_ROOT / "configs" / "hazard.yaml"
    stem = hm.cv_report_stem(hm.hazard_config(config_path))
    return {f"config/{config_path.name}": config_path,
            f"report/{stem}.json": PROJECT_ROOT / "reports" / f"{stem}.json"}


def _model_paths(model_dir: Path) -> dict[str, Path]:
    paths = {name: model_dir / name for name in MODEL_FILES}
    if (model_dir / hm.REGION_CALIBRATOR_FILE).is_file():
        paths[hm.REGION_CALIBRATOR_FILE] = model_dir / hm.REGION_CALIBRATOR_FILE
    for member in sorted((model_dir / hm.ENSEMBLE_DIR).glob("member_*.txt")):
        paths[f"{hm.ENSEMBLE_DIR}/{member.name}"] = member
    return paths


def _digests(model_dir: Path, external: dict[str, Path]) -> dict[str, str]:
    paths = {**_model_paths(model_dir), **external}
    missing = sorted(label for label, path in paths.items() if not Path(path).is_file())
    if missing:
        raise FrozenMismatchError(f"frozen files missing: {missing}")
    return {label: sha256_file(path) for label, path in paths.items()}


def write_freeze(model_dir: Path | None = None, external: dict[str, Path] | None = None, force: bool = False) -> Path:
    directory = Path(model_dir or hm.default_model_dir())
    record_path = directory / FROZEN_NAME
    superseded = None
    if record_path.exists():
        if not force:
            raise FrozenMismatchError(f"{record_path} already exists; a freeze is never rewritten (--force replaces it "
                                      "and keeps the old record)")
        if (directory / EVALUATION_RECORD).exists():
            raise FrozenMismatchError(f"{directory / EVALUATION_RECORD} exists: the test evaluation belongs to the "
                                      "current freeze, which therefore cannot be replaced")
        old = json.loads(record_path.read_text(encoding="utf-8"))
        superseded = [*old.get("superseded", []), {"created_utc": old["created_utc"], "sha256": old["sha256"]}]
    external = default_external_files() if external is None else external
    record = {"created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "note": "model, ensemble, calibrator, card, thresholds and configuration frozen before any test_2018, "
                      "window or case scoring (protocol v2)",
              "external_files": sorted(external), "sha256": _digests(directory, external)}
    if superseded:
        record["superseded"] = superseded
    dump_json(record_path, record)
    return record_path


def verify_freeze(model_dir: Path | None = None, external: dict[str, Path] | None = None) -> dict:
    """Raise FrozenMismatchError unless every frozen file still has its recorded checksum; returns the record."""
    directory = Path(model_dir or hm.default_model_dir())
    record_path = directory / FROZEN_NAME
    if not record_path.is_file():
        raise FrozenMismatchError(f"{record_path} not found: the model has not been frozen")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    external = default_external_files() if external is None else external
    expected = record["sha256"]
    if sorted(external) != sorted(record["external_files"]):
        raise FrozenMismatchError(f"external files {sorted(external)} differ from the frozen set "
                                  f"{sorted(record['external_files'])}")
    actual = _digests(directory, external)
    extra = sorted(set(actual) - set(expected))
    changed = sorted(label for label in expected if actual.get(label) != expected[label])
    if extra or changed:
        raise FrozenMismatchError(f"model differs from its freeze record: changed or missing {changed}, new {extra}")
    return record


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=None, help="hazard configuration (default configs/hazard.yaml)")
    parser.add_argument("--model", type=Path, default=None,
                        help="model directory (default: the configuration's model_dir, else the v2 model)")
    parser.add_argument("--force", action="store_true",
                        help="replace an existing freeze record (refused once a test evaluation is recorded)")
    args = parser.parse_args(argv)
    model_dir = args.model or hm.configured_model_dir(hm.hazard_config(args.config))
    try:
        path = write_freeze(model_dir, default_external_files(args.config), force=args.force)
    except FrozenMismatchError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"froze {len(json.loads(path.read_text())['sha256'])} files: {hm.display_path(path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
