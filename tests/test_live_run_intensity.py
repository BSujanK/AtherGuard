"""The W3 live switch: lead 0 scored by a model with rain-intensity inputs read from the complete Late half-hourly days,
the forecast leads by a model without them, the fallback while a day is missing, and the live day fetch."""
from __future__ import annotations

from datetime import date

import lightgbm as lgb
import numpy as np
import pandas as pd
import pytest

from aetherguard.features import imerg_intensity as ii
from aetherguard.hazard.calibration import MonotoneCalibrator
from aetherguard.hazard.model import HazardModel
from aetherguard.ingest import imerg, imerg_hh
from aetherguard.live import run as live_run
from aetherguard.manifest import Manifest

import live_run_helpers as H

IINT = ii.feature_names()
LAG = 1


def intensity_model() -> HazardModel:
    """The tiny test model plus the six intensity inputs, lag 1 on its card."""
    rng = np.random.default_rng(5)
    n = 4000
    acc3 = rng.uniform(0, 320, n)
    frame = pd.DataFrame({"irain_acc_1": acc3 * 0.4, "irain_acc_3": acc3, "irain_acc_7": acc3 * 1.5, "iapi_90": acc3 * 0.7,
                          "inbr_max_acc_1": acc3 * 0.45, "stat_slope_mean": rng.uniform(5, 40, n),
                          **{c: acc3 * 0.1 + rng.uniform(0, 5, n) for c in IINT}}).astype(np.float32)
    y = (acc3 + rng.normal(0, 25, n) > 140).astype(int)
    constraints = [1, 1, 1, 1, 1, 0, *[1] * len(IINT)]
    params = dict(objective="binary", num_leaves=7, min_data_in_leaf=20, learning_rate=0.2, verbosity=-1, seed=1,
                  deterministic=True, force_row_wise=True, monotone_constraints=constraints)
    booster = lgb.train(params, lgb.Dataset(frame, y), num_boost_round=30)
    members = [lgb.train({**params, "seed": 10 + k}, lgb.Dataset(frame, y), num_boost_round=30) for k in range(3)]
    calibrator = MonotoneCalibrator([0.0, 1.0], [0.0, 0.6])
    return HazardModel([*H.MODEL_COLUMNS, *IINT], constraints, booster, 30, members, calibrator,
                       {"intensity": {"group": "iint", "lag_days": LAG, "inputs": IINT}})


def lead0_days(day: date = H.DAY) -> list[date]:
    return ii.window_days([day], LAG)


def write_late_days(root, days, value: float = 4.0) -> None:
    for day in days:
        maps = {name: np.full((imerg.ROWS, imerg.COLS), value * (k + 1), dtype=np.float32) for k, name in enumerate(ii.FIELDS)}
        imerg_hh._write_day(imerg_hh._day_path(root, ii.RUN, day), maps)


def split_deps(tmp_path, fetch=None, **fields) -> live_run.LiveDeps:
    return H.make_deps(model=intensity_model(), forecast_model=H.tiny_model(), forecast_thresholds=H.THRESHOLDS,
                       intensity_root=tmp_path / "imerg_intensity", intensity_fetch=fetch or (lambda run, days, root: {}),
                       **fields)


def test_lead_0_reads_the_lagged_late_days_and_the_leads_use_their_own_model(tmp_path):
    cfg = H.make_cfg(tmp_path)
    write_late_days(tmp_path / "imerg_intensity", lead0_days())
    summary = live_run.run_day(H.DAY, cfg, deps=split_deps(tmp_path))
    assert summary["intensity"]["used"] is True and summary["intensity"]["lag_days"] == LAG
    assert summary["intensity"]["days"] == [d.isoformat() for d in lead0_days()] == ["2026-08-09", "2026-08-10", "2026-08-11"]
    assert summary["model"]["n_columns"] == len(H.MODEL_COLUMNS) + 6 and summary["forecast_model"]["n_columns"] == len(H.MODEL_COLUMNS)
    run_dir = live_run.live_root(cfg) / H.DAY.isoformat()
    d0 = pd.read_parquet(run_dir / "features_D0.parquet")
    expected = ii.cell_features(H.DAY, d0["cell_id"].to_numpy(), tmp_path / "imerg_intensity", ii.RUN, LAG)
    assert np.allclose(d0[IINT].to_numpy(), expected.to_numpy(), equal_nan=True) and np.isfinite(d0[IINT].to_numpy()).all()
    d1 = pd.read_parquet(run_dir / "features_D1.parquet")
    assert not set(IINT) & set(d1.columns)                    # the forecast leads never carry an intensity input
    assert summary["audit"]["total_violations"] == 0, summary["audit"]


