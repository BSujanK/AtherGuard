"""Forecast configurations, per-lead resolution with the GFS fallback, and the dry / forecast / wet scenarios
(aetherguard.live.forecast_choice). Synthetic arrays; no network, no project data."""
from datetime import date, datetime, timezone

import numpy as np
import pytest

from aetherguard.ingest import ecmwf
from aetherguard.live import forecast_choice as fc

UTC = timezone.utc
SHAPE = (3, 4, 5)
CYCLE = datetime(2024, 7, 14, 18, tzinfo=UTC)


class DoubleMaps:
    """Stands in for ForecastMaps: the corrected rain is twice the raw one."""

    def apply(self, source, lead, field):
        return np.asarray(field, dtype=np.float32) * 2.0


def product(value, valid=(True, True, True), p90=None, mean=None, cycle=CYCLE):
    return fc.ProductDay(np.full(SHAPE, value, dtype=np.float32), np.array(valid), cycle,
                         None if p90 is None else np.full(SHAPE, p90, dtype=np.float32),
                         None if mean is None else np.full(SHAPE, mean, dtype=np.float32))


def choice(*, mapped=False, source="ecmwf_hres"):
    return fc.ForecastChoice({k: fc.Config(source, mapped) for k in fc.LEADS}, maps_file="maps.json" if mapped else None)


def test_labels_name_the_source_and_licence():
    assert fc.source_label("ecmwf_hres", False) == "ECMWF IFS HRES (CC BY 4.0)"
    assert fc.source_label("ecmwf_ens_mean", True) == "ECMWF IFS ensemble mean (CC BY 4.0), bias-corrected"
    assert fc.source_label("gfs", False) == "NOAA GFS"
    assert fc.source_label("gfs", False, fallback=True) == "GFS fallback"


def test_config_rejects_an_unknown_source_and_a_choice_needs_all_leads():
    with pytest.raises(ValueError, match="source"):
        fc.Config("gefs")
    with pytest.raises(ValueError, match="leads"):
        fc.ForecastChoice({1: fc.GFS_RAW})
    with pytest.raises(ValueError, match="mapping file"):
        fc.ForecastChoice({k: fc.Config("gfs", True) for k in fc.LEADS})


def test_choice_round_trips_through_its_file(tmp_path):
    original = fc.ForecastChoice({1: fc.Config("ecmwf_hres", True), 2: fc.GFS_RAW, 3: fc.Config("ecmwf_ens_mean")},
                                 maps_file="data/maps.json", report="reports/x.md")
    path = tmp_path / "choice.json"
    fc.save_choice(path, original, {"why": "test"})
    assert fc.load_choice(path) == original
    assert original.needs_ecmwf and not fc.GFS_EVERYWHERE.needs_ecmwf


def test_missing_choice_file_means_gfs_everywhere(tmp_path):
    assert fc.load_choice(tmp_path / "none.json") == fc.GFS_EVERYWHERE and fc.load_choice(None) == fc.GFS_EVERYWHERE


def test_choice_with_a_wrong_version_is_rejected():
    with pytest.raises(ValueError, match="version"):
        fc.ForecastChoice.from_dict({"version": 99, "leads": {}, "fallback": {}})


def test_resolve_uses_the_chosen_source_for_the_first_k_days():
    lead = fc.resolve_lead({"ecmwf_hres": product(3.0), "gfs": product(1.0)}, choice(), None, 2)
    assert lead.days.shape == (2, 4, 5) and np.allclose(lead.days, 3.0)
    assert not lead.fallback and lead.label == "ECMWF IFS HRES (CC BY 4.0)" and lead.cycle == CYCLE


def test_resolve_falls_back_to_gfs_when_the_source_is_missing_or_invalid():
    gfs_only = {"gfs": product(1.0)}
    lead = fc.resolve_lead(gfs_only, choice(), None, 1)
    assert lead.fallback and lead.config == fc.GFS_RAW and lead.label == "GFS fallback" and np.allclose(lead.days, 1.0)
    partly = {"ecmwf_hres": product(3.0, valid=(True, False, True)), "gfs": product(1.0)}
    assert not fc.resolve_lead(partly, choice(), None, 1).fallback
    assert fc.resolve_lead(partly, choice(), None, 2).fallback            # D+2 is invalid, so is any lead that needs it


def test_resolve_is_none_when_nothing_covers_the_lead():
    assert fc.resolve_lead({}, choice(), None, 1) is None
    assert fc.resolve_lead({"gfs": product(1.0, valid=(False, True, True))}, choice(), None, 1) is None


