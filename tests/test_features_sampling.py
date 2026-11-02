"""Sampling primitives: rain coverage, event buffer, terrain attachment, slope floor, negatives, universe."""
import numpy as np
import pandas as pd
import pytest

from aetherguard.config import load_config
from aetherguard.features import sampling
from aetherguard.features.sampling import EventBuffer, RainCoverage, SamplingError
from aetherguard.grid import ID_STRIDE


def cid(lat_index, lon_index):
    return lat_index * ID_STRIDE + lon_index


def days(*values):
    return np.array(values, dtype="datetime64[D]")


# ---------------------------------------------------------------------------------------- rain coverage

@pytest.fixture
def coverage():
    return RainCoverage([("2007-01-01", "2018-12-31"), ("2023-05-01", "2023-08-15")], lookback_days=30)


def test_coverage_needs_the_full_lookback_inside_one_range(coverage):
    got = coverage.drawable(days("2007-01-30", "2007-01-31", "2018-12-31", "2019-01-05", "2023-05-30",
                                 "2023-05-31", "2023-08-15", "2023-08-16", "2020-06-01"))
    assert list(got) == [False, True, True, False, False, True, True, False, False]


def test_coverage_does_not_bridge_two_ranges():
    two = RainCoverage([("2010-01-01", "2010-03-31"), ("2010-04-01", "2010-06-30")], lookback_days=30)
    assert list(two.drawable(days("2010-04-15", "2010-05-01"))) == [False, True]


def test_coverage_drawable_days_lists_every_covered_day_in_a_range(coverage):
    got = coverage.drawable_days("2007-01-25", "2007-02-03")
    assert got.dtype == np.dtype("datetime64[D]")
    assert got[0] == np.datetime64("2007-01-31") and got[-1] == np.datetime64("2007-02-03") and len(got) == 4


def test_coverage_from_config_matches_the_ingest_ranges():
    cov = RainCoverage.from_config(load_config("ingest"), lookback_days=30)
    assert cov.ranges == [(pd.Timestamp("2007-01-01"), pd.Timestamp("2018-12-31")),
                          (pd.Timestamp("2023-05-01"), pd.Timestamp("2023-08-15")),
                          (pd.Timestamp("2024-06-01"), pd.Timestamp("2024-08-15"))]


# ---------------------------------------------------------------------------------------- event buffer

BASE_DAY = np.datetime64("2010-07-10")


@pytest.fixture
def buffer():
    return EventBuffer(np.array([cid(100, 200)]), days("2010-07-10"), cells=3, days=3)


@pytest.mark.parametrize("dlat,dlon,expected", [
    (0, 0, True), (2, 0, True), (3, 0, False), (0, 2, True), (0, 3, False), (-2, 0, True), (-3, 0, False),
    (0, -2, True), (0, -3, False), (2, 2, True), (-2, -2, True), (3, 2, False), (2, 3, False), (3, 3, False),
])
def test_buffer_cell_distance_boundary_is_chebyshev_two_inside_three_outside(buffer, dlat, dlon, expected):
    got = buffer.hits(np.array([cid(100 + dlat, 200 + dlon)]), days("2010-07-10"))
    assert bool(got[0]) is expected


@pytest.mark.parametrize("offset,expected", [(0, True), (3, True), (4, False), (-3, True), (-4, False)])
def test_buffer_date_boundary_is_three_days_inside_four_outside(buffer, offset, expected):
    day = BASE_DAY + np.timedelta64(offset, "D")
    assert bool(buffer.hits(np.array([cid(100, 200)]), np.array([day]))[0]) is expected


def test_buffer_needs_both_conditions_at_once(buffer):
    cells = np.array([cid(102, 202), cid(102, 202), cid(103, 200), cid(100, 200)])
    when = days("2010-07-13", "2010-07-14", "2010-07-10", "2010-07-14")
    assert list(buffer.hits(cells, when)) == [True, False, False, False]


def test_buffer_longitude_index_wraps_like_the_grid():
    wrap = EventBuffer(np.array([cid(100, 0)]), days("2010-07-10"), cells=3, days=3)
    assert list(wrap.hits(np.array([cid(100, 7199), cid(100, 7198), cid(100, 7197)]),
                          days("2010-07-10", "2010-07-10", "2010-07-10"))) == [True, True, False]


def test_buffer_latitude_does_not_wrap():
    edge = EventBuffer(np.array([cid(0, 200)]), days("2010-07-10"), cells=3, days=3)
    assert not edge.hits(np.array([cid(3599, 200)]), days("2010-07-10"))[0]


