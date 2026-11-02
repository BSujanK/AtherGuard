import json
import os
import stat

import numpy as np
import pandas as pd
import pytest
from integrity_helpers import synthetic_set

from aetherguard.grid import cell_center, latlon_to_cell
from aetherguard.integrity import hazard_features as hf
from aetherguard.integrity.neighbours import haversine_km

NAN = np.nan
INDEX = pd.date_range("2010-01-01", periods=12, freq="D").as_unit("ns")
CELL = (20.0, 75.0)
# station coordinates: A on the cell, B ~50 km north, C ~166 km (outside 100 km), D ~445 km (beyond 300 km)
COORDS = {"A": (20.0, 75.0), "B": (20.45, 75.0), "C": (21.5, 75.0), "D": (24.0, 75.0)}


def make_days(value=None, trust=None, flagged=None, genuine=None, ids=("A", "B", "C", "D")):
    n, m = len(INDEX), len(ids)
    shape = (n, m)
    return hf.StationDays(
        INDEX, list(ids), np.array([COORDS[s][0] for s in ids]), np.array([COORDS[s][1] for s in ids]),
        np.full(shape, NAN) if value is None else np.asarray(value, float),
        np.full(shape, NAN) if trust is None else np.asarray(trust, float),
        np.zeros(shape, bool) if flagged is None else np.asarray(flagged, bool),
        np.zeros(shape, bool) if genuine is None else np.asarray(genuine, bool))


def feats(sd, day=6, rain1=5.0):
    return hf.integ_features(sd, [CELL[0]], [CELL[1]], [INDEX[day]], [rain1]).iloc[0]


def dist(a, b):
    return float(haversine_km(*COORDS[a], *COORDS[b]))


def test_idw_trust_weighting_hand_calculation():
    value = np.full((12, 4), NAN)
    trust = np.full((12, 4), NAN)
    value[6] = [10.0, 30.0, 99.0, 99.0]
    trust[6] = [0.5, 1.0, 1.0, 1.0]
    sd = make_days(value, trust)
    row = feats(sd)
    d_b = dist("A", "B")
    w_a, w_b = 0.5 / 1.0 ** 2, 1.0 / d_b ** 2          # A sits on the cell: the distance is floored at 1 km
    expected = (w_a * 10.0 + w_b * 30.0) / (w_a + w_b)
    assert row["integ_trw_rain_1"] == pytest.approx(expected, rel=1e-5)
    assert row["integ_n_st_100km"] == 2 and row["integ_frac_trusted_100km"] == 1.0
    assert row["integ_max_st_rain_1_100km"] == 30.0
    assert row["integ_st_minus_grid_1"] == pytest.approx(expected - 5.0, rel=1e-5)
    assert row["integ_dist_nearest_km"] == pytest.approx(0.0, abs=1e-6)
    assert row.index.tolist() == hf.COLUMNS


def test_stations_outside_100_km_are_not_used_but_count_for_the_nearest_distance_within_300_km():
    value = np.full((12, 4), NAN)
    trust = np.full((12, 4), NAN)
    value[6, 2] = 80.0                                     # C only: 166 km away
    trust[6, 2] = 1.0
    row = feats(make_days(value, trust))
    assert row["integ_n_st_100km"] == 0 and np.isnan(row["integ_trw_rain_1"]) and np.isnan(row["integ_frac_trusted_100km"])
    assert np.isnan(row["integ_max_st_rain_1_100km"]) and np.isnan(row["integ_st_minus_grid_1"])
    assert row["integ_dist_nearest_km"] == pytest.approx(dist("A", "C"), rel=1e-5)
    value[6] = [NAN, NAN, NAN, 7.0]                         # D only: 445 km, beyond 300 km
    trust[6] = [NAN, NAN, NAN, 1.0]
    assert np.isnan(feats(make_days(value, trust))["integ_dist_nearest_km"])


def test_nan_rules_counts_are_zero_and_never_nan_and_no_station_gives_nan_not_zero():
    row = feats(make_days())
    assert row["integ_n_st_100km"] == 0 and row["integ_n_flagged_100km_7d"] == 0
    assert all(np.isnan(row[c]) for c in ("integ_frac_trusted_100km", "integ_trw_rain_1", "integ_trw_rain_3",
                                          "integ_st_minus_grid_1", "integ_max_st_rain_1_100km", "integ_dist_nearest_km"))
    out = hf.integ_features(make_days(), [CELL[0]], [CELL[1]], [INDEX[6]], [NAN])
    assert all(out[c].dtype == np.float32 for c in hf.COLUMNS)