def test_a_missing_late_day_scores_lead_0_with_the_forecast_model_and_says_why(tmp_path):
    cfg = H.make_cfg(tmp_path)
    days = lead0_days()
    write_late_days(tmp_path / "imerg_intensity", days[:-1])
    asked = []

    def fetch(run, wanted, root):
        asked.append((run, list(wanted)))
        return {days[-1]: "CMR lists 40 of 48 half-hours"}
    summary = live_run.run_day(H.DAY, cfg, deps=split_deps(tmp_path, fetch))
    assert asked == [(ii.RUN, days)]
    assert summary["intensity"]["used"] is False and "fallback" in summary["intensity"]
    assert "2026-08-11: CMR lists 40 of 48 half-hours" in summary["intensity"]["reason"]
    assert "forecast_model" not in summary and summary["model"]["n_columns"] == len(H.MODEL_COLUMNS)
    d0 = pd.read_parquet(live_run.live_root(cfg) / H.DAY.isoformat() / "features_D0.parquet")
    assert not set(IINT) & set(d0.columns)
    assert summary["audit"]["total_violations"] == 0, summary["audit"]


def test_a_fetch_that_raises_never_stops_the_run(tmp_path):
    def fetch(run, wanted, root):
        raise ConnectionError("network down")
    summary = live_run.run_day(H.DAY, H.make_cfg(tmp_path), deps=split_deps(tmp_path, fetch))
    assert summary["status"] == "complete" and "ConnectionError: network down" in summary["intensity"]["reason"]


def test_a_model_with_intensity_inputs_is_never_the_forecast_lead_model(tmp_path):
    with pytest.raises(live_run.LiveRunError, match="forecast-lead model reads rain-intensity"):
        live_run.run_day(H.DAY, H.make_cfg(tmp_path), deps=H.make_deps(model=intensity_model()))


def test_a_run_without_intensity_inputs_is_unchanged(tmp_path):
    summary = live_run.run_day(H.DAY, H.make_cfg(tmp_path), deps=H.make_deps())
    assert summary["intensity"] == {"used": False, "reason": "the lead-0 model reads no rain-intensity input"}
    assert "forecast_model" not in summary


# --------------------------------------------------------------------------------------------- the live fetch

class NoFetchers:
    def __init__(self, workers):
        self.pool = self.sessions = None

    def close(self):
        pass


def listing(n: int) -> dict:
    return {k: imerg_hh._Listing(f"https://example.invalid/{k}", "V07B", "2026-08-12") for k in range(n)}


def test_the_live_fetch_writes_only_complete_days_and_skips_days_it_has(tmp_path, monkeypatch):
    root = tmp_path / "store"
    have, partial, whole = date(2026, 8, 9), date(2026, 8, 10), date(2026, 8, 11)
    write_late_days(root, [have])
    listed = {partial: listing(47), whole: listing(48)}
    asked = []
    monkeypatch.setattr(imerg_hh, "_Fetchers", NoFetchers)
    monkeypatch.setattr(imerg_hh, "_half_hour_listing", lambda run, day: asked.append(day) or listed[day])
    monkeypatch.setattr(imerg_hh, "_reduce_within_deadline", lambda run, day, found, fetchers, n:
                        {name: np.ones((imerg.ROWS, imerg.COLS), np.float32) for name in (*ii.FIELDS, "n_halfhours")})
    problems = imerg_hh.fetch_complete_days(ii.RUN, [have, partial, whole], root, manifest=Manifest(tmp_path / "m.jsonl", tmp_path))
    assert asked == [partial, whole]                                       # a day with a file is not asked for
    assert problems == {partial: "CMR lists 47 of 48 half-hours"}
    assert imerg_hh._day_path(root, ii.RUN, whole).is_file() and not imerg_hh._day_path(root, ii.RUN, partial).exists()


