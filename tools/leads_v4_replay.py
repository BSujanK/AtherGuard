"""W7 E2: scratch replays of archived live days in backtest mode, one candidate set at a time, never into data/live.

    python tools/leads_v4_replay.py <out_dir> <set: c|a|b> <first YYYY-MM-DD> <last YYYY-MM-DD>

Sets (docs/superpowers/specs/2026-11-14-aetherguard-leads-v4.md section 3): c = the incumbent (leads by v3, the configuration
of the main tree), a = leads by v4 at the selected forecast rain, b = a with the expected risk over the ensemble. Lead 0 is
v4 in every set. Run with PYTHONPATH at this worktree's src, AETHERGUARD_DATA_DIR at the real data, from the worktree (its
`data` junction). Resumable: a day whose run.json exists in the set is skipped; `replay_summary.json` lists every day done.
"""
import json
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

REAL = Path(r"C:\Users\sujan\AtherGuard")
STUDY = "data/processed/lead_intensity"
LEAD_INTENSITY = {"maps_file": f"{STUDY}/intensity_maps.json", "late_root": f"{STUDY}/imerg_hh", "early_root": f"{STUDY}/imerg_hh"}


def main() -> int:
    out, name = Path(sys.argv[1]), sys.argv[2]
    first, last = date.fromisoformat(sys.argv[3]), date.fromisoformat(sys.argv[4])
    import aetherguard
    from aetherguard.live import run as live_run
    from aetherguard.live.sources import project_path
    print("code:", aetherguard.__file__, flush=True)
    set_dir = out / name
    cfg = live_run.load_run_config()
    cfg.update(live_dir=str(set_dir / "live"), report_dir=str(set_dir / "reports"), replay_dir=str(set_dir / "replay"))
    if name in ("a", "b"):
        cfg[live_run.LEAD_KEY] = cfg[live_run.LEAD0_KEY]
        cfg["lead_intensity"] = {**LEAD_INTENSITY, "expected_risk": name == "b"}
    live = set_dir / "live"
    (live / "cache").mkdir(parents=True, exist_ok=True)
    for cached in ("imerg_climatology.npz", "station_climatology.parquet"):
        if not (live / "cache" / cached).is_file():
            shutil.copy2(REAL / "data" / "live" / "cache" / cached, live / "cache" / cached)
    for folder in sorted((REAL / "data" / "live").iterdir()):       # the IMD files the real runs received, as the run cache
        source = folder / "raw" / "imd_rt"
        if source.is_dir():
            target = live / folder.name / "raw" / "imd_rt"
            target.mkdir(parents=True, exist_ok=True)
            for f in source.glob("*.grd"):
                if not (target / f.name).is_file():
                    shutil.copy2(f, target / f.name)
    deps = live_run.LiveDeps(intensity_root=project_path(LEAD_INTENSITY["late_root"]))
    summary_path = set_dir / "replay_summary.json"
    done = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.is_file() else {}
    day = first
    while day <= last:
        if day.isoformat() in done and (live / day.isoformat() / "run.json").is_file():
            day += timedelta(days=1)
            continue
        summary = live_run.run_day(day, cfg, force=True, backtest=True, deps=deps)
        done[day.isoformat()] = {
            "model": summary["model"]["dir"], "forecast_model": (summary.get("forecast_model") or {}).get("dir"),
            "intensity_used": summary.get("intensity", {}).get("used"), "lead_intensity": summary.get("lead_intensity"),
            "levels": {k: v.get("levels") for k, v in summary["leads"].items()},
            "expected_risk": {k: v.get("expected_risk") is not None for k, v in summary["leads"].items() if k != "0"},
            "forecast": {k: v.get("forecast") for k, v in summary["leads"].items() if k != "0"},
            "audit": summary["audit"]["total_violations"],
            "audit_violations": {k: v for k, v in summary["audit"]["violations"].items() if v}}
        print(day, name, json.dumps(done[day.isoformat()]["levels"]), "audit", done[day.isoformat()]["audit"], flush=True)
        summary_path.write_text(json.dumps(done, indent=1), encoding="utf-8")
        day += timedelta(days=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
