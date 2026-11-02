from aetherguard.audit import static


def test_dem_tile_naming_matches_the_published_pattern():
    assert static.dem_tile_name(11.55, 76.13) == "Copernicus_DSM_COG_10_N11_00_E076_00_DEM"
    assert static.dem_tile_name(-0.5, -0.5) == "Copernicus_DSM_COG_10_S01_00_W001_00_DEM"
    assert static.dem_tile_url(11.55, 76.13).endswith(
        "Copernicus_DSM_COG_10_N11_00_E076_00_DEM/Copernicus_DSM_COG_10_N11_00_E076_00_DEM.tif")


def test_worldcover_tiles_are_three_degree_blocks():
    assert static.worldcover_tile_name(11.55, 76.13) == "ESA_WorldCover_10m_2021_v200_N09E075_Map.tif"
    assert static.worldcover_tile_name(-4.0, -70.0) == "ESA_WorldCover_10m_2021_v200_S06W072_Map.tif"


def test_tiles_needed_counts_partial_tiles():
    himalaya = {"lat_min": 22.0, "lat_max": 36.0, "lon_min": 72.0, "lon_max": 98.0}
    ghats = {"lat_min": 8.0, "lat_max": 21.5, "lon_min": 72.5, "lon_max": 78.5}
    assert static.tiles_needed(himalaya, 1.0) == 14 * 26
    assert static.tiles_needed(ghats, 1.0) == 14 * 7
    assert static.domain_tile_count(1.0) == 364 + 98
    assert static.domain_tile_count(3.0) == 45 + 18


def test_probe_dem_returns_fail_on_a_corrupt_tile_instead_of_raising(monkeypatch, tmp_path):
    def fake_download(url, dest, manifest, *args, **kwargs):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"this is not a GeoTIFF")

    monkeypatch.setattr(static, "download", fake_download)
    res = static.probe_dem(11.55, 76.13, tmp_path, None)
    assert res.name == "dem"
    assert res.status == "fail"


class _FakeHead:
    def __init__(self, status=200, headers=None):
        self.status_code = status
        self.headers = headers if headers is not None else {}


def _patch_head(monkeypatch, responder):
    monkeypatch.setattr(static.requests, "head", lambda url, **kw: responder(url))


def _india_or_nepal(url):
    return "india" if "india" in url else "nepal"


def test_worldcover_without_content_length_is_partial_with_unknown_size(monkeypatch):
    _patch_head(monkeypatch, lambda url: _FakeHead(200, {}))
    res = static.probe_worldcover(11.55, 76.13)
    assert res.status == "partial"
    assert res.evidence["tile_bytes"] is None and res.evidence["est_total_gb"] is None
    assert "unknown" in res.summary


def test_worldcover_with_garbled_content_length_is_partial_and_does_not_raise(monkeypatch):
    _patch_head(monkeypatch, lambda url: _FakeHead(200, {"Content-Length": "abc"}))
    res = static.probe_worldcover(11.55, 76.13)
    assert res.status == "partial"
    assert res.evidence["tile_bytes"] is None and res.evidence["est_total_gb"] is None


def test_worldcover_with_valid_content_length_is_ok(monkeypatch):
    _patch_head(monkeypatch, lambda url: _FakeHead(200, {"Content-Length": "1000000000"}))
    res = static.probe_worldcover(11.55, 76.13)
    assert res.status == "ok" and res.evidence["tile_bytes"] == 10**9
    assert res.evidence["est_total_gb"] == round(static.domain_tile_count(3.0), 1)


def test_osm_one_region_404_is_partial_and_the_summary_names_it(monkeypatch):
    def responder(url):
        if _india_or_nepal(url) == "india":
            return _FakeHead(200, {"Content-Length": "1600000000"})
        return _FakeHead(404)

    _patch_head(monkeypatch, responder)
    res = static.probe_osm_roads()
    assert res.status == "partial"
    assert "nepal" in res.summary and "excludes nepal" in res.summary
    assert any("nepal" in e and "404" in e for e in res.evidence["errors"])


def test_osm_all_404_is_fail_not_unreachable(monkeypatch):
    _patch_head(monkeypatch, lambda url: _FakeHead(404))
    assert static.probe_osm_roads().status == "fail"


def test_osm_all_503_is_unreachable(monkeypatch):
    _patch_head(monkeypatch, lambda url: _FakeHead(503))
    assert static.probe_osm_roads().status == "unreachable"


def test_osm_all_connection_errors_are_unreachable(monkeypatch):
    def responder(url):
        raise static.requests.ConnectionError("down")

    _patch_head(monkeypatch, responder)
    assert static.probe_osm_roads().status == "unreachable"


def test_osm_missing_content_length_records_none_and_a_problem(monkeypatch):
    def responder(url):
        if _india_or_nepal(url) == "india":
            return _FakeHead(200, {})
        return _FakeHead(200, {"Content-Length": "abc"})

    _patch_head(monkeypatch, responder)
    res = static.probe_osm_roads()
    assert res.evidence["pbf_bytes"] == {"india": None, "nepal": None}
    assert len(res.evidence["errors"]) == 2
    assert res.status == "partial"


def test_osm_all_ok_reports_combined_size(monkeypatch):
    _patch_head(monkeypatch, lambda url: _FakeHead(200, {"Content-Length": "1000000000"}))
    res = static.probe_osm_roads()
    assert res.status == "ok" and "2.0 GB" in res.summary
