"""End to end on real data (run with -m realdata): one Kerala 2018 day -> hazard model -> alert engine -> replay store -> API."""
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from aetherguard.alerts import derive, replay
from aetherguard.alerts import levels as lv
from aetherguard.alerts.config import alerts_settings
from aetherguard.alerts.frames import load_feature_frame
from aetherguard.alerts.store import ReplayStore, write_manifest, write_set
from aetherguard.hazard import data as hd
from aetherguard.hazard import model as hm
from aetherguard.hazard.model import score_frame
from aetherguard.integrity.common import integrity_dir
from aetherguard.integrity.stations import select_station_meta
from aetherguard.serve import api

SET = "case_kerala_2018_samples"
DAY = "2018-08-12"
FEATURES = hd.features_dir()
needs_data = pytest.mark.skipif(
    not ((FEATURES / f"{SET}_features.parquet").is_file() and (hm.default_model_dir() / hm.CARD_FILE).is_file()
         and (integrity_dir() / replay.OOF_OUTPUTS).is_file() and (FEATURES / "integ").is_dir()),
    reason="feature store, hazard model or integrity outputs not built")


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory):
    model = hm.load_cached()
    config, _ = derive.derive()
    thresholds = lv.thresholds_from_card(model.card, alerts_settings()["v1_card_fallback"])
    frame = load_feature_frame(SET, model_columns=model.columns)
    frame = frame[frame["date"] == DAY].reset_index(drop=True)
    alerts, sensors = replay.replay_set(frame, score_frame, model.contributions, replay.load_station_outputs(),
                                        select_station_meta(), thresholds, config)
    root = tmp_path_factory.mktemp("e2e")
    entry = write_set(root, SET, alerts, sensors)
    write_manifest(root, {SET: entry}, thresholds=thresholds.to_dict(), model={"card_sha256": "x"}, provisional=None)
    return alerts, thresholds, TestClient(api.create_app(root))


@pytest.mark.realdata
@needs_data
def test_one_kerala_day_runs_end_to_end_and_the_api_agrees_with_the_engine(pipeline):
    alerts, thresholds, client = pipeline
    assert len(alerts) > 5000 and alerts["date"].eq(pd.Timestamp(DAY)).all()
    assert np.isfinite(alerts[["risk", "risk_lo", "risk_hi"]].to_numpy()).all()
    assert (alerts["risk_lo"] <= alerts["risk_hi"]).all()
    body = client.get("/risk", params={"date": DAY}).json()
    assert body["n_cells"] == len(alerts) and body["set"] == SET
    served = {c["cell_id"]: c for c in body["cells"]}
    expected = alerts.set_index("cell_id")
    assert all(served[c]["level"] == expected.at[c, "level"] and served[c]["confidence"] == expected.at[c, "confidence"]
               for c in list(served)[:500])
    assert sum(body["level_counts"].values()) == len(alerts)
    assert body["thresholds"]["watch"] == thresholds.watch


@pytest.mark.realdata
@needs_data
def test_cell_endpoint_gives_the_same_level_and_a_full_explanation(pipeline):
    alerts, _, client = pipeline
    for cell in (alerts.sort_values("risk").iloc[-1], alerts.iloc[len(alerts) // 2]):
        body = client.get(f"/risk/cell/{int(cell['cell_id'])}", params={"date": DAY}).json()
        assert body["level"] == cell["level"] and body["level_name"] == cell["level_name"]
        assert body["confidence"] == cell["confidence"]
        assert body["risk"] == pytest.approx(cell["risk"]) and body["risk_lo"] <= body["risk_hi"]
        assert 1 <= len(body["shap"]) <= hm.TOP_CONTRIBUTIONS
        assert {"imd_acc_1", "chirps_acc_1", "station_max_1"} <= set(body["sources"])
    sensors = client.get("/sensors", params={"date": DAY}).json()
    assert sensors["n_stations"] == 140 and sum(sensors["state_counts"].values()) == 140
