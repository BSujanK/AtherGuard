from aetherguard.audit import labels

CFG = {"catalog": {"max_accuracy_km": 5.0,
                   "manual_files": {"nasa_glc": "raw/manual/nasa_glc.csv",
                                    "hma_ls_cat": "raw/manual/hma_ls_cat_v2.csv"}}}
HEADER = "event_id,event_date,latitude,longitude,location_accuracy,landslide_trigger,country_name\n"


def test_missing_manual_files_are_pending_not_failed(tmp_path):
    results = {r.name: r for r in labels.probe_manual_catalogs(tmp_path, CFG)}
    assert results["catalog_nasa_glc"].status == "manual_pending"
    assert results["catalog_hma_ls_cat"].status == "manual_pending"
    assert "raw/manual/nasa_glc.csv" in results["catalog_nasa_glc"].summary


def test_present_catalog_is_summarised(tmp_path):
    path = tmp_path / "raw" / "manual" / "nasa_glc.csv"
    path.parent.mkdir(parents=True)
    path.write_text(HEADER + "1,2018-08-16,11.55,76.13,5km,downpour,India\n", encoding="utf-8")
    res = {r.name: r for r in labels.probe_manual_catalogs(tmp_path, CFG)}["catalog_nasa_glc"]
    assert res.status == "ok"
    assert res.evidence["summary"]["western_ghats"]["n_located"] == 1
    assert res.evidence["report"]["kept_rows"] == 1


def test_unreadable_catalog_fails_loudly_with_the_reason(tmp_path):
    path = tmp_path / "raw" / "manual" / "nasa_glc.csv"
    path.parent.mkdir(parents=True)
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    res = {r.name: r for r in labels.probe_manual_catalogs(tmp_path, CFG)}["catalog_nasa_glc"]
    assert res.status == "fail"
    assert "missing required column" in res.summary


def test_catalog_with_no_accurate_in_domain_events_is_partial(tmp_path):
    path = tmp_path / "raw" / "manual" / "nasa_glc.csv"
    path.parent.mkdir(parents=True)
    path.write_text(HEADER + "1,2018-08-16,11.55,76.13,unknown,downpour,India\n", encoding="utf-8")
    res = {r.name: r for r in labels.probe_manual_catalogs(tmp_path, CFG)}["catalog_nasa_glc"]
    assert res.status == "partial"


def test_one_empty_catalog_does_not_abort_the_other(tmp_path):
    manual = tmp_path / "raw" / "manual"
    manual.mkdir(parents=True)
    (manual / "nasa_glc.csv").write_bytes(b"")
    (manual / "hma_ls_cat_v2.csv").write_text(
        HEADER + "1,2018-08-16,11.55,76.13,5km,downpour,India\n", encoding="utf-8")
    results = {r.name: r for r in labels.probe_manual_catalogs(tmp_path, CFG)}
    assert results["catalog_nasa_glc"].status == "fail"
    assert results["catalog_nasa_glc"].summary
    assert results["catalog_hma_ls_cat"].status == "ok"


def test_catalog_path_that_is_a_directory_fails_without_aborting_the_other(tmp_path):
    manual = tmp_path / "raw" / "manual"
    (manual / "nasa_glc.csv").mkdir(parents=True)
    (manual / "hma_ls_cat_v2.csv").write_text(
        HEADER + "1,2018-08-16,11.55,76.13,5km,downpour,India\n", encoding="utf-8")
    results = {r.name: r for r in labels.probe_manual_catalogs(tmp_path, CFG)}
    assert results["catalog_nasa_glc"].status == "fail"
    assert results["catalog_hma_ls_cat"].status == "ok"


def test_permission_error_is_a_per_catalog_failure(tmp_path, monkeypatch):
    manual = tmp_path / "raw" / "manual"
    manual.mkdir(parents=True)
    for name in ("nasa_glc.csv", "hma_ls_cat_v2.csv"):
        (manual / name).write_text(HEADER + "1,2018-08-16,11.55,76.13,5km,downpour,India\n", encoding="utf-8")
    real = labels.read_catalog_csv

    def locked(path):
        if path.name == "nasa_glc.csv":
            raise PermissionError("file is locked")
        return real(path)

    monkeypatch.setattr(labels, "read_catalog_csv", locked)
    results = {r.name: r for r in labels.probe_manual_catalogs(tmp_path, CFG)}
    assert results["catalog_nasa_glc"].status == "fail"
    assert "PermissionError" in results["catalog_nasa_glc"].summary
    assert results["catalog_hma_ls_cat"].status == "ok"
