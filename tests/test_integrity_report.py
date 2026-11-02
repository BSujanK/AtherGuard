import json

import numpy as np
import pytest
from integrity_helpers import month_lines, write_raw_tree

from aetherguard.integrity import baseline_report as br


def synthetic_raw(tmp_path, n_stations=10, years=(2000, 2001, 2002), seed=0):
    rng = np.random.default_rng(seed)
    stations, texts = [], {}
    for k in range(n_stations):
        sid = f"IN{k:09d}"
        stations.append((sid, 20.0 + 0.1 * k, 75.0, 100.0 + 120.0 * k, f"STATION {k}"))
        text = ""
        for year in years:
            months = {}
            for month, days in enumerate([31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31], start=1):
                wet = rng.random(days) < 0.45
                months[month] = list(np.where(wet, np.round(rng.gamma(0.8, 9.0, days) + 1.0, 1), 0.0))
            text += month_lines(sid, year, months)
        texts[sid] = text
    return write_raw_tree(tmp_path / "ghcnd", stations, texts)


@pytest.fixture
def report_run(tmp_path, isolated_data_root):
    raw = synthetic_raw(tmp_path)
    out = tmp_path / "reports"
    assert br.main(["--raw-dir", str(raw), "--reports-dir", str(out), "--n-boot", "20"]) == 0
    return out, isolated_data_root


def test_pipeline_writes_dataset_splits_and_strict_json_report(report_run):
    out, data = report_run
    integrity = data / "processed" / "integrity"
    assert (integrity / "fault_dataset.parquet").is_file() and (integrity / "fault_dataset_report.json").is_file()
    assert (integrity / "station_splits.json").is_file()
    text = (out / "phase2a_baselines.json").read_text(encoding="utf-8")
    report = json.loads(text, parse_constant=lambda c: pytest.fail(f"non-strict JSON constant {c}"))
    assert set(report["evaluation"]) == {"val", "test"}
    for split in report["evaluation"].values():
        assert set(split["methods"]) == set(br.METHODS)
    assert "\\" not in json.dumps(report["fault_dataset"]["path"]) and not report["fault_dataset"]["path"].startswith("C:")
    md = (out / "phase2a_baselines.md").read_text(encoding="utf-8")
    assert "Recall per fault type" in md and "Real NOAA flags" in md


def test_report_contains_denominators_and_sanity_counts(report_run):
    out, _ = report_run
    report = json.loads((out / "phase2a_baselines.json").read_text(encoding="utf-8"))
    test = report["evaluation"]["test"]["methods"]
    for result in test.values():
        for setting in br.RETENTION_VARIANTS:
            r = result["retention"][setting]
            assert {"numerator", "denominator"} <= set(r) and r["numerator"] <= r["denominator"]
        assert set(result["per_type"]) == set(report["config"]["fault_types"])
    assert test["range_check"]["binary"] and not test["robust_zscore"]["binary"]
    sanity = report["real_flag_sanity"]
    assert sanity["total_flagged_values"] == 0 and set(sanity["methods"]) == set(br.METHODS)
    assert report["l1_real_false_flag_rates"]["rules"]["bounds"]["flagged"] == 0


def test_rerun_reuses_the_dataset_and_is_reproducible(tmp_path, isolated_data_root, report_run):
    out, data = report_run
    first = (out / "phase2a_baselines.json").read_text(encoding="utf-8")
    dataset = data / "processed" / "integrity" / "fault_dataset.parquet"
    stamp = dataset.stat().st_mtime_ns
    raw = tmp_path / "ghcnd"
    assert br.main(["--raw-dir", str(raw), "--reports-dir", str(out), "--n-boot", "20"]) == 0
    assert dataset.stat().st_mtime_ns == stamp
    assert (out / "phase2a_baselines.json").read_text(encoding="utf-8") == first


