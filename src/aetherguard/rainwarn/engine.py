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
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from ..ingest import imerg
from . import prob as P

LEADS = (0, 1, 2, 3)
ENS_STATS = ("p10", "p50", "p90", "mean")
STATE = "season_state"
STATE_WINDOW = (2, 31)          # IMD days D-31..D-2: what IMERG Late has observed by the run time (spec section 12.2)
STATE_MIN_DAYS = 20
STATE_GROUPS = ("himalaya", "western_ghats")


def state_days(day: date) -> list[date]:
    return [day - timedelta(days=k) for k in range(STATE_WINDOW[1], STATE_WINDOW[0] - 1, -1)]


def season_state(observed: np.ndarray, clim_heavy: np.ndarray, regions: np.ndarray) -> np.ndarray:
    """Season-state predictor per domain pixel (spec section 12.2) from the IMERG Late IMD-day totals `observed`
    (n_pixels, n_days) of the window and the matching climatological heavy-rain probabilities `clim_heavy`:
    ln((count + 1) / (expected + 1)) per group (himalaya, western_ghats, the rest of the domain); 0 everywhere when
    fewer than STATE_MIN_DAYS days of the window have any value."""
    observed = np.asarray(observed, dtype=np.float64)
    finite = np.isfinite(observed)
    out = np.zeros(observed.shape[0])
    if int(finite.any(axis=0).sum()) < STATE_MIN_DAYS:
        return out
    exceed = np.where(finite, observed, -np.inf) > P.FIXED_MM["heavy"]
    expected_cells = np.where(finite, clim_heavy, 0.0)
    regions = np.asarray(regions, dtype=object)
    rest = ~np.isin(regions, STATE_GROUPS)
    for member in [regions == g for g in STATE_GROUPS] + [rest]:
        if member.any():
            count, expected = exceed[member].sum(), expected_cells[member].sum()
            out[member] = np.log((count + 1.0) / (expected + 1.0))
    return out


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


def design(fields: dict[str, np.ndarray], lead: int, radius: int, name: str, threshold, clim, state: bool = False
           ) -> np.ndarray:
    x = P.predictors(fields, predictor_names(lead, radius), threshold, clim, percentile=P.is_percentile(name))
    return np.column_stack([x, np.asarray(fields[STATE], dtype=np.float64)]) if state else x


def levels_v2(probs: dict[str, np.ndarray], cutoffs: dict) -> np.ndarray:
    """Spec section 12.3: red P_vh >= c_r, orange max(P_h, P_99) >= c_o, yellow max(P_h, P_95) >= c_y (first match
    from red); -1 where any probability is missing."""
    p = {k: np.asarray(v, dtype=np.float64) for k, v in probs.items()}
    level = np.zeros(p["heavy"].shape, dtype=np.int8)
    level[np.fmax(p["heavy"], p["p95"]) >= cutoffs["yellow"]] = 1
    level[np.fmax(p["heavy"], p["p99"]) >= cutoffs["orange"]] = 2
    level[p["very_heavy"] >= cutoffs["red"]] = 3
    missing = np.zeros(level.shape, dtype=bool)
    for values in p.values():
        missing |= ~np.isfinite(values)
    level[missing] = P.LEVEL_UNAVAILABLE
    return level


