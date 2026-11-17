"""Illustrative power of the 12-row look rule for a small deciding set (no data read; assumptions are parameters).

    python tools/leads_v5_power.py <out.json>

Model (stated, not fitted): each of the 12 rows is independent; in a row each of n independent slides is discordant (one
model detects it, the other does not) with probability q, and a discordant slide favours the candidate with probability p
(p = 0.5: no difference). Rule (i): every row has candidate >= incumbent and at least one row has candidate > incumbent.
Rule (iii), no-harm: every row has candidate >= incumbent. Independence of the rows makes passing (iii) and failing (i) by a
single lower row look rarer than it is, since the real rows share slides. Seeded Monte Carlo, 20,000 draws per cell.
"""
import json
import sys

import numpy as np

ROWS, DRAWS, SEED = 12, 20000, 20261117
NS = (3, 6, 10, 15, 25)
QS = (0.1, 0.25)
PS = (0.5, 0.65, 0.8)


def simulate(n: int, q: float, p: float, rng: np.random.Generator) -> dict:
    discordant = rng.binomial(n, q, size=(DRAWS, ROWS))
    favour = rng.binomial(discordant, p)
    b, c = favour, discordant - favour
    not_lower = (b >= c).all(axis=1)
    higher = (b > c).any(axis=1)
    return {"rule_i_adopt": float((not_lower & higher).mean()), "rule_iii_pass": float(not_lower.mean()),
            "all_rows_tied": float((b == c).all(axis=1).mean())}


def main() -> int:
    rng = np.random.default_rng(SEED)
    table = {f"n={n}": {f"q={q}": {f"p={p}": simulate(n, q, p, rng) for p in PS} for q in QS} for n in NS}
    payload = {"model": __doc__.split("Model (stated, not fitted): ")[1].split("Seeded")[0].strip(), "seed": SEED, "draws": DRAWS,
               "results": table}
    with open(sys.argv[1], "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=1)
    for n in NS:
        for q in QS:
            row = table[f"n={n}"][f"q={q}"]
            print(f"n={n:2d} q={q}: " + "  ".join(f"p={p}: adopt(i) {row[f'p={p}']['rule_i_adopt']:.2f} pass(iii) "
                                                  f"{row[f'p={p}']['rule_iii_pass']:.2f}" for p in PS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
