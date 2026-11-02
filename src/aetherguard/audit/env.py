"""Environment probes: geospatial stack, disk space, Earthdata credential presence."""
from __future__ import annotations

import importlib
import netrc
import os
import platform
import shutil
import sys
from pathlib import Path

from .result import ProbeResult

_MODULES = ("numpy", "pandas", "pyarrow", "rasterio", "shapely", "pyproj", "yaml", "requests")


def _python_is_supported() -> bool:
    return sys.version_info[:2] == (3, 13)


def probe_geolibs() -> ProbeResult:
    versions: dict[str, str] = {}
    missing: list[str] = []
    for name in _MODULES:
        try:
            module = importlib.import_module(name)
            versions[name] = str(getattr(module, "__version__", "unknown"))
        except Exception as exc:  # binary mismatch (ValueError), DLL failure (OSError), ImportError, ...
            missing.append(f"{name}: {type(exc).__name__}: {exc}")
            continue
        if name == "rasterio":
            try:
                versions["gdal"] = str(module.__gdal_version__)
            except Exception as exc:
                missing.append(f"rasterio gdal version: {type(exc).__name__}: {exc}")
    versions["python"] = platform.python_version()
    python_ok = _python_is_supported()
    problems = []
    if missing:
        problems.append(f"modules failed: {missing}")
    if not python_ok:
        problems.append(f"interpreter is Python {versions['python']}, not 3.13")
    ok = not problems
    summary = "geospatial stack imports on Python 3.13" if ok else "problems: " + "; ".join(problems)
    return ProbeResult("geolibs", "ok" if ok else "fail", summary, {"versions": versions, "missing": missing})


def probe_disk(path, min_free_gb: float) -> ProbeResult:
    try:
        usage = shutil.disk_usage(Path(path))
    except OSError as exc:
        return ProbeResult("disk", "fail", f"cannot read disk usage for {path}: {exc}",
                           {"path": str(path), "required_free_gb": min_free_gb})
    free_gb = round(usage.free / 1e9, 1)
    evidence = {"free_gb": free_gb, "total_gb": round(usage.total / 1e9, 1),
                "cpu_count": os.cpu_count(), "required_free_gb": min_free_gb}
    ok = free_gb >= min_free_gb
    return ProbeResult("disk", "ok" if ok else "fail",
                       f"{free_gb} GB free (need {min_free_gb} GB)", evidence)


def netrc_candidate_paths() -> list[Path]:
    """Existing netrc files in the home directory: `.netrc` (POSIX) and `_netrc` (Windows)."""
    home = Path(os.path.expanduser("~"))
    return [path for path in (home / ".netrc", home / "_netrc") if path.is_file()]


def _netrc_has_earthdata_entry() -> bool:
    for path in netrc_candidate_paths():
        try:
            if netrc.netrc(str(path)).authenticators("urs.earthdata.nasa.gov") is not None:
                return True
        except (netrc.NetrcParseError, OSError, UnicodeDecodeError):
            continue  # an unreadable or malformed file is simply "no credentials here"
    return False


def probe_earthdata_credentials() -> ProbeResult:
    """Report only whether credentials exist - never their values."""
    env_vars = bool(os.environ.get("EARTHDATA_TOKEN")
                    or (os.environ.get("EARTHDATA_USERNAME") and os.environ.get("EARTHDATA_PASSWORD")))
    in_netrc = _netrc_has_earthdata_entry()
    evidence = {"env_vars": env_vars, "netrc": in_netrc}
    if env_vars or in_netrc:
        return ProbeResult("earthdata_credentials", "ok", "Earthdata credentials are configured", evidence)
    return ProbeResult(
        "earthdata_credentials", "needs_login",
        "no Earthdata credentials found; create a free account at urs.earthdata.nasa.gov and set "
        "EARTHDATA_USERNAME / EARTHDATA_PASSWORD (or a .netrc entry) to unlock the HMA catalog and IMERG",
        evidence)