def test_buffer_from_events_uses_every_record_with_a_date_and_a_cell():
    events = pd.DataFrame({
        "cell_id": pd.array([cid(100, 200), cid(300, 300), pd.NA, cid(500, 500)], dtype="Int64"),
        "event_date": pd.to_datetime(["2010-07-10", None, "2010-07-10", "2010-07-10"]),
        "drop_reason": ["out_of_scope_region", None, "bad_coordinates", "duplicate_id"],
    })
    buf = EventBuffer.from_events(events, cells=3, days=3)
    assert buf.n_records == 2
    got = buf.hits(np.array([cid(101, 200), cid(300, 300), cid(500, 501)]), days("2010-07-10", "2010-07-10", "2010-07-12"))
    assert list(got) == [True, False, True]


def test_buffer_without_records_hits_nothing():
    empty = EventBuffer(np.empty(0, dtype=np.int64), np.empty(0, dtype="datetime64[D]"), cells=3, days=3)
    assert not empty.hits(np.array([cid(1, 1)]), days("2010-07-10")).any()


# ---------------------------------------------------------------------------------------- terrain / floor

def _terrain(rows):
    return pd.DataFrame(rows, columns=["cell_id", "slope_mean"])


def _positives(rows):
    out = pd.DataFrame(rows, columns=["cell_id", "event_date", "split", "region"])
    out["event_date"] = pd.to_datetime(out["event_date"])
    return out


def test_attach_terrain_own_nearest_land_and_none():
    terrain = _terrain([(cid(100, 200), 10.0), (cid(100, 203), 20.0), (cid(110, 200), 30.0)])
    positives = _positives([
        (cid(100, 200), "2010-07-01", "train", "himalaya"),      # own
        (cid(100, 205), "2010-07-02", "train", "himalaya"),      # nearest kept cell at 2 cells east -> (100, 203)
        (cid(104, 204), "2010-07-03", "train", "himalaya"),      # 4 cells from everything -> none
        (cid(100, 206), "2010-07-04", "train", "himalaya"),      # exactly 3 cells from (100, 203) -> allowed
        (cid(100, 207), "2010-07-05", "train", "himalaya"),      # 4 cells -> none
    ])
    got = sampling.attach_terrain(positives, terrain, max_cells=3)
    assert list(got["terrain_source"]) == ["own", "nearest_land", "none", "nearest_land", "none"]
    assert got["terrain_cell_id"].tolist()[:2] == [cid(100, 200), cid(100, 203)]
    assert got["terrain_cell_id"].isna().tolist() == [False, False, True, False, True]
    assert got["slope_mean"].tolist()[:2] == [10.0, 20.0]
    assert np.isnan(got["slope_mean"].iloc[2])


def test_attach_terrain_nearest_is_euclidean_then_lowest_cell_id():
    terrain = _terrain([(cid(100, 202), 1.0), (cid(101, 201), 2.0), (cid(99, 201), 3.0)])
    positives = _positives([(cid(100, 200), "2010-07-01", "train", "himalaya")])
    got = sampling.attach_terrain(positives, terrain, max_cells=3)
    # (101,201) and (99,201) are both sqrt(2) away and nearer than (100,202) at 2: the lower cell id wins
    assert got["terrain_cell_id"].iloc[0] == cid(99, 201)


def test_slope_floor_is_a_percentile_of_unique_train_positive_cells_with_own_terrain():
    terrain = _terrain([(cid(100, 200 + i), float(i)) for i in range(1, 101)])
    rows = [(cid(100, 200 + i), "2010-07-01", "train", "himalaya") for i in range(1, 101)]
    rows += [(cid(100, 201), "2010-07-05", "train", "himalaya")]               # repeated cell counts once
    rows += [(cid(100, 250), "2017-07-01", "validation", "himalaya")]          # not the reference split
    rows += [(cid(200, 200), "2010-07-01", "train", "himalaya")]               # nearest_land / none: no own terrain
    positives = sampling.attach_terrain(_positives(rows), terrain, max_cells=3)
    got = sampling.slope_floor(positives, percentile=5, reference_split="train")
    assert got["n_cells"] == 100
    assert got["floor"] == pytest.approx(np.percentile(np.arange(1, 101, dtype=float), 5))
    assert got["per_region"]["himalaya"]["n_cells"] == 100


def test_slope_floor_per_region_and_missing_reference_is_an_error():
    terrain = _terrain([(cid(100, 200), 4.0), (cid(100, 201), 8.0), (cid(50, 100), 20.0)])
    rows = [(cid(100, 200), "2010-07-01", "train", "himalaya"), (cid(100, 201), "2010-07-02", "train", "himalaya"),
            (cid(50, 100), "2010-07-03", "train", "western_ghats")]
    positives = sampling.attach_terrain(_positives(rows), terrain, max_cells=3)
    got = sampling.slope_floor(positives, percentile=50, reference_split="train")
    assert got["per_region"]["himalaya"]["floor"] == pytest.approx(6.0)
    assert got["per_region"]["western_ghats"]["floor"] == pytest.approx(20.0)
    with pytest.raises(ValueError, match="no positive"):
        sampling.slope_floor(positives, percentile=5, reference_split="validation")


