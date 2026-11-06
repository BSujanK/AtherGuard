"""`iint`: rain-intensity features per 0.05-degree cell from the half-hourly-derived daily fields (W3).

Everything is synthetic: day files in the layout of `ingest.imerg_hh` (`<root>/<run>/<yyyy>/<yyyymmdd>.npz`), with the planted
values at known pixels. Covers the six features, the strict NaN rule, the truncated (live) variant through the same code path,
the frozen feature tables (development samples and held-out season panels) and the 2024 train-serve gap with its 20% rule.
"""
import json
import stat
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from aetherguard.config import PROJECT_ROOT
from aetherguard.features import imerg_build as B
from aetherguard.features import imerg_features as F
from aetherguard.features import imerg_intensity as I
from aetherguard.grid import latlon_to_cell
from aetherguard.hazard import data as hd
from aetherguard.hazard import model as hm
from aetherguard.ingest import imerg, imerg_hh
from aetherguard.ingest.imerg import imerg_pixel

from test_features_imerg import real_cells, tiny_store  # noqa: F401  (fixture: development store, index and fake store)

ROWS, COLS = imerg.ROWS, imerg.COLS
WAYANAD = latlon_to_cell(11.47, 76.13)
KATHMANDU = latlon_to_cell(27.70, 85.32)
OUTSIDE = latlon_to_cell(60.0, 10.0)
D = date(2024, 8, 10)
NAMES = ["iint_max1h_1", "iint_max3h_1", "iint_max6h_1", "iint_max3h_max3d", "iint_max6h_max3d", "iint_wet_hours_1"]
EXTRAS = hm.hazard_config(PROJECT_ROOT / "configs" / "hazard_v3.yaml")["extra_groups"]


def fields(**planted):
    """Day maps (all zero) with `{name: {(row, col): value}}` planted."""
    maps = {name: np.zeros((ROWS, COLS), dtype=np.float32) for name in ("max1h", "max3h", "max6h", "wet_hours", "n_halfhours")}
    maps["n_halfhours"][:] = 48
    for name, cells in planted.items():
        for (row, col), value in cells.items():
            maps[name][row, col] = value
    maps["versions"] = np.array(["V07B"])
    return maps


def write_day(root, run, day, maps=None, **planted):
    maps = fields(**planted) if maps is None else maps
    path = root / run / f"{day.year}" / f"{day:%Y%m%d}.npz"
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **maps)
    return path


def write_window(root, run, day, per_day):
    """Write D-2, D-1 and D with the planted values of `per_day` (oldest first)."""
    for k, planted in zip((2, 1, 0), per_day):
        write_day(root, run, day - timedelta(days=k), **planted)


# ----------------------------------------------------------------------------------------------- the six features

def test_feature_names_are_the_six_declared_columns():
    assert I.feature_names() == NAMES


def test_hand_values_from_three_days(tmp_path):
    pix = imerg_pixel(WAYANAD)
    write_window(tmp_path, "late", D, [
        {"max3h": {pix: 40.0}, "max6h": {pix: 70.0}},                      # D-2
        {"max3h": {pix: 15.0}, "max6h": {pix: 90.0}},                      # D-1
        {"max1h": {pix: 12.0}, "max3h": {pix: 25.0}, "max6h": {pix: 31.0}, "wet_hours": {pix: 7.5}}])   # D
    out = I.cell_features(D, [WAYANAD], tmp_path)
    assert list(out.columns) == NAMES and len(out) == 1
    assert out.iloc[0].tolist() == pytest.approx([12.0, 25.0, 31.0, 40.0, 90.0, 7.5])
    assert (out.dtypes == np.float32).all()


def test_max_over_three_days_ignores_older_days(tmp_path):
    pix = imerg_pixel(WAYANAD)
    write_window(tmp_path, "late", D, [{}, {}, {"max3h": {pix: 5.0}}])
    write_day(tmp_path, "late", D - timedelta(days=3), max3h={pix: 500.0})
    row = I.cell_features(D, [WAYANAD], tmp_path).iloc[0]
    assert row["iint_max3h_max3d"] == 5.0 and row["iint_max3h_1"] == 5.0


def test_cells_map_to_the_pixel_that_holds_them_in_the_daily_orientation(tmp_path):
    pix_w, pix_k = imerg_pixel(WAYANAD), imerg_pixel(KATHMANDU)
    assert pix_w != pix_k and pix_w[0] < pix_k[0]                           # row 0 is the southern edge
    write_window(tmp_path, "late", D, [{}, {}, {"max1h": {pix_w: 3.0, pix_k: 8.0}}])
    out = I.cell_features(D, [KATHMANDU, WAYANAD, KATHMANDU], tmp_path)
    assert out["iint_max1h_1"].tolist() == [8.0, 3.0, 8.0]                   # input order and duplicates kept


