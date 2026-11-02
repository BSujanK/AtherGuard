"""Report of the challenger experiments: reports/phase6_challengers.{md,json} (the JSON is the source of truth).

Every number is computed from the saved OOF frames; nothing is typed in. Differences are FA@90(challenger) minus
FA@90(selected v3), from one paired bootstrap, so a negative difference favours the challenger.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from ..config import PROJECT_ROOT
from . import challengers as ch
from . import cv
from . import model as hm
from .jsonio import dump_json
from .tables import _num, _table

PROBE_FILE = "susceptibility_probe.json"


def _design_logloss(frame) -> float | None:
    oof = ch.oof_scores(frame)
    return cv.log_loss(np.r_[np.ones(len(oof.pos)), np.zeros(len(oof.matched))], np.r_[oof.pos, oof.matched])


def build_payload(cfg: dict, config: Path, frames: dict, metas: dict, reproduction: dict, rows: dict,
                  seconds: float) -> dict:
    boot, ops = cfg["bootstrap"], cfg["operating_points"]
    if ch.INCUMBENT not in frames or ch.FROZEN_V2 not in frames:
        raise ValueError("the incumbent and frozen v2 OOF frames are required")
    challengers = [n for n in frames if n not in (ch.INCUMBENT, ch.FROZEN_V2)]
    pairs = [(ch.INCUMBENT, ch.FROZEN_V2)] + [(n, ch.INCUMBENT) for n in challengers]
    result = ch.paired_fa_differences(frames, pairs, boot["n"], boot["seed"], boot["level"], ops["recalls"],
                                      ops["fa_shares"])
    candidates = []
    for name, frame in frames.items():
        meta = metas[name]
        entry = {**{k: meta[k] for k in ("name", "family", "description", "n_inputs", "hp", "neg_mix", "n_trees",
                                          "adoptable")},
                 "parents": meta.get("parents"), "columns": meta["columns"],
                 "metrics": result["metrics"][name],
                 "logloss": _design_logloss(frame) if meta["probabilistic"] else None}
        if name in challengers:
            entry["paired_vs_v3"] = result["differences"][f"{name}-{ch.INCUMBENT}"]
        candidates.append(entry)
    fa_v3 = result["metrics"][ch.INCUMBENT][ch.HEADLINE]["value"]
    eligible = [{"name": n, "fa": result["metrics"][n][ch.HEADLINE]["value"],
                 "se": result["differences"][f"{n}-{ch.INCUMBENT}"]["se"]} for n in challengers if metas[n]["adoptable"]]
    adopted = ch.choose_adoption(fa_v3, eligible)
    table = []
    for n in challengers:
        diff = result["differences"][f"{n}-{ch.INCUMBENT}"]
        table.append({"name": n, "adoptable": metas[n]["adoptable"], **ch.adoption(fa_v3, result["metrics"][n][ch.HEADLINE]["value"],
                                                                                   diff["se"])})
    probe_path = ch.oof_dir(cfg) / PROBE_FILE
    return {
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "config": hm.display_path(Path(config)), "incumbent": ch.INCUMBENT, "frozen_v2": ch.FROZEN_V2,
        "protocol": "protocol v2: year-blocked CV over 2007-2017, pooled OOF FA@90 on the weighted universe, "
                    "bootstrap of positives as events and universe rows iid within year-region strata",
        "bootstrap": {"n": boot["n"], "seed": boot["seed"], "level": boot["level"]},
        "reproduction": reproduction, "rows": rows,
        "candidates": candidates,
        "v3_vs_v2": {**result["differences"][f"{ch.INCUMBENT}-{ch.FROZEN_V2}"],
                     "better_than_v2": bool(result["differences"][f"{ch.INCUMBENT}-{ch.FROZEN_V2}"]["ci_hi"] < 0)},
        "adoption": {"rule": "a challenger replaces the selected v3 configuration only if its pooled OOF FA@90 is "
                             "lower by MORE than the bootstrap SE of the paired difference",
                     "incumbent_fa_at_90": fa_v3, "evaluated": table, "adopted": adopted},
        "multiple_comparisons": {"n_challengers": len(challengers),
                                 "note": f"{len(challengers)} challenger candidates were compared with the same "
                                         "development rows; the chance that the best of them looks better than it is "
                                         "grows with that number. The single look at test_2018 is the check."},
        "susceptibility_probe": (json.loads(probe_path.read_text(encoding="utf-8")) if probe_path.is_file() else None),
        "seconds": seconds,
    }


def _ci(entry: dict, digits: int = 4) -> str:
    return f"{_num(entry['value'], digits)} [{_num(entry['lo'], digits)}, {_num(entry['hi'], digits)}]"


def _diff_cell(d: dict) -> str:
    return (f"{_num(d['point_difference'], 4)} [{_num(d['ci_lo'], 4)}, {_num(d['ci_hi'], 4)}]"
            f"{' *' if d['excludes_zero'] else ''}")


def render_markdown(payload: dict) -> str:
    lines = ["# Challenger experiments (Task 5)", "",
             f"Protocol: {payload['protocol']}. Bootstrap n={payload['bootstrap']['n']}, seed "
             f"{payload['bootstrap']['seed']}, level {payload['bootstrap']['level']}. Config `{payload['config']}`.", "",
             "## Reproduction check", ""]
    rows = [[k, v["name"], _num(v["reported_fa_at_90"], 6), _num(v["recomputed_fa_at_90"], 6),
             _num(v["abs_difference"], 6), f"{v['reported_n_trees']} / {v['n_trees']}"]
            for k, v in payload["reproduction"].items()]
    lines += [_table(["scorer", "selected group", "reported FA@90", "recomputed FA@90", "abs difference",
                      "trees (reported / recomputed)"], rows), "",
              f"Development rows (identical for v2 and v3, checked key by key): {payload['rows']['positives']} positives, "
              f"{payload['rows']['universe']:,} universe negatives, {payload['rows']['matched']} matched negatives.", ""]
    v = payload["v3_vs_v2"]
    verdict = ("the interval excludes zero: v3-live beats frozen v2" if v["better_than_v2"] else
               "the interval does not exclude zero in favour of v3-live" if not v["excludes_zero"] else
               "the interval excludes zero in favour of frozen v2")
    lines += ["## Selected v3-live versus frozen v2 (paired)", "",
              f"FA@90 v3 {_num(v['fa_a'])} versus v2 {_num(v['fa_b'])}: point difference "
              f"{_num(v['point_difference'], 4)}, bootstrap mean {_num(v['mean_difference'], 4)}, SE {_num(v['se'], 4)}, "
              f"{int(100 * v['level'])}% CI [{_num(v['ci_lo'], 4)}, {_num(v['ci_hi'], 4)}]; {verdict}. "
              f"Share of resamples with v3 better: {_num(v['share_a_better'], 3)}.", "",
              "## All candidates (pooled OOF)", "",
              "Difference = FA@90(candidate) - FA@90(selected v3), one shared resample; `*` = the interval excludes 0; "
              "negative favours the candidate.", ""]
    body = []
    for c in payload["candidates"]:
        m = c["metrics"]
        body.append([c["name"], c["family"], "n/a" if c["n_inputs"] is None else str(c["n_inputs"]),
                     "n/a" if c["n_trees"] is None else str(c["n_trees"]), _ci(m[ch.HEADLINE]),
                     _diff_cell(c["paired_vs_v3"]) if "paired_vs_v3" in c else "",
                     _ci(m["recall_at_fa_0.01"]), _ci(m["recall_at_fa_0.05"]), _num(c["logloss"], 4)])
    lines += [_table(["candidate", "family", "inputs", "trees", "FA@90 [95% CI]", "difference vs v3 [95% CI]",
                      "recall @ FA 1%", "recall @ FA 5%", "design log-loss"], body), "", "## Descriptions", ""]
    lines += [f"- `{c['name']}`: {c['description']}" for c in payload["candidates"]]
    a = payload["adoption"]
    lines += ["", "## Adoption", "", a["rule"] + ".", "",
              _table(["challenger", "adoptable", "gain over v3", "paired SE", "gain / SE", "replaces v3"],
                     [[e["name"], "yes" if e["adoptable"] else "no", _num(e["gain"], 4), _num(e["se"], 4),
                       _num(e["gain_over_se"], 2), "yes" if e["adopt"] and e["adoptable"] else "no"]
                      for e in a["evaluated"]]), "",
              (f"Adopted: `{a['adopted']['name']}`." if a["adopted"] else
               "Adopted: none. The selected v3-live configuration is unchanged."), ""]
    lines += ["## Caveat on multiple comparisons", "", payload["multiple_comparisons"]["note"], ""]
    probe = payload.get("susceptibility_probe")
    if probe:
        lines += ["## Static susceptibility prior (probe)", "", f"{probe['summary']}", ""]
    lines += [f"Runtime {payload['seconds']:.0f} s.", ""]
    return "\n".join(lines)


def write_report(cfg: dict, config: Path, frames: dict, metas: dict, reproduction: dict, rows: dict,
                 seconds: float, report_dir: Path | None = None) -> dict:
    payload = build_payload(cfg, config, frames, metas, reproduction, rows, seconds)
    reports = Path(report_dir) if report_dir is not None else PROJECT_ROOT / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    stem = ch.challenger_settings(cfg).get("report_stem", ch.DEFAULT_REPORT_STEM)
    dump_json(reports / f"{stem}.json", payload)
    (reports / f"{stem}.md").write_text(render_markdown(payload), encoding="utf-8")
    return payload
