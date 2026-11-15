"""Inputs and calibration of the heavy-rain probabilities, shared by the study and the daily command so that both build
exactly the same predictors (spec section 4).

Leads 1-3 read one ECMWF day file (`ingest.ecmwf.load_day`): the ensemble p10 / p50 / p90 / mean of the IMD-day total on
the 0.1 degree grid. The neighbourhood statistics are taken on the full grid, then read at the domain pixels. Lead 0 reads
the observed IMD-day total of day D (IMERG Early plus the 0-3 h tail) at the domain pixels only; pixels off the domain are
NaN in its grid, in the study as in the live run, so a neighbourhood means the same thing in both.

A calibration is, per lead and threshold, the neighbourhood radius chosen on the fitting days and a logistic model
(`prob.LogisticModel`). It is stored as JSON.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

from ..ingest import imerg
from . import prob as P

LEADS = (0, 1, 2, 3)
ENS_STATS = ("p10", "p50", "p90", "mean")


def ens_names(radius: int) -> tuple[str, ...]:
    return (f"p90_max_r{radius}", f"p50_max_r{radius}", f"mean_mean_r{radius}")


def obs_names(radius: int) -> tuple[str, ...]:
    return (f"obs_max_r{radius}", "obs")


def predictor_names(lead: int, radius: int) -> tuple[str, ...]:
    return obs_names(radius) if lead == 0 else ens_names(radius)


def ensemble_grids(forecast, lead: int) -> dict[str, np.ndarray] | None:
    """The four ensemble statistics of `lead` (1..3) as (ROWS, COLS) float64 grids, None when that lead is invalid."""
    if forecast is None or forecast.ens_mean is None or not bool(forecast.ens_valid[lead - 1]):
        return None
    source = {"p10": forecast.ens_p10, "p50": forecast.ens_p50, "p90": forecast.ens_p90, "mean": forecast.ens_mean}
    return {name: np.asarray(source[name][lead - 1], dtype=np.float64) for name in ENS_STATS}


def forecast_fields(grids: dict[str, np.ndarray], radii, pixels: np.ndarray) -> dict[str, np.ndarray]:
    """Domain-pixel values of the raw statistics and of every neighbourhood predictor for the radii."""
    flat = {name: grid.ravel() for name, grid in grids.items()}
    out = {f"ens_{name}": flat[name][pixels] for name in ENS_STATS}
    for r in radii:
        out[f"p90_max_r{r}"] = P.neighbourhood(grids["p90"], r, "max").ravel()[pixels]
        out[f"p50_max_r{r}"] = P.neighbourhood(grids["p50"], r, "max").ravel()[pixels]
        out[f"mean_mean_r{r}"] = P.neighbourhood(grids["mean"], r, "mean").ravel()[pixels]
    return out


def observed_fields(values: np.ndarray, radii, pixels: np.ndarray) -> dict[str, np.ndarray]:
    """Lead-0 predictors from the observed IMD-day total at the domain pixels (NaN off the domain)."""
    grid = np.full(imerg.ROWS * imerg.COLS, np.nan)
    grid[pixels] = values
    grid = grid.reshape(imerg.ROWS, imerg.COLS)
    out = {"obs": np.asarray(values, dtype=np.float64)}
    for r in radii:
        out[f"obs_max_r{r}"] = P.neighbourhood(grid, r, "max").ravel()[pixels]
    return out


def design(fields: dict[str, np.ndarray], lead: int, radius: int, name: str, threshold, clim) -> np.ndarray:
    return P.predictors(fields, predictor_names(lead, radius), threshold, clim, percentile=P.is_percentile(name))


@dataclass
class Calibration:
    fit: list[dict]
    radii: list[int]
    entries: dict[int, dict[str, dict]]           # lead -> threshold -> {"radius", "model", "log_loss_by_radius"}

    def model(self, lead: int, name: str) -> tuple[int, P.LogisticModel]:
        entry = self.entries[lead][name]
        return int(entry["radius"]), entry["model"]

    def probability(self, fields: dict[str, np.ndarray], lead: int, name: str, threshold, clim) -> np.ndarray:
        radius, model = self.model(lead, name)
        return P.predict_logistic(model, design(fields, lead, radius, name, threshold, clim))

    def to_dict(self) -> dict:
        return {"schema": 1, "fit": self.fit, "radii": self.radii, "thresholds": list(P.THRESHOLDS),
                "leads": {str(lead): {name: {"radius": e["radius"], "model": e["model"].to_dict(),
                                             "log_loss_by_radius": e["log_loss_by_radius"],
                                             "predictors": list(predictor_names(lead, e["radius"]))}
                                      for name, e in by_name.items()}
                          for lead, by_name in self.entries.items()}}

    def save(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=1) + "\n", encoding="utf-8")
        tmp.replace(path)
        return path

    @classmethod
    def from_dict(cls, data: dict) -> "Calibration":
        entries = {int(lead): {name: {"radius": int(e["radius"]), "model": P.LogisticModel.from_dict(e["model"]),
                                      "log_loss_by_radius": e["log_loss_by_radius"]}
                               for name, e in by_name.items()}
                   for lead, by_name in data["leads"].items()}
        return cls(fit=data["fit"], radii=[int(r) for r in data["radii"]], entries=entries)

    @classmethod
    def load(cls, path: Path) -> "Calibration":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def fit_threshold(rows: list[tuple[dict, np.ndarray, np.ndarray, np.ndarray]], lead: int, name: str, radii,
                  ridge: float) -> dict:
    """Fit one lead and threshold on fitting pixel-days and choose the radius by log loss.

    `rows` holds, per fitting day, (fields, threshold mm, clim probability, observed total) at the domain pixels."""
    results = {}
    for r in radii:
        xs, ys = [], []
        for fields, threshold, clim, observed in rows:
            x = design(fields, lead, r, name, threshold, clim)
            keep = np.isfinite(x).all(axis=1) & np.isfinite(observed)
            xs.append(x[keep])
            ys.append(observed[keep] > np.broadcast_to(threshold, observed.shape)[keep])
        x, y = np.concatenate(xs), np.concatenate(ys)
        results[r] = P.fit_logistic(x, y, ridge=ridge)
    best = min(results, key=lambda r: results[r].log_loss)
    return {"radius": int(best), "model": results[best],
            "log_loss_by_radius": {str(r): m.log_loss for r, m in results.items()},
            "n": results[best].n, "n_events": results[best].n_events}


def iso(days: list[date]) -> list[str]:
    return [d.isoformat() for d in days]