def test_mapping_is_the_one_of_the_daily_imerg_features(tmp_path):
    cells = np.array([WAYANAD, WAYANAD + 2, WAYANAD + 20_000, KATHMANDU], dtype=np.int64)
    flat = F.cell_pixels(cells)
    assert len(set(flat.tolist())) == 4
    maps = fields()
    maps["max1h"].reshape(-1)[flat] = np.arange(1, 5, dtype=np.float32)
    write_window(tmp_path, "late", D, [{}, {}, {}])
    write_day(tmp_path, "late", D, maps)
    assert I.cell_features(D, cells, tmp_path)["iint_max1h_1"].tolist() == [1.0, 2.0, 3.0, 4.0]


def test_a_cell_outside_the_grid_is_nan_in_every_column(tmp_path):
    write_window(tmp_path, "late", D, [{}, {}, {}])
    out = I.cell_features(D, [OUTSIDE, WAYANAD], tmp_path)
    assert out.iloc[0].isna().all() and out.iloc[1].notna().all()


# ----------------------------------------------------------------------------------------------- strict NaN

def test_a_missing_day_file_is_nan_never_zero(tmp_path):
    pix = imerg_pixel(WAYANAD)
    write_window(tmp_path, "late", D, [{}, {}, {"max3h": {pix: 9.0}}])
    (tmp_path / "late" / "2024" / f"{D:%Y%m%d}.npz").unlink()
    assert I.cell_features(D, [WAYANAD], tmp_path).iloc[0].isna().all()


@pytest.mark.parametrize("missing", [1, 2])
def test_a_missing_earlier_day_makes_only_the_three_day_maxima_nan(tmp_path, missing):
    pix = imerg_pixel(WAYANAD)
    write_window(tmp_path, "late", D, [{}, {}, {"max3h": {pix: 9.0}, "max6h": {pix: 11.0}, "wet_hours": {pix: 4.0}}])
    (tmp_path / "late" / "2024" / f"{D - timedelta(days=missing):%Y%m%d}.npz").unlink()
    row = I.cell_features(D, [WAYANAD], tmp_path).iloc[0]
    assert np.isnan(row["iint_max3h_max3d"]) and np.isnan(row["iint_max6h_max3d"])
    assert row[["iint_max3h_1", "iint_max6h_1", "iint_wet_hours_1"]].tolist() == [9.0, 11.0, 4.0]


@pytest.mark.parametrize("nan_day", [0, 1, 2])
def test_a_nan_pixel_on_any_of_the_three_days_makes_the_three_day_maxima_nan(tmp_path, nan_day):
    pix, other = imerg_pixel(WAYANAD), imerg_pixel(KATHMANDU)
    per_day = [{"max3h": {pix: 50.0, other: 1.0}, "max6h": {pix: 50.0, other: 1.0}} for _ in range(3)]
    per_day[nan_day] = {"max3h": {pix: np.nan, other: 1.0}, "max6h": {pix: np.nan, other: 1.0}}
    write_window(tmp_path, "late", D, per_day)
    out = I.cell_features(D, [WAYANAD, KATHMANDU], tmp_path)
    assert np.isnan(out.loc[0, "iint_max3h_max3d"]) and np.isnan(out.loc[0, "iint_max6h_max3d"])
    assert out.loc[1, "iint_max3h_max3d"] == 1.0                              # the neighbouring pixel is unaffected
    assert np.isnan(out.loc[0, "iint_max3h_1"]) == (nan_day == 2)             # the 1-day features see only D


def test_a_corrupt_day_file_is_an_error_not_a_gap(tmp_path):
    write_window(tmp_path, "late", D, [{}, {}, {}])
    maps = fields()
    maps["max3h"] = maps["max3h"][:10]
    write_day(tmp_path, "late", D, maps)
    with pytest.raises(ValueError, match="max3h"):
        I.cell_features(D, [WAYANAD], tmp_path)


# ----------------------------------------------------------------------------------------------- live window

def synthetic_halfhours(seed=4):
    rng = np.random.default_rng(seed)
    return (rng.gamma(0.3, 3.0, size=(48, ROWS, COLS)) * (rng.random((48, ROWS, COLS)) < 0.4)).astype(np.float32)


def test_truncated_from_halfhours_is_reduce_day_of_the_prefix():
    halfhours = synthetic_halfhours()
    expected = imerg_hh.reduce_day(halfhours[:44], n_expected=44)
    for given in (halfhours, halfhours[:44]):
        maps = I.truncated_from_halfhours(given)
        assert set(maps) == set(expected)
        for name, values in expected.items():
            np.testing.assert_array_equal(maps[name], values)
    assert I.truncated_from_halfhours(halfhours, 40)["n_halfhours"].max() == 40


