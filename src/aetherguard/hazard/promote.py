"""Promote a challenger that its own held-out look adopted into a frozen live model directory.

    python -m aetherguard.hazard.promote --study configs/hazard_v4_int.yaml --name model_v4_int_live

Copies the challenger's model files from `data/processed/hazard/<study output_dir>/models/<challenger>/` to
`data/processed/hazard/<name>/` (never over an existing directory), writes its development record as `cv_results.json`,
writes `configs/hazard_<name>.yaml` (the model directory and the study's committed report, the two files the freeze
covers besides the model) and freezes the directory with `hazard.freeze`. The live run then scores lead 0 with it when
`configs/live_run.yaml` names that file as `lead0_model_config`. Refuses unless the study's `heldout.json` adopted it.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from ..config import PROJECT_ROOT, data_root
from . import model as hm
from . import v4_int as study_runner
from .freeze import default_external_files, write_freeze
from .jsonio import dump_json

COPIED = (hm.MODEL_FILE, hm.CALIBRATOR_FILE, hm.REGION_CALIBRATOR_FILE, hm.CARD_FILE)


class NotAdoptedError(RuntimeError):
    """The study's own held-out look did not adopt the challenger (or was not taken)."""


def promote(study: dict, name: str, configs_dir: Path | None = None) -> Path:
    """The frozen live directory of the study's adopted challenger; see the module doc."""
    if Path(name).name != name or not name.startswith("model_"):
        raise ValueError(f"name must be a plain directory name starting with model_, got {name!r}")
    out = study_runner.output_dir(study)
    heldout = out / study_runner.HELDOUT
    if not heldout.is_file() or json.loads(heldout.read_text(encoding="utf-8"))["decision"]["adopt"] is not True:
        raise NotAdoptedError(f"{hm.display_path(heldout)} does not adopt {study['challenger']}: nothing is promoted")
    source = out / study_runner.MODEL_SUBDIR / study["challenger"]
    target = data_root() / "processed" / "hazard" / name
    if target.exists():
        raise FileExistsError(f"{target} exists; a live model directory is never overwritten")
    report = PROJECT_ROOT / "reports" / f"{study['report_stem']}.json"
    if not report.is_file():
        raise FileNotFoundError(f"{report} not found: write and commit the study's report first")
    config = Path(configs_dir or PROJECT_ROOT / "configs") / f"hazard_{name}.yaml"
    if config.exists():
        raise FileExistsError(f"{config} exists")
    target.mkdir(parents=True)
    for file in COPIED:
        if (source / file).is_file():
            shutil.copy2(source / file, target / file)
    shutil.copytree(source / hm.ENSEMBLE_DIR, target / hm.ENSEMBLE_DIR)
    dev = study_runner.load_dev_results(study)
    dump_json(target / "cv_results.json", {"promoted_from": hm.display_path(source), "heldout": hm.display_path(heldout),
                                           **dev, "selected": {"name": study["challenger"],
                                                               **dev["candidates"][study["challenger"]]}})
    config.write_text(f"# The live copy of {study['challenger']}, adopted on its held-out look ({report.name}); written by\n"
                      f"# python -m aetherguard.hazard.promote. The live run reads only model_dir; the freeze also covers\n"
                      f"# this file and the report named by cv_report_stem.\n"
                      f"model_dir: {name}\ncv_report_stem: {study['report_stem']}\n", encoding="utf-8")
    write_freeze(target, default_external_files(config))
    return target


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--study", type=Path, required=True, help="the study configuration (e.g. configs/hazard_v4_int.yaml)")
    parser.add_argument("--name", required=True, help="the live directory under data/processed/hazard, e.g. model_v4_int_live")
    args = parser.parse_args(argv)
    target = promote(study_runner.load_study(args.study), args.name)
    print(f"promoted and frozen: {hm.display_path(target)}; configuration configs/hazard_{args.name}.yaml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
