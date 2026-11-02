from aetherguard.audit import zenodo


def test_summarize_record_legacy_file_list():
    rec = {"id": 1, "doi": "10.5281/zenodo.1",
           "metadata": {"title": "T", "license": {"id": "cc-by-4.0"}},
           "files": [{"key": "a.zip", "size": 100}, {"key": "b.zip", "size": 50}]}
    out = zenodo.summarize_record(rec)
    assert out["title"] == "T" and out["license"] == "cc-by-4.0"
    assert out["n_files"] == 2 and out["total_bytes"] == 150
    assert out["files"] == ["a.zip", "b.zip"]


def test_summarize_record_newer_entries_schema_and_missing_license():
    rec = {"id": 2, "metadata": {"title": "T2"},
           "files": {"entries": {"x.csv": {"key": "x.csv", "size": 7}}}}
    out = zenodo.summarize_record(rec)
    assert out["n_files"] == 1 and out["total_bytes"] == 7
    assert out["license"] is None


def test_probe_record_reports_size_and_license(monkeypatch):
    monkeypatch.setattr(zenodo, "fetch_json", lambda *a, **k: {
        "id": 3, "metadata": {"title": "Big", "license": {"id": "cc-by-4.0"}},
        "files": [{"key": "m.7z", "size": 5 * 10**9}]})
    res = zenodo.probe_zenodo_record("gaolan", "15180387", "note")
    assert res.status == "ok"
    assert res.evidence["total_bytes"] == 5 * 10**9


def test_probe_search_fails_when_nothing_found(monkeypatch):
    monkeypatch.setattr(zenodo, "fetch_json", lambda *a, **k: {"hits": {"hits": []}})
    assert zenodo.probe_zenodo_search("lithology_search", "nothing").status == "fail"


def _rec(files, license_id="cc-by-4.0", title="T"):
    meta = {"title": title}
    if license_id:
        meta["license"] = {"id": license_id}
    return {"id": 9, "metadata": meta, "files": files}


def _patch_record(monkeypatch, rec):
    monkeypatch.setattr(zenodo, "fetch_json", lambda *a, **k: rec)


def test_record_with_zero_files_is_partial(monkeypatch):
    _patch_record(monkeypatch, _rec([]))
    res = zenodo.probe_zenodo_record("x", "1", "n")
    assert res.status == "partial" and "no files" in res.summary


def test_record_with_unsized_file_is_partial_and_counts_it(monkeypatch):
    _patch_record(monkeypatch, _rec([{"key": "a", "size": 10}, {"key": "b"}]))
    res = zenodo.probe_zenodo_record("x", "1", "n")
    assert res.status == "partial"
    assert res.evidence["n_unsized_files"] == 1 and res.evidence["total_bytes"] == 10
    assert "size" in res.summary


def test_record_without_licence_is_partial(monkeypatch):
    _patch_record(monkeypatch, _rec([{"key": "a", "size": 10}], license_id=None))
    res = zenodo.probe_zenodo_record("x", "1", "n")
    assert res.status == "partial" and "licence" in res.summary


def test_summarize_record_tolerates_null_fields():
    out = zenodo.summarize_record({"id": 1, "metadata": None,
                                   "files": [{"key": "a", "size": None}, {"key": "b", "size": 5}]})
    assert out["title"] is None and out["license"] is None
    assert out["n_unsized_files"] == 1 and out["total_bytes"] == 5 and out["n_files"] == 2
    assert zenodo.summarize_record({"files": None, "metadata": {"license": None}})["n_files"] == 0


def test_search_with_good_top_hit_is_ok_but_says_candidates(monkeypatch):
    monkeypatch.setattr(zenodo, "fetch_json", lambda *a, **k: {"hits": {"hits": [
        _rec([{"key": "a", "size": 1}], title="GLiM")]}})
    res = zenodo.probe_zenodo_search("s", "q")
    assert res.status == "ok" and "candidates" in res.summary
    assert len(res.evidence["hits"]) == 1


def test_search_partial_when_top_hit_lacks_title_or_files(monkeypatch):
    for top in (_rec([{"key": "a", "size": 1}], title=""), _rec([], title="Has title")):
        monkeypatch.setattr(zenodo, "fetch_json",
                            lambda *a, _top=top, **k: {"hits": {"hits": [_top, _rec([{"key": "b"}])]}})
        res = zenodo.probe_zenodo_search("s", "q")
        assert res.status == "partial" and "candidates" in res.summary
        assert len(res.evidence["hits"]) == 2


def test_search_hit_without_metadata_does_not_raise(monkeypatch):
    monkeypatch.setattr(zenodo, "fetch_json", lambda *a, **k: {"hits": {"hits": [{"id": 5}]}})
    res = zenodo.probe_zenodo_search("s", "q")
    assert res.status == "partial"
