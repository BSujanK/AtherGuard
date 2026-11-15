"""W7: the forecast leads scored by a model with rain-intensity inputs (`lead_model_config`), their intensity from the
Late days, the Early day D and the GFS forecast days, the fallback to the incumbent, and the ensemble expected risk."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from aetherguard.features import imerg_intensity as ii
from aetherguard.ingest import imerg, imerg_hh
from aetherguard.ingest.ecmwf import EcmwfForecast
from aetherguard.live import forecast_choice as fc
from aetherguard.live import lead_intensity as li
from aetherguard.live import run as live_run
from aetherguard.live.sources import SourceStatus

import live_run_helpers as H
from test_live_run_intensity import IINT, intensity_model, lead0_days, write_late_days

SHAPE = (imerg.ROWS, imerg.COLS)


class Identity:
    def apply(self, source, offset, field):
        return np.asarray(field, dtype=np.float32)


def gfs_maps(value: float = 3.0) -> dict:
    return {name: np.full(SHAPE, value * (k + 1), dtype=np.float32) for k, name in enumerate(ii.FIELDS)}


def lead_days(day: date = H.DAY) -> list[date]:
    """Every Late day the forecast leads read before D (D-2 and D-1); lead 0 needs D-3..D-1."""
    return [day - timedelta(days=2), day - timedelta(days=1)]


def write_early_day(root, day: date, value: float = 5.0) -> None:
    maps = {name: np.full(SHAPE, value * (k + 1), dtype=np.float32) for k, name in enumerate(ii.FIELDS)}
    imerg_hh._write_day(imerg_hh._day_path(root, li.EARLY, day), maps)


def sources_factory(root, gfs_missing: bool = False):
    def make(day, gfs):
        forecast = {} if gfs_missing else {day + timedelta(days=k): gfs_maps(3.0 * k) for k in (1, 2)}
        return li.LeadSources(late_root=root, early_root=root, gfs=lambda d: forecast.get(d), maps=Identity())
    return make


def v4_leads_deps(tmp_path, **fields) -> live_run.LiveDeps:
    root = tmp_path / "imerg_intensity"
    write_late_days(root, lead0_days())
    write_early_day(root, H.DAY)
    model = intensity_model()
    return H.make_deps(**{"model": model, "forecast_model": model, "incumbent_model": H.tiny_model(),
                          "incumbent_thresholds": H.THRESHOLDS, "intensity_root": root,
                          "intensity_fetch": lambda run, days, root: {}, "lead_sources": sources_factory(root), **fields})


def test_the_forecast_leads_read_their_own_intensity_window(tmp_path):
    cfg = H.make_cfg(tmp_path)
    deps = v4_leads_deps(tmp_path)
    summary = live_run.run_day(H.DAY, cfg, deps=deps)
    assert summary["lead_intensity"]["used"] is True
    assert summary["lead_intensity"]["leads"]["3"]["days"] == {"2026-08-12": "early_live", "2026-08-13": "gfs3h",
                                                                "2026-08-14": "gfs3h"}
    assert "forecast_model" not in summary                     # one model for every lead
    run_dir = live_run.live_root(cfg) / H.DAY.isoformat()
    for lead in (1, 2, 3):
        features = pd.read_parquet(run_dir / f"features_D{lead}.parquet")
        sources = sources_factory(tmp_path / "imerg_intensity")(H.DAY, None)
        expected, _ = li.lead_frame(H.DAY, lead, features["cell_id"].to_numpy(), sources)
        assert np.allclose(features[IINT].to_numpy(), expected.to_numpy()) and np.isfinite(features[IINT].to_numpy()).all()
    assert summary["audit"]["total_violations"] == 0, summary["audit"]


def test_a_missing_forecast_intensity_day_scores_every_lead_with_the_incumbent(tmp_path):
    cfg = H.make_cfg(tmp_path)
    deps = v4_leads_deps(tmp_path, lead_sources=sources_factory(tmp_path / "imerg_intensity", gfs_missing=True))
    summary = live_run.run_day(H.DAY, cfg, deps=deps)
    info = summary["lead_intensity"]
    assert info["used"] is False and "2026-08-13 (gfs3h)" in info["reason"]
    assert summary["forecast_model"]["n_columns"] == len(H.MODEL_COLUMNS)        # the incumbent scored the leads
    assert summary["model"]["n_columns"] == len(H.MODEL_COLUMNS) + 6              # lead 0 kept its own model
    features = pd.read_parquet(live_run.live_root(cfg) / H.DAY.isoformat() / "features_D1.parquet")
    assert not set(IINT) & set(features.columns)
    assert summary["audit"]["total_violations"] == 0, summary["audit"]


def test_a_missing_lead_0_day_scores_lead_0_and_the_leads_with_the_incumbent(tmp_path):
    cfg = H.make_cfg(tmp_path)
    root = tmp_path / "imerg_intensity"
    deps = v4_leads_deps(tmp_path)
    imerg_hh._day_path(root, ii.RUN, lead0_days()[0]).unlink()
    summary = live_run.run_day(H.DAY, cfg, deps=deps)
    assert summary["model"]["n_columns"] == len(H.MODEL_COLUMNS) and "forecast_model" not in summary
    assert summary["lead_intensity"]["used"] is False
    assert summary["audit"]["total_violations"] == 0, summary["audit"]


def test_an_intensity_lead_model_needs_its_lead_sources(tmp_path):
    with pytest.raises(live_run.LiveRunError, match="forecast-lead model reads rain-intensity"):
        live_run.run_day(H.DAY, H.make_cfg(tmp_path), deps=H.make_deps(model=H.tiny_model(), forecast_model=intensity_model()))


# ------------------------------------------------------------------------------------------- expected risk

class FakeEcmwf:
    name = "ecmwf"

    def __init__(self, day: date = H.DAY) -> None:
        rows, cols = np.indices(SHAPE)
        mean = np.full((3,) + SHAPE, 4.0, dtype=np.float32)            # D+1 as GFS has it: the audit chains lead 2 to lead 1
        mean[1][H.heavy_mask(rows, cols)] = H.HEAVY_MM
        cycle = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
        valid = np.array([True, True, True])
        self.forecast = EcmwfForecast(hres=mean.copy(), ens_mean=mean, ens_p10=mean * 0.2, ens_p50=mean * 0.8,
                                      ens_p90=mean * 2.5, hres_valid=valid, ens_valid=valid, hres_cycle=cycle,
                                      ens_cycle=cycle, n_members=51)

    def fetch(self, ctx) -> SourceStatus:
        cycle = self.forecast.ens_cycle
        return SourceStatus("ecmwf", True, H.imd_day_end(ctx.day + timedelta(days=3)), cycle + timedelta(hours=8.2), 8.2, None)

    def load(self, ctx):
        return self.forecast


def ensemble_choice() -> fc.ForecastChoice:
    mean = fc.Config("ecmwf_ens_mean", False)
    return fc.ForecastChoice({1: fc.Config("gfs", False), 2: mean, 3: mean}, fallback=fc.Config("gfs", False))


def test_expected_risk_is_the_weighted_mean_over_the_ensemble_scenarios(tmp_path):
    cfg = H.make_cfg(tmp_path)
    deps = v4_leads_deps(tmp_path, sources={**H.healthy_sources(), "ecmwf": FakeEcmwf()}, choice=ensemble_choice(),
                         expected_risk=True)
    summary = live_run.run_day(H.DAY, cfg, deps=deps)
    run_dir = live_run.live_root(cfg) / H.DAY.isoformat()
    assert summary["leads"]["1"]["expected_risk"] is None                         # GFS: one deterministic field
    info = summary["leads"]["2"]["expected_risk"]
    assert info["scenarios"] == ["p10", "p50", "p90"] and info["weights"] == [0.3, 0.4, 0.3]
    scenarios = pd.read_parquet(run_dir / "scenarios_D2.parquet")
    risk = pd.read_parquet(run_dir / "risk_D2.parquet").set_index("cell_id")["risk"]
    expected = sum(w * deps.forecast_model.score(part.drop(columns=["scenario", "weight"]).reset_index(drop=True))["risk"]
                   .set_axis(part["cell_id"].to_numpy()) for (name, w), part in scenarios.groupby(["scenario", "weight"]))
    scored = risk.dropna()
    assert np.allclose(scored.to_numpy(), expected.reindex(scored.index).to_numpy(), rtol=1e-9)
    point = deps.forecast_model.score(pd.read_parquet(run_dir / "features_D2.parquet"))["risk"].to_numpy()
    assert not np.allclose(np.sort(point), np.sort(risk.to_numpy()))            # not the model at the mean
    assert summary["audit"]["total_violations"] == 0, summary["audit"]
