"""Verification arithmetic of the heavy-rain warnings (spec section 6): per-day tallies that make every score and its
day-resampled bootstrap interval cheap.

One `Tally` holds, for one forecast kind on one group of pixels, per test day: the count of pixel-days, the sums of the
Brier terms, of the probabilities and of the events, a reliability table on `REL_EDGES` and the histograms of the
probabilities of events and non-events on `AUC_EDGES` (log-spaced, because the rare thresholds live at small
probabilities). A bootstrap resample is a weight vector over days, so every statistic of a resample is a weighted sum.
Neighbouring pixels of one day are not independent: the interval resamples days, never pixels.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

REL_EDGES = np.array([0.0, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
AUC_EDGES = np.concatenate([[0.0], np.geomspace(1e-4, 1.0, 100)])
N_REL, N_AUC = len(REL_EDGES) - 1, len(AUC_EDGES) - 1


def _bin(p: np.ndarray, edges: np.ndarray) -> np.ndarray:
    return np.clip(np.searchsorted(edges, p, side="right") - 1, 0, len(edges) - 2)


@dataclass
class Tally:
    n_days: int
    n: np.ndarray = field(init=False)
    bs: np.ndarray = field(init=False)
    sp: np.ndarray = field(init=False)
    ev: np.ndarray = field(init=False)
    rel_n: np.ndarray = field(init=False)
    rel_p: np.ndarray = field(init=False)
    rel_o: np.ndarray = field(init=False)
    hist_e: np.ndarray = field(init=False)
    hist_n: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        d = self.n_days
        self.n, self.bs, self.sp, self.ev = (np.zeros(d) for _ in range(4))
        self.rel_n, self.rel_p, self.rel_o = (np.zeros((d, N_REL)) for _ in range(3))
        self.hist_e, self.hist_n = (np.zeros((d, N_AUC), dtype=np.float32) for _ in range(2))

    def add(self, day: int, p, o) -> None:
        """Add one day's pairs; pairs with a NaN probability or truth must be removed by the caller."""
        p = np.clip(np.asarray(p, dtype=np.float64), 0.0, 1.0)
        o = np.asarray(o, dtype=bool)
        if p.size == 0:
            return
        of = o.astype(np.float64)
        self.n[day] += p.size
        self.bs[day] += float(np.sum((p - of) ** 2))
        self.sp[day] += float(p.sum())
        self.ev[day] += float(of.sum())
        rb = _bin(p, REL_EDGES)
        self.rel_n[day] += np.bincount(rb, minlength=N_REL)
        self.rel_p[day] += np.bincount(rb, weights=p, minlength=N_REL)
        self.rel_o[day] += np.bincount(rb, weights=of, minlength=N_REL)
        ab = _bin(p, AUC_EDGES)
        self.hist_e[day] += np.bincount(ab[o], minlength=N_AUC).astype(np.float32)
        self.hist_n[day] += np.bincount(ab[~o], minlength=N_AUC).astype(np.float32)

    def arrays(self) -> dict[str, np.ndarray]:
        return {k: getattr(self, k) for k in ("n", "bs", "sp", "ev", "rel_n", "rel_p", "rel_o", "hist_e", "hist_n")}

    @classmethod
    def from_arrays(cls, data: dict[str, np.ndarray]) -> "Tally":
        tally = cls(int(len(data["n"])))
        for key, value in data.items():
            setattr(tally, key, np.asarray(value, dtype=getattr(tally, key).dtype))
        return tally