def test_stale_dataset_is_refused_unless_rebuilt(tmp_path, isolated_data_root, report_run):
    out, _ = report_run
    changed = synthetic_raw(tmp_path / "other", seed=1)   # same stations, different readings
    with pytest.raises(RuntimeError, match="rebuild"):
        br.main(["--raw-dir", str(changed), "--reports-dir", str(out), "--n-boot", "20"])
    assert br.main(["--raw-dir", str(changed), "--reports-dir", str(out), "--n-boot", "20",
                    "--rebuild-dataset"]) == 0


def test_a_different_station_set_is_refused_by_the_frozen_splits(tmp_path, isolated_data_root, report_run):
    out, _ = report_run
    other = synthetic_raw(tmp_path / "more", n_stations=12)
    with pytest.raises(ValueError, match="frozen"):
        br.main(["--raw-dir", str(other), "--reports-dir", str(out), "--n-boot", "20"])


def test_degenerate_intervals_and_unmeasurable_retention_are_labelled():
    assert br._ci([1.0, 1.0]) == " n/a (degenerate)" and br._ci([0.0, 0.0]) == " n/a (degenerate)"
    assert br._ci([0.2, 0.6]) == " [0.20, 0.60]" and br._ci([float("nan"), float("nan")]) == ""
    assert "not measurable at this density" in br._retention_cell(
        {"numerator": 0, "denominator": 0, "retention": float("nan"), "retention_ci": [float("nan")] * 2})
    cell = br._retention_cell({"numerator": 3, "denominator": 4, "retention": 0.75, "retention_ci": [0.25, 1.0]})
    assert cell == "3/4 = 0.750 [0.25, 1.00]"


def test_report_shows_every_retention_variant_and_the_sensitivity_run(report_run):
    out, _ = report_run
    md = (out / "phase2a_baselines.md").read_text(encoding="utf-8")
    for label in ("design-strict", "wide_1neighbour", "uncorroborated (proxy)", "no single number"):
        assert label in md
    report = json.loads((out / "phase2a_baselines.json").read_text(encoding="utf-8"))
    assert report["l1_real_false_flag_rates"]["min_valid_days_per_year"] == 200
    assert report["l1_real_false_flag_rates_min_valid_300"]["min_valid_days_per_year"] == 300


def test_force_splits_rebuilds_the_frozen_split_file(tmp_path, isolated_data_root, report_run):
    _, data = report_run
    path = data / "processed" / "integrity" / "station_splits.json"
    stamp = path.stat().st_mtime_ns
    br.prepare(tmp_path / "ghcnd")                       # reuses the frozen file
    assert path.stat().st_mtime_ns == stamp
    br.prepare(tmp_path / "ghcnd", force_splits=True)    # deliberate rebuild
    assert path.stat().st_mtime_ns != stamp


@pytest.mark.realdata
def test_real_dataset_invariants_and_rule_false_flag_rates():
    import pandas as pd

    from aetherguard.integrity import inject
    inputs = br.prepare()
    table, splits = inputs.table, inputs.splits
    owner = [s for ids in splits.values() for s in ids]
    assert len(owner) == len(set(owner)) == 140            # no station in two splits, all covered
    assert set(table["station"].astype(str)) == set(owner)
    per_station_split = table.groupby("station", observed=True)["split"].nunique()
    assert (per_station_split == 1).all()
    for split in ("train", "val", "test"):
        for name in inject.FAULT_TYPES:
            cell = inputs.dataset_report["splits"][split]["by_type"][name]
            assert cell["episodes"] > 0 and cell["days"] > 0, (split, name)
    in_episode = table["episode_id"] >= 0
    assert table.loc[in_episode, "clean_real"].all()
    rates = br.l1_false_flag_rates(inputs.sset, {"design": br.neighbours.neighbour_table(inputs.sset.meta)})
    for rule in ("bounds", "stuck", "duplicate_block", "l1_flag"):
        assert rates["rules"][rule]["rate"] < 0.01, rule
    assert pd.Series(inputs.dataset_report["splits"]).map(lambda r: r["clean_real_days"]).min() > 0
