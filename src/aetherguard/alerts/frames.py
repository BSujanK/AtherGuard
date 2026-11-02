"""Feature frames for the alert engine: a frozen feature table joined with its `integ_` (and, when the model uses
them, `corr_`) group files, which share its `cell_id`, `date` keys and row order."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..hazard import data as hd

INTEG_DIR = "integ"
CORR_DIR = "corrector"
KEYS = ["cell_id", "date"]


def group_path(name: str, directory: Path, group_dir: str, suffix: str) -> Path:
    return directory / group_dir / f"{name}_{suffix}.parquet"


def join_group(frame: pd.DataFrame, path: Path) -> pd.DataFrame:
    """`frame` plus the non-key columns of the group file `path`; the keys must match row for row."""
    if not path.is_file():
        raise FileNotFoundError(f"{path} not found; build it first (integrity.hazard_features / corrector)")
    group = pd.read_parquet(path)
    if len(group) != len(frame) or not (group[KEYS].reset_index(drop=True) == frame[KEYS].reset_index(drop=True)).all().all():
        raise ValueError(f"{path.name} does not match the keys / row order of its feature table; rebuild it")
    extra = group.drop(columns=KEYS).set_axis(frame.index)
    clash = sorted(set(extra.columns) & set(frame.columns))
    if clash:
        raise ValueError(f"{path.name} repeats feature columns {clash}")
    return pd.concat([frame, extra], axis=1)


def load_feature_frame(name: str, directory: Path | None = None, model_columns=()) -> pd.DataFrame:
    """The feature table `<name>_features.parquet` with its integ_ columns, and its corr_ columns when
    `model_columns` contains any."""
    directory = Path(directory or hd.features_dir())
    frame = hd.load_features(name, directory)
    frame = join_group(frame, group_path(name, directory, INTEG_DIR, "integ"))
    if any(str(c).startswith("corr_") for c in model_columns):
        frame = join_group(frame, group_path(name, directory, CORR_DIR, "corr"))
    return frame
