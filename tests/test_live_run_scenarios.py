"""Section 12 in the daily run: forecast rain from ECMWF or GFS per lead, the dry / forecast / wet scenarios and the certainty
fields of the forecast rows, and the audit of them. Synthetic sources (tests/live_run_helpers.py); no network."""
import numpy as np
import pandas as pd
import pytest

from aetherguard.ingest import ecmwf, imerg
from aetherguard.live import audit
from aetherguard.live import forecast_choice as fc
from aetherguard.live import postrules as pr
from aetherguard.live import run as live_run
from aetherguard.live import sources as S

import live_run_helpers as H

CYCLE = H.NOW.replace(hour=0) - pd.Timedelta(hours=6)            # the 18Z run of D-1


def run_dir(cfg):
    return live_run.live_root(cfg) / H.DAY.isoformat()


def lead_table(cfg, lead):
    return pd.read_parquet(run_dir(cfg) / f"risk_D{lead}.parquet")


def write_ecmwf(root, heavy_hres_leads=(), heavy_p90_leads=(), valid=(True, True, True), ens_valid=None):
    """An ECMWF day file: light rain everywhere; heavy HRES rain near Wayanad on `heavy_hres_leads`, a heavy ensemble p90 there
    on `heavy_p90_leads`."""
    rows, cols = np.indices((imerg.ROWS, imerg.COLS))
    near = H.heavy_mask(rows, cols)
    hres = np.full((3, imerg.ROWS, imerg.COLS), 4.0, np.float32)
    mean = np.full_like(hres, 4.0)
    p90 = np.full_like(hres, 6.0)
    for lead in heavy_hres_leads:
        hres[lead - 1][near] = H.HEAVY_MM
    for lead in heavy_p90_leads:
        p90[lead - 1][near] = H.HEAVY_MM * 2
    ens_valid = valid if ens_valid is None else ens_valid
    path = ecmwf.day_file_path(root, H.DAY)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, lead_days=np.array([1, 2, 3]), hres=hres, hres_valid=np.array(valid), hres_cycle=np.array(CYCLE.isoformat()),
             ens_mean=mean, ens_p10=mean * 0.5, ens_p50=mean, ens_p90=p90, ens_valid=np.array(ens_valid),
             ens_cycle=np.array(CYCLE.isoformat()), n_members=np.array(51))


def sources_with_ecmwf(tmp_path, **kwargs):
    return {**H.healthy_sources(), "ecmwf": S.EcmwfSource({}, latency_h=8.2, root=tmp_path, fetch_live=lambda *a, **k: None)}


@pytest.fixture
def cfg(tmp_path):
    out = H.make_cfg(tmp_path)
    H.write_widening(tmp_path / "forecast_widening.json")
    return out


def test_every_forecast_row_has_certainty_and_a_level_range(cfg):
    summary = live_run.run_day(H.DAY, cfg, deps=H.make_deps())
    for lead in (1, 2, 3):
        table = lead_table(cfg, lead)
        assert set(table["certainty"]) <= {pr.CERTAINTY_FIRM, pr.CERTAINTY_DEPENDS}
        assert (table["level_min"] <= table["level"]).all() and (table["level"] <= table["level_max"]).all()
        firm = table["certainty"] == pr.CERTAINTY_FIRM
        assert (table.loc[firm, "level_min"] == table.loc[firm, "level_max"]).all()
        assert (table.loc[~firm, "level_min"] < table.loc[~firm, "level_max"]).all()
    assert pd.read_parquet(run_dir(cfg) / "risk_D0.parquet")["certainty"].isna().all()
    assert summary["audit"]["total_violations"] == 0
    assert sum(summary["leads"]["2"]["certainty"].values()) == summary["leads"]["2"]["n_scored"]


def test_a_cell_whose_level_the_forecast_sets_depends_and_one_set_by_rain_on_the_ground_is_firm(cfg):
    """GFS puts heavy rain near Wayanad on D+2: the dry scenario is Normal there, the forecast and the wet bound are not."""
    live_run.run_day(H.DAY, cfg, deps=H.make_deps())
    wayanad = H.wayanad_row(lead_table(cfg, 2))
    assert wayanad["certainty"] == pr.CERTAINTY_DEPENDS and wayanad["level_min"] == 0 and wayanad["level_max"] >= wayanad["level"] > 0
    calm = lead_table(cfg, 2).query("region == 'himalaya'")
    assert (calm["certainty"] == pr.CERTAINTY_FIRM).all()


def test_the_default_run_uses_gfs_and_records_it(cfg):
    summary = live_run.run_day(H.DAY, cfg, deps=H.make_deps())
    for lead in "123":
        info = summary["leads"][lead]["forecast"]
        assert info["source"] == "gfs" and not info["fallback"] and info["label"] == "NOAA GFS"
        assert info["wet_bound"] == "high_factor"
    assert summary["forecast_rain"]["choice"]["fallback"] == {"source": "gfs", "mapped": False}


