"""Early -> Late IMERG quantile mapping (spec section 10): the Early run is published 4.5 h after a UTC day ends, the Late
run 14.5 h, so at 11:00 IST the live run only has Early for UTC day D-1 and moves it to the Late scale before use.

    python -m aetherguard.live.early_map fit [--fit-years 2019 ... 2024] [--holdout-year 2018] [--processed DIR]
                                             [--out PATH] [--reports-dir DIR]

The mapping is pooled over the whole domain and over the days of June-September of the fit years that both runs hold:
  * a pixel-day is dry when Early < `dry_mm` (0.1 mm): it maps to 0 and takes no part in the quantile fit;
  * wet pixel-days: the Early quantiles (of Early values >= `dry_mm`) are matched to the Late quantiles (of Late values
    >= `dry_mm`) at the same probabilities, a piecewise-linear monotone curve through the (Early, Late) quantile pairs;
  * below the first fitted quantile the curve runs linearly to the origin, above the top one it scales by the Late/Early
    ratio at the top quantile;
  * NaN stays NaN.
Whether the live run uses this mapping or the Early run as it is (`IdentityMap`) is the setting `early_map.mode`
(`identity` | `fitted`) of configs/live_run.yaml; the fit stays as evidence.
The held-out check compares Early before and after the mapping with Late on the June-September overlap of the hold-out
year (default 2018, the test season): bias, MAE and correlation. It is a rain-only check; no labels are used.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from ..config import PROJECT_ROOT, data_root
from ..hazard.jsonio import dump_json, jsonable
from ..ingest import imerg as imerg_mod

QUANTILES = tuple(float(round(q, 3)) for q in np.arange(0.01, 1.0, 0.01)) + (0.995, 0.999)
DRY_MM = 0.1
MIN_WET_VALUES = 200
SEASON_MONTHS = (6, 7, 8, 9)
FIT_YEARS = tuple(range(2019, 2025))
HOLDOUT_YEAR = 2018
MAP_NAME = "imerg_early_to_late.json"
REPORT_STEM = "phase6_early_late_map"
VERSION = 1
CHUNK_DAYS = 31
WET_CHECK_MM = 1.0


class IdentityMap:
    """The Early run used as it is (`early_map.mode: identity`, the shipped default): the fitted curve did not improve
    the held-out 2018 season (reports/phase6_early_late_map.md)."""
    label = "early"

    def apply(self, values) -> np.ndarray:
        return np.array(values, dtype=np.float32)


@dataclass(frozen=True)
class EarlyLateMap:
    """Monotone piecewise-linear map from Early to Late daily rain (mm) (`early_map.mode: fitted`)."""
    label = "early_mapped"
    early_q: np.ndarray
    late_q: np.ndarray
    dry_mm: float = DRY_MM
    info: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        early, late = np.asarray(self.early_q, dtype=np.float64), np.asarray(self.late_q, dtype=np.float64)
        if early.ndim != 1 or early.shape != late.shape or early.size < 2:
            raise ValueError("a mapping needs at least two (Early, Late) quantile pairs")
        if not (np.isfinite(early).all() and np.isfinite(late).all()) or early[0] <= 0 or late[0] <= 0:
            raise ValueError("mapping quantiles must be finite and positive")
        if np.any(np.diff(early) <= 0) or np.any(np.diff(late) < 0):
            raise ValueError("mapping quantiles must be increasing in Early and non-decreasing in Late")
        object.__setattr__(self, "early_q", early)
        object.__setattr__(self, "late_q", late)

    def apply(self, values) -> np.ndarray:
        """Early rain on the Late scale, float32, same shape; NaN stays NaN, Early below `dry_mm` becomes 0."""
        x = np.asarray(values, dtype=np.float64)
        out = np.full(x.shape, np.nan)
        finite = np.isfinite(x)
        out[finite & (x < self.dry_mm)] = 0.0
        wet = finite & (x >= self.dry_mm)
        w = x[wet]
        y = np.interp(w, self.early_q, self.late_q)
        low, high = w < self.early_q[0], w > self.early_q[-1]
        y[low] = w[low] * (self.late_q[0] / self.early_q[0])
        y[high] = w[high] * (self.late_q[-1] / self.early_q[-1])
        out[wet] = y
        return out.astype(np.float32)

    def to_dict(self) -> dict:
        return {"version": VERSION, "dry_mm": self.dry_mm, "early_q": self.early_q.tolist(),
                "late_q": self.late_q.tolist(), "info": self.info}

    @classmethod
    def from_dict(cls, payload: dict) -> "EarlyLateMap":
        if payload.get("version") != VERSION:
            raise ValueError(f"unsupported mapping version {payload.get('version')!r}")
        return cls(np.array(payload["early_q"]), np.array(payload["late_q"]), float(payload["dry_mm"]),
                   dict(payload.get("info", {})))

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        dump_json(path, self.to_dict())

    @classmethod
    def load(cls, path: Path) -> "EarlyLateMap":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def fit_early_to_late(early, late, quantiles=QUANTILES, dry_mm: float = DRY_MM) -> EarlyLateMap:
    """The mapping from paired Early and Late arrays (any shape, pooled); pairs with a NaN are ignored.

    Raises ValueError with fewer than `MIN_WET_VALUES` wet values in either run.
    """
    early, late = np.asarray(early, dtype=np.float64).ravel(), np.asarray(late, dtype=np.float64).ravel()
    if early.shape != late.shape:
        raise ValueError("early and late must have the same shape")
    paired = np.isfinite(early) & np.isfinite(late)
    wet_early, wet_late = early[paired & (early >= dry_mm)], late[paired & (late >= dry_mm)]
    if min(wet_early.size, wet_late.size) < MIN_WET_VALUES:
        raise ValueError(f"need at least {MIN_WET_VALUES} wet values in each run, got {wet_early.size} (Early) "
                         f"and {wet_late.size} (Late)")
    probabilities = np.asarray(quantiles, dtype=np.float64)
    qe, ql = np.quantile(wet_early, probabilities), np.quantile(wet_late, probabilities)
    ql = np.maximum.accumulate(ql)
    keep = np.concatenate([[True], np.diff(qe) > 0])
    if keep.sum() < 2:
        raise ValueError("the Early quantiles collapse to a single value; the data cannot define a mapping")
    info = {"pairs": int(paired.sum()), "wet_early": int(wet_early.size), "wet_late": int(wet_late.size),
            "quantiles": probabilities[keep].tolist()}
    return EarlyLateMap(qe[keep], ql[keep], dry_mm, info)


def agreement(estimate, late) -> dict:
    """Bias (estimate - Late), MAE and Pearson correlation over the finite pairs, all and where Late >= 1 mm."""
    estimate, late = np.asarray(estimate, dtype=np.float64).ravel(), np.asarray(late, dtype=np.float64).ravel()
    paired = np.isfinite(estimate) & np.isfinite(late)

    def stats(mask) -> dict:
        e, l = estimate[mask], late[mask]
        if e.size < 2:
            return {"n": int(e.size), "bias_mm": None, "mae_mm": None, "correlation": None}
        corr = float(np.corrcoef(e, l)[0, 1]) if e.std() > 0 and l.std() > 0 else None
        return {"n": int(e.size), "bias_mm": float((e - l).mean()), "mae_mm": float(np.abs(e - l).mean()),
                "correlation": corr}
    return {"all": stats(paired), "late_wet": stats(paired & (late >= WET_CHECK_MM))}


# ---------------------------------------------------------------------------------------------------- the fit

def season_days(early, late, years) -> dict[int, list[date]]:
    """June-September days of each year that both stores hold."""
    both = sorted(set(early.dates()) & set(late.dates()))
    return {y: [d for d in both if d.year == y and d.month in SEASON_MONTHS] for y in years}


def overlap_pairs(early, late, days: list[date]) -> tuple[np.ndarray, np.ndarray]:
    """Paired (Early, Late) float32 values of every domain pixel on `days`, finite pairs only, flattened."""
    rows, cols = np.indices((imerg_mod.ROWS, imerg_mod.COLS))
    rows, cols = rows.ravel(), cols.ravel()
    early_parts, late_parts = [], []
    for lo in range(0, len(days), CHUNK_DAYS):
        chunk = days[lo:lo + CHUNK_DAYS]
        start = 0                  # days need not be consecutive: one gather per run of consecutive days
        while start < len(chunk):
            end = start
            while end + 1 < len(chunk) and chunk[end + 1] == chunk[end] + timedelta(days=1):
                end += 1
            e = early.gather(rows, cols, chunk[start], end - start + 1)
            l = late.gather(rows, cols, chunk[start], end - start + 1)
            keep = np.isfinite(e) & np.isfinite(l)
            early_parts.append(e[keep])
            late_parts.append(l[keep])
            start = end + 1
    return np.concatenate(early_parts), np.concatenate(late_parts)


def run_fit(early, late, fit_years=FIT_YEARS, holdout_year: int = HOLDOUT_YEAR) -> tuple[EarlyLateMap, dict]:
    """Fit on the June-September overlap of `fit_years` (never the hold-out year) and check on the hold-out year."""
    if holdout_year in fit_years:
        raise ValueError(f"the hold-out year {holdout_year} must not be in the fit years")
    days = season_days(early, late, [*fit_years, holdout_year])
    fit_days = [d for y in fit_years for d in days[y]]
    if not fit_days:
        raise ValueError("no June-September day of the fit years is in both stores; build them first "
                         "(python -m aetherguard.ingest.imerg_build --run early / --run late)")
    e, l = overlap_pairs(early, late, fit_days)
    mapping = fit_early_to_late(e, l)
    mapping.info.update(fit_years=list(fit_years), fit_days={str(y): len(days[y]) for y in fit_years})
    del e, l
    report = {"fit": mapping.info, "dry_mm": mapping.dry_mm, "holdout_year": holdout_year,
              "holdout_days": len(days[holdout_year]), "curve": [
                  {"early_mm": float(a), "late_mm": float(b), "ratio": float(b / a)}
                  for a, b in zip(mapping.early_q, mapping.late_q)][::10]}
    if days[holdout_year]:
        he, hl = overlap_pairs(early, late, days[holdout_year])
        report["holdout"] = {"before": agreement(he, hl), "after": agreement(mapping.apply(he), hl)}
    else:
        report["holdout"] = None
    return mapping, report


def _fmt(value) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def render_report(report: dict, map_path: str) -> str:
    lines = ["# Early -> Late IMERG mapping (rain-only check)", "",
             f"Mapping file: `{map_path}`. Fitted on the June-September overlap of {report['fit']['fit_years']} "
             f"({report['fit']['pairs']} pixel-day pairs; days per year {report['fit']['fit_days']}); dry threshold "
             f"{report['dry_mm']} mm (Early below it maps to 0). The hold-out year {report['holdout_year']} was not used in the fit.", ""]
    if report["holdout"] is None:
        lines.append(f"No June-September overlap day of {report['holdout_year']} in both stores: no hold-out check.")
    else:
        lines += [f"## Hold-out {report['holdout_year']} June-September ({report['holdout_days']} days), Early vs Late", "",
                  "| subset | mapping | n | bias (mm) | MAE (mm) | correlation |", "|---|---|---|---|---|---|"]
        for subset, label in (("all", "all pixel-days"), ("late_wet", "Late >= 1 mm")):
            for stage in ("before", "after"):
                s = report["holdout"][stage][subset]
                lines.append(f"| {label} | {stage} | {s['n']} | {_fmt(s['bias_mm'])} | {_fmt(s['mae_mm'])} | "
                             f"{_fmt(s['correlation'])} |")
    lines += ["", "## Curve (every 10th fitted quantile)", "", "| Early (mm) | Late (mm) | Late/Early |", "|---|---|---|"]
    lines += [f"| {c['early_mm']:.2f} | {c['late_mm']:.2f} | {c['ratio']:.3f} |" for c in report["curve"]]
    if report.get("decision"):
        lines += ["", report["decision"]]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    fit = sub.add_parser("fit", help="fit the mapping and write the hold-out report")
    fit.add_argument("--fit-years", type=int, nargs="+", default=list(FIT_YEARS))
    fit.add_argument("--holdout-year", type=int, default=HOLDOUT_YEAR)
    fit.add_argument("--processed", type=Path, default=None, help="IMERG store directory (default data/processed/rain)")
    fit.add_argument("--out", type=Path, default=None, help=f"mapping file (default data/processed/rain/{MAP_NAME})")
    fit.add_argument("--reports-dir", type=Path, default=PROJECT_ROOT / "reports")
    fit.add_argument("--decision", default=None, help="one closing line recorded in the report")
    args = parser.parse_args(argv)
    processed = Path(args.processed or data_root() / "processed" / "rain")
    out = Path(args.out or processed / MAP_NAME)
    early, late = imerg_mod.ImergStore(processed, "early"), imerg_mod.ImergStore(processed, "late")
    try:
        mapping, report = run_fit(early, late, tuple(args.fit_years), args.holdout_year)
    except ValueError as exc:
        print(f"early_map fit failed: {exc}", file=sys.stderr)
        return 1
    mapping.save(out)
    args.reports_dir.mkdir(parents=True, exist_ok=True)
    report["mapping_file"] = out.name
    report["decision"] = args.decision
    (args.reports_dir / f"{REPORT_STEM}.json").write_text(json.dumps(jsonable(report), indent=2, allow_nan=False) + "\n",
                                                           encoding="utf-8")
    (args.reports_dir / f"{REPORT_STEM}.md").write_text(render_report(report, out.name), encoding="utf-8")
    print(f"wrote {out} and {args.reports_dir / (REPORT_STEM + '.md')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