def test_a_failed_day_is_reported_and_the_others_still_fetched(tmp_path, monkeypatch):
    root, bad, good = tmp_path / "store", date(2026, 8, 10), date(2026, 8, 11)
    monkeypatch.setattr(imerg_hh, "_Fetchers", NoFetchers)
    monkeypatch.setattr(imerg_hh, "_half_hour_listing", lambda run, day: listing(48))

    def reduce(run, day, found, fetchers, n):
        if day == bad:
            raise imerg_hh.DownloadError("HTTP 503")
        return {name: np.ones((imerg.ROWS, imerg.COLS), np.float32) for name in (*ii.FIELDS, "n_halfhours")}
    monkeypatch.setattr(imerg_hh, "_reduce_within_deadline", reduce)
    problems = imerg_hh.fetch_complete_days(ii.RUN, [bad, good], root, manifest=Manifest(tmp_path / "m.jsonl", tmp_path))
    assert list(problems) == [bad] and "HTTP 503" in problems[bad]
    assert imerg_hh._day_path(root, ii.RUN, good).is_file()


def test_a_split_day_is_audited_later_with_the_models_its_run_json_names(tmp_path):
    import json

    from aetherguard.live import audit
    cfg = H.make_cfg(tmp_path)
    write_late_days(tmp_path / "imerg_intensity", lead0_days())
    deps = split_deps(tmp_path)
    live_run.run_day(H.DAY, cfg, deps=deps)
    run_dir = live_run.live_root(cfg) / H.DAY.isoformat()
    record = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    for key, model in (("model", deps.model), ("forecast_model", deps.forecast_model)):
        model.save(tmp_path / key)
        record[key]["dir"] = str(tmp_path / key)
    (run_dir / "run.json").write_text(json.dumps(record), encoding="utf-8")
    context = audit.AuditContext(rescore=True, alert_config=H.ALERT_CONFIG)          # nothing handed in, as from the CLI
    result = audit.audit_day(run_dir, live_run.load_post_rules(cfg, live_run.LiveDeps()), context=context)
    assert result["rescore"]["ran"] and set(result["rescore"]["rows_scored"]) == {"alerts", "risk_D1", "risk_D2", "risk_D3"}
    assert result["total_violations"] == 0, {n: t["examples"] for n, t in result["tables"].items() if t["examples"]}


# ----------------------------------------------------------------------------------------------- promotion

def promotable(tmp_path, adopt: bool):
    """A study whose output directory holds a refitted challenger and a held-out result that adopts it (or not)."""
    from aetherguard.hazard import v4_int as w3
    study = w3.load_study()
    out = w3.output_dir(study)
    model = intensity_model()
    model.save(out / w3.MODEL_SUBDIR / study["challenger"])
    (out / w3.HELDOUT).write_text('{"decision": {"adopt": %s}}' % ("true" if adopt else "false"), encoding="utf-8")
    (out / w3.DEV_RESULTS).write_text('{"candidates": {"%s": {"columns": []}}}' % study["challenger"], encoding="utf-8")
    return study


def test_an_adopted_challenger_is_copied_and_frozen_under_its_own_name(tmp_path, isolated_data_root):
    from aetherguard.hazard import freeze, promote
    from aetherguard.hazard.model import hazard_config
    study = promotable(tmp_path, adopt=True)
    target = promote.promote(study, "model_test_live", configs_dir=tmp_path)
    config = tmp_path / "hazard_model_test_live.yaml"
    assert hazard_config(config)["model_dir"] == "model_test_live" and target.name == "model_test_live"
    assert freeze.verify_freeze(target, freeze.default_external_files(config))["external_files"]
    assert HazardModel.load(target).columns == [*H.MODEL_COLUMNS, *IINT]
    with pytest.raises(FileExistsError):
        promote.promote(study, "model_test_live", configs_dir=tmp_path)


def test_a_challenger_its_look_did_not_adopt_is_never_promoted(tmp_path, isolated_data_root):
    from aetherguard.hazard import promote
    with pytest.raises(promote.NotAdoptedError):
        promote.promote(promotable(tmp_path, adopt=False), "model_test_live", configs_dir=tmp_path)
