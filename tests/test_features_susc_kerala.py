"""Stage 1 of the Kerala two-stage study: labels from the mapped inventory, the two surface forms, the district-blocked
evaluation and the per-cell table (spec 2026-11-17 section 3)."""
import struct

import numpy as np
import pandas as pd
import pytest

from aetherguard.features import susc_kerala as sk
from aetherguard.grid import latlon_to_cell


def _points(lat, lon, nrsc, gsi, new):
    return pd.DataFrame({"lat": lat, "lon": lon, "nrsc": nrsc, "gsi": gsi, "new": new})


def test_labels_count_points_per_cell_and_drop_points_outside_the_universe():
    a, b, outside = latlon_to_cell(10.02, 76.02), latlon_to_cell(10.12, 76.12), latlon_to_cell(12.52, 75.02)
    points = _points([10.02, 10.021, 10.12, 12.52], [76.02, 76.021, 76.12, 75.02],
                     [True, False, False, True], [False, True, True, False], [False, False, False, False])
    labels = sk.cell_labels(points, np.array([a, b, latlon_to_cell(9.5, 77.0)]))
    assert labels.set_index("cell_id").loc[a, "points"] == 2 and labels.set_index("cell_id").loc[b, "points"] == 1
    assert labels["label"].tolist() == [1, 1, 0]
    # cell b holds only a GSI field point: no imagery point, so the imagery-only label leaves it out
    assert labels.set_index("cell_id").loc[b, "imagery_points"] == 0
    assert labels.set_index("cell_id").loc[a, "imagery_points"] == 1
    assert outside not in set(labels["cell_id"])
    assert labels.attrs["dropped_points"] == 1


def test_shapefile_points_are_read_in_record_order(tmp_path):
    path = tmp_path / "p.shp"
    header = struct.pack(">7i", 9994, 0, 0, 0, 0, 0, 0) + struct.pack("<2i", 1000, 1) + b"\0" * 64
    body = b"".join(struct.pack(">2i", i + 1, 10) + struct.pack("<i2d", 1, x, y) for i, (x, y) in enumerate([(76.5, 10.2), (77.0, 9.5)]))
    path.write_bytes(header + body)
    assert sk.read_shp_points(path).tolist() == [[76.5, 10.2], [77.0, 9.5]]
    z = header + struct.pack(">2i", 1, 18) + struct.pack("<i4d", 11, 76.5, 10.2, 0.0, 0.0)      # PointZ: x, y, z, m
    path.write_bytes(z)
    assert sk.read_shp_points(path).tolist() == [[76.5, 10.2]]


def _toy(n=300, seed=0):
    rng = np.random.default_rng(seed)
    x = pd.DataFrame({"slope": rng.normal(size=n), "soil": rng.normal(size=n), sk.RAIN: rng.normal(1000, 200, size=n)})
    logit = 2.0 * x["slope"] + 0.004 * (x[sk.RAIN] - 1000)
    y = (rng.random(n) < 1 / (1 + np.exp(-logit))).astype(int).to_numpy()
    return x, y


def test_the_logistic_surface_clips_to_the_training_range_and_imputes_the_training_median():
    x, y = _toy()
    model = sk.fit_candidate("S_lr", x, y)
    far = pd.DataFrame({"slope": [50.0, x["slope"].max()], "soil": [0.0, 0.0], sk.RAIN: [1000.0, 1000.0]})
    p = model.predict(far)
    assert p[0] == pytest.approx(p[1])                         # beyond the training range is the edge of it
    missing = pd.DataFrame({"slope": [np.nan], "soil": [0.0], sk.RAIN: [1000.0]})
    median = pd.DataFrame({"slope": [x["slope"].median()], "soil": [0.0], sk.RAIN: [1000.0]})
    assert model.predict(missing)[0] == pytest.approx(model.predict(median)[0])


def test_the_surface_holds_the_trigger_at_one_value_for_every_cell():
    x, y = _toy()
    model = sk.fit_candidate("S_gbm", x, y)
    wet, dry = x.assign(**{sk.RAIN: 2000.0}), x.assign(**{sk.RAIN: 100.0})
    assert np.allclose(sk.surface(model, wet, 900.0), sk.surface(model, dry, 900.0))


def test_the_gbm_surface_is_non_decreasing_in_the_trigger():
    x, y = _toy()
    model = sk.fit_candidate("S_gbm", x, y)
    row = x.iloc[[0] * 5].reset_index(drop=True).assign(**{sk.RAIN: [200.0, 600.0, 1000.0, 1400.0, 1800.0]})
    assert np.all(np.diff(model.predict(row)) >= 0)


