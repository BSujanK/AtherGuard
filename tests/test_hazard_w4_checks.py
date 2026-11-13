"""W4 development checks and reports (spec 2026-11-13 sections 4-6): the C1-C3 flag rules exactly as declared, the ablation
set, the climatological part, the built-up terciles, the status of the workstream from the stored results, and the report text."""
import numpy as np
import pandas as pd
import pytest

from aetherguard.features import wetness as wt
from aetherguard.hazard import data as hd
from aetherguard.hazard import w4_wetness as w4

IWET = wt.feature_names()


def test_the_ablation_is_each_input_alone_each_left_out_and_the_climatological_part():
    v = w4.variants(IWET)
    assert v["v3+iwet_sat_l2"] == ["iwet_sat_l2"] and v["v3+iwet-iwet_sat_l2"] == ["iwet_sat_anom_l2", "iwet_satdays30_l2"]
    assert v["v3+iwet_sat_clim"] == ["iwet_sat_clim"] and len(v) == 7


def test_c1_flags_when_the_static_part_alone_does_as_well_as_the_wetness_group():
    assert w4.c1_flag({"v3+iwet_sat_clim": 0.18, "w4_wet": 0.19}, "w4_wet")["flag"] is True
    assert w4.c1_flag({"v3+iwet_sat_clim": 0.19, "w4_wet": 0.19}, "w4_wet")["flag"] is True       # "at or below"
    assert w4.c1_flag({"v3+iwet_sat_clim": 0.20, "w4_wet": 0.19}, "w4_wet")["flag"] is False


@pytest.mark.parametrize("low, middle, top, flag", [(0.0, 0.01, -0.02, True), (0.0, 0.0, -0.01, True), (-0.01, 0.0, -0.02, False),
                                                     (0.01, 0.02, 0.0, False), (0.01, -0.001, -0.02, False)])
def test_c2_flags_only_a_gain_found_in_the_most_built_up_tercile_alone(low, middle, top, flag):
    tiers = {k: {"point_difference": v} for k, v in (("low", low), ("middle", middle), ("top", top))}
    assert w4.c2_flag(tiers)["flag"] is flag


def test_c3_flags_missingness_that_differs_by_more_than_one_point():
    ok = {c: {"positives": 0.010, "universe_negatives": 0.005} for c in IWET}
    assert w4.c3_flag(ok)["flag"] is False
    bad = {**ok, IWET[1]: {"positives": 0.03, "universe_negatives": 0.005}}
    assert w4.c3_flag(bad)["flag"] is True and w4.c3_flag(bad)["gaps"][IWET[1]] == pytest.approx(0.025)


def test_the_climatological_part_is_saturation_minus_anomaly():
    frame = pd.DataFrame({"iwet_sat_l2": np.array([0.8, np.nan], dtype=np.float32), "iwet_sat_anom_l2": np.array([0.3, 0.1], dtype=np.float32)})
    dev = w4.with_climatology(hd.Development(frame, frame.copy(), {"x": "y"}, {"r": 1}))
    assert dev.samples[w4.CLIM].iloc[0] == pytest.approx(0.5) and np.isnan(dev.universe[w4.CLIM].iloc[1])
    assert dev.column_map[w4.CLIM] == "iwet" and dev.universe_sizes == {"r": 1}


def test_terciles_cut_at_the_rows_own_built_up_values():
    frame = pd.DataFrame({"cell_id": [1, 2, 3, 4, 5, 6, 7]})
    built = pd.Series({1: 0.0, 2: 0.1, 3: 0.2, 4: 0.3, 5: 0.4, 6: 0.5})
    assert w4.terciles(frame, built).tolist() == ["low", "low", "middle", "middle", "top", "top", "unknown"]


PASS = {"stage_one": {"passed": True}}
FAIL = {"stage_one": {"passed": False}}


@pytest.mark.parametrize("args, status", [
    ((None, None, None, 0, None, None), "stage 1 not run"),
    ((FAIL, None, None, 0, None, None), "STOPPED: stage 1 failed"),
    ((PASS, None, None, 0, None, None), "checks not run"),
    ((PASS, {"passed": False}, None, 0, None, None), "STOPPED: a pre-declared check flagged"),
    ((PASS, {"passed": True}, FAIL, 0, None, None), "STOPPED: stage 2"),
    ((PASS, {"passed": True}, PASS, 5, None, None), "seasons scored: 5 of 8"),
    ((PASS, {"passed": True}, PASS, 8, {"passed": False}, None), "preflight not passed"),
    ((PASS, {"passed": True}, PASS, 8, {"passed": True}, None), "READY FOR HELD-OUT LOOK"),
    ((PASS, {"passed": True}, PASS, 8, {"passed": True}, {"decision": {"adopt": False}}), "held-out look taken: v5 not adopted")])
def test_the_status_follows_the_stored_results_in_the_declared_order(args, status):
    got, step = w4.state(*args)
    assert got.startswith(status)
    if status == "READY FOR HELD-OUT LOOK":
        assert step == "python -m aetherguard.hazard.v4_combined heldout --config configs/hazard_v5.yaml"
    if got.startswith("STOPPED"):
        assert step == "none"


def test_the_report_renders_from_stored_results_only():
    metrics = {n: {w4.HEADLINE: {"value": v, "lo": v - 0.02, "hi": v + 0.02}} for n, v in (("C0", 0.1955), ("w4_wet", 0.19))}
    diff = {"point_difference": -0.005, "ci_lo": -0.02, "ci_hi": 0.01}
    result = {"status": "checks not run", "next": "python -m aetherguard.hazard.w4_wetness checks", "spec": "spec.md",
              "probe": {"choice": "iwet", "candidates": [{"candidate": "bucket", "verdict": "passes"}]},
              "tables": {"imerg_days_missing": {"n_missing": 0}, "files": {"a": {"rows": 10, "nan_share": {"x": 0.0}}}},
              "stage1": {"reproduction": {"abs_difference": 0.0}, "comparison": {"metrics": metrics, "difference": diff},
                         "candidates": {"C0": {"n_inputs": 26, "n_trees": 315}, "w4_wet": {"n_inputs": 29, "n_trees": 300}},
                         "stage_one": {"difference": -0.005, "ci": [-0.02, 0.01], "passed": True, "verdict": "includes zero"}},
              "checks": None, "v5": None, "seasons_scored": 0, "preflight": None}
    text = w4.markdown(result)
    assert "**Status: checks not run.**" in text and "| w4_wet | 29 | 300 | 0.1900 [0.1700, 0.2100] |" in text
    assert "w4_wet - C0 = -0.0050" in text and "**passed** (includes zero)" in text and "—" not in text
