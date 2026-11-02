"""Zenodo record and search probes (Nepal inventories, Gaolan sensors, lithology, Kerala)."""
from __future__ import annotations

from ..http import DownloadError, fetch_json
from .result import ProbeResult, failure_status

ZENODO_API = "https://zenodo.org/api/records"


def _known_size(f: dict) -> int | None:
    try:
        return int(f.get("size"))
    except (TypeError, ValueError):
        return None


def summarize_record(rec: dict) -> dict:
    meta = rec.get("metadata") or {}
    files = rec.get("files") or []
    if isinstance(files, dict):  # newer schema: {"entries": {name: {...}}}
        files = list((files.get("entries") or {}).values())
    files = [f if isinstance(f, dict) else {} for f in files]
    sizes = [_known_size(f) for f in files]
    licence = meta.get("license")
    return {
        "id": rec.get("id"),
        "doi": rec.get("doi") or meta.get("doi"),
        "title": meta.get("title"),
        "license": licence.get("id") if isinstance(licence, dict) else None,
        "n_files": len(files),
        "n_unsized_files": sum(1 for x in sizes if x is None),
        "total_bytes": sum(x for x in sizes if x is not None),
        "files": [f.get("key") or f.get("filename") for f in files][:20],
    }


def probe_zenodo_record(name: str, record_id: str, note: str) -> ProbeResult:
    try:
        rec = fetch_json(f"{ZENODO_API}/{record_id}")
    except DownloadError as exc:
        return ProbeResult(name, failure_status([exc]), f"Zenodo record {record_id} failed: {exc}")
    info = summarize_record(rec) | {"note": note}
    text = (f"{info['title']} | {info['license']} | "
            f"{info['n_files']} files, {info['total_bytes'] / 1e9:.2f} GB")
    missing = []
    if info["n_files"] == 0:
        missing.append("no files")
    if info["n_unsized_files"]:
        missing.append(f"{info['n_unsized_files']} file(s) without a size")
    if not info["license"]:
        missing.append("no licence id")
    if missing:
        info["missing"] = missing
        return ProbeResult(name, "partial", f"{text}; incomplete: {', '.join(missing)}", info)
    return ProbeResult(name, "ok", text, info)


def probe_zenodo_search(name: str, query: str) -> ProbeResult:
    try:
        data = fetch_json(ZENODO_API, params={"q": query, "size": 5})
    except DownloadError as exc:
        return ProbeResult(name, failure_status([exc]), f"Zenodo search failed: {exc}")
    raw_hits = ((data.get("hits") or {}).get("hits")) or []
    hits = [summarize_record(h if isinstance(h, dict) else {}) for h in raw_hits]
    if not hits:
        return ProbeResult(name, "fail", f"no Zenodo records for query {query!r}", {"query": query, "hits": []})
    top = hits[0]
    top_ok = bool((top["title"] or "").strip()) and top["n_files"] >= 1
    summary = (f"{len(hits)} candidates only (relevance not verified); "
               f"top: {top['title']}")
    if not top_ok:
        summary += "; top hit lacks a title or files"
    return ProbeResult(name, "ok" if top_ok else "partial", summary, {"query": query, "hits": hits})


def probe_nepal_inventories() -> ProbeResult:
    return probe_zenodo_record(
        "nepal_inventories", "10410752",
        "Database of 117 Nepal landslide inventories (metadata); each inventory is a separate download.")


def probe_gaolan() -> ProbeResult:
    return probe_zenodo_record(
        "gaolan", "15180387",
        "Gaolan Mountain loess-slope multi-sensor dataset (China): real physics, no fault labels documented.")


def probe_lithology_search() -> ProbeResult:
    return probe_zenodo_search("lithology_search", "global lithological map GLiM")


def probe_kerala_inventory_search() -> ProbeResult:
    return probe_zenodo_search("kerala_inventory_search", "Kerala landslide inventory 2018")
