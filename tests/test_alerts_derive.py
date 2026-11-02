"""Threshold derivation: weighted percentiles, the development-only guard and the stored config."""
import json

import numpy as np
import pandas as pd
import pytest

from aetherguard.alerts import config as ac
from aetherguard.alerts import derive as dv
from aetherguard.config import load_config
from aetherguard.hazard import data as hd
from aetherguard.integrity.model import HEADLINE_FPR
from alerts_helpers import CONFIG

SETTINGS = load_config("alerts")


def test_weighted_quantile_follows_the_weights():
    assert dv.weighted_quantile([1, 2, 3, 4], [1, 1, 1, 1], 50) == 2
    assert dv.weighted_quantile([1, 2, 3, 4], [1, 1, 1, 100], 50) == 4
    assert dv.weighted_quantile([1, np.nan, 3], [1, 5, 1], 100) == 3
    assert dv.weighted_quantile([5.0], [2.0], 5) == 5.0
    with pytest.raises(ValueError, match="finite"):
        dv.weighted_quantile([np.nan], [1.0], 50)


def test_engine_target_in_the_config_is_the_integrity_headline_rate():
    assert SETTINGS["stations"]["engine_target_flag_rate"] == HEADLINE_FPR


def _universe(n=2000, seed=0, split="train", end="2015-12-31"):
    rng = np.random.default_rng(seed)
    imd = np.exp(rng.normal(1.0, 1.2, n))
    chi = imd * rng.uniform(0.3, 3.0, n)
    rows = pd.DataFrame({"cell_id": np.arange(n), "date": pd.Timestamp(end), "split": split,
                         "weight": rng.uniform(1, 3, n), "src_imd_acc_1": imd, "src_chi_acc_1": chi,
                         "src_imd_acc_3": imd * 2, "src_chi_acc_3": chi * 2, "src_dis_ratio_3": (imd + 1) / (chi + 1),
                         "src_dis_both": 1.0, "rain_acc_1": imd, "integ_n_st_100km": 1.0,
                         "integ_frac_trusted_100km": 1.0, "integ_trw_rain_1": imd + rng.normal(0, 1, n),
                         "integ_trw_rain_3": imd * 2, "integ_max_st_rain_1_100km": imd,
                         "integ_n_flagged_100km_7d": 0.0})
    rows["integ_st_minus_grid_1"] = rows["integ_trw_rain_1"] - rows["rain_acc_1"]
    return rows


def test_derived_parameters_are_percentiles_of_the_development_frame_and_complete():
    universe = _universe()
    config, record = dv.derive_parameters(universe, universe.iloc[:50], SETTINGS)
    w = universe["weight"].to_numpy()
    assert config.dis_ratio_lo == dv.weighted_quantile(universe["src_dis_ratio_3"], w, 5)
    assert config.dis_ratio_hi == dv.weighted_quantile(universe["src_dis_ratio_3"], w, 95)
    assert config.dis_ratio_lo < 1 < config.dis_ratio_hi
    top = np.fmax(universe["src_imd_acc_1"], universe["src_chi_acc_1"])
    assert config.heavy_acc1_mm == dv.weighted_quantile(top, w, 95) and config.heavy_acc3_mm > config.heavy_acc1_mm
    assert config.agree_abs_mm > 0 and config.agree_rel > 0
    assert config.exit_days == 2 and config.exit_factor == 0.8 and config.radius_km == 100.0
    behaviour = record["development_behaviour"]
    assert behaviour["heavy_rain_share_universe"]["derived"] == pytest.approx(0.05, abs=0.02)
    assert set(behaviour["universe_confidence_share"]) == {"High", "Degraded", "Insufficient"}
    assert sum(behaviour["universe_confidence_share"].values()) == pytest.approx(1.0)


@pytest.mark.parametrize("split, end, match", [("test_2018", "2015-12-31", "splits"), ("train", "2018-03-01", "after")])
def test_derivation_refuses_non_development_rows(split, end, match):
    with pytest.raises(hd.LeakageError, match=match):
        dv._assert_development(_universe(10, split=split, end=end), "x", SETTINGS)


def test_config_roundtrip_and_validation(tmp_path):
    path = tmp_path / "alerts" / "alert_config.json"
    ac.save_config(path, CONFIG, {"note": "x"})
    assert ac.load_config_file(path) == CONFIG
    assert json.loads(path.read_text())["derivation"] == {"note": "x"}
    with pytest.raises(FileNotFoundError, match="derive"):
        ac.load_config_file(tmp_path / "none.json")
    payload = json.loads(path.read_text())
    payload["version"] = 99
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="version"):
        ac.load_config_file(path)
    with pytest.raises(ValueError, match="lacks"):
        ac.AlertConfig.from_dict({"exit_days": 2})
    with pytest.raises(ValueError, match="dis_ratio"):
        ac.AlertConfig.from_dict({**CONFIG.to_dict(), "dis_ratio_lo": 20.0})


def test_config_ood_rate_is_three_times_the_engine_target():
    assert CONFIG.ood_rate == pytest.approx(0.03)
    assert ac.structural_parameters(SETTINGS)["ood_multiple"] == 3.0


def test_the_uncertain_high_bound_defaults_to_the_models_upper_interval_and_older_configs_load_with_it():
    from dataclasses import replace
    from aetherguard.hazard.model import INTERVAL_PERCENTILES
    assert CONFIG.uncertain_percentile == ac.DEFAULT_UNCERTAIN_PERCENTILE == INTERVAL_PERCENTILES[1]
    old_values = {k: v for k, v in CONFIG.to_dict().items() if k != "uncertain_percentile"}
    assert ac.AlertConfig.from_dict(old_values) == CONFIG
    for value in (None, 75.0):
        assert ac.AlertConfig.from_dict(replace(CONFIG, uncertain_percentile=value).to_dict()).uncertain_percentile == value
    for bad in (50.0, 101.0, 0.0):
        with pytest.raises(ValueError, match="uncertain_percentile"):
            ac.AlertConfig.from_dict({**CONFIG.to_dict(), "uncertain_percentile": bad})
    assert ac.upper_column(75.0) == "risk_p75" and ac.upper_column(62.5) == "risk_p62.5"