def test_flagged_readings_are_excluded_from_rain_but_counted_in_fraction_and_the_7_day_count():
    value = np.full((12, 4), NAN)
    trust = np.full((12, 4), NAN)
    flagged = np.zeros((12, 4), bool)
    value[6], trust[6] = [10.0, 500.0, NAN, NAN], [0.9, 0.1, NAN, NAN]
    flagged[6, 1] = True                                    # B reads 500 mm but is flagged
    flagged[3, 1] = True                                    # earlier flagged readings inside D-6..D
    value[3, 1], trust[3, 1] = 4.0, 0.2
    flagged[5, 0] = True
    value[5, 0], trust[5, 0] = 2.0, 0.3
    flagged[2, 1] = True                                    # day D-4: still inside the window
    value[2, 1], trust[2, 1] = 4.0, 0.2
    flagged[0, 1] = True                                    # day D-6 is inside (D-6..D)... index 0 is 6 days earlier
    value[0, 1], trust[0, 1] = 4.0, 0.2
    row = feats(make_days(value, trust, flagged))
    assert row["integ_trw_rain_1"] == pytest.approx(10.0) and row["integ_max_st_rain_1_100km"] == 10.0
    assert row["integ_n_st_100km"] == 2 and row["integ_frac_trusted_100km"] == pytest.approx(0.5)
    assert row["integ_n_flagged_100km_7d"] == 5             # B: days 0, 2, 3, 6; A: day 5
    later = feats(make_days(value, trust, flagged), day=7)
    assert later["integ_n_flagged_100km_7d"] == 4           # day 0 drops out of the 7-day window


def test_retained_genuine_extremes_count_with_full_weight_even_when_their_trust_is_low():
    value = np.full((12, 4), NAN)
    trust = np.full((12, 4), NAN)
    value[6], trust[6] = [10.0, 200.0, NAN, NAN], [1.0, 0.05, NAN, NAN]
    genuine = np.zeros((12, 4), bool)
    genuine[6, 1] = True                                    # not flagged (the arbiter retained it), trust is low
    row = feats(make_days(value, trust, genuine=genuine))
    d_b = dist("A", "B")
    w_a, w_b = 1.0, 1.0 / d_b ** 2
    assert row["integ_trw_rain_1"] == pytest.approx((w_a * 10.0 + w_b * 200.0) / (w_a + w_b), rel=1e-5)
    assert row["integ_max_st_rain_1_100km"] == 200.0


def test_three_day_total_needs_all_three_days_usable_and_uses_mean_trust():
    value = np.full((12, 4), NAN)
    trust = np.full((12, 4), NAN)
    value[4:7, 0], trust[4:7, 0] = [1.0, 2.0, 3.0], [1.0, 0.5, 0.0]
    value[4:7, 1], trust[4:7, 1] = [6.0, NAN, 9.0], [1.0, NAN, 1.0]       # B misses a day: no 3-day total
    row = feats(make_days(value, trust))
    assert row["integ_trw_rain_3"] == pytest.approx(6.0)     # only A's total (1 + 2 + 3), weight irrelevant alone
    value[5, 1], trust[5, 1] = 3.0, 1.0
    both = feats(make_days(value, trust))
    d_b = dist("A", "B")
    w_a = ((1.0 + 0.5 + hf.MIN_TRUST) / 3) / 1.0
    w_b = 1.0 / d_b ** 2
    assert both["integ_trw_rain_3"] == pytest.approx((w_a * 6.0 + w_b * 18.0) / (w_a + w_b), rel=1e-5)


def test_features_at_day_d_do_not_change_when_later_data_changes():
    rng = np.random.default_rng(0)
    value = rng.gamma(0.8, 10.0, (12, 4))
    trust = rng.random((12, 4))
    flagged = rng.random((12, 4)) < 0.2
    genuine = rng.random((12, 4)) < 0.1
    base = make_days(value, trust, flagged, genuine)
    days = [INDEX[3], INDEX[5], INDEX[6]]
    before = hf.integ_features(base, [CELL[0]] * 3, [CELL[1]] * 3, days, [5.0] * 3)
    value2, trust2, flagged2, genuine2 = value.copy(), trust.copy(), flagged.copy(), genuine.copy()
    value2[7:], trust2[7:], flagged2[7:], genuine2[7:] = 999.0, 0.0, ~flagged[7:], ~genuine[7:]
    after = hf.integ_features(make_days(value2, trust2, flagged2, genuine2), [CELL[0]] * 3, [CELL[1]] * 3, days, [5.0] * 3)
    pd.testing.assert_frame_equal(before, after)
    changed = hf.integ_features(make_days(value2, trust2, flagged2, genuine2), [CELL[0]], [CELL[1]], [INDEX[9]], [5.0])
    assert not changed.equals(hf.integ_features(base, [CELL[0]], [CELL[1]], [INDEX[9]], [5.0]))


