"""Probes for the hand-placed landslide catalog files."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .landslides import CatalogFormatError, read_catalog_csv, summarize_catalog
from .result import ProbeResult

_NAMES = {"nasa_glc": "catalog_nasa_glc", "hma_ls_cat": "catalog_hma_ls_cat"}
# CatalogFormatError is a ValueError; it is listed for clarity. OSError covers locked files and directories. One unreadable catalog must not abort the others.
_READ_ERRORS = (CatalogFormatError, pd.errors.EmptyDataError, UnicodeDecodeError, ValueError, OSError)


def probe_manual_catalogs(data_root, cfg) -> list[ProbeResult]:
    max_km = cfg["catalog"]["max_accuracy_km"]
    results = []
    for key, rel in cfg["catalog"]["manual_files"].items():
        name = _NAMES.get(key, f"catalog_{key}")
        path = Path(data_root) / rel
        if not path.exists():
            results.append(ProbeResult(
                name, "manual_pending", f"file not found: place the CSV export at data/{rel}",
                {"expected_path": f"data/{rel}"}))
            continue
        try:
            df, report = read_catalog_csv(path)
            summary = summarize_catalog(df, max_km)
        except _READ_ERRORS as exc:
            results.append(ProbeResult(
                name, "fail", f"cannot read {path.name}: {type(exc).__name__}: {exc}", {"path": str(path)}))
            continue
        located = sum(v["n_located"] for k, v in summary.items() if k != "outside_domain")
        evidence = {"report": report.as_dict(), "summary": summary, "max_accuracy_km": max_km}
        status = "ok" if located > 0 else "partial"
        results.append(ProbeResult(
            name, status,
            f"{report.kept_rows} events kept of {report.total_rows}; {located} in-domain within {max_km} km",
            evidence))
    return results