def test_the_truncated_day_uses_the_same_function_as_the_complete_day(tmp_path):
    """Live and training features differ only by the window end: the truncated maps go through `features_from_maps` and
    through a day file of the live build identically, and equal the complete day's wherever the tail is dry."""
    halfhours = synthetic_halfhours()
    halfhours[44:] = 0.0                                                      # the missing tail holds no rain
    cells = np.array([WAYANAD, KATHMANDU, WAYANAD + 1], dtype=np.int64)
    pixels = F.cell_pixels(cells)
    truncated = I.truncated_from_halfhours(halfhours)
    full = imerg_hh.reduce_day(halfhours)
    history = [truncated, truncated, truncated]
    live = I.features_from_maps(history, pixels)
    for run, maps in (("early_live", truncated), ("late", full)):
        for k in (2, 1, 0):
            write_day(tmp_path, run, D - timedelta(days=k), maps={**maps, "versions": np.array(["V07B"])})
    from_files = I.cell_features(D, cells, tmp_path, run="early_live")
    np.testing.assert_array_equal(from_files.to_numpy(), live)
    complete = I.cell_features(D, cells, tmp_path, run="late")
    for name in ("iint_max1h_1", "iint_max3h_1", "iint_max6h_1", "iint_max3h_max3d", "iint_max6h_max3d"):
        np.testing.assert_array_equal(from_files[name].to_numpy(), complete[name].to_numpy())


def test_the_truncated_window_never_sees_rain_after_its_end():
    halfhours = np.zeros((48, ROWS, COLS), dtype=np.float32)
    row, col = imerg_pixel(WAYANAD)
    halfhours[46, row, col] = 30.0                                            # 01:30 UTC on D: not available live
    live = I.features_from_maps([None, None, I.truncated_from_halfhours(halfhours)], F.cell_pixels([WAYANAD]))
    assert live[0, 1] == 0.0 and live[0, 5] == 0.0
    complete = I.features_from_maps([None, None, imerg_hh.reduce_day(halfhours)], F.cell_pixels([WAYANAD]))
    assert complete[0, 1] == pytest.approx(15.0)


def test_features_from_maps_needs_the_three_day_window():
    with pytest.raises(ValueError, match="three"):
        I.features_from_maps([None, None], np.array([0]))


# ----------------------------------------------------------------------------------------------- frames

def random_root(root, days, cells, seed=2, nan_rate=0.1):
    rng = np.random.default_rng(seed)
    rows, cols = imerg_pixel(np.asarray(cells))
    for day in days:
        maps = fields()
        for name in ("max1h", "max3h", "max6h", "wet_hours"):
            values = rng.gamma(0.8, 6.0, size=len(cells)).astype(np.float32)
            values[rng.random(len(cells)) < nan_rate] = np.nan
            maps[name][rows, cols] = values
        write_day(root, "late", day, maps)


def test_frame_features_equal_the_per_day_cell_features_and_keep_order_and_index(tmp_path):
    cells = real_cells()
    days = [D + timedelta(k) for k in range(-2, 5)]
    random_root(tmp_path, days[:5] + days[6:], cells)                         # D+3 has no file
    rng = np.random.default_rng(8)
    frame = pd.DataFrame({"cell_id": rng.choice(cells, 40), "date": pd.to_datetime(rng.choice(days[2:], 40))},
                         index=np.arange(100, 140))
    out = I.frame_features(frame, I.DayLoader(tmp_path))
    assert list(out.index) == list(frame.index) and (out.dtypes == np.float32).all()
    for position, (cell, stamp) in enumerate(zip(frame["cell_id"], frame["date"])):
        expected = I.cell_features(stamp.date(), [cell], tmp_path).iloc[0].to_numpy()
        np.testing.assert_array_equal(out.iloc[position].to_numpy(), expected)


def test_loader_remembers_the_missing_days_and_keeps_few_days_in_memory(tmp_path):
    random_root(tmp_path, [D - timedelta(days=1), D], real_cells())
    loader = I.DayLoader(tmp_path)
    loader.window(D)
    assert loader.missing == {D - timedelta(days=2)}
    for k in range(20):
        loader.get(D + timedelta(k))
    assert len(loader._cache) <= I.CACHE_DAYS


# ----------------------------------------------------------------------------------------------- frozen tables

def write_store_days(root, inputs):
    """Planted day files for the dates of the train sample table (and the two days before each); the first of those
    dates has no file of its own, and the other tables' dates mostly have none."""
    sample = pd.read_parquet(inputs.features_dir / "train_samples_features.parquet", columns=["date"])["date"]
    dates = sorted({stamp.date() - timedelta(days=k) for stamp in sample for k in range(3)})
    without = sorted({stamp.date() for stamp in sample})[0]
    random_root(root, [d for d in dates if d != without], real_cells()[:3], nan_rate=0.0)
    return dates


def write_panel(directory, year, cells, days):
    directory.mkdir(parents=True, exist_ok=True)
    np.savez(directory / f"season_{year}_training.npz", cell_id=np.asarray(cells, dtype=np.int64),
             days=np.array([d.isoformat() for d in days]), risk=np.zeros((len(cells), len(days))))