def test_causal_flags_remove_the_retroactive_l1_look_ahead():
    dates = pd.date_range("2010-01-01", periods=20).as_unit("ns")

    def frame(station, flagged, l1, reasons, l1_reason):
        return pd.DataFrame({"station": station, "date": dates, "flagged": flagged, "l1_flag": l1,
                             "reasons": reasons, "l1_reason": l1_reason})

    stuck = np.zeros(20, bool)
    stuck[2:6] = True                                      # a 4-day streak flagged by L1 only
    a = frame("A", stuck, stuck, np.where(stuck, "l1:stuck", ""), np.where(stuck, "stuck", ""))
    dup = np.zeros(20, bool)
    dup[1:10] = True                                       # a 9-day duplicate block
    b = frame("B", dup, dup, np.where(dup, "l1:duplicate_block", ""), np.where(dup, "duplicate_block", ""))
    bounds = np.zeros(20, bool)
    bounds[4] = True
    c = frame("C", bounds, bounds, np.where(bounds, "l1:bounds", ""), np.where(bounds, "bounds", ""))
    modelled = np.zeros(20, bool)
    modelled[2:5] = True                                   # model flags are causal: unchanged
    d = frame("D", modelled, modelled, np.where(modelled, "model;l1:stuck", ""), np.where(modelled, "stuck", ""))
    oof = pd.concat([a, b, c, d], ignore_index=True)
    causal = hf.causal_flags(oof)
    by = {s: causal[oof["station"] == s].to_numpy() for s in "ABCD"}
    assert by["A"].tolist() == [False] * 4 + [True, True] + [False] * 14       # days 2,3 are not yet confirmed
    assert np.flatnonzero(by["B"]).tolist() == [7, 8, 9]                        # the block is confirmed on its 7th day
    assert np.flatnonzero(by["C"]).tolist() == [4]
    assert np.flatnonzero(by["D"]).tolist() == [2, 3, 4]


def make_oof(station_set, station="IN000000001"):
    rows = []
    for sid in station_set.values.columns:
        v = station_set.values[sid]
        ok = v.notna().to_numpy()
        rows.append(pd.DataFrame({"station": sid, "date": v.index, "trust": np.where(ok, 0.9, NAN), "p_fault": np.where(ok, 0.1, NAN),
                                  "fault_type": "", "flagged": False, "genuine_extreme": False,
                                  "repaired": np.where(ok, 123456.0, NAN), "repaired_lo": NAN, "repaired_hi": NAN,
                                  "reasons": "", "l1_flag": False, "l1_reason": "", "fold": np.int8(0)}))
    return pd.concat(rows, ignore_index=True)


def tiny_world(tmp_path):
    n = 40
    rng = np.random.default_rng(1)
    sset = synthetic_set({"IN000000001": rng.gamma(0.8, 8.0, n), "IN000000002": rng.gamma(0.8, 8.0, n)}, start="2010-01-01",
                         meta_rows={"IN000000001": (20.0, 75.0, 100.0), "IN000000002": (20.2, 75.0, 100.0)})
    oof = make_oof(sset)
    features_dir = tmp_path / "features"
    features_dir.mkdir()
    cell = int(latlon_to_cell(20.0, 75.0))
    files = {}
    for name, count in (("a_features.parquet", 6), ("b_features.parquet", 4)):
        dates = pd.to_datetime(["2010-01-05", "2010-01-20", "2010-02-01", "2010-01-05", "2010-02-05", "2010-01-31"][:count])
        table = pd.DataFrame({"cell_id": np.array([cell, cell + 1, cell, cell + 5, cell, cell + 1][:count], dtype=np.int64),
                              "date": dates.as_unit("ns"), "region": "western_ghats", "label": [1, 0, 0, 1, 0, 0][:count],
                              "rain_acc_1": np.linspace(0, 20, count).astype(np.float32)})
        table.to_parquet(features_dir / name, index=False)
        files[name] = {"sha256": "x"}
    (features_dir / "features_manifest.json").write_text(json.dumps({"files": files}), encoding="utf-8")
    oof_path = tmp_path / "oof.parquet"
    oof.to_parquet(oof_path, index=False)
    return sset, oof, features_dir, oof_path


