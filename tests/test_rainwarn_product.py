"""The daily heavy-rain warning command on a synthetic run directory, rain store and tables (no real data)."""
import hashlib
import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from aetherguard.features import imerg_features as F
from aetherguard.grid import latlon_to_cell
from aetherguard.ingest import imerg
from aetherguard.rainwarn import climatology as C
from aetherguard.rainwarn import engine as E
from aetherguard.rainwarn import prob as P
from aetherguard.rainwarn import product
from aetherguard.rainwarn.__main__ import main

DAY = date(2026, 11, 14)
CFG = {"rain_dir": "processed/rain", "out_dir": "processed/rainwarn", "climatology": {"file": "climatology.npz"}}
LATS, LONS = [30.025, 30.075, 12.025], [79.025, 79.075, 75.525]
REGIONS = ["himalaya", "himalaya", "western_ghats"]


def cells():
    ids = np.asarray(latlon_to_cell(np.array(LATS), np.array(LONS)), dtype=np.int64)
    return pd.DataFrame({"cell_id": ids, "lat": LATS, "lon": LONS, "region": REGIONS, "irain_acc_1": [150.0, 150.0, 1.0]})


def write_tables(root):
    frame = cells()
    pixels = np.unique(F.cell_pixels(frame["cell_id"].to_numpy()))
    n = len(pixels)
    regions = C.domain_of_cells(frame["cell_id"].to_numpy(), frame["region"].to_numpy()).regions
    clim = C.Climatology(pixels=pixels, regions=regions,
                         p95=np.full(n, 40.0, dtype=np.float32), p99=np.full(n, 80.0, dtype=np.float32),
                         clim=np.full((len(P.THRESHOLDS), n, C.DOY), 0.01, dtype=np.float32), years=(2007, 2022),
                         window_days=15)
    clim.save(root / "processed" / "rainwarn" / "climatology.npz")
    entries = {}
    for lead in E.LEADS:
        entries[lead] = {}
        for name in P.THRESHOLDS:
            k = len(E.predictor_names(lead, 0)) + 1 + (1 if P.is_percentile(name) else 0)
            coef = np.zeros(k + 1)
            coef[1] = 3.0                     # p = sigmoid(3 (log1p(first predictor) - log1p(t)))
            model = P.LogisticModel(coef=coef, mean=np.zeros(k), scale=np.ones(k), n=1, n_events=1, log_loss=0.1)
            entries[lead][name] = {"radius": 0, "model": model, "log_loss_by_radius": {"0": 0.1}}
    E.Calibration(fit=[], radii=[0], entries=entries).save(root / "processed" / "rainwarn" / "calibration_shipped.json")
    return pixels


def write_ecmwf(root, pixels, valid=(True, True, False)):
    grid = np.zeros((3, imerg.ROWS, imerg.COLS), dtype=np.float16)
    wet = F.cell_pixels(cells()["cell_id"].to_numpy())[0]          # the Himalaya pixel
    grid[:, wet // imerg.COLS, wet % imerg.COLS] = 200.0
    folder = root / "processed" / "rain"
    folder.mkdir(parents=True, exist_ok=True)
    np.savez(folder / f"ecmwf_imdday_{DAY.isoformat()}.npz", hres=grid, hres_valid=np.array(valid),
             hres_cycle=np.array("2026-11-13T12:00:00+00:00"), ens_mean=grid, ens_p10=grid, ens_p50=grid, ens_p90=grid,
             ens_valid=np.array(valid), ens_cycle=np.array("2026-11-13T18:00:00+00:00"), n_members=np.array(50))


@pytest.fixture
def setup(tmp_path, monkeypatch):
    root = tmp_path / "data"
    monkeypatch.setenv("AETHERGUARD_DATA_DIR", str(root))
    pixels = write_tables(root)
    write_ecmwf(root, pixels)
    run = tmp_path / "live" / DAY.isoformat()
    run.mkdir(parents=True)
    cells().to_parquet(run / "features_D0.parquet", index=False)
    pd.DataFrame({"cell_id": cells()["cell_id"], "level": np.int8([3, 2, 0])}).to_parquet(run / "alerts.parquet")
    pd.DataFrame({"cell_id": cells()["cell_id"], "level": np.int8([1, 1, 0])}).to_parquet(run / "risk_D1.parquet")
    (run / "run.json").write_text(json.dumps({"date": DAY.isoformat()}))
    return run


def digest(folder):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.iterdir()) if p.is_file()}


def test_run_writes_every_cell_and_lead_and_marks_a_missing_lead(setup):
    assert product.run_day(CFG, DAY, setup) == 0
    table = pd.read_parquet(setup / product.PARQUET)
    assert len(table) == 3 * 4 and sorted(table["lead"].unique()) == [0, 1, 2, 3]
    lead1 = table[table["lead"] == 1].set_index("region")
    wet = table[(table["lead"] == 1) & (table["region"] == "himalaya")]
    assert (wet["p_extremely_heavy"] < wet["p_heavy"]).all() and (wet["p_heavy"] > 0.9).all()
    assert (wet["level_name"] == "red").all()
    dry = lead1.loc["western_ghats"]
    assert dry["p_heavy"] < 0.01 and dry["level_name"] == "none"
    lead3 = table[table["lead"] == 3]
    assert lead3["level_name"].eq("unavailable").all() and lead3["p_heavy"].isna().all()
    assert not lead3["published"].any() and lead3["reason"].str.contains("ensemble").all()
    lead0 = table[table["lead"] == 0]
    assert (lead0["source"] == "imerg_early+nowcast_tail").all()
    assert lead0.loc[lead0["region"] == "himalaya", "p_heavy"].min() > 0.5
    assert (table["target_date"] - table["date"]).dt.days.tolist() == list(np.repeat([0, 1, 2, 3], 3))
    text = (setup / product.BULLETIN).read_text(encoding="utf-8")
    assert "research prototype" in text and "does not change any landslide alert level" in text
    assert "D+3 not published" in text


def test_run_does_not_touch_the_landslide_outputs(setup):
    before = digest(setup)
    product.run_day(CFG, DAY, setup)
    after = digest(setup)
    assert {k: after[k] for k in before} == before
    assert set(after) - set(before) == {product.PARQUET, product.BULLETIN}


def test_out_dir_keeps_the_run_directory_unchanged(setup, tmp_path):
    before = digest(setup)
    out = tmp_path / "scratch" / DAY.isoformat()
    assert main(["run", "--date", DAY.isoformat(), "--live-dir", str(setup), "--out-dir", str(out)]) == 0
    assert digest(setup) == before
    assert (out / product.PARQUET).is_file() and (out / product.BULLETIN).is_file()


def test_run_refuses_a_run_directory_of_another_day(setup):
    with pytest.raises(product.ProductError, match="not 2026-11-15"):
        product.run_day(CFG, date(2026, 11, 15), setup)


def test_run_without_an_ensemble_day_publishes_lead_zero_only(setup, tmp_path):
    (tmp_path / "data" / "processed" / "rain" / f"ecmwf_imdday_{DAY.isoformat()}.npz").unlink()
    product.run_day(CFG, DAY, setup)
    table = pd.read_parquet(setup / product.PARQUET)
    assert table.groupby("lead")["published"].all().to_dict() == {0: True, 1: False, 2: False, 3: False}