def auc_from_hist(hist_e: np.ndarray, hist_n: np.ndarray) -> np.ndarray:
    """ROC area from binned probabilities (ties within a bin count one half); last axis = bins; NaN without both."""
    hist_e, hist_n = np.asarray(hist_e, dtype=np.float64), np.asarray(hist_n, dtype=np.float64)
    below = np.cumsum(hist_n, axis=-1) - hist_n
    e, nn = hist_e.sum(axis=-1), hist_n.sum(axis=-1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where((e > 0) & (nn > 0), (hist_e * (below + 0.5 * hist_n)).sum(axis=-1) / (e * nn), np.nan)


def point(t: Tally) -> dict:
    """Scores on all test days: BS, base rate, mean probability, Murphy terms on REL_EDGES, ROC area, counts."""
    n, ev = t.n.sum(), t.ev.sum()
    if n == 0:
        return {"n": 0, "events": 0, "event_days": 0}
    base, bs, mean_p = ev / n, t.bs.sum() / n, t.sp.sum() / n
    rn, rp, ro = t.rel_n.sum(axis=0), t.rel_p.sum(axis=0), t.rel_o.sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        pk, ok = rp / rn, ro / rn
    used = rn > 0
    rel = float(np.sum(rn[used] * (pk[used] - ok[used]) ** 2) / n)
    res = float(np.sum(rn[used] * (ok[used] - base) ** 2) / n)
    unc = float(base * (1 - base))
    return {"n": int(n), "events": int(ev), "event_days": int(np.sum(t.ev > 0)), "days": int(np.sum(t.n > 0)),
            "base_rate": float(base), "mean_prob": float(mean_p), "bs": float(bs),
            "calibration_in_the_large": float(mean_p / base) if base > 0 else None,
            "rel": rel, "res": res, "unc": unc, "rel_over_unc": rel / unc if unc > 0 else None,
            "auc": float(auc_from_hist(t.hist_e.sum(axis=0), t.hist_n.sum(axis=0))),
            "reliability": [{"bin": [float(REL_EDGES[k]), float(REL_EDGES[k + 1])], "n": int(rn[k]),
                             "mean_prob": float(pk[k]) if used[k] else None,
                             "observed": float(ok[k]) if used[k] else None} for k in range(N_REL)]}


def bootstrap_weights(n_days: int, n_boot: int, seed: int) -> np.ndarray:
    """(n_boot, n_days) multinomial day counts: each row is one resample of the test days with replacement."""
    rng = np.random.default_rng(seed)
    picks = rng.integers(0, n_days, size=(n_boot, n_days))
    weights = np.zeros((n_boot, n_days))
    np.add.at(weights, (np.repeat(np.arange(n_boot), n_days), picks.ravel()), 1.0)
    return weights


def _ci(values: np.ndarray) -> list[float | None]:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return [None, None]
    lo, hi = np.percentile(finite, [2.5, 97.5])
    return [float(lo), float(hi)]


def boot_bs(t: Tally, w: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore", divide="ignore"):
        return (w @ t.bs) / (w @ t.n)


def boot_sample_clim_bs(t: Tally, w: np.ndarray) -> np.ndarray:
    """BS of the constant forecast 'base rate of the resample' (sample climatology)."""
    with np.errstate(invalid="ignore", divide="ignore"):
        base = (w @ t.ev) / (w @ t.n)
    return base * (1 - base)


def boot_auc(t: Tally, w: np.ndarray) -> np.ndarray:
    return auc_from_hist(w @ t.hist_e.astype(np.float64), w @ t.hist_n.astype(np.float64))


def compare(product: Tally, reference: Tally | None, baselines: dict[str, Tally], w: np.ndarray, *,
            sample_reference: bool = False) -> dict:
    """Point scores of `product` plus 95% day-bootstrap intervals of its BSS (against `reference`, or the sample
    climatology), its ROC area and BS(product) - BS(baseline) for each baseline."""
    out = point(product)
    if out["n"] == 0:
        return out
    bs_p = boot_bs(product, w)
    if sample_reference:
        ref_point = out["unc"]
        bs_r = boot_sample_clim_bs(product, w)
    else:
        ref_point = float(reference.bs.sum() / reference.n.sum())
        bs_r = boot_bs(reference, w)
    out["bs_reference"] = ref_point
    out["bss"] = 1 - out["bs"] / ref_point if ref_point > 0 else None
    with np.errstate(invalid="ignore", divide="ignore"):
        out["bss_ci"] = _ci(1 - bs_p / bs_r)
    out["auc_ci"] = _ci(boot_auc(product, w))
    out["vs"] = {}
    for name, base in baselines.items():
        if base.n.sum() == 0:
            continue
        diff_point = out["bs"] - float(base.bs.sum() / base.n.sum())
        out["vs"][name] = {"bs": float(base.bs.sum() / base.n.sum()), "diff": diff_point,
                           "diff_ci": _ci(bs_p - boot_bs(base, w)), "n": int(base.n.sum())}
    return out


def statements(result: dict, rules: dict) -> dict:
    """The pre-declared statements (spec section 6) of one product summary from `compare`."""
    enough = (result.get("events", 0) >= rules["min_event_pixel_days"]
              and result.get("event_days", 0) >= rules["min_event_days"])
    if not enough:
        return {"enough_events": False}
    lo_bss = (result.get("bss_ci") or [None])[0]
    lo_auc = (result.get("auc_ci") or [None])[0]
    cal = result.get("calibration_in_the_large")
    low, high = rules["calibration_in_the_large"]
    beats = {name: v["diff_ci"][1] is not None and v["diff_ci"][1] < 0 for name, v in result.get("vs", {}).items()}
    return {"enough_events": True,
            "skilful": lo_bss is not None and lo_bss > 0,
            "beats_baselines": bool(beats) and all(beats.values()), "beats": beats,
            "reliable": (result.get("rel_over_unc") is not None and result["rel_over_unc"] <= rules["rel_over_unc_max"]
                         and cal is not None and low <= cal <= high),
            "discriminates": lo_auc is not None and lo_auc > 0.5}