def test_station_days_never_use_repaired_values(tmp_path):
    sset, oof, features_dir, oof_path = tiny_world(tmp_path)
    a = hf.station_days(oof, sset.values, sset.meta)
    b = hf.station_days(oof.assign(repaired=-5.0), sset.values, sset.meta)
    np.testing.assert_array_equal(a.value, b.value)
    assert not hasattr(a, "repaired") and np.nanmax(a.value) < 1000
    assert a.value.shape == a.trust.shape == a.flagged.shape == (40, 2)


def test_build_keeps_keys_and_row_order_and_adds_float32_integ_columns(tmp_path):
    sset, oof, features_dir, oof_path = tiny_world(tmp_path)
    out = tmp_path / "integ"
    manifest, reused = hf.build_integ(features_dir, out, oof_path, station_set=sset)
    assert not reused and manifest["frozen"] is True
    for name in ("a_features.parquet", "b_features.parquet"):
        base = pd.read_parquet(features_dir / name)
        made = pd.read_parquet(out / hf.integ_name(name))
        assert list(made.columns) == ["cell_id", "date"] + hf.COLUMNS
        assert made[["cell_id", "date"]].equals(base[["cell_id", "date"]])
        assert all(made[c].dtype == np.float32 for c in hf.COLUMNS)
    made = pd.read_parquet(out / "a_integ.parquet")
    assert made["integ_n_st_100km"].iloc[0] == 2 and made["integ_n_st_100km"].iloc[3] == 2
    far = made["integ_n_st_100km"] == 0
    assert far.sum() == 0
    assert json.loads((out / "integ_columns.json").read_text(encoding="utf-8")) == {c: "integ" for c in hf.COLUMNS}
    report = json.loads((out / "integ_report.json").read_text(encoding="utf-8"))
    assert report["files"]["a_integ.parquet"]["columns"]["integ_trw_rain_1"]["nan_share"] == 0.0
    assert "by_region" in report["files"]["a_integ.parquet"]
    positives = report["files"]["a_integ.parquet"]["by_region"]["western_ghats"]["positives"]
    assert positives["rows"] == 2 and positives["share_with_station_100km"] == 1.0
    for f in out.iterdir():
        assert not os.access(f, os.W_OK)


def test_second_build_verifies_and_reuses_and_tampering_is_detected(tmp_path):
    sset, oof, features_dir, oof_path = tiny_world(tmp_path)
    out = tmp_path / "integ"
    hf.build_integ(features_dir, out, oof_path, station_set=sset)
    again, reused = hf.build_integ(features_dir, out, oof_path, station_set=sset)
    assert reused and again["files"].keys()
    target = out / "a_integ.parquet"
    os.chmod(target, stat.S_IWRITE | stat.S_IREAD)
    pd.read_parquet(target).assign(integ_trw_rain_1=1.0).to_parquet(target, index=False)
    with pytest.raises(hf.IntegIntegrityError, match="checksum"):
        hf.build_integ(features_dir, out, oof_path, station_set=sset)
    rebuilt, reused = hf.build_integ(features_dir, out, oof_path, force=True, station_set=sset)
    assert not reused
    assert hf.verify_integ(out, features_dir, oof_path)["ok"]
    pd.read_parquet(oof_path).assign(trust=0.5).to_parquet(oof_path, index=False)    # an input changed
    assert not hf.verify_integ(out, features_dir, oof_path)["ok"]


def test_cell_coordinates_are_the_cell_centres():
    cell = int(latlon_to_cell(11.51, 76.13))
    lat, lon = hf.cell_coordinates([cell])
    assert (float(lat[0]), float(lon[0])) == pytest.approx(cell_center(cell))


@pytest.mark.realdata
def test_real_integ_files_match_the_frozen_features_keys_and_order():
    features_dir = hf.default_features_dir()
    out = features_dir / "integ"
    result = hf.verify_integ(out, features_dir, hf.integrity_dir() / "engine_outputs_2007_oof.parquet")
    assert result["ok"], result["problems"]
    manifest = json.loads((out / hf.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert len(manifest["feature_files"]) == 9