def test_an_ecmwf_choice_builds_the_leads_from_ecmwf_and_the_wet_bound_from_the_ensemble(cfg, tmp_path):
    write_ecmwf(tmp_path, heavy_p90_leads=(3,))
    choice = fc.ForecastChoice({k: fc.Config("ecmwf_hres") for k in fc.LEADS})
    summary = live_run.run_day(H.DAY, cfg, deps=H.make_deps(sources_with_ecmwf(tmp_path), choice=choice))
    for lead in "123":
        info = summary["leads"][lead]["forecast"]
        assert info["source"] == "ecmwf_hres" and info["label"] == "ECMWF IFS HRES (CC BY 4.0)"
        assert info["wet_bound"] == "ensemble_spread" and info["cycle"] == CYCLE.isoformat()
    assert summary["sources"]["ecmwf"]["state"] == "ok" and "ecmwf" not in summary["failed_sources"]
    features = pd.read_parquet(run_dir(cfg) / "features_D1.parquet")
    assert np.allclose(features["gfs_rain_d1"], 4.0, atol=0.01)                       # the HRES field, not the GFS one
    wayanad = H.wayanad_row(lead_table(cfg, 3))
    assert wayanad["certainty"] == pr.CERTAINTY_DEPENDS and wayanad["level_max"] > wayanad["level"]    # heavy p90 only
    assert summary["audit"]["total_violations"] == 0


def test_a_missing_ecmwf_falls_back_to_gfs_and_says_so(cfg):
    choice = fc.ForecastChoice({k: fc.Config("ecmwf_hres") for k in fc.LEADS})
    summary = live_run.run_day(H.DAY, cfg, deps=H.make_deps(choice=choice))
    for lead in "123":
        info = summary["leads"][lead]["forecast"]
        assert info["source"] == "gfs" and info["fallback"] and info["label"] == "GFS fallback"


def test_a_lead_ecmwf_cannot_supply_falls_back_alone(cfg, tmp_path):
    write_ecmwf(tmp_path, valid=(True, True, False))
    choice = fc.ForecastChoice({k: fc.Config("ecmwf_hres") for k in fc.LEADS})
    summary = live_run.run_day(H.DAY, cfg, deps=H.make_deps(sources_with_ecmwf(tmp_path), choice=choice))
    assert [summary["leads"][k]["forecast"]["fallback"] for k in "123"] == [False, False, True]
    assert summary["sources"]["ecmwf"]["state"] == "late"


class DoubleMaps:
    def apply(self, source, lead, field):
        return np.asarray(field, dtype=np.float32) * 2


def test_a_bias_corrected_choice_applies_the_maps_to_the_rain_of_the_features(cfg, tmp_path):
    write_ecmwf(tmp_path)
    choice = fc.ForecastChoice({k: fc.Config("ecmwf_hres", True) for k in fc.LEADS}, maps_file="maps.json")
    summary = live_run.run_day(H.DAY, cfg, deps=H.make_deps(sources_with_ecmwf(tmp_path), choice=choice, maps=DoubleMaps()))
    assert summary["leads"]["1"]["forecast"]["mapped"] and "bias-corrected" in summary["leads"]["1"]["forecast"]["label"]
    assert np.allclose(pd.read_parquet(run_dir(cfg) / "features_D1.parquet")["gfs_rain_d1"], 8.0, atol=0.02)


def test_the_fallback_uses_its_own_widening_factors(cfg, tmp_path, monkeypatch):
    import json
    (tmp_path / "forecast_widening.json").write_text(json.dumps({
        "leads": {str(k): {"lo": 0.9, "hi": 1.1} for k in (1, 2, 3)},
        "fallback": {"leads": {str(k): {"lo": 0.2, "hi": 7.0} for k in (1, 2, 3)}}}), encoding="utf-8")
    write_ecmwf(tmp_path, valid=(True, False, False))
    seen = []
    original = live_run.lead_scores
    monkeypatch.setattr(live_run, "lead_scores", lambda *args: seen.append(args[-1]) or original(*args))
    choice = fc.ForecastChoice({k: fc.Config("ecmwf_hres") for k in fc.LEADS})
    live_run.run_day(H.DAY, cfg, deps=H.make_deps(sources_with_ecmwf(tmp_path), choice=choice))
    assert set(seen[:3]) == {(0.9, 1.1)} and set(seen[3:]) == {(0.2, 7.0)}      # lead 1 (ECMWF) and its two scenarios, then leads 2, 3


