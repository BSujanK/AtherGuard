"""The live IMD sampling can read the real-time grid a number of columns east or west of the nearest point
(`imd_lon_offset_columns`, reports/live/audit/rain_registration_study.json); the frozen store lookup is unchanged."""
from datetime import date, timedelta

import numpy as np
import pytest

from aetherguard.features.sources import _imd_pixels
from aetherguard.grid import latlon_to_cell
from aetherguard.ingest import imd as imd_mod
from aetherguard.live import adapter, run as live_run

import live_run_helpers as H

DAY = date(2026, 10, 24)


def _column_grid():
    """A grid whose value is its column index (row * 1000 + column to also tell rows apart)."""
    rows, cols = np.indices((imd_mod.N_LAT, imd_mod.N_LON))
    return (rows * 1000.0 + cols).astype(np.float32)


def _cell_at(i, j):
    return int(latlon_to_cell(imd_mod.LAT_MIN + i * imd_mod.STEP, imd_mod.LON_MIN + j * imd_mod.STEP))


def test_the_default_offset_is_the_nearest_point_and_the_store_lookup_is_unchanged():
    cells = np.array([_cell_at(40, 50), _cell_at(10, 0)])
    pixels = _imd_pixels(cells)
    assert (pixels // imd_mod.N_LON).tolist() == [40, 10] and (pixels % imd_mod.N_LON).tolist() == [50, 0]
    assert (_imd_pixels(cells, lon_offset_columns=0) == pixels).all()


def test_an_offset_moves_the_sampled_column_by_exactly_that_many():
    cells = np.array([_cell_at(40, 50), _cell_at(41, 51)])
    for offset in (-2, -1, 1):
        moved = _imd_pixels(cells, lon_offset_columns=offset)
        assert (moved // imd_mod.N_LON).tolist() == [40, 41]
        assert (moved % imd_mod.N_LON).tolist() == [50 + offset, 51 + offset]


def test_the_offset_never_wraps_to_the_next_row_and_leaves_the_grid_as_minus_one():
    cells = np.array([_cell_at(40, 0), _cell_at(40, imd_mod.N_LON - 1), _cell_at(40, 1)])
    west = _imd_pixels(cells, lon_offset_columns=-1)
    assert west.tolist()[:1] == [-1] and west[1] == 40 * imd_mod.N_LON + imd_mod.N_LON - 2 and west[2] == 40 * imd_mod.N_LON
    east = _imd_pixels(cells, lon_offset_columns=1)
    assert east[1] == -1 and east[0] == 40 * imd_mod.N_LON + 1


def test_the_cell_series_reads_the_shifted_column_and_is_nan_beyond_the_edge():
    grid = _column_grid()
    cells = np.array([_cell_at(40, 50), _cell_at(40, 0)])
    plain = adapter.imd_cell_series({DAY: grid}, cells, DAY, length=2)
    shifted = adapter.imd_cell_series({DAY: grid}, cells, DAY, length=2, lon_offset_columns=-1)
    assert plain[:, 1].tolist() == [40050.0, 40000.0]
    assert shifted[0, 1] == 40049.0                       # exactly one column west of the nearest point
    assert np.isnan(shifted[1, 1])                        # column 0 minus one: no wrap to the previous row's last column
    assert np.isnan(shifted[:, 0]).all()                  # a day without a grid stays missing


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    out = {}
    for offset in (0, -1):
        root = tmp_path_factory.mktemp(f"offset{offset}")
        cfg = H.make_cfg(root, imd_lon_offset_columns=offset)
        cells = H.tiny_cells()
        i, j = imd_mod.ImdGrid.nearest_index(float(cells["lat"].iloc[0]), float(cells["lon"].iloc[0]))

        def post(day, timeout, j=j):
            grid = np.zeros((imd_mod.N_LAT, imd_mod.N_LON), dtype="<f4")
            grid[:, j] = 70.0              # heavy in the cell's nearest column only
            return grid.tobytes()
        sources = {**H.healthy_sources(), "imd_rt": H.imd_source(post)}
        live_run.run_day(H.DAY, cfg, deps=H.make_deps(sources))
        out[offset] = (live_run.live_root(cfg) / H.DAY.isoformat(), int(cells["cell_id"].iloc[0]))
    return out


def test_a_live_run_samples_the_configured_column(runs):
    import pandas as pd
    plain = pd.read_parquet(runs[0][0] / "features_D0.parquet").set_index("cell_id")
    shifted = pd.read_parquet(runs[-1][0] / "features_D0.parquet").set_index("cell_id")
    cell = runs[0][1]
    assert plain.loc[cell, "src_imd_acc_1"] == pytest.approx(70.0)
    assert shifted.loc[cell, "src_imd_acc_1"] == pytest.approx(0.0)       # one column west holds no rain in this grid
    assert (plain["irain_acc_1"] == shifted["irain_acc_1"]).all()         # the model's rain is not touched
