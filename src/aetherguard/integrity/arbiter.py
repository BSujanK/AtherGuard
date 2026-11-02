"""L4 arbiter: a flagged reading that independent references corroborate is RETAINED as a genuine extreme.

References (all date x station values, NaN = unavailable): imd, chirps_aligned and the wide-neighbour idw mean
(`neighbours`). IMD is a label-consistency check rather than an independent one (the grid probably ingests these
gauges), so every rule can run with IMD excluded (`use_imd=False`).

Rule E (model flags). A flagged reading is retained when obs >= 20 mm and
  * two or more references are available and at least 2 of them have value >= 0.3 * obs; or
  * exactly one reference is available, its value is >= 0.6 * obs and the model's P(fault) < 0.9.
No reference available: never retained. Retained readings get reasons "corroborated_by:imd,chirps,neighbours"
(the supporting references); a flagged reading that is not retained stays flagged and low-trust (never deleted).

Rule S (the only L1 exception). An L1 flag whose ONLY reason is `stuck` (>= 3 identical positive values) is
retained when at least 2 references are available with |ref - obs| <= 0.3 * obs, reason
"stuck_corroborated_by:...". L1 `bounds` and `duplicate_block` flags are never overridden.
"""
from __future__ import annotations

import numpy as np

EXTREME_MIN_MM = 20.0
AGREE_FRACTION = 0.3
SINGLE_REF_FRACTION = 0.6
SINGLE_REF_MAX_P_FAULT = 0.9
STUCK_TOLERANCE = 0.3
MIN_STUCK_REFS = 2
REFERENCE_NAMES = ("imd", "chirps_aligned", "neighbours")
_SHORT = {"imd": "imd", "chirps_aligned": "chirps", "neighbours": "neighbours"}


def _available(refs: dict, use_imd: bool) -> dict:
    return {name: np.asarray(refs[name], dtype=np.float64) for name in REFERENCE_NAMES if use_imd or name != "imd"}


def _reasons(prefix: str, support: dict, rows: np.ndarray) -> np.ndarray:
    out = np.full(len(rows), "", dtype=object)
    for i in np.flatnonzero(rows):
        names = ",".join(_SHORT[n] for n, hit in support.items() if hit[i])
        out[i] = f"{prefix}:{names}"
    return out


def corroborate(obs, refs: dict, p_fault, use_imd: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """Rule E: (retained bool array, reasons object array) for readings that are already flagged."""
    obs = np.asarray(obs, dtype=np.float64)
    p_fault = np.asarray(p_fault, dtype=np.float64)
    avail = _available(refs, use_imd)
    with np.errstate(invalid="ignore"):
        have = {n: np.isfinite(v) for n, v in avail.items()}
        agree = {n: have[n] & (v >= AGREE_FRACTION * obs) for n, v in avail.items()}
        strong = {n: have[n] & (v >= SINGLE_REF_FRACTION * obs) for n, v in avail.items()}
        n_have = sum(h.astype(int) for h in have.values())
        n_agree = sum(a.astype(int) for a in agree.values())
        big = np.isfinite(obs) & (obs >= EXTREME_MIN_MM)
        two = (n_have >= 2) & (n_agree >= 2)
        one = (n_have == 1) & (p_fault < SINGLE_REF_MAX_P_FAULT) & np.logical_or.reduce(list(strong.values()))
    retained = big & (two | one)
    # supporting references: those that agree (two-reference case) or the single strong one
    support = {n: np.where(n_have >= 2, agree[n], strong[n]) for n in agree}
    return retained, _reasons("corroborated_by", support, retained)


def stuck_exception(obs, refs: dict, use_imd: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """Rule S: (retained bool array, reasons) for readings whose only L1 reason is `stuck`."""
    obs = np.asarray(obs, dtype=np.float64)
    avail = _available(refs, use_imd)
    with np.errstate(invalid="ignore"):
        close = {n: np.isfinite(v) & (np.abs(v - obs) <= STUCK_TOLERANCE * obs) for n, v in avail.items()}
        n_close = sum(c.astype(int) for c in close.values())
    retained = np.isfinite(obs) & (obs > 0) & (n_close >= MIN_STUCK_REFS)
    return retained, _reasons("stuck_corroborated_by", close, retained)
