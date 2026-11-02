"""Real label store -> frozen splits (run with -m realdata); always builds into a temporary directory."""
import pandas as pd
import pytest

from aetherguard.config import PROJECT_ROOT
from aetherguard.splits.freeze import CELL_DAYS_NAME, WINDOWS_NAME, build_splits, verify_splits

EVENTS = PROJECT_ROOT / "data" / "processed" / "labels" / "events.parquet"


@pytest.mark.realdata
def test_real_label_store_builds_verifies_and_keeps_every_cell_day_in_one_split(splits_out_dir):
    if not EVENTS.is_file():
        pytest.skip("real label store not built (python -m aetherguard.events.build)")
    manifest = build_splits(EVENTS, splits_out_dir)
    assert manifest["totals"]["day_exact_events"] == 956
    assert manifest["totals"]["day_exact_cell_days"] == 919
    cell_days = pd.read_parquet(splits_out_dir / CELL_DAYS_NAME)
    windows = pd.read_parquet(splits_out_dir / WINDOWS_NAME)
    assert not cell_days.duplicated(["cell_id", "event_date"]).any()
    assert cell_days.groupby(["cell_id", "event_date"])["split"].nunique().max() == 1
    assert manifest["case_studies"]["wayanad_2024"]["cell_days"] == 0
    assert manifest["case_studies"]["wayanad_2024"]["events"] == 0
    assert manifest["window_test"]["events"] == 176
    assert set(windows["window_start"]) == {pd.Timestamp("2023-06-16")}
    assert set(windows["window_end"]) == {pd.Timestamp("2023-07-31")}
    assert windows["n_events"].sum() == 176
    assert verify_splits(splits_out_dir, EVENTS) == {"ok": True, "problems": []}