@pytest.fixture
def tables(tiny_store, tmp_path):
    inputs, out, _ = tiny_store
    root = tmp_path / "intensity"
    write_store_days(root, inputs)
    panels = tmp_path / "panels"
    season_days = [date(2018, 6, 1) + timedelta(k) for k in range(-3, 6)]
    random_root(root, season_days[:-2], real_cells()[:3], seed=5)
    write_panel(panels, 2018, real_cells()[:3], season_days)
    return inputs, out, root, panels


def build(tables, **kwargs):
    inputs, out, root, panels = tables
    kwargs.setdefault("allow_missing", True)
    return I.build_iint_tables(inputs, out, root, panels, years=(2018,), **kwargs)


def test_tables_have_the_keys_of_the_sample_files_and_load_through_hazard_data(tables):
    inputs, out, root, panels = tables
    manifest, reused = build(tables)
    assert not reused and manifest["group"] == "iint" and manifest["frozen"]
    for stem in ("train_samples", "validation_samples", "universe_train", "universe_validation"):
        base = pd.read_parquet(inputs.features_dir / f"{stem}_features.parquet", columns=["cell_id", "date"])
        table = pd.read_parquet(out / f"{stem}_iint.parquet")
        assert list(table.columns) == ["cell_id", "date", *NAMES]
        assert table[["cell_id", "date"]].equals(base) and (table[NAMES].dtypes == np.float32).all()
    assert json.loads((out / "iint_columns.json").read_text()) == {c: "iint" for c in NAMES}
    extras = {**EXTRAS, "iint": {"subdir": "imerg", "suffix": "iint", "columns_file": "iint_columns.json",
                                 "manifest_file": "iint_manifest.json"}}
    table = hd.load_table("train_samples", inputs.features_dir, extras, ("iint",))
    assert set(NAMES) <= set(table.columns) and table[NAMES].notna().to_numpy().any()
    assert table[NAMES].isna().to_numpy().any()                                # the day without a file


def test_sample_rows_equal_cell_features_and_missing_days_are_nan(tables):
    inputs, out, root, panels = tables
    build(tables)
    table = pd.read_parquet(out / "train_samples_iint.parquet")
    for position in range(0, len(table), 37):
        row = table.iloc[position]
        expected = I.cell_features(row["date"].date(), [int(row["cell_id"])], root).iloc[0]
        np.testing.assert_array_equal(row[NAMES].to_numpy(dtype=np.float32), expected.to_numpy())
    report = json.loads((out / "iint_report.json").read_text())
    assert report["files"]["train_samples_features.parquet"]["rows"] == len(table)
    assert set(report["files"]["train_samples_features.parquet"]["nan_share"]) == set(NAMES)
    assert report["files"]["train_samples_features.parquet"]["days_without_file"] >= 1


def test_season_table_is_cells_by_days_in_panel_order(tables):
    inputs, out, root, panels = tables
    build(tables)
    cells, days = real_cells()[:3], [date(2018, 6, 1) + timedelta(k) for k in range(-3, 6)]
    table = pd.read_parquet(out / "season_2018_iint.parquet")
    assert list(table.columns) == ["cell_id", "date", *NAMES] and len(table) == len(cells) * len(days)
    assert table["cell_id"].tolist() == np.repeat(cells, len(days)).tolist()                 # cell-major = panel[cells, days].ravel()
    assert [t.date() for t in table["date"][: len(days)]] == days
    day_index = days.index(date(2018, 6, 2))
    row = table.iloc[1 * len(days) + day_index]
    expected = I.cell_features(date(2018, 6, 2), [int(cells[1])], root).iloc[0]
    np.testing.assert_array_equal(row[NAMES].to_numpy(dtype=np.float32), expected.to_numpy())
    last = table[table["date"] == pd.Timestamp(days[-1])]
    assert last[NAMES].isna().to_numpy().all()                                               # the days without files stay NaN


def test_only_the_iint_files_are_written_and_they_are_read_only(tables):
    inputs, out, root, panels = tables
    build(tables)
    names = {p.name for p in out.iterdir()}
    assert all("iint" in n for n in names) and "iint_manifest.json" in names and "season_2018_iint.parquet" in names
    assert not (out / "iint_manifest.json").stat().st_mode & stat.S_IWRITE
    assert not (out / "train_samples_iint.parquet").stat().st_mode & stat.S_IWRITE


def test_manifest_records_inputs_checksums_and_config(tables):
    inputs, out, root, panels = tables
    manifest, _ = build(tables)
    assert manifest["config"]["features"] == NAMES and manifest["config"]["run"] == "late"
    assert manifest["inputs"]["features_manifest"]["sha256"]
    store = manifest["inputs"]["intensity_store"]
    assert store["signature"] and store["n_files"] == len(list((root / "late").rglob("*.npz")))
    assert set(manifest["inputs"]["season_panels"]) == {"2018"} and manifest["inputs"]["season_panels"]["2018"]["sha256"]
    assert manifest["files"]["season_2018_iint.parquet"]["n_rows"] == 27
    assert manifest["season_files"] == ["season_2018_iint.parquet"]
    assert all(entry["sha256"] for entry in manifest["files"].values())


