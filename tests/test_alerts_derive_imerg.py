"""The IMERG-era alert-engine parameters (alerts.derive_imerg) on hand-made rows: the proxy columns, the weighted
percentiles and the validity shares."""
import json

import numpy as np
import pandas as pd
import pytest

from aetherguard.alerts import derive_imerg as di
from aetherguard.alerts.config import alerts_settings
from aetherguard.features import sources as fs


class FakeStore:
    """A DailyStore-like IMD store: `values[(pixel, day_number)]`, NaN elsewhere."""

    def __init__(self, values):
        self.values = values

    def gather(self, pix, first_day, length):
        out = np.full((len(pix), length), np.nan, dtype=np.float32)
        first = np.broadcast_to(np.asarray(first_day), (len(pix),))
        for r, p in enumerate(pix):
            for k in range(length):
                out[r, k] = self.values.get((int(p), int(first[r]) + k), np.nan)
        return out


def test_imd_windows_read_the_live_sampling_point_and_need_every_day():
    cell = 23485372
    frame = pd.DataFrame({"cell_id": [cell, cell], "date": pd.to_datetime(["2010-07-03", "2010-07-04"])})
    day = int(fs.day_numbers(pd.to_datetime(["2010-07-03"]).to_numpy())[0])
    west = int(fs._imd_pixels(np.array([cell]), -1)[0])
    store = FakeStore({(west, day - 2): 1.0, (west, day - 1): 2.0, (west, day): 3.0, (west, day + 1): -999.0})
    out = di.imd_windows(frame, store, -1)
    assert out[1][0] == 3.0 and out[3][0] == 6.0
    assert np.isnan(out[1][1]) and np.isnan(out[3][1])            # a missing (negative) day is NaN, never 0
    nearest = di.imd_windows(frame, store, 0)
    assert np.isnan(nearest[1][0])                                 # the nearest point holds nothing in this store


def test_derive_from_proxy_uses_weighted_percentiles_of_the_live_pair():
    n = 1000
    rng = np.random.default_rng(0)
    imd3 = rng.uniform(0, 100, n)
    frame = pd.DataFrame({"imd_1": imd3 / 3, "imd_3": imd3, "sat_1": imd3 / 3, "sat_3": imd3, "both": True,
                          "ratio_3": (imd3 + 1) / (imd3 + 1), "station": imd3 / 3 + 1.0, "grid": imd3 / 3, "month": 7})
    out = di.derive_from_proxy(frame, np.ones(n), alerts_settings())
    v = out["values"]
    assert v["dis_ratio_lo"] == pytest.approx(1.0) and v["dis_ratio_hi"] == pytest.approx(1.0)
    assert v["heavy_acc3_mm"] == pytest.approx(np.percentile(imd3, 95), rel=0.02)
    assert v["agree_abs_mm"] == pytest.approx(1.0)
    assert out["rows"]["universe"] == n and out["rows"]["both_sources"] == n


def test_outside_share_counts_both_tails_with_weights():
    ratio = np.array([0.05, 1.0, 1.0, 20.0, np.nan])
    both = np.array([True, True, True, True, True])
    assert di.outside_share(ratio, both, 0.1, 10.0) == pytest.approx(0.5)
    assert di.outside_share(ratio, both, 0.1, 10.0, np.array([1, 3, 3, 1, 1.0])) == pytest.approx(0.25)
    assert di.outside_share(ratio, np.zeros(5, dtype=bool), 0.1, 10.0) is None


def test_live_check_reads_only_days_with_a_day_d_file(tmp_path):
    for name, both, ratio in (("2026-11-01", [1, 1, 1, 1], [0.05, 1, 1, 20]), ("2026-11-02", [0, 0, 0, 0], [np.nan] * 4)):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "run.json").write_text(json.dumps({}), encoding="utf-8")
        pd.DataFrame({"src_dis_both": np.array(both, dtype=np.float32),
                      "src_dis_ratio_3": np.array(ratio, dtype=np.float32)}).to_parquet(folder / "features_D0.parquet")
    out = di.live_check(tmp_path, {"narrow": (0.1, 10.0), "wide": (0.01, 100.0)})
    assert out["days"] == ["2026-11-01"] and out["cell_days"] == 4 and out["months"] == [11]
    assert out["outside"] == {"narrow": 0.5, "wide": 0.0}
