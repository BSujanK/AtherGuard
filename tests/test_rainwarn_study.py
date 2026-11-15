"""Pieces of the heavy-rain verification study: pixel averaging, categories, level table, 0/1 scores, inputs."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from aetherguard.features import imerg_features as F
from aetherguard.grid import latlon_to_cell
from aetherguard.rainwarn import climatology as C
from aetherguard.rainwarn import engine as E
from aetherguard.rainwarn import study as S
from aetherguard.rainwarn import verify as V


def test_pixel_values_average_the_cells_of_each_pixel():
    ids = np.asarray(latlon_to_cell(np.array([30.025, 30.075, 12.025]), np.array([79.025, 79.075, 75.525])), dtype=np.int64)
    pixels = np.unique(F.cell_pixels(ids))
    domain = C.Domain(pixels=np.append(pixels, pixels.max() + 1), regions=np.array(["", "", ""], dtype=object))
    frame = pd.DataFrame({"cell_id": ids, "v": [10.0, 20.0, 5.0]})
    out = S.pixel_values(domain, frame, "v")
    by_pixel = dict(zip(domain.pixels.tolist(), out.tolist()))
    assert by_pixel[int(F.cell_pixels(ids[:1])[0])] == pytest.approx(15.0)
    assert by_pixel[int(F.cell_pixels(ids[2:])[0])] == pytest.approx(5.0)
    assert np.isnan(out[-1])


def test_observed_categories_use_strict_imd_limits():
    assert S.obs_category(np.array([64.5, 64.6, 115.7, 204.5, 204.6, -1.0])).tolist() == [0, 1, 2, 2, 3, 0]


def test_level_table_shares_and_event_coverage():
    matrix = np.zeros((len(S.LEVEL_CODES), len(S.OBS_CATEGORIES)), dtype=np.int64)
    matrix[0] = [90, 2, 0, 0]          # none
    matrix[1] = [5, 2, 0, 0]           # yellow
    matrix[3] = [0, 0, 1, 0]           # red
    table = S.level_table(matrix)
    assert table["pixel_days"] == 100
    assert table["levels"]["yellow"]["share"] == pytest.approx(0.07)
    assert table["levels"]["yellow"]["freq_heavy_or_more"] == pytest.approx(2 / 7)
    assert table["levels"]["none"]["share_of_heavy_events"] == pytest.approx(2 / 5)
    assert table["levels"]["red"]["share_of_very_heavy_events"] == pytest.approx(1.0)
    assert table["levels"]["orange"]["n"] == 0 and table["levels"]["orange"]["freq_heavy_or_more"] is None


def test_det_scores_hit_rate_and_false_alarm_ratio():
    t = V.Tally(1)
    t.add(0, np.array([1.0, 1.0, 0.0, 0.0]), np.array([True, False, True, False]))
    s = S.det_scores(t)
    assert s["hit_rate"] == pytest.approx(0.5) and s["false_alarm_ratio"] == pytest.approx(0.5) and s["forecast_yes"] == 2


def test_ranges_and_membership():
    ranges = S._ranges([{"first": "2023-06-01", "last": "2023-06-30"}])
    assert S._inside(date(2023, 6, 30), ranges) and not S._inside(date(2023, 7, 1), ranges)


def test_lead_zero_inputs_keep_off_domain_pixels_out_of_the_neighbourhood():
    pixels = np.array([0, 1, 2], dtype=np.int64)
    fields = E.observed_fields(np.array([5.0, 50.0, 0.0]), [0, 1], pixels)
    assert fields["obs_max_r0"].tolist() == [5.0, 50.0, 0.0]
    assert fields["obs_max_r1"].tolist() == [50.0, 50.0, 50.0]


def test_day_inputs_are_float32():
    item = S.DayInputs({"a": np.array([1.0])}, {"gfs": np.array([2.0])})
    assert item.fields["a"].dtype == np.float32 and item.det["gfs"].dtype == np.float32