def test_freeze_reuse_verify_and_force(tables):
    inputs, out, root, panels = tables
    build(tables)
    _, reused = build(tables)
    assert reused
    assert I.verify_iint_tables(out, inputs, root, panels)["ok"]
    (out / "train_samples_iint.parquet").chmod(stat.S_IWRITE)
    with (out / "train_samples_iint.parquet").open("ab") as handle:
        handle.write(b"x")
    result = I.verify_iint_tables(out, inputs, root, panels)
    assert not result["ok"] and any("checksum mismatch" in p for p in result["problems"])
    with pytest.raises(I.IintIntegrityError):
        build(tables)
    _, reused = build(tables, force=True)
    assert not reused and I.verify_iint_tables(out, inputs, root, panels)["ok"]


def test_verify_detects_a_changed_day_file_panel_or_config(tables):
    inputs, out, root, panels = tables
    build(tables)
    changed = I.build_config((2018,))
    changed["max_days"] = 5
    assert not I.verify_iint_tables(out, inputs, root, panels, changed)["ok"]
    write_day(root, "late", date(2007, 1, 1))                                                 # a new day file in the store
    result = I.verify_iint_tables(out, inputs, root, panels)
    assert not result["ok"] and any("intensity store" in p for p in result["problems"])
    (root / "late" / "2007" / "20070101.npz").unlink()
    assert I.verify_iint_tables(out, inputs, root, panels)["ok"]
    write_panel(panels, 2018, real_cells()[:2], [date(2018, 6, 1)])
    result = I.verify_iint_tables(out, inputs, root, panels)
    assert not result["ok"] and any("season_2018_training.npz" in p for p in result["problems"])


def test_a_missing_panel_or_sample_manifest_is_reported_not_guessed(tables):
    inputs, out, root, panels = tables
    with pytest.raises(FileNotFoundError, match="season_2019"):
        I.build_iint_tables(inputs, out, root, panels, years=(2019,), allow_missing=True)
    (inputs.features_dir / "features_manifest.json").unlink()
    with pytest.raises(FileNotFoundError):
        build(tables)


def test_existing_frozen_groups_are_not_touched(tables):
    inputs, out, root, panels = tables
    out.mkdir(parents=True)
    old = out / "irain_manifest.json"
    old.write_text("{}")
    build(tables)
    assert old.read_text() == "{}"
    assert not any(p.name.startswith("irain") for p in out.iterdir() if p != old)


# ----------------------------------------------------------------------------------------------- the 2024 gap

GAP_DAYS = [date(2024, 6, 1) + timedelta(k) for k in range(4)]


def gap_roots(root, full_by_day, live_by_day, cells=(WAYANAD, KATHMANDU)):
    pix = [imerg_pixel(c) for c in cells]
    for day, full, live in zip(GAP_DAYS, full_by_day, live_by_day):
        if full is not None:
            write_day(root, "late", day, max3h={p: v for p, v in zip(pix, full)})
        if live is not None:
            write_day(root, "early_live", day, max3h={p: v for p, v in zip(pix, live)})
    return np.array(cells, dtype=np.int64)


def test_gap_median_relative_error_over_wet_cell_days(tmp_path):
    cells = gap_roots(tmp_path,
                      [(10.0, 20.0), (10.0, 20.0), (10.0, 20.0), (10.0, 20.0)],
                      [(9.0, 21.0), (8.0, 25.0), (13.0, 10.0), (10.0, 20.0)])
    result = I.train_serve_gap(cells, GAP_DAYS, tmp_path)
    errors = [0.1, 0.05, 0.2, 0.25, 0.3, 0.5, 0.0, 0.0]
    assert result["cells"]["n_compared"] == 8
    assert result["cells"]["median_relative_error"] == pytest.approx(np.median(errors))
    assert result["cells"]["share_over_limit"] == pytest.approx(3 / 8)
    assert result["cells"]["by_month"]["2024-06"]["n"] == 8


def test_gap_counts_only_wet_cell_days_nan_and_missing_days(tmp_path):
    cells = gap_roots(tmp_path,
                      [(0.5, 20.0), (10.0, np.nan), (10.0, 20.0), (10.0, 20.0)],
                      [(5.0, 21.0), (np.nan, 20.0), (10.0, 20.0), None])
    result = I.train_serve_gap(cells, GAP_DAYS, tmp_path, require_complete=False)
    stats = result["cells"]
    assert stats["n_wet"] == 4                       # 0.5 mm is dry, a NaN full value is not wet, day 4 has no live file
    assert stats["n_wet_live_nan"] == 1
    assert stats["n_compared"] == 3
    assert result["days"] == {"first": "2024-06-01", "last": "2024-06-04", "requested": 4, "compared": 3,
                              "missing_full": [], "missing_live": ["2024-06-04"]}
    assert stats["median_relative_error"] == pytest.approx(np.median([0.05, 0.0, 0.0]))


