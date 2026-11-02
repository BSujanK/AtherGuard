"""Probe registry, safe execution and the audit command line."""
from __future__ import annotations

import argparse
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import requests

from ..config import PROJECT_ROOT, data_root, load_config
from ..http import DownloadError
from ..manifest import Manifest
from . import env, feasibility, ghcnd, labels, rain, static, zenodo
from .report import collect_secrets, redact, write_reports
from .result import ProbeResult, failure_status

PARTIAL_DIR_NAME = "partial"  # --only runs go to reports/partial/ so they never overwrite the full report


@dataclass
class Context:
    audit_cfg: dict
    domain_cfg: dict
    data_root: Path
    manifest: Manifest
    lat: float
    lon: float
    dates: list[str]

    @property
    def period_days(self) -> int:
        return feasibility._period_days(self.domain_cfg)


def build_registry() -> dict[str, Callable[[Context], ProbeResult | list[ProbeResult]]]:
    return {
        "geolibs": lambda c: env.probe_geolibs(),
        "disk": lambda c: env.probe_disk(c.data_root, c.audit_cfg["disk"]["min_free_gb"]),
        "earthdata_credentials": lambda c: env.probe_earthdata_credentials(),
        "ghcnd": lambda c: ghcnd.probe_ghcnd(c.data_root, c.manifest, c.audit_cfg),
        "isd": lambda c: ghcnd.probe_isd_history(c.data_root, c.manifest, c.audit_cfg),
        "open_meteo": lambda c: rain.probe_open_meteo(c.lat, c.lon, c.dates),
        "power_api": lambda c: rain.probe_power_api(c.lat, c.lon, c.dates),
        "power_zarr": lambda c: rain.probe_power_zarr(c.lat, c.lon, c.dates),
        "chirps": lambda c: rain.probe_chirps(c.dates, c.lat, c.lon, c.data_root, c.manifest, c.period_days),
        "imd": lambda c: rain.probe_imd(c.lat, c.lon, c.dates, c.data_root, c.manifest),
        "dem": lambda c: static.probe_dem(c.lat, c.lon, c.data_root, c.manifest),
        "worldcover": lambda c: static.probe_worldcover(c.lat, c.lon),
        "soilgrids": lambda c: static.probe_soilgrids(c.lat, c.lon),
        "osm_roads": lambda c: static.probe_osm_roads(),
        "nepal_inventories": lambda c: zenodo.probe_nepal_inventories(),
        "gaolan": lambda c: zenodo.probe_gaolan(),
        "lithology_search": lambda c: zenodo.probe_lithology_search(),
        "kerala_inventory_search": lambda c: zenodo.probe_kerala_inventory_search(),
        "manual_catalogs": lambda c: labels.probe_manual_catalogs(c.data_root, c.audit_cfg),
        "feasibility": lambda c: feasibility.probe_feasibility(c.domain_cfg, c.audit_cfg),
    }


def safe(name: str, fn, ctx) -> list[ProbeResult]:
    """Run one probe; a failure becomes a result and never aborts the audit."""
    try:
        out = fn(ctx)
    except DownloadError as exc:  # non-retriable (e.g. 404) is a real failure, retriable is reachability
        return [ProbeResult(name, failure_status([exc]), f"download error: {exc}")]
    except requests.RequestException as exc:
        return [ProbeResult(name, "unreachable", f"network error: {exc}")]
    except Exception as exc:  # a probe bug must not abort the audit
        return [ProbeResult(name, "inconclusive", f"probe raised {type(exc).__name__}: {exc}",
                            {"traceback": traceback.format_exc(limit=5)})]
    if isinstance(out, ProbeResult):
        return [out]
    if isinstance(out, (list, tuple)) and all(isinstance(item, ProbeResult) for item in out):
        return list(out)
    return [ProbeResult(name, "inconclusive", f"probe returned {type(out).__name__} instead of ProbeResult(s)")]


def run_audit(only: set[str] | None = None, reports_dir: Path | None = None,
              manifest_path: Path | None = None, *, default_reports_dir: Path | None = None
              ) -> list[ProbeResult]:
    registry = build_registry()
    unknown = (only or set()) - set(registry)
    if unknown:  # reject before any side effect (config load, directories, manifest)
        raise SystemExit(f"unknown probe name(s): {sorted(unknown)}; choose from {sorted(registry)}")
    audit_cfg, domain_cfg = load_config("audit"), load_config("domain")
    root = data_root()
    root.mkdir(parents=True, exist_ok=True)
    manifest = Manifest(manifest_path or PROJECT_ROOT / "manifests" / "data_manifest.jsonl", root)
    point = audit_cfg["reference_point"]
    ctx = Context(audit_cfg, domain_cfg, root, manifest, point["lat"], point["lon"], audit_cfg["event_dates"])
    results: list[ProbeResult] = []
    for name, fn in registry.items():
        if only and name not in only:
            continue
        print(f"[audit] {name} ...", flush=True)
        results += safe(name, fn, ctx)
    full_dir = default_reports_dir or PROJECT_ROOT / "reports"
    out_dir = reports_dir or (full_dir / PARTIAL_DIR_NAME if only else full_dir)
    print(f"[audit] writing reports to {out_dir}", flush=True)
    md, js = write_reports(results, out_dir, collect_secrets(), audit_cfg, manifest.entries())
    problems = manifest.verify()
    print(f"[audit] wrote {md} and {js}; manifest problems: {problems or 'none'}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Phase 0 data audit.")
    parser.add_argument("--only", default="", help="comma-separated probe names (default: all)")
    parser.add_argument("--reports-dir", default=None, type=Path)
    args = parser.parse_args()
    only = {n.strip() for n in args.only.split(",") if n.strip()} or None
    secrets = collect_secrets()
    for result in run_audit(only, args.reports_dir):
        # redact the whole summary first: truncating first could leave a fragment of a secret visible
        print(f"{result.status:>15}  {result.name:<24} {redact(result.summary, secrets)[:90]}")


if __name__ == "__main__":
    main()