@dataclass
class Calibration:
    fit: list[dict]
    radii: list[int]
    entries: dict[int, dict[str, dict]]           # lead -> threshold -> {"radius", "model", "log_loss_by_radius", "state"}
    levels: dict[int, dict] | None = None         # lead -> {"red", "orange", "yellow"} cutoffs (v2); None: section 7 rules

    def uses_state(self) -> bool:
        return any(e.get("state", False) for by_name in self.entries.values() for e in by_name.values())

    def warning_levels(self, lead: int, probs: dict[str, np.ndarray]) -> np.ndarray:
        if self.levels is None:
            return P.warning_levels(probs)
        return levels_v2(probs, self.levels[lead])

    def model(self, lead: int, name: str) -> tuple[int, P.LogisticModel]:
        entry = self.entries[lead][name]
        return int(entry["radius"]), entry["model"]

    def probability(self, fields: dict[str, np.ndarray], lead: int, name: str, threshold, clim) -> np.ndarray:
        radius, model = self.model(lead, name)
        state = bool(self.entries[lead][name].get("state", False))
        return P.predict_logistic(model, design(fields, lead, radius, name, threshold, clim, state))

    def to_dict(self) -> dict:
        out = {"schema": 1, "fit": self.fit, "radii": self.radii, "thresholds": list(P.THRESHOLDS),
               "leads": {str(lead): {name: {"radius": e["radius"], "model": e["model"].to_dict(),
                                            "log_loss_by_radius": e["log_loss_by_radius"],
                                            "state": bool(e.get("state", False)),
                                            "predictors": list(predictor_names(lead, e["radius"]))
                                            + ([STATE] if e.get("state") else [])}
                                     for name, e in by_name.items()}
                         for lead, by_name in self.entries.items()}}
        if self.levels is not None:
            out["levels_v2"] = {str(lead): cut for lead, cut in self.levels.items()}
        return out

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
                                      "log_loss_by_radius": e["log_loss_by_radius"],
                                      "state": bool(e.get("state", False))}
                               for name, e in by_name.items()}
                   for lead, by_name in data["leads"].items()}
        levels = {int(k): v for k, v in data["levels_v2"].items()} if "levels_v2" in data else None
        return cls(fit=data["fit"], radii=[int(r) for r in data["radii"]], entries=entries, levels=levels)

    @classmethod
    def load(cls, path: Path) -> "Calibration":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def fit_threshold(rows: list[tuple[dict, np.ndarray, np.ndarray, np.ndarray]], lead: int, name: str, radii,
                  ridge: float, state: bool = False) -> dict:
    """Fit one lead and threshold on fitting pixel-days and choose the radius by log loss.

    `rows` holds, per fitting day, (fields, threshold mm, clim probability, observed total) at the domain pixels."""
    results = {}
    for r in radii:
        xs, ys = [], []
        for fields, threshold, clim, observed in rows:
            x = design(fields, lead, r, name, threshold, clim, state)
            keep = np.isfinite(x).all(axis=1) & np.isfinite(observed)
            xs.append(x[keep])
            ys.append(observed[keep] > np.broadcast_to(threshold, observed.shape)[keep])
        x, y = np.concatenate(xs), np.concatenate(ys)
        results[r] = P.fit_logistic(x, y, ridge=ridge)
    best = min(results, key=lambda r: results[r].log_loss)
    return {"radius": int(best), "model": results[best],
            "log_loss_by_radius": {str(r): m.log_loss for r, m in results.items()},
            "n": results[best].n, "n_events": results[best].n_events, "state": bool(state)}


def log_loss_total(entry: dict, rows, lead: int, name: str) -> tuple[float, int]:
    """Summed log loss and pixel-day count of a fitted entry on other days (`rows` as in fit_threshold)."""
    total, n = 0.0, 0
    for fields, threshold, clim, observed in rows:
        x = design(fields, lead, entry["radius"], name, threshold, clim, bool(entry.get("state", False)))
        keep = np.isfinite(x).all(axis=1) & np.isfinite(observed)
        if not keep.any():
            continue
        p = np.clip(P.predict_logistic(entry["model"], x[keep]), 1e-15, 1 - 1e-15)
        y = observed[keep] > np.broadcast_to(threshold, observed.shape)[keep]
        total += float(-np.sum(np.where(y, np.log(p), np.log(1 - p))))
        n += int(keep.sum())
    return total, n


def bisect_cutoff(share_at, target: float, tol: float = 1e-9) -> float:
    """The cutoff c in [0, 1] where share_at(c), a share that falls as c rises, crosses `target`."""
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if share_at(mid) > target:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            break
    return 0.5 * (lo + hi)


def derive_levels(probs: dict[str, np.ndarray], targets: dict[str, float]) -> dict:
    """Cutoffs of the v2 levels so that red, orange-or-above and yellow-or-above fire on the target shares of the given
    pixel-days (spec section 12.3)."""
    p = {k: np.asarray(v, dtype=np.float64) for k, v in probs.items()}
    ok = np.ones(p["heavy"].shape, dtype=bool)
    for v in p.values():
        ok &= np.isfinite(v)
    p = {k: v[ok] for k, v in p.items()}
    red_score = p["very_heavy"]
    orange_score, yellow_score = np.fmax(p["heavy"], p["p99"]), np.fmax(p["heavy"], p["p95"])
    c_r = float(np.quantile(red_score, 1.0 - targets["red"]))
    red = red_score >= c_r
    c_o = bisect_cutoff(lambda c: float(np.mean(red | (orange_score >= c))), targets["orange"])
    orange = red | (orange_score >= c_o)
    c_y = bisect_cutoff(lambda c: float(np.mean(orange | (yellow_score >= c))), targets["yellow"])
    return {"red": c_r, "orange": c_o, "yellow": c_y, "n": int(ok.sum())}


def iso(days: list[date]) -> list[str]:
    return [d.isoformat() for d in days]