@pytest.mark.parametrize("live_scale, decision, lag", [(0.85, "same_day_truncated", 0), (0.79, "previous_complete_day", 1)])
def test_the_twenty_percent_rule_picks_the_basis(tmp_path, live_scale, decision, lag):
    cells = gap_roots(tmp_path, [(10.0, 20.0)] * 4, [(10.0 * live_scale, 20.0 * live_scale)] * 4)
    result = I.train_serve_gap(cells, GAP_DAYS, tmp_path)
    assert result["limit"] == 0.20 and result["decision"] == decision and result["declared_lag_days"] == lag


def test_a_median_of_exactly_the_limit_keeps_the_same_day():
    assert I.decide(0.20) == ("same_day_truncated", 0)
    assert I.decide(0.2000001) == ("previous_complete_day", 1)
    assert I.decide(0.0) == ("same_day_truncated", 0)


def test_gap_without_a_wet_cell_day_is_an_error_not_a_pass(tmp_path):
    cells = gap_roots(tmp_path, [(0.5, 0.2)] * 4, [(0.4, 0.2)] * 4)
    with pytest.raises(ValueError, match="wet"):
        I.train_serve_gap(cells, GAP_DAYS, tmp_path)


def test_gap_domain_check_uses_every_pixel(tmp_path):
    cells = gap_roots(tmp_path, [(10.0, 20.0)] * 4, [(9.0, 18.0)] * 4)
    result = I.train_serve_gap(cells, GAP_DAYS, tmp_path)
    assert result["domain"]["n_compared"] == 8                                   # two planted pixels per day, the rest dry
    assert result["domain"]["median_relative_error"] == pytest.approx(0.1)
    assert result["decision"] == "same_day_truncated"                            # decided on the cells, not the domain


def test_gap_cli_writes_the_report_from_a_season_panel(tmp_path, capsys):
    root, panels = tmp_path / "intensity", tmp_path / "panels"
    cells = gap_roots(root, [(10.0, 20.0)] * 4, [(5.0, 10.0)] * 4)
    write_panel(panels, 2024, cells, GAP_DAYS)
    out = tmp_path / "gap.json"
    code = I.main(["gap", "--root", str(root), "--panels-dir", str(panels), "--start", "2024-06-01",
                   "--end", "2024-06-04", "--out", str(out)])
    assert code == 0
    report = json.loads(out.read_text())
    assert report["decision"] == "previous_complete_day" and report["declared_lag_days"] == 1
    assert report["cells"]["median_relative_error"] == pytest.approx(0.5)
    assert report["wet_definition"] == "full Late max3h >= 1.0 mm" and "previous_complete_day" in capsys.readouterr().out


def test_gap_cli_reports_a_missing_panel(tmp_path, capsys):
    code = I.main(["gap", "--root", str(tmp_path), "--panels-dir", str(tmp_path), "--out", str(tmp_path / "gap.json")])
    assert code == 1 and "season_2024" in capsys.readouterr().err


def test_tables_cli_builds_and_reuses(tables, monkeypatch, capsys):
    inputs, out, root, panels = tables
    monkeypatch.setattr(B, "default_inputs", lambda: inputs)
    args = ["tables", "--out-dir", str(out), "--root", str(root), "--panels-dir", str(panels), "--years", "2018",
            "--allow-missing", "--lag", "0"]
    assert I.main(args) == 0 and "built and frozen" in capsys.readouterr().out
    assert I.main(args) == 0 and "reused" in capsys.readouterr().out


# ----------------------------------------------------------------------------------------------- completeness

def test_gap_refuses_when_a_day_is_missing_in_either_store(tmp_path):
    cells = gap_roots(tmp_path, [(10.0, 20.0), None, (10.0, 20.0), (10.0, 20.0)],
                      [(9.0, 18.0), (9.0, 18.0), (9.0, 18.0), None])
    with pytest.raises(I.IncompleteGapError) as caught:
        I.train_serve_gap(cells, GAP_DAYS, tmp_path)
    message = str(caught.value)
    assert "2024-06-02" in message and "2024-06-04" in message and "Late" in message and "live-window" in message


def test_gap_cli_exits_nonzero_listing_the_missing_days_and_writes_no_report(tmp_path, capsys):
    root, panels = tmp_path / "intensity", tmp_path / "panels"
    cells = gap_roots(root, [(10.0, 20.0)] * 4, [(9.0, 18.0), (9.0, 18.0), None, (9.0, 18.0)])
    write_panel(panels, 2024, cells, GAP_DAYS)
    out = tmp_path / "gap.json"
    code = I.main(["gap", "--root", str(root), "--panels-dir", str(panels), "--start", "2024-06-01", "--end", "2024-06-04",
                   "--out", str(out)])
    assert code == 1 and not out.exists()
    assert "2024-06-03" in capsys.readouterr().err


