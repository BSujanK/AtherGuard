"""Features for the forecast leads: observed IMERG rain through D plus GFS IMD-day totals after D (no network)."""
from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from aetherguard.features import imerg_features as F
from aetherguard.ingest import imerg
from aetherguard.live import forecast_features as FF

import live_run_helpers as H

DAY = H.DAY
CELLS = H.tiny_cells()
CLIM = H.tiny_clim(CELLS)
NAMES = F.all_names()


class RandomStore:
    """Deterministic UTC-day rain at every pixel; days listed in `planted` are replaced by a constant."""

    def __init__(self, planted=None, last_day=None):
        self.planted, self.last_day = dict(planted or {}), last_day

    def gather(self, rows, cols, first_day, length):
        rows, cols = np.asarray(rows, dtype=np.int64), np.asarray(cols, dtype=np.int64)
        out = np.empty((rows.size, length), dtype=np.float32)
        for k in range(length):
            d = first_day + timedelta(days=k)
            if d in self.planted:
                out[:, k] = self.planted[d]
            else:
                mix = (d.toordinal() * 7919 + rows * 104729 + cols * 1299709) % 997
                out[:, k] = np.where(mix % 5 == 0, 0.0, mix / 997 * 40.0)
        return out


def forecast_from(store, day, n=3):
    """The IMD-day series of the store after `day` as a (n, rows, cols) forecast array."""
    rows, cols = np.indices((imerg.ROWS, imerg.COLS))
    utc = store.gather(rows.ravel(), cols.ravel(), day, n + 1)
    return F.imd_day_series(utc).T.reshape(n, imerg.ROWS, imerg.COLS).astype(np.float32)


def frame_at(day):
    return CELLS[["cell_id"]].assign(date=pd.Timestamp(day))


def test_lead_zero_is_the_training_feature_row():
    store = RandomStore()
    reference = F.build_imerg_features(frame_at(DAY), store, CLIM)
    lead0 = FF.lead_features(CELLS, DAY, 0, store, None, CLIM)
    pd.testing.assert_frame_equal(lead0, reference)


@pytest.mark.parametrize("lead", [1, 2, 3])
def test_forecast_equal_to_the_observed_series_reproduces_the_training_features(lead):
    store = RandomStore()
    reference = F.build_imerg_features(frame_at(DAY + timedelta(days=lead)), store, CLIM)
    got = FF.lead_features(CELLS, DAY, lead, store, forecast_from(store, DAY), CLIM)
    pd.testing.assert_frame_equal(got, reference)


def test_forecast_values_never_change_lead_zero():
    store = RandomStore()
    forecast = forecast_from(store, DAY)
    base = FF.lead_features(CELLS, DAY, 0, store, forecast, CLIM)
    bumped = FF.lead_features(CELLS, DAY, 0, store, forecast + 500.0, CLIM)
    pd.testing.assert_frame_equal(base, bumped)
    assert FF.lead_features(CELLS, DAY, 1, store, forecast + 500.0, CLIM)["irain_acc_1"].gt(400).all()


def test_observed_values_after_day_d_change_nothing():
    forecast = forecast_from(RandomStore(), DAY)
    future = {DAY + timedelta(days=k): 9999.0 for k in range(1, 8)}
    clean, planted = RandomStore(), RandomStore(planted=future)
    for lead in (0, 1, 2, 3):
        pd.testing.assert_frame_equal(FF.lead_features(CELLS, DAY, lead, clean, forecast, CLIM),
                                      FF.lead_features(CELLS, DAY, lead, planted, forecast, CLIM))


def test_forecast_enters_only_the_days_after_d():
    store = RandomStore()
    forecast = forecast_from(store, DAY) * 0 + np.array([10.0, 20.0, 40.0], dtype=np.float32)[:, None, None]
    observed = F.build_imerg_features(frame_at(DAY), store, CLIM)
    lead2 = FF.lead_features(CELLS, DAY, 2, store, forecast, CLIM)
    assert (lead2["irain_acc_1"] == 20.0).all()
    assert np.allclose(lead2["irain_acc_3"], 10.0 + 20.0 + observed["irain_acc_1"], rtol=1e-5)


def test_a_missing_forecast_day_gives_nan_features_not_zero():
    store = RandomStore()
    forecast = forecast_from(store, DAY)
    forecast[1] = np.nan
    lead2 = FF.lead_features(CELLS, DAY, 2, store, forecast, CLIM)
    assert lead2["irain_acc_1"].isna().all() and lead2["irain_acc_3"].isna().all() and lead2["irain_acc_30"].isna().all()
    assert lead2["irain_max1d_7"].isna().all()
    assert FF.lead_features(CELLS, DAY, 1, store, forecast, CLIM)["irain_acc_1"].notna().all()


def test_a_missing_observed_day_propagates_by_the_nan_rule():
    gap = {DAY - timedelta(days=1): np.nan}
    lead1 = FF.lead_features(CELLS, DAY, 1, RandomStore(planted=gap), forecast_from(RandomStore(), DAY), CLIM)
    assert lead1["irain_acc_3"].isna().all() and lead1["irain_acc_1"].notna().all()


def test_cells_outside_the_domain_grid_are_nan():
    outside = CELLS.assign(cell_id=int(__import__("aetherguard.grid", fromlist=["x"]).latlon_to_cell(45.0, 10.0)))
    out = FF.lead_features(outside.iloc[:1], DAY, 0, RandomStore(), None, CLIM)
    assert out.isna().all().all() and list(out.columns) == NAMES and out.dtypes.eq(np.float32).all()


def test_invalid_arguments_are_refused():
    store = RandomStore()
    with pytest.raises(ValueError, match="lead must be"):
        FF.lead_features(CELLS, DAY, 4, store, None, CLIM)
    with pytest.raises(ValueError, match="needs forecast"):
        FF.lead_features(CELLS, DAY, 1, store, None, CLIM)
    with pytest.raises(ValueError, match="needs forecast"):
        FF.lead_features(CELLS, DAY, 2, store, forecast_from(store, DAY)[:1], CLIM)


def test_series_assembly_keeps_observed_and_forecast_columns_apart():
    utc = np.array([[1.0, 2.0, 3.0, 4.0]])
    series = FF.imd_series_with_forecast(utc, np.array([[10.0, 20.0]]))
    assert series.shape == (1, 5)
    assert np.allclose(series[0], [0.875 * 1 + 0.125 * 2, 0.875 * 2 + 0.125 * 3, 0.875 * 3 + 0.125 * 4, 10.0, 20.0])
    assert FF.imd_series_with_forecast(utc, None).shape == (1, 3)
    with pytest.raises(ValueError, match="same pixels"):
        FF.imd_series_with_forecast(utc, np.zeros((2, 2)))
