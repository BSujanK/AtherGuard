"""Synthetic parts for the integrity-audit tests: feature tables built with the real feature functions from random daily
rain, so every identity the audit asserts holds by construction until a test plants a violation."""
from __future__ import annotations

import numpy as np
import pandas as pd

from aetherguard.features import imerg_features as F
from aetherguard.features.compute import anomaly
from aetherguard.grid import cell_center, latlon_to_cell

SERIES = F.LOOKBACK + F.API_SPINUP + 2      # observed IMD days available before the forecast days
FORECAST = 3
CLIM = 12.0


def world(n: int = 40, seed: int = 3, heavy: bool = True) -> dict:
    """{"cells", "daily" (n, 9, SERIES + 3), "features": {0..3: DataFrame}}: the IMD-day rain of the 3x3 pixels around
    each cell (pixel 4 is the cell's own) and the `irain/iapi/inbr` + `gfs_rain_d*` columns of leads 0..3."""
    rng = np.random.default_rng(seed)
    lat = 11.525 + 0.05 * np.arange(n)
    ids = latlon_to_cell(lat, np.full(n, 76.125))
    wet = rng.random((n, 9, SERIES + FORECAST)) < 0.35
    amount = rng.gamma(0.8, 9.0 if heavy else 2.0, (n, 9, SERIES + FORECAST))
    daily = np.where(wet, amount, 0.0)
    cells = pd.DataFrame({"cell_id": ids, "lat": cell_center(ids)[0], "lon": cell_center(ids)[1],
                          "region": "western_ghats"})
    return {"cells": cells, "daily": daily, "features": {k: features_at(cells, daily, k) for k in range(FORECAST + 1)}}


def features_at(cells: pd.DataFrame, daily: np.ndarray, lead: int) -> pd.DataFrame:
    """The lead's feature table: the series up to IMD day D + lead (the observed part ends at column SERIES - 1)."""
    last = SERIES + lead                               # columns [0, last) are visible
    own = daily[:, 4, :last]
    out = pd.DataFrame({"cell_id": cells["cell_id"].to_numpy(), "date": pd.Timestamp("2026-10-20") + pd.Timedelta(days=lead),
                        "lat": cells["lat"].to_numpy(), "lon": cells["lon"].to_numpy(), "region": cells["region"].to_numpy()})
    block = F.accumulation_block(own[:, -F.LOOKBACK:])
    for name, values in block.items():
        out[f"irain_{name}"] = values.astype(np.float32)
    for window in (3, 7, 30):
        out[f"irain_acc{window}_vs_clim"] = anomaly(block[f"acc_{window}"], np.full(len(out), CLIM)).astype(np.float32)
    for k in F.API_DECAYS:
        state = F.api_state(own, k)
        t = np.full(len(out), last - 1)
        out[f"iapi_{round(k * 100)}"] = F.api_at(state, own, k, np.arange(len(out)), t).astype(np.float32)
    acc1 = np.stack([daily[:, p, :last][:, -1] for p in range(9)], axis=1)
    acc3 = np.stack([daily[:, p, :last][:, -3:].sum(axis=1) for p in range(9)], axis=1)
    for window, values in ((1, acc1), (3, acc3)):
        top, mean = F.neighbourhood_stats(values)
        out[f"inbr_max_acc_{window}"], out[f"inbr_mean_acc_{window}"] = top.astype(np.float32), mean.astype(np.float32)
    for j in range(1, lead + 1):
        out[f"gfs_rain_d{j}"] = daily[:, 4, SERIES + j - 1].astype(np.float32)
    return out
