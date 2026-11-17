"""Thresholds of the 2025 no-harm veto (spec leads v5, amendment 2), chosen by simulation; no data is read.

    python tools/leads_v5_veto.py <out.json>

The veto is triggered when the candidate is clearly worse on the pooled net change:
  NET_ALL = sum over the 12 deciding rows of (slides the incumbent detects and the candidate misses) minus (the reverse),
  NET_CE  = the same sum over the three cell-exact Emergency rows (leads 1, 2, 3);
  veto when NET_ALL >= T_ALL or NET_CE >= T_CE.
Two bounding models of how the rows depend on each other (the truth lies between them):
  independent - each row draws its own discordant slides (Binomial(n, q)) and directions (p to the candidate);
  shared      - every row has the same discordant slides and directions (one draw per slide, copied to all rows).
The thresholds are the smallest (most sensitive) pair for which an equal candidate (p = 0.5) passes with probability at
least 0.8 under BOTH models, for every q in QS, at the deciding size n = 3 slides. Seeded Monte Carlo.
"""
import itertools
import json
import sys

import numpy as np

ROWS, CE_ROWS, DRAWS, SEED = 12, 3, 40000, 20261117
QS = (0.1, 0.25, 0.4)
N = 3
PASS_TARGET = 0.8
EQUAL, WORSE = 0.5, 0.35


def nets(n: int, q: float, p: float, model: str, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    if model == "independent":
        discordant = rng.binomial(n, q, size=(DRAWS, ROWS))
        to_candidate = rng.binomial(discordant, p)
        per_row = discordant - 2 * to_candidate              # lost - gained = (d - k) - k
    else:
        discordant = rng.binomial(n, q, size=DRAWS)
        to_candidate = rng.binomial(discordant, p)
        per_row = np.repeat((discordant - 2 * to_candidate)[:, None], ROWS, axis=1)
    return per_row.sum(axis=1), per_row[:, -CE_ROWS:].sum(axis=1)


def rates(t_all: int, t_ce: int, p: float, rng) -> dict:
    out = {}
    for model in ("independent", "shared"):
        for q in QS:
            net_all, net_ce = nets(N, q, p, model, rng)
            out[f"{model} q={q}"] = float(((net_all >= t_all) | (net_ce >= t_ce)).mean())
    return out


def main() -> int:
    rng = np.random.default_rng(SEED)
    chosen = None
    for t_all, t_ce in sorted(itertools.product(range(1, 37), range(1, 10)), key=lambda t: (t[0] + 3 * t[1], t)):
        blocked_equal = rates(t_all, t_ce, EQUAL, rng)
        if all(1 - b >= PASS_TARGET for b in blocked_equal.values()):
            chosen = (t_all, t_ce, blocked_equal)
            break
    t_all, t_ce, blocked_equal = chosen
    blocked_worse = rates(t_all, t_ce, WORSE, rng)
    payload = {"rule": "veto when NET_ALL >= T_ALL or NET_CE >= T_CE (lost minus gained slides)", "n_slides": N, "qs": list(QS),
               "pass_target_equal": PASS_TARGET, "T_ALL": t_all, "T_CE": t_ce,
               "pass_probability_equal_p0.5": {k: 1 - v for k, v in blocked_equal.items()},
               "block_probability_worse_p0.35": blocked_worse, "seed": SEED, "draws": DRAWS,
               "models": "independent rows and fully shared rows bound the truth"}
    with open(sys.argv[1], "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=1)
    print(json.dumps(payload, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