def test_gap_output_shows_n_wet_live_nan_and_the_report_states_its_scope(tmp_path, capsys):
    root, panels = tmp_path / "intensity", tmp_path / "panels"
    cells = gap_roots(root, [(10.0, 20.0)] * 4, [(9.0, np.nan)] * 4)
    write_panel(panels, 2024, cells, GAP_DAYS)
    out = tmp_path / "gap.json"
    assert I.main(["gap", "--root", str(root), "--panels-dir", str(panels), "--start", "2024-06-01", "--end", "2024-06-04",
                   "--out", str(out)]) == 0
    assert "n_wet_live_nan: 4" in capsys.readouterr().out
    scope = json.loads(out.read_text())["scope"]
    assert "max3h" in scope and "max1h" in scope and "wet_hours" in scope


def complete_store_days(root, inputs, panels_days):
    """Day files for every date any sample table or the panel needs, D-2 included."""
    dates = set()
    for stem in B._sample_stems(inputs)[0]:
        for stamp in pd.read_parquet(inputs.features_dir / B.base_name(stem), columns=["date"])["date"]:
            dates.update(stamp.date() - timedelta(days=k) for k in range(3))
    for day in panels_days:
        dates.update(day - timedelta(days=k) for k in range(3))
    random_root(root, sorted(dates), real_cells()[:3], nan_rate=0.0)
    return sorted(dates)


def test_tables_refuse_when_a_needed_day_is_missing_unless_allowed(tables):
    inputs, out, root, panels = tables
    with pytest.raises(I.IncompleteStoreError) as caught:
        I.build_iint_tables(inputs, out, root, panels, years=(2018,))
    message = str(caught.value)
    assert "--allow-missing" in message and "2018-05-27" in message and not out.exists()    # D-2 of the first panel day
    manifest, _ = I.build_iint_tables(inputs, out, root, panels, years=(2018,), allow_missing=True)
    assert manifest["allow_missing"] is True and manifest["required_days_missing"] > 0


def test_tables_build_without_the_flag_once_every_needed_day_exists(tables):
    inputs, out, root, panels = tables
    panel_days = read_days(panels)
    complete_store_days(root, inputs, panel_days)
    manifest, reused = I.build_iint_tables(inputs, out, root, panels, years=(2018,))
    assert not reused and manifest["allow_missing"] is False and manifest["required_days_missing"] == 0


def read_days(panels):
    return I.read_panel(panels, 2018)[1]


def test_only_development_rows_and_panel_days_are_required():
    needed = I.required_days([date(2017, 12, 31), date(2018, 1, 5), date(2007, 3, 1)], [date(2018, 6, 1)])
    assert needed == I.window_days([date(2007, 3, 1), date(2017, 12, 31), date(2018, 6, 1)])
    assert date(2018, 1, 5) not in needed and date(2018, 5, 30) in needed and date(2007, 2, 27) in needed


def test_a_missing_window_day_of_a_panel_day_is_listed(tmp_path):
    root = tmp_path / "intensity"
    write_day(root, "late", date(2018, 5, 31))
    write_day(root, "late", date(2018, 6, 1))
    missing = I.missing_days(root, I.window_days([date(2018, 6, 1), date(2018, 6, 2)]))
    assert missing == [date(2018, 5, 30), date(2018, 6, 2)]


def test_ranges_collapse_consecutive_days():
    days = [date(2018, 5, 30), date(2018, 5, 31), date(2018, 6, 1), date(2019, 1, 5)]
    assert I.format_ranges(days) == "2018-05-30..2018-06-01 (3), 2019-01-05 (1)"


def test_tables_cli_refuses_with_the_missing_days_listed(tables, monkeypatch, capsys):
    inputs, out, root, panels = tables
    monkeypatch.setattr(B, "default_inputs", lambda: inputs)
    code = I.main(["tables", "--out-dir", str(out), "--root", str(root), "--panels-dir", str(panels), "--years", "2018",
                   "--lag", "0"])
    assert code == 1
    err = capsys.readouterr().err
    assert "2018-05-27" in err and "--allow-missing" in err


# ----------------------------------------------------------------------------------------------- the declared lag

