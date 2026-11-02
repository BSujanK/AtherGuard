import importlib
import json

from aetherguard.audit import env


def test_geolibs_reports_versions_on_this_interpreter():
    res = env.probe_geolibs()
    assert res.evidence["versions"]["rasterio"]
    assert res.evidence["versions"]["python"].startswith("3.13")
    assert res.status == "ok"


def test_disk_probe_thresholds(tmp_path):
    assert env.probe_disk(tmp_path, min_free_gb=0.001).status == "ok"
    assert env.probe_disk(tmp_path, min_free_gb=10**9).status == "fail"


def test_disk_probe_on_missing_path_fails_explicitly(tmp_path):
    res = env.probe_disk(tmp_path / "missing", 1)
    assert res.status == "fail"
    assert "missing" in res.summary


def test_earthdata_presence_never_exposes_values(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("EARTHDATA_USERNAME", "someone-name")
    monkeypatch.setenv("EARTHDATA_PASSWORD", "hunter2-secret")
    res = env.probe_earthdata_credentials()
    assert res.status == "ok"
    assert res.evidence["env_vars"] is True
    dumped = json.dumps(res.as_dict())
    assert "hunter2-secret" not in dumped and "someone-name" not in dumped


def test_earthdata_missing_means_needs_login(monkeypatch, tmp_path):
    monkeypatch.delenv("EARTHDATA_USERNAME", raising=False)
    monkeypatch.delenv("EARTHDATA_PASSWORD", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    res = env.probe_earthdata_credentials()
    assert res.status == "needs_login"
    assert res.evidence == {"env_vars": False, "netrc": False}


def _patch_imports(monkeypatch, broken: dict):
    real = importlib.import_module

    def fake(name, *args, **kwargs):
        if name in broken:
            raise broken[name]
        return real(name, *args, **kwargs)

    monkeypatch.setattr(env.importlib, "import_module", fake)


def test_geolibs_value_error_on_import_is_a_reported_failure(monkeypatch):
    _patch_imports(monkeypatch, {"pandas": ValueError("numpy.dtype size changed")})
    res = env.probe_geolibs()
    assert res.status == "fail"
    assert any(m.startswith("pandas: ValueError: numpy.dtype size changed") for m in res.evidence["missing"])
    assert "pandas" in res.summary


def test_geolibs_os_error_and_import_error_are_reported_failures(monkeypatch):
    _patch_imports(monkeypatch, {"rasterio": OSError("DLL load failed"), "shapely": ImportError("no shapely")})
    res = env.probe_geolibs()
    assert res.status == "fail"
    missing = " | ".join(res.evidence["missing"])
    assert "rasterio: OSError: DLL load failed" in missing
    assert "shapely: ImportError: no shapely" in missing


def test_geolibs_gdal_version_lookup_failure_is_guarded(monkeypatch):
    import rasterio
    monkeypatch.delattr(rasterio, "__gdal_version__", raising=False)
    res = env.probe_geolibs()
    assert res.status == "fail"
    assert any(m.startswith("rasterio gdal version:") for m in res.evidence["missing"])


def test_geolibs_summary_reports_both_missing_modules_and_wrong_python(monkeypatch):
    _patch_imports(monkeypatch, {"pyproj": ImportError("no pyproj")})
    monkeypatch.setattr(env, "_python_is_supported", lambda: False)
    res = env.probe_geolibs()
    assert res.status == "fail"
    assert "pyproj" in res.summary and "3.13" in res.summary


# --- final review fixes: Windows _netrc and EARTHDATA_TOKEN -------------------------------------

def _clean_home(monkeypatch, tmp_path):
    for var in ("EARTHDATA_USERNAME", "EARTHDATA_PASSWORD", "EARTHDATA_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))


def test_windows_underscore_netrc_counts_and_values_stay_out_of_evidence(monkeypatch, tmp_path):
    from aetherguard.audit.report import collect_secrets
    _clean_home(monkeypatch, tmp_path)
    (tmp_path / "_netrc").write_text(
        "machine urs.earthdata.nasa.gov login win-login-xx password win-pass-word-xx\n", encoding="utf-8")
    res = env.probe_earthdata_credentials()
    assert res.status == "ok"
    assert res.evidence == {"env_vars": False, "netrc": True}
    dumped = json.dumps(res.as_dict())
    assert "win-login-xx" not in dumped and "win-pass-word-xx" not in dumped
    assert {"win-login-xx", "win-pass-word-xx"} <= set(collect_secrets())


def test_netrc_without_an_earthdata_entry_is_not_credentials(monkeypatch, tmp_path):
    _clean_home(monkeypatch, tmp_path)
    (tmp_path / "_netrc").write_text("machine example.org login someone password something-else\n",
                                     encoding="utf-8")
    (tmp_path / ".netrc").write_text("this is not a valid netrc file\n", encoding="utf-8")
    res = env.probe_earthdata_credentials()
    assert res.status == "needs_login" and res.evidence == {"env_vars": False, "netrc": False}


def test_earthdata_token_alone_counts_and_is_redacted(monkeypatch, tmp_path):
    from aetherguard.audit.report import collect_secrets, redact
    _clean_home(monkeypatch, tmp_path)
    monkeypatch.setenv("EARTHDATA_TOKEN", "tok-0123456789-abcdef")
    res = env.probe_earthdata_credentials()
    assert res.status == "ok"
    assert res.evidence == {"env_vars": True, "netrc": False}
    assert "tok-0123456789-abcdef" not in json.dumps(res.as_dict())
    assert "tok-0123456789-abcdef" in collect_secrets()
    assert "tok-0123456789-abcdef" not in redact("header tok-0123456789-abcdef end", collect_secrets())