def test_load_fallback_widening_reads_the_fallback_block(cfg, tmp_path):
    import json
    (tmp_path / "forecast_widening.json").write_text(json.dumps({
        "leads": {str(k): {"lo": 0.9, "hi": 1.1} for k in (1, 2, 3)},
        "fallback": {"leads": {str(k): {"lo": 0.2, "hi": 7.0} for k in (1, 2, 3)}}}), encoding="utf-8")
    assert live_run.load_fallback_widening(cfg, live_run.LiveDeps()) == {k: (0.2, 7.0) for k in (1, 2, 3)}
    assert live_run.load_widening(cfg, live_run.LiveDeps())[0] == {k: (0.9, 1.1) for k in (1, 2, 3)}
    H.write_widening(tmp_path / "forecast_widening.json")
    assert live_run.load_fallback_widening(cfg, live_run.LiveDeps()) is None


def test_the_unavailable_forecast_names_both_sources(cfg, tmp_path):
    sources = {**H.healthy_sources(), "gfs": H.FakeGfs(H.DAY, valid=(False, False, False)),
               "ecmwf": S.EcmwfSource({}, latency_h=8.2, root=tmp_path, fetch_live=lambda *a, **k: None)}
    choice = fc.ForecastChoice({k: fc.Config("ecmwf_hres") for k in fc.LEADS})
    summary = live_run.run_day(H.DAY, cfg, deps=H.make_deps(sources, choice=choice))
    reason = summary["leads"]["1"]["reason"]
    assert not summary["leads"]["1"]["published"] and "GFS forecast day D+1 not available" in reason and "ECMWF forecast day D+1" in reason


def test_the_audit_flags_a_broken_certainty(cfg):
    live_run.run_day(H.DAY, cfg, deps=H.make_deps())
    path = run_dir(cfg) / "risk_D2.parquet"
    table = pd.read_parquet(path)
    table.loc[table["certainty"] == pr.CERTAINTY_DEPENDS, "certainty"] = pr.CERTAINTY_FIRM        # firm with a level range
    table.loc[table.index[1], "level_min"] = 3                                                   # level below level_min
    table.loc[table.index[2], "certainty"] = "sure"
    table.to_parquet(path, index=False)
    result = audit.audit_day(run_dir(cfg), pr.load_rules(live_run.project_path(cfg["post_rules"])))
    found = result["tables"]["risk_D2"]
    assert found["violations"]["certainty"] >= 3
    texts = " ".join(e["why"] for e in found["examples"]["certainty"])
    assert "firm with a level range" in texts or "level outside" in texts
    assert result["tables"]["risk_D1"]["violations"]["certainty"] == 0


def test_a_widened_interval_never_leaves_the_probability_range():
    """risk_hi x the widening factor is a probability: it is capped at 1 (a forecast row of a very likely cell)."""
    model = H.tiny_model()
    cells = H.tiny_cells()
    frame = pd.concat([cells, pd.DataFrame({c: np.float32(300.0) for c in H.MODEL_COLUMNS if c != "stat_slope_mean"},
                                           index=cells.index)], axis=1)
    scores, _, _ = live_run.lead_scores(model, frame, np.ones(len(frame), dtype=bool), H.THRESHOLDS, H.ALERT_CONFIG,
                                        pr.NO_RULES, (0.5, 50.0))
    assert (scores["risk"] > 0.5).all()
    assert (scores["risk_hi"] <= 1.0).all() and (scores["risk_hi"] >= scores["risk"]).all()
    assert (scores["risk_lo"] <= scores["risk"]).all()


class _SpreadModel:
    """A model whose interval is wide: point 0.1 (Normal), risk_hi 0.15 (below Watch 0.2), so only a widened risk_hi
    (x2 = 0.3) makes the row uncertain-high."""
    columns = list(H.MODEL_COLUMNS)

    def score(self, frame):
        n = len(frame)
        return pd.DataFrame({"risk": np.full(n, 0.1), "risk_lo": np.full(n, 0.05), "risk_hi": np.full(n, 0.15),
                             "risk_per_100k": np.full(n, 1e4), "member_median_risk": np.full(n, 0.1),
                             "ensemble_agreement": np.ones(n)}, index=frame.index)


@pytest.mark.parametrize("bound, expect_uncertain", [("unwidened", False), ("widened", True)])
def test_the_unwidened_lead_bound_is_not_the_widened_interval(bound, expect_uncertain):
    """`lead_uncertain_bound: unwidened` tests the model's own risk_hi, not the lead-widened one: widening the published
    interval in place must not leak into the bound the level is tested on."""
    from dataclasses import replace
    cells = H.tiny_cells()
    frame = pd.concat([cells, pd.DataFrame({c: np.float32(1.0) for c in H.MODEL_COLUMNS if c not in cells.columns},
                                           index=cells.index)], axis=1)
    rules = replace(pr.NO_RULES, lead_uncertain_bound=bound)
    scores, level, uncertain = live_run.lead_scores(_SpreadModel(), frame, np.ones(len(frame), dtype=bool), H.THRESHOLDS,
                                                    H.ALERT_CONFIG, rules, (1.0, 2.0))
    assert np.allclose(scores["risk_hi"], 0.3)              # the published interval is widened either way
    assert uncertain.tolist() == [expect_uncertain] * len(frame)