def test_candidate_cells_keep_in_scope_cells_at_or_above_the_floor():
    terrain = _terrain([(1, 3.0), (2, 5.0), (3, 9.0), (4, 9.0), (5, np.nan)])
    regions = pd.DataFrame({"cell_id": [1, 2, 3, 4, 5], "country_code": ["IN"] * 5,
                            "region": ["himalaya", "himalaya", "western_ghats", "out_of_scope", "himalaya"]})
    got = sampling.candidate_cells(terrain, regions, slope_floor=5.0)
    assert list(got.columns) == ["cell_id", "region", "slope_mean"]
    assert got["cell_id"].tolist() == [2, 3]
    assert got["region"].tolist() == ["himalaya", "western_ghats"]


def test_candidate_cells_require_a_region_row_for_every_terrain_cell():
    terrain = _terrain([(1, 3.0), (2, 5.0)])
    regions = pd.DataFrame({"cell_id": [1], "country_code": ["IN"], "region": ["himalaya"]})
    with pytest.raises(ValueError, match="no region"):
        sampling.candidate_cells(terrain, regions, slope_floor=0.0)


# ---------------------------------------------------------------------------------------- negatives

START, END = pd.Timestamp("2010-01-01"), pd.Timestamp("2011-12-31")


def _empty_buffer():
    return EventBuffer(np.empty(0, dtype=np.int64), np.empty(0, dtype="datetime64[D]"), cells=3, days=3)


def _draw(seed=1, n=200, cells=None, probs=None, buffer=None, coverage=None, start=START, end=END, **kwargs):
    cells = np.arange(1_000_000, 1_000_050, dtype=np.int64) if cells is None else cells
    month_probs = np.zeros(12) if probs is None else probs
    if probs is None:
        month_probs[[5, 6, 7]] = [0.2, 0.5, 0.3]  # June, July, August
    coverage = coverage or RainCoverage([("2007-01-01", "2024-12-31")], lookback_days=30)
    return sampling.draw_negatives(np.random.default_rng(seed), n, cells, month_probs, start, end, coverage,
                                   buffer or _empty_buffer(), **kwargs)


def test_negatives_exact_count_unique_and_in_requested_months_and_range():
    rows, stats = _draw(n=300)
    assert len(rows) == 300 and stats["accepted"] == 300
    assert not rows.duplicated(["cell_id", "date"]).any()
    assert set(rows["date"].dt.month) <= {6, 7, 8}
    assert rows["date"].min() >= START and rows["date"].max() <= END
    assert set(rows["date"].dt.year) == {2010, 2011}
    assert rows["cell_id"].isin(np.arange(1_000_000, 1_000_050)).all()
    assert list(rows.columns) == ["cell_id", "date"]


def test_negatives_follow_the_month_distribution():
    rows, _ = _draw(n=3000, cells=np.arange(2_000_000, 2_000_500, dtype=np.int64))
    shares = rows["date"].dt.month.value_counts(normalize=True)
    assert shares[7] == pytest.approx(0.5, abs=0.05)
    assert shares[6] == pytest.approx(0.2, abs=0.05)


def test_negatives_are_deterministic_for_a_seed_and_differ_between_seeds():
    first, _ = _draw(seed=7)
    again, _ = _draw(seed=7)
    other, _ = _draw(seed=8)
    pd.testing.assert_frame_equal(first, again)
    assert not first.equals(other)


def test_negatives_never_fall_inside_the_buffer_and_stats_count_rejections():
    cells = np.arange(cid(100, 200), cid(100, 210), dtype=np.int64)
    buf = EventBuffer(np.array([cid(100, 205)]), days("2010-07-15"), cells=3, days=3)
    rows, stats = _draw(n=400, cells=cells, buffer=buf)
    assert not buf.hits(rows["cell_id"].to_numpy(), rows["date"].to_numpy().astype("datetime64[D]")).any()
    assert stats["rejected"]["in_buffer"] > 0
    assert stats["attempts"] == stats["accepted"] + sum(stats["rejected"].values())


def test_negatives_reject_dates_without_rain_lookback_and_count_them():
    jan = pd.Timestamp("2007-01-01"), pd.Timestamp("2007-02-28")
    probs = np.zeros(12)
    probs[[0, 1]] = [0.5, 0.5]
    rows, stats = _draw(n=100, probs=probs, start=jan[0], end=jan[1],
                        coverage=RainCoverage([("2007-01-01", "2024-12-31")], lookback_days=30))
    assert rows["date"].min() >= pd.Timestamp("2007-01-31")
    assert stats["rejected"]["no_rain_coverage"] > 0


