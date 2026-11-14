"""The second-opinion rain check of the live run uses the newest IMD real-time day due by the run time (spec 2026-10-14
section 5, IMD latency about a day): a day still inside its declared latency is not a degradation, a later one is."""
import json
from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from aetherguard.live import audit
from aetherguard.live import run as live_run
from aetherguard.live.sources import ImdRealtimeSource

import live_run_helpers as H

D1 = H.DAY - timedelta(days=1)


def run_dir(cfg):
    return live_run.live_root(cfg) / H.DAY.isoformat()


def imd_until(last, heavy_mm=60.0):
    """IMD real-time files for every day up to `last` (None: none at all), as the server answers."""
    def post(day, timeout):
        return None if last is None or day > last else H.imd_grid_bytes(heavy_mm)
    return post


def run_with_imd(tmp_path, post, days=4, **cfg_overrides):
    cfg = H.make_cfg(tmp_path, **cfg_overrides)
    sources = H.healthy_sources()
    sources["imd_rt"] = ImdRealtimeSource(days=days, timeout_s=1, attempts=1, latency_h=24, post=post)
    summary = live_run.run_day(H.DAY, cfg, deps=H.make_deps(sources))
    alerts = pd.read_parquet(run_dir(cfg) / "alerts.parquet")
    features = pd.read_parquet(run_dir(cfg) / "features_D0.parquet")
    text = (live_run.project_path(cfg["report_dir"]) / f"{H.DAY}.md").read_text(encoding="utf-8")
    return cfg, summary, alerts, features, text


def test_day_d_not_published_yet_is_not_a_degradation(tmp_path):
    cfg, summary, alerts, features, text = run_with_imd(tmp_path, imd_until(D1))
    assert not alerts["confidence_causes"].str.contains("imd_missing").any()
    assert (alerts["confidence"] == "High").any()
    record = summary["second_opinion"]
    assert record["check_day"] == D1.isoformat() and record["due_day"] == D1.isoformat() and record["lag_days"] == 1
    assert record["window"] == [(D1 - timedelta(days=2)).isoformat(), D1.isoformat()]
    assert record["days_present"] == [(D1 - timedelta(days=k)).isoformat() for k in (2, 1, 0)]
    assert record["state"] == "on_time" and record["latency_h"] == 24
    assert summary["sources"]["imd_rt"]["state"] == "ok" and "imd_rt" not in summary["late_sources"]
    # the day-D columns stay what they are (no IMD file of D), the check columns hold D-1's comparison
    row = H.wayanad_row(features)
    assert np.isnan(row["src_imd_acc_1"]) and row["chk_imd_acc_1"] == pytest.approx(60.0)
    assert row["chk_lag_days"] == 1
    assert "second opinion" in text.lower() and D1.isoformat() in text


def test_imd_later_than_its_latency_degrades_every_cell_and_says_why(tmp_path):
    cfg, summary, alerts, features, text = run_with_imd(tmp_path, imd_until(H.DAY - timedelta(days=2)))
    assert (alerts["confidence"] == "Degraded").all() and alerts["confidence_causes"].str.contains("imd_missing").all()
    record = summary["second_opinion"]
    assert record["check_day"] is None and record["due_day"] == D1.isoformat() and record["state"] == "late"
    assert summary["sources"]["imd_rt"]["state"] == "late"
    assert features["chk_imd_acc_1"].isna().all() and features["chk_lag_days"].isna().all()
    failed = text.split("## Failed / missing sources")[1].split("## Alerts by lead")[0]
    assert "`imd_rt`" in failed and "later than its declared latency" in failed


def test_no_imd_at_all_is_missing(tmp_path):
    cfg, summary, alerts, _, _ = run_with_imd(tmp_path, imd_until(None))
    assert (alerts["confidence"] == "Degraded").all() and alerts["confidence_causes"].str.contains("imd_missing").all()
    assert summary["second_opinion"]["state"] == "missing" and summary["second_opinion"]["check_day"] is None


def test_a_published_day_d_is_used_when_it_is_there(tmp_path):
    _, summary, alerts, features, _ = run_with_imd(tmp_path, imd_until(H.DAY))
    assert summary["second_opinion"]["check_day"] == H.DAY.isoformat() and summary["second_opinion"]["lag_days"] == 0
    row = H.wayanad_row(features)
    assert row["chk_imd_acc_1"] == row["src_imd_acc_1"] and row["chk_dis_ratio_3"] == row["src_dis_ratio_3"]


def test_a_disagreeing_second_opinion_still_degrades(tmp_path):
    # IMD shows almost nothing where IMERG has heavy rain: the sources disagree on the check window
    _, _, alerts, _, _ = run_with_imd(tmp_path, imd_until(D1, heavy_mm=0.0))
    row = H.wayanad_row(alerts)
    assert row["confidence"] == "Degraded" and "sources_disagree" in row["confidence_causes"]


def test_the_audit_rederives_confidence_and_catches_a_tampered_cause(tmp_path):
    cfg, summary, alerts, _, _ = run_with_imd(tmp_path, imd_until(D1))
    assert summary["audit"]["total_violations"] == 0
    rules = live_run.load_post_rules(cfg, live_run.LiveDeps())
    clean = audit.audit_day(run_dir(cfg), rules)
    assert clean["violations"]["confidence"] == 0 and clean["tables"]["alerts"]["checked"]["confidence"]
    tampered = alerts.copy()
    i = int(np.flatnonzero((tampered["confidence"] == "High").to_numpy())[0])
    tampered.loc[i, "confidence"], tampered.loc[i, "confidence_causes"] = "Degraded", "imd_missing"
    tampered.to_parquet(run_dir(cfg) / "alerts.parquet", index=False)
    d0 = pd.read_parquet(run_dir(cfg) / "risk_D0.parquet")
    d0.loc[d0["cell_id"] == tampered.loc[i, "cell_id"], ["confidence", "confidence_causes"]] = ["Degraded", "imd_missing"]
    d0.to_parquet(run_dir(cfg) / "risk_D0.parquet", index=False)
    found = audit.audit_day(run_dir(cfg), rules)
    assert found["violations"]["confidence"] >= 1
    whys = [e["why"] for e in found["tables"]["alerts"]["examples"]["confidence"]]
    assert any("re-derived" in w for w in whys)