def test_leave_one_group_out_never_scores_a_group_with_a_model_that_saw_it():
    x, y = _toy(120)
    groups = np.repeat(np.array(["a", "b", "c", "d"]), 30)
    seen = []

    def fit(xf, yf):
        seen.append(set(xf.index))
        return sk.fit_candidate("S_lr", xf, yf)

    oof = sk.group_oof(x, y, groups, fit, rain_ref=None)
    assert np.isfinite(oof).all() and len(seen) == 4
    for g, rows in zip("abcd", seen):
        assert not rows & set(np.flatnonzero(groups == g))


def test_the_group_bootstrap_is_seeded_and_brackets_the_point():
    rng = np.random.default_rng(1)
    y = rng.integers(0, 2, 200)
    score = y + rng.normal(0, 1, 200)
    groups = np.repeat(np.arange(10), 20)
    one = sk.group_bootstrap(y, {"s": score, "b": rng.normal(size=200)}, groups, n=200, seed=5)
    two = sk.group_bootstrap(y, {"s": score, "b": rng.normal(size=200)}, groups, n=200, seed=5)
    assert one["s"]["roc_auc"] == two["s"]["roc_auc"]
    lo, hi = one["s"]["roc_auc"]["ci"]
    assert lo <= one["s"]["roc_auc"]["value"] <= hi


def test_selection_takes_the_higher_auc_and_passes_only_above_the_slope_baseline():
    metrics = {"S_lr": {"roc_auc": {"value": 0.80}}, "S_gbm": {"roc_auc": {"value": 0.82}}, "B_slope": {"roc_auc": {"value": 0.75}}}
    assert sk.select(metrics) == {"selected": "S_gbm", "passed": True, "selected_auc": 0.82, "baseline_auc": 0.75,
                                  "rule": sk.SELECTION_RULE}
    metrics["B_slope"]["roc_auc"]["value"] = 0.83
    assert sk.select(metrics)["passed"] is False


def test_the_cell_table_has_the_surface_everywhere_and_the_ghats_copy_only_in_the_ghats():
    cells = pd.DataFrame({"cell_id": [1, 2, 3], "region": ["western_ghats", "himalaya", "out_of_scope"]})
    table = sk.cell_table(cells, np.array([0.1, 0.5, 0.9]))
    assert list(table.columns) == ["cell_id", *sk.SURFACE_COLUMNS]
    assert table["susc_kerala"].tolist() == [0.1, 0.5, 0.9]
    assert table["susc_kerala_wg"].iloc[0] == 0.1 and table["susc_kerala_wg"].iloc[1:].isna().all()


def test_within_district_skips_a_district_with_one_class_and_scores_the_others():
    oof = pd.DataFrame({"district": ["a"] * 4 + ["b"] * 2, "label": [0, 1, 0, 1, 0, 0],
                        **{f"oof_{k}": [0.1, 0.9, 0.2, 0.8, 0.5, 0.5] for k in sk.SCORES}})
    rows = sk.within_district(oof)
    assert [r["district"] for r in rows] == ["a"] and rows[0]["S_gbm"] == 1.0 and rows[0]["positive"] == 2


def _result(passed):
    entry = {"value": 0.8, "ci": [0.7, 0.9]}
    metric = {"roc_auc": entry, "average_precision": entry}
    auc = {"roc_auc": 0.8, "average_precision": 0.5}
    return {
        "spec": "spec.md", "rain_ref_mm": 1500.0, "bootstrap": {"n": 10},
        "selection": {"selected": "S_gbm", "passed": passed, "selected_auc": 0.82, "baseline_auc": 0.83, "rule": sk.SELECTION_RULE},
        "metrics": {**{k: metric for k in sk.SCORES}, "differences": {"S_gbm-B_slope": metric}},
        "inventory": {"source": "src", "licence": "CC-BY-4.0", "points": 10, "nrsc": 5, "gsi": 4, "new": 1, "gsi_only": 3,
                      "attribute_mismatch_points": 1},
        "cells": {"training": 100, "positive": 30, "points_used": 9, "dropped_points": 1, "dropped_cells": 1},
        "checks": {"reported_surface": {"training_positive_cells": 5, "training_cells": 1000, "kerala": auc,
                                        "training_positive_cells_by_region": {"himalaya": 4, "western_ghats": 1}},
                   "spearman_with_exposure": {k: {"road_density": 0.1, "lc_built": -0.1} for k in ("surface", "reported_surface")},
                   "imagery_only": {"cells": 90, "positive_cells": 25, "left_out_gsi_only_cells": 10, **auc, "slope_roc_auc": 0.8},
                   "full_model_oof": {"S_lr": auc, "S_gbm": auc}}}


def test_the_report_states_a_failed_stage_one_ends_the_study_and_a_passed_one_does_not():
    rows = [{"district": "a", "cells": 4, "positive": 2, **{k: 0.9 for k in sk.SCORES}}]
    failed = sk.markdown(_result(False), rows)
    assert "Stage 1 FAILED" in failed and "no held-out number exists" in failed and "—" not in failed
    assert "Stage 1 passed" in sk.markdown(_result(True), rows)