def test_negatives_fail_loudly_when_the_space_is_exhausted():
    # one cell, one month of ~31 days minus the buffer: fewer valid (cell, date) pairs than requested
    probs = np.zeros(12)
    probs[6] = 1.0
    with pytest.raises(SamplingError, match="could not draw") as err:
        _draw(n=500, cells=np.array([cid(100, 200)]), probs=probs, start=pd.Timestamp("2010-07-01"),
              end=pd.Timestamp("2010-07-31"), max_draws_per_target=20)
    assert "no_rain_coverage" in str(err.value) and "duplicate" in str(err.value)


def test_negatives_zero_target_returns_an_empty_frame():
    rows, stats = _draw(n=0)
    assert rows.empty and stats["attempts"] == 0
    assert list(rows.columns) == ["cell_id", "date"]


def test_negatives_with_a_target_but_no_month_mass_is_an_error():
    with pytest.raises(ValueError, match="month distribution"):
        _draw(n=5, probs=np.zeros(12))


# ---------------------------------------------------------------------------------------- universe

def test_universe_draws_unique_rows_with_weight_and_flags():
    cells = np.arange(cid(100, 200), cid(100, 220), dtype=np.int64)
    window = np.arange(np.datetime64("2010-03-01"), np.datetime64("2010-04-01"), dtype="datetime64[D]")
    buf = EventBuffer(np.array([cid(100, 205)]), days("2010-03-15"), cells=3, days=3)
    positives = pd.DataFrame({"cell_id": [cid(100, 205), cid(100, 219)],
                              "event_date": pd.to_datetime(["2010-03-15", "2010-03-02"])})
    rows, size = sampling.draw_universe(np.random.default_rng(3), cells, window, 600, buf, positives)
    assert size == 20 * 31
    assert len(rows) == 600 and not rows.duplicated(["cell_id", "date"]).any()
    assert (rows["weight"] == size / 600).all() and (rows["universe_size"] == size).all()
    assert rows["date"].between("2010-03-01", "2010-03-31").all()
    expected = buf.hits(rows["cell_id"].to_numpy(), rows["date"].to_numpy().astype("datetime64[D]"))
    assert (rows["in_buffer"].to_numpy() == expected).all() and expected.any()
    is_pos = ((rows["cell_id"] == cid(100, 205)) & (rows["date"] == "2010-03-15")
              | (rows["cell_id"] == cid(100, 219)) & (rows["date"] == "2010-03-02"))
    assert (rows["is_positive_cell_day"] == is_pos).all() and is_pos.sum() >= 1


def test_universe_smaller_than_the_draw_takes_every_cell_day_with_unit_weight():
    cells = np.array([cid(100, 200), cid(100, 201)], dtype=np.int64)
    window = np.arange(np.datetime64("2010-03-01"), np.datetime64("2010-03-04"), dtype="datetime64[D]")
    rows, size = sampling.draw_universe(np.random.default_rng(3), cells, window, 100, _empty_buffer(),
                                        pd.DataFrame({"cell_id": [], "event_date": pd.to_datetime([])}))
    assert size == 6 and len(rows) == 6 and (rows["weight"] == 1.0).all()


def test_universe_is_deterministic_for_a_seed():
    cells = np.arange(cid(100, 200), cid(100, 300), dtype=np.int64)
    window = np.arange(np.datetime64("2010-01-01"), np.datetime64("2010-12-31"), dtype="datetime64[D]")
    empty = pd.DataFrame({"cell_id": [], "event_date": pd.to_datetime([])})
    a, _ = sampling.draw_universe(np.random.default_rng(5), cells, window, 500, _empty_buffer(), empty)
    b, _ = sampling.draw_universe(np.random.default_rng(5), cells, window, 500, _empty_buffer(), empty)
    pd.testing.assert_frame_equal(a, b)


def test_universe_without_candidates_or_days_is_an_error():
    empty = pd.DataFrame({"cell_id": [], "event_date": pd.to_datetime([])})
    with pytest.raises(ValueError, match="empty universe"):
        sampling.draw_universe(np.random.default_rng(1), np.empty(0, dtype=np.int64),
                               days("2010-01-01"), 10, _empty_buffer(), empty)


def test_stream_seeds_are_distinct_per_purpose_split_and_region_and_reproducible():
    a = sampling.stream(1, "negatives", 0, 0).integers(0, 10**9, 4)
    assert (a == sampling.stream(1, "negatives", 0, 0).integers(0, 10**9, 4)).all()
    for other in (sampling.stream(1, "universe", 0, 0), sampling.stream(1, "negatives", 1, 0),
                  sampling.stream(1, "negatives", 0, 1), sampling.stream(2, "negatives", 0, 0)):
        assert not (a == other.integers(0, 10**9, 4)).all()
