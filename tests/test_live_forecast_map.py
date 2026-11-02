"""Quantile mapping of forecast rain onto IMERG Late (aetherguard.live.forecast_map). Synthetic pairs; no project data."""
import numpy as np
import pytest

from aetherguard.ingest import imerg
from aetherguard.live import forecast_choice as fc
from aetherguard.live import forecast_map as fm

N_PIX = imerg.ROWS * imerg.COLS


def pairs(n=200_000, seed=3, scale=2.0, drizzle=0.0):
    rng = np.random.default_rng(seed)
    wet = rng.random(n) < 0.4
    observed = np.where(wet, rng.gamma(0.7, 12.0, n), 0.0)
    forecast = np.where(wet, observed / scale * rng.lognormal(0, 0.2, n), 0.0)
    forecast = np.where(~wet & (rng.random(n) < drizzle), rng.uniform(0.2, 3.0, n), forecast)
    return forecast.astype(np.float32), observed.astype(np.float32)


def test_curve_matches_the_distribution_of_the_observations():
    forecast, observed = pairs()
    curve = fm.fit_curve(forecast, observed)
    mapped = curve.apply(forecast)
    for q in (0.5, 0.8, 0.95):
        assert np.quantile(mapped, q) == pytest.approx(np.quantile(observed, q), rel=0.08)
    assert mapped[forecast > 5].mean() > 1.5 * forecast[forecast > 5].mean()       # the under-forecast is corrected


def test_curve_is_monotone_and_keeps_nan():
    forecast, observed = pairs()
    curve = fm.fit_curve(forecast, observed)
    grid = np.linspace(0, 200, 4001, dtype=np.float32)
    assert np.all(np.diff(curve.apply(grid)) >= -1e-4)
    assert np.isnan(curve.apply(np.array([np.nan], dtype=np.float32))[0])


def test_drizzle_the_observations_do_not_have_is_mapped_to_zero():
    forecast, observed = pairs(drizzle=0.5)
    curve = fm.fit_curve(forecast, observed)
    assert curve.info["forecast_dry_below_mm"] > 0.2                             # the extra drizzle sits below the threshold
    mapped = curve.apply(forecast)
    assert abs((mapped >= 0.1).mean() - (observed >= 0.1).mean()) < 0.02        # the wet share is the observed one


def test_fit_needs_enough_wet_values():
    with pytest.raises(ValueError, match="wet observed"):
        fm.fit_curve(np.zeros(1000), np.zeros(1000))
    with pytest.raises(ValueError, match="same shape"):
        fm.fit_curve(np.zeros(3), np.zeros(4))


def test_nan_pairs_are_ignored():
    forecast, observed = pairs()
    forecast[::7] = np.nan
    observed[::11] = np.nan
    assert fm.fit_curve(forecast, observed).info["pairs"] < forecast.size


def make_maps(factors):
    """Maps of source gfs with one curve per region, fitted on pairs whose forecast is `scale` times too low."""
    regions = np.array(["rest"] * N_PIX, dtype=object)
    regions[:100] = "himalaya"
    regions[100:200] = "western_ghats"
    curves = {}
    for region, scale in factors.items():
        forecast, observed = pairs(scale=scale)
        for k in fc.LEADS:
            curves[("gfs", k, region)] = fm.fit_curve(forecast, observed)
    return fm.ForecastMaps(curves, regions, {"note": "test"})


def test_apply_uses_the_curve_of_each_pixels_region():
    maps = make_maps({"himalaya": 4.0, "western_ghats": 1.0, "rest": 2.0})
    field = np.full((imerg.ROWS, imerg.COLS), 20.0, dtype=np.float32)
    out = maps.apply("gfs", 1, field).ravel()
    assert out[:100].mean() > out[200:].mean() > out[100:200].mean()   # lifted most where the forecast was 4x too low
    assert out.shape == (N_PIX,)
    with pytest.raises(ValueError, match="pixels"):
        maps.apply("gfs", 1, np.zeros((3, 3)))
    with pytest.raises(KeyError):
        maps.apply("ecmwf_hres", 1, field)


def test_maps_round_trip_through_json(tmp_path):
    maps = make_maps({"himalaya": 4.0, "western_ghats": 1.0, "rest": 2.0})
    path = tmp_path / "maps.json"
    maps.save(path)
    again = fm.ForecastMaps.load(path, maps.pixel_region)
    field = np.random.default_rng(1).gamma(0.7, 10.0, (imerg.ROWS, imerg.COLS)).astype(np.float32)
    assert np.allclose(maps.apply("gfs", 2, field), again.apply("gfs", 2, field), equal_nan=True)
    assert again.sources() == ["gfs"] and again.info == {"note": "test"}


def test_maps_file_version_is_checked():
    with pytest.raises(ValueError, match="version"):
        fm.ForecastMaps.from_dict({"version": 9, "curves": {}}, np.array([]))


class FakeStore:
    """Observed IMERG UTC-day rain = 10 mm everywhere on every day, so every IMD day is 10 mm."""

    def gather(self, rows, cols, first_day, length):
        return np.full((len(rows), length), 10.0, dtype=np.float32)


def test_collect_pairs_pairs_each_lead_with_its_imd_day(tmp_path, monkeypatch):
    days = fm.season_days(2023)[:3]
    monkeypatch.setattr(fm, "season_days", lambda year: days)
    for i, day in enumerate(days):
        np.savez(tmp_path / f"gfs_imdday_{day.isoformat()}.npz",
                 days=np.full((3, imerg.ROWS, imerg.COLS), float(i + 1), np.float32),
                 day_valid=np.array([True, True, i != 1]), cycle=np.array("2023-06-01T00:00:00+00:00"))
    regions = np.array(["rest"] * N_PIX, dtype=object)
    regions[:5] = "himalaya"
    got = fm.collect_pairs(FakeStore(), tmp_path, "gfs", (2023,), regions)
    assert len(got[1]["himalaya"]) == 3 and len(got[3]["himalaya"]) == 2          # day 2 has an invalid D+3
    forecast, observed = got[1]["himalaya"][1]
    assert forecast.shape == observed.shape == (5,) and np.all(forecast == 2.0) and np.all(observed == 10.0)
    assert len(got[2]["rest"]) == 3