def test_gfs_choice_that_fails_is_not_reported_as_a_fallback():
    assert fc.resolve_lead({}, fc.GFS_EVERYWHERE, None, 1) is None
    only = fc.resolve_lead({"gfs": product(1.0)}, fc.GFS_EVERYWHERE, None, 1)
    assert not only.fallback and only.label == "NOAA GFS"


def test_mapped_choice_applies_the_maps_per_lead():
    lead = fc.resolve_lead({"ecmwf_hres": product(3.0)}, choice(mapped=True), DoubleMaps(), 3)
    assert np.allclose(lead.days, 6.0) and lead.config.mapped and "bias-corrected" in lead.label


def test_scenarios_dry_forecast_and_wet_with_an_ensemble():
    products = {"ecmwf_hres": product(3.0, p90=9.0, mean=4.0)}
    lead = fc.resolve_lead(products, choice(), None, 2)
    scenes = fc.scenario_fields(lead, hi_factor=5.0)
    assert set(scenes) == set(fc.SCENARIOS)
    assert np.all(scenes["dry"] == 0) and np.allclose(scenes["forecast"], 3.0)
    assert np.allclose(scenes["wet"], 3.0 + 5.0)                    # forecast + (p90 - mean)


def test_wet_of_the_ensemble_mean_source_is_the_ensemble_p90():
    products = {"ecmwf_ens_mean": product(4.0, p90=9.0, mean=4.0)}
    lead = fc.resolve_lead(products, choice(source="ecmwf_ens_mean"), None, 1)
    assert np.allclose(fc.scenario_fields(lead, 5.0)["wet"], 9.0)


def test_wet_without_an_ensemble_scales_the_forecast_by_the_high_factor():
    lead = fc.resolve_lead({"gfs": product(2.0)}, fc.GFS_EVERYWHERE, None, 3)
    scenes = fc.scenario_fields(lead, hi_factor=4.1)
    assert np.allclose(scenes["wet"], 8.2, atol=1e-5) and np.allclose(scenes["forecast"], 2.0)


def test_wet_is_never_below_the_forecast():
    products = {"ecmwf_hres": product(3.0, p90=1.0, mean=4.0)}       # p90 under the mean: no negative spread
    lead = fc.resolve_lead(products, choice(), None, 1)
    assert np.all(fc.scenario_fields(lead, 0.5)["wet"] >= lead.days)
    gfs_lead = fc.resolve_lead({"gfs": product(2.0)}, fc.GFS_EVERYWHERE, None, 1)
    assert np.allclose(fc.scenario_fields(gfs_lead, 0.5)["wet"], 2.0)    # a factor under 1 never lowers it


def test_a_nan_ensemble_gives_no_spread():
    products = {"ecmwf_hres": product(3.0, p90=np.nan, mean=4.0)}
    lead = fc.resolve_lead(products, choice(), None, 1)
    assert lead.spread is None


def test_load_product_days_reads_both_archives(tmp_path):
    day = date(2024, 7, 15)
    days = np.full((3, 280, 260), 2.0, dtype=np.float32)
    np.savez(tmp_path / f"gfs_imdday_{day.isoformat()}.npz", days=days, day_valid=np.array([True, True, False]),
             cycle=np.array(CYCLE.isoformat()))
    arrays = {"lead_days": np.array([1, 2, 3]), "hres": days * 3, "hres_valid": np.ones(3, dtype=bool),
              "hres_cycle": np.array(CYCLE.isoformat()), "ens_mean": days * 4, "ens_p10": days, "ens_p50": days * 4,
              "ens_p90": days * 6, "ens_valid": np.ones(3, dtype=bool), "ens_cycle": np.array(CYCLE.isoformat()),
              "n_members": np.array(51)}
    np.savez(tmp_path / ecmwf.day_file_name(day), **arrays)
    got = fc.load_product_days(tmp_path, day)
    assert set(got) == {"gfs", "ecmwf_hres", "ecmwf_ens_mean"}
    assert got["gfs"].valid.tolist() == [True, True, False] and got["gfs"].p90 is None
    assert np.allclose(got["ecmwf_hres"].days, 6.0) and np.allclose(got["ecmwf_hres"].p90, 12.0)
    assert np.allclose(got["ecmwf_ens_mean"].days, 8.0) and got["ecmwf_ens_mean"].cycle == CYCLE
    assert fc.load_product_days(tmp_path, date(2024, 7, 16)) == {}


def test_load_product_days_skips_a_gfs_file_with_no_valid_day(tmp_path):
    day = date(2024, 7, 15)
    np.savez(tmp_path / f"gfs_imdday_{day.isoformat()}.npz", days=np.full((3, 280, 260), np.nan, dtype=np.float32),
             day_valid=np.zeros(3, dtype=bool), cycle=np.array(CYCLE.isoformat()))
    assert fc.load_product_days(tmp_path, day) == {}