def test_a_lag_of_one_day_gives_every_feature_of_day_d_from_the_previous_complete_day(tmp_path):
    p = imerg_pixel(WAYANAD)
    write_window(tmp_path, "late", D - timedelta(days=1), [
        {"max1h": {p: 1.0}, "max3h": {p: 2.0}, "max6h": {p: 3.0}, "wet_hours": {p: 4.0}},
        {"max1h": {p: 5.0}, "max3h": {p: 9.0}, "max6h": {p: 7.0}, "wet_hours": {p: 6.0}},
        {"max1h": {p: 8.0}, "max3h": {p: 3.0}, "max6h": {p: 6.0}, "wet_hours": {p: 2.0}}])
    write_day(tmp_path, "late", D, max1h={p: 99.0}, max3h={p: 99.0})          # day D itself is ignored by the lagged features
    lagged = I.cell_features(D, [WAYANAD], tmp_path, lag_days=1).iloc[0]
    yesterday = I.cell_features(D - timedelta(days=1), [WAYANAD], tmp_path).iloc[0]
    assert lagged.to_dict() == yesterday.to_dict()
    assert lagged["iint_max1h_1"] == 8.0 and lagged["iint_max3h_max3d"] == 9.0 and lagged["iint_wet_hours_1"] == 2.0
    assert I.cell_features(D, [WAYANAD], tmp_path).iloc[0]["iint_max1h_1"] == 99.0


def test_frame_features_with_a_lag_equal_the_per_day_lagged_features(tmp_path):
    cells = real_cells()[:3]
    random_root(tmp_path, [D - timedelta(days=k) for k in range(6)], cells, seed=3)
    frame = pd.DataFrame({"cell_id": cells, "date": pd.Timestamp(D)})
    out = I.frame_features(frame, I.DayLoader(tmp_path), lag_days=1)
    expected = I.cell_features(D, cells, tmp_path, lag_days=1)
    np.testing.assert_array_equal(out.to_numpy(), expected.to_numpy())
    assert not np.array_equal(np.nan_to_num(out.to_numpy()), np.nan_to_num(I.frame_features(frame, I.DayLoader(tmp_path)).to_numpy()))


def test_lag_names_and_the_days_a_lagged_window_needs():
    assert I.group_name(0) == "iint" and I.group_name(1) == "iint_lag1" and I.season_name(2019, 1) == "season_2019_iint_lag1.parquet"
    assert I.season_name(2019) == "season_2019_iint.parquet" and I.report_name(1) == "iint_lag1_report.json"
    with pytest.raises(ValueError, match="lag_days"):
        I.group_name(2)
    assert I.window_days([date(2018, 6, 1)], 1) == [date(2018, 5, 29), date(2018, 5, 30), date(2018, 5, 31)]
    assert I.required_days([date(2018, 1, 5)], [date(2018, 6, 1)], 1) == I.window_days([date(2018, 6, 1)], 1)


def test_a_lag_one_build_is_its_own_group_next_to_the_untouched_lag_zero_build(tables):
    inputs, out, root, panels = tables
    zero, _ = build(tables)
    before = {p.name: p.read_bytes() for p in out.glob("*iint*")}
    one, reused = build(tables, lag_days=1)
    assert not reused and one["lag_days"] == 1 and one["config"]["lag_days"] == 1 and zero["config"]["lag_days"] == 0
    assert (out / "iint_lag1_manifest.json").is_file() and (out / "season_2018_iint_lag1.parquet").is_file()
    assert {p.name: p.read_bytes() for p in out.glob("*iint*") if "lag1" not in p.name} == before
    assert json.loads((out / "iint_lag1_columns.json").read_text(encoding="utf-8")) == {c: "iint" for c in NAMES}
    assert I.verify_iint_tables(out, inputs, root, panels, lag_days=1)["ok"]
    lagged = pd.read_parquet(out / "season_2018_iint_lag1.parquet")
    row = lagged.iloc[len(lagged) // 2]
    expected = I.cell_features(row["date"].date(), [int(row["cell_id"])], root, lag_days=1).iloc[0]
    np.testing.assert_array_equal(row[NAMES].to_numpy(dtype=np.float32), expected.to_numpy())


def test_the_declared_lag_is_read_from_the_gap_report_and_a_missing_report_is_refused(tmp_path, tables, monkeypatch, capsys):
    with pytest.raises(FileNotFoundError, match="gap"):
        I.read_declared_lag(tmp_path / "none.json")
    report = tmp_path / "gap.json"
    report.write_text(json.dumps({"declared_lag_days": 1}), encoding="utf-8")
    assert I.read_declared_lag(report) == 1
    report.write_text(json.dumps({"declared_lag_days": 3}), encoding="utf-8")
    with pytest.raises(ValueError, match="declares lag"):
        I.read_declared_lag(report)
    inputs, out, root, panels = tables
    monkeypatch.setattr(B, "default_inputs", lambda: inputs)
    args = ["tables", "--out-dir", str(out), "--root", str(root), "--panels-dir", str(panels), "--years", "2018", "--allow-missing"]
    assert I.main([*args, "--gap-report", str(tmp_path / "none.json")]) == 1 and "gap" in capsys.readouterr().err
    report.write_text(json.dumps({"declared_lag_days": 1}), encoding="utf-8")
    assert I.main([*args, "--gap-report", str(report)]) == 0
    assert (out / "iint_lag1_manifest.json").is_file() and not (out / "iint_manifest.json").exists()
