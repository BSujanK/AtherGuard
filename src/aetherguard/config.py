"""Project paths and YAML config loading."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def data_root() -> Path:
    """Root of the git-ignored data tree; override with AETHERGUARD_DATA_DIR (used by tests)."""
    override = os.environ.get("AETHERGUARD_DATA_DIR")
    return Path(override) if override else PROJECT_ROOT / "data"


def data_dir(*parts: str) -> Path:
    path = data_root().joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_config_file(path: Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_config(name: str) -> dict:
    return load_config_file(PROJECT_ROOT / "configs" / f"{name}.yaml")
