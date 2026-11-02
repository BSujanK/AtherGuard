"""Place names of the modelled cells: the GeoNames extract, the label rule, the country from the base-map mask, the build.

Everything is synthetic (a tiny gazetteer and a hand-made mask in tmp_path); nothing is downloaded.
"""
import io
import json
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aetherguard.alerts import store as alert_store
from aetherguard.grid import cell_center, latlon_to_cell
from aetherguard.manifest import Manifest
from aetherguard.serve import basemap as bm
from aetherguard.serve import places as pl

import live_run_helpers as H

TINY = bm.Grid(lat0=27.0, lon0=84.0, rows=20, cols=40)      # lat 27-28, lon 84-86
KM_PER_DEG = 6371.0088 * np.pi / 180


def tiny_mask(border_col=20):
    """India west of lon 85, Nepal east of it."""
    mask = np.full((TINY.rows, TINY.cols), bm.INDIA, dtype=np.uint8)
    mask[:, border_col:] = bm.NEPAL
    return mask


def gazetteer(*rows):
    """(place, lat, lon, population[, country_code[, district[, state]]]) -> a gazetteer frame."""
    out = []
    for i, row in enumerate(rows):
        place, lat, lon, population, *rest = row
        code, district, state = (list(rest) + [None] * 3)[:3] if rest else (None, None, None)
        out.append({"geonameid": i + 1, "place": place, "district": district, "state": state,
                    "country_code": code or "IN", "lat": lat, "lon": lon, "population": population})
    return pd.DataFrame(out)


CELL = (27.525, 84.475)                                      # centre of a cell in the India half of TINY
CELL_ID = int(latlon_to_cell(*CELL))


def label(frame, lat_lon=CELL, mask=None, grid=TINY):
    cell = int(latlon_to_cell(*lat_lon))
    return pl.label_cells([cell], frame, tiny_mask() if mask is None else mask, grid).iloc[0]


# --- the label rule -----------------------------------------------------------------------------

def test_the_score_is_log_population_minus_distance_over_15():
    assert pl.place_score(990, 15.0) == pytest.approx(3.0 - 1.0)
    assert pl.place_score(0, 0.0) == pytest.approx(1.0)


def test_a_town_a_few_km_away_beats_a_hamlet_next_door():
    near = gazetteer(("Hamlet", CELL[0] + 0.009, CELL[1], 300), ("Town", CELL[0] - 0.054, CELL[1], 50_000))
    row = label(near)
    assert row["place"] == "Town" and row["distance_km"] == 6 and row["population"] == 50_000


def test_a_big_city_far_away_does_not_beat_a_village_next_door():
    row = label(gazetteer(("Village", CELL[0] + 0.009, CELL[1], 500), ("City", CELL[0] + 0.72, CELL[1], 1_000_000)))
    assert row["place"] == "Village" and row["distance_km"] == 1


def test_the_distance_is_great_circle_km_from_the_cell_centre_rounded():
    row = label(gazetteer(("Due north", CELL[0] + 0.1, CELL[1], 5000)))
    assert row["distance_km"] == round(0.1 * KM_PER_DEG) == 11
    row = label(gazetteer(("Due east", CELL[0], CELL[1] + 0.1, 5000)))
    assert row["distance_km"] == round(0.1 * KM_PER_DEG * np.cos(np.radians(CELL[0]))) == 10
    assert row["place_lat"] == CELL[0] and row["place_lon"] == pytest.approx(CELL[1] + 0.1)


def test_the_search_is_exact_against_brute_force():
    rng = np.random.default_rng(3)
    frame = gazetteer(*[(f"P{i}", 27.0 + rng.random(), 84.0 + 0.9 * rng.random(), int(10 ** rng.uniform(2.7, 6.5)))
                        for i in range(400)])
    cells = np.unique(latlon_to_cell(27.0 + rng.random(60), 84.0 + 0.9 * rng.random(60)))
    got = pl.label_cells(cells, frame, tiny_mask(), TINY).set_index("cell_id")
    lat, lon = cell_center(cells)
    for cell, la, lo in zip(cells, lat, lon):
        dlat, dlon = np.radians(frame["lat"] - la), np.radians(frame["lon"] - lo)
        a = np.sin(dlat / 2) ** 2 + np.cos(np.radians(la)) * np.cos(np.radians(frame["lat"])) * np.sin(dlon / 2) ** 2
        km = 2 * 6371.0088 * np.arcsin(np.sqrt(a))
        best = frame.iloc[int(np.argmax(pl.place_score(frame["population"], km)))]
        assert got.loc[cell, "place"] == best["place"]


# --- country from the mask -------------------------------------------------------------------------

def test_country_classes_agree_with_the_grid_locate_rule():
    mask = np.random.default_rng(0).integers(0, 5, size=(630, 600), dtype=np.uint8)
    points = [(6.01, 68.01), (11.55, 76.15), (30.4, 79.3), (37.49, 97.99), (5.0, 80.0), (20.0, 98.5)]
    lat, lon = zip(*points)
    got = pl.country_classes(lat, lon, mask, bm.INDIA_GRID)
    for (la, lo), cls in zip(points, got):
        try:
            row, col = bm.INDIA_GRID.locate(la, lo)
            assert cls == mask[row, col]
        except ValueError:
            assert cls == 0


def test_an_india_cell_takes_an_indian_place_even_when_a_nepalese_town_is_nearer():
    mixed = gazetteer(("Across", CELL[0], 85.05, 90_000, "NP", "Parsa", "Province 2"),
                      ("Home", CELL[0] + 0.2, CELL[1], 3000, "IN", "Pune", "Maharashtra"))
    row = label(mixed)
    assert row["place"] == "Home" and row["country"] == "India"


def test_a_nepal_cell_takes_a_nepalese_place_and_is_called_nepal():
    mixed = gazetteer(("Home", 27.525, 85.05, 90_000, "IN"), ("Across", 27.525, 85.50, 4000, "NP", "Parsa", "Province 2"))
    row = label(mixed, (27.525, 85.525))
    assert row["place"] == "Across" and row["country"] == "Nepal" and row["state"] == "Province 2"


def test_a_place_inside_indias_claim_is_india_whatever_geonames_says():
    claimed = gazetteer(("Skardu", CELL[0] + 0.01, CELL[1], 20_000, "PK", "Skardu", "Gilgit-Baltistan"))
    assert label(claimed)["country"] == "India"


def test_a_cell_off_the_three_countries_takes_the_nearest_by_rule_and_its_geonames_country():
    mask = tiny_mask()
    mask[:, :4] = bm.OTHER
    frame = gazetteer(("Nowhere", 27.525, 84.05, 8000, "CN", "Shigatse", "Xizang"), ("Indian town", 27.525, 84.9, 90_000, "IN"))
    row = label(frame, (27.525, 84.025), mask)
    assert row["place"] == "Nowhere" and row["country"] == "China"


def test_a_cell_falls_back_to_any_place_when_its_country_has_none():
    row = label(gazetteer(("Across", 27.525, 85.5, 4000, "NP")), CELL)
    assert row["place"] == "Across" and row["country"] == "India"


def test_missing_district_and_state_stay_missing():
    row = label(gazetteer(("Plain", CELL[0], CELL[1], 800)))
    assert row["district"] is None and row["state"] is None
    row = label(gazetteer(("Half", CELL[0], CELL[1], 800, "IN", "Some district", None)))
    assert row["district"] == "Some district" and row["state"] is None


def test_label_table_has_one_row_per_distinct_cell_sorted_by_id():
    frame = gazetteer(("Only", CELL[0], CELL[1], 800))
    neighbour = int(latlon_to_cell(CELL[0] + 0.05, CELL[1]))
    table = pl.label_cells([neighbour, CELL_ID, neighbour], frame, tiny_mask(), TINY)
    assert list(table.columns) == pl.TABLE_COLUMNS
    assert list(table["cell_id"]) == sorted({CELL_ID, neighbour})


def test_label_cells_rejects_nothing_to_label():
    with pytest.raises(pl.PlacesError, match="no cells"):
        pl.label_cells([], gazetteer(("Only", CELL[0], CELL[1], 800)), tiny_mask(), TINY)
    with pytest.raises(pl.PlacesError, match="no places"):
        pl.label_cells([CELL_ID], gazetteer(), tiny_mask(), TINY)


# --- showing a label --------------------------------------------------------------------------------

def record(**fields):
    base = {"place": "Mananthavady", "district": "Wayanad", "state": "Kerala", "country": "India", "distance_km": 8,
            "place_lat": 11.8, "place_lon": 76.0, "population": 41000}
    return {**base, **fields}


def test_place_name_joins_place_district_state_and_adds_a_foreign_country():
    assert pl.place_name(record()) == "Mananthavady, Wayanad, Kerala"
    assert pl.place_name(record(place="Kathmandu", district=None, state="Bagmati", country="Nepal")) == "Kathmandu, Bagmati, Nepal"
    assert pl.place_name(record(place="Shimla", district="Shimla")) == "Shimla, Kerala"


def test_place_name_marks_a_remote_cell_with_its_distance():
    assert pl.place_name(record(distance_km=24)) == "Mananthavady, Wayanad, Kerala"
    assert pl.place_name(record(distance_km=25)) == "Mananthavady, Wayanad, Kerala (25 km)"


# --- the extract ------------------------------------------------------------------------------------

def city(geonameid, name, ascii_name, lat, lon, code, admin1, admin2, population):
    fields = [geonameid, name, ascii_name, "", lat, lon, "P", "PPL", code, "", admin1, admin2, "", "", population, "", "0", "Asia/Kolkata", "2020-01-01"]
    return "\t".join(str(f) for f in fields)


CITIES = [
    city(1, "Mananthavady", "Mananthavady", 11.8, 76.0, "IN", "19", "598", 41000),
    city(2, "Kāṭhmāṇḍu", "Kathmandu", 27.7172, 85.324, "NP", "P3", "", 1_000_000),
    city(3, "Chamoli", "Chamoli", 30.4, 79.32, "IN", "39", "", 5000),
    city(4, "Lahore", "Lahore", 31.55, 74.34, "PK", "04", "", 11_000_000),
    city(5, "Denver", "Denver", 39.74, -104.99, "US", "CO", "031", 700_000),
    city(6, "Lhasa", "Lhasa", 29.65, 91.1, "CN", "14", "", 200_000),
    city(7, "Harbin", "Harbin", 45.75, 126.63, "CN", "08", "", 5_000_000),
    city(8, "Nameless", "", 27.0, 85.0, "NP", "P3", "", 600),
    city(9, "Ghost", "Ghost", 11.9, 76.1, "IN", "99", "999", 700),
]
ADMIN1 = "IN.19\tKerala\tKerala\t1267254\nIN.39\tUttarakhand\tUttarakhand\t1444366\nNP.P3\tBagmati\tBagmati\t1\n"
ADMIN2 = "IN.19.598\tWayanad\tWayanad\t1\nUS.CO.031\tDenver\tDenver\t2\n"


def write_sources(raw_dir: Path):
    raw_dir.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("cities500.txt", "\n".join(CITIES) + "\n")
    (raw_dir / "cities500.zip").write_bytes(buffer.getvalue())
    (raw_dir / "admin1CodesASCII.txt").write_text(ADMIN1, encoding="utf-8")
    (raw_dir / "admin2Codes.txt").write_text(ADMIN2, encoding="utf-8")


@pytest.fixture
def gazetteer_frame(tmp_path):
    write_sources(tmp_path)
    return pl.extract_places(pl.read_cities(tmp_path / "cities500.zip"), pl.read_admin_names(tmp_path / "admin1CodesASCII.txt"),
                             pl.read_admin_names(tmp_path / "admin2Codes.txt"))


def test_the_extract_keeps_the_home_countries_and_the_box_and_drops_the_rest(gazetteer_frame):
    assert set(gazetteer_frame["place"]) == {"Mananthavady", "Kathmandu", "Chamoli", "Lahore", "Lhasa", "Nameless", "Ghost"}


def test_the_extract_uses_ascii_names_and_resolves_district_and_state(gazetteer_frame):
    rows = gazetteer_frame.set_index("place")
    assert rows.loc["Mananthavady", ["district", "state", "country_code", "population"]].tolist() == ["Wayanad", "Kerala", "IN", 41000]
    assert rows.loc["Kathmandu", "state"] == "Bagmati" and rows.loc["Kathmandu", "district"] is None


def test_the_extract_never_invents_a_name_for_an_unknown_code(gazetteer_frame):
    ghost = gazetteer_frame.set_index("place").loc["Ghost"]
    assert ghost["district"] is None and ghost["state"] is None


def test_the_extract_falls_back_to_the_name_when_there_is_no_ascii_name(gazetteer_frame):
    assert "Nameless" in set(gazetteer_frame["place"])


def test_a_file_that_is_not_the_cities_zip_is_reported(tmp_path):
    (tmp_path / "cities500.zip").write_bytes(b"not a zip")
    with pytest.raises(pl.PlacesError, match="cities500.zip"):
        pl.read_cities(tmp_path / "cities500.zip")


# --- build ------------------------------------------------------------------------------------------

def fake_fetch(url, dest, manifest, source, licence):
    write_sources(Path(dest).parent)
    manifest.add(dest, source, url, licence)
    return dest


def basemap_file(tmp_path):
    """A full-India-grid mask: Nepal around Kathmandu, India elsewhere."""
    grid = bm.INDIA_GRID
    mask = np.full((grid.rows, grid.cols), bm.INDIA, dtype=np.uint8)
    lat, lon = np.meshgrid(grid.lat_centres(), grid.lon_centres(), indexing="ij")
    mask[(lat > 26.5) & (lat < 28.5) & (lon > 83) & (lon < 87)] = bm.NEPAL
    path = tmp_path / "india_basemap.npz"
    np.savez_compressed(path, elev=np.zeros_like(mask, dtype=np.float32), mask=mask, lat0=np.float64(grid.lat0),
                        lon0=np.float64(grid.lon0), step=np.float64(bm.GRID_STEP))
    return path


def replay_store(tmp_path, cell_ids):
    root = tmp_path / "replay"
    alerts = pd.DataFrame({"cell_id": cell_ids, "date": pd.Timestamp("2024-07-30")})
    entry = alert_store.write_set(root, "case", alerts, None)
    alert_store.write_manifest(root, {"case": entry})
    return root


def build(tmp_path, **kwargs):
    cfg = H.make_cfg(tmp_path)
    H.write_cell_tables(tmp_path, cfg)
    replay_cell = int(latlon_to_cell(30.52, 79.33))
    manifest = Manifest(tmp_path / "manifests" / "m.jsonl", tmp_path / "data")
    sources = pl.default_sources(tmp_path / "data" / "raw" / "geonames")
    meta = pl.build_places(sources, cfg, replay_store(tmp_path, [replay_cell, int(H.tiny_cells()["cell_id"][0])]),
                           tmp_path / "out", manifest, basemap_file(tmp_path), **{"fetch": fake_fetch, **kwargs})
    return meta, manifest, replay_cell


def test_build_labels_the_candidate_cells_and_the_replay_cells(tmp_path):
    meta, _, replay_cell = build(tmp_path)
    table = pl.read_table(tmp_path / "out" / pl.TABLE_NAME)
    assert list(table.columns) == pl.TABLE_COLUMNS
    assert set(table["cell_id"]) == {*H.tiny_cells()["cell_id"], replay_cell}
    assert meta["counts"]["candidate_cells"] == 4 and meta["counts"]["replay_cells"] == 2 and meta["counts"]["cells"] == 5
    by_cell = table.set_index("cell_id")
    wayanad = by_cell.loc[int(latlon_to_cell(11.55, 76.15))]
    assert (wayanad["place"], wayanad["district"], wayanad["state"], wayanad["country"]) == ("Mananthavady", "Wayanad", "Kerala", "India")
    kathmandu = by_cell.loc[int(latlon_to_cell(27.70, 85.30))]
    assert (kathmandu["place"], kathmandu["country"]) == ("Kathmandu", "Nepal") and pd.isna(kathmandu["district"])
    assert by_cell.loc[replay_cell, "place"] == "Chamoli"


def test_build_writes_the_json_with_source_licence_attribution_date_and_counts(tmp_path):
    meta, _, _ = build(tmp_path)
    on_disk = json.loads((tmp_path / "out" / pl.META_NAME).read_text(encoding="utf-8"))
    assert on_disk == meta
    assert meta["source"] == "GeoNames" and "CC BY 4.0" in meta["licence"]
    assert meta["attribution"] == "Place names: GeoNames (CC BY 4.0)"
    assert len(meta["build_date"]) == 10 and meta["build_date"][4] == "-"
    counts = meta["counts"]
    assert counts["gazetteer_places"] == 7 and counts["by_country"]["Nepal"] == 1
    assert set(counts["distance_km"]) == {"median", "p90", "max"}
    assert meta["files"][pl.TABLE_NAME]["sha256"] == pl.sha256_file(tmp_path / "out" / pl.TABLE_NAME)
    assert not list((tmp_path / "out").glob("*.tmp"))


def test_build_records_every_download_and_the_extract_in_the_manifest_with_url_and_licence(tmp_path):
    _, manifest, _ = build(tmp_path)
    rows = {r["path"]: r for r in map(json.loads, (tmp_path / "manifests" / "m.jsonl").read_text(encoding="utf-8").splitlines())}
    assert set(rows) == {"raw/geonames/cities500.zip", "raw/geonames/admin1CodesASCII.txt", "raw/geonames/admin2Codes.txt",
                         "raw/geonames/geonames_places.parquet"}
    assert rows["raw/geonames/cities500.zip"]["url"] == "https://download.geonames.org/export/dump/cities500.zip"
    assert rows["raw/geonames/admin2Codes.txt"]["url"] == "https://download.geonames.org/export/dump/admin2Codes.txt"
    assert all("CC BY 4.0" in r["licence"] for r in rows.values())
    assert manifest.verify() == []


def test_build_does_not_fetch_a_source_that_is_already_current(tmp_path):
    build(tmp_path)
    calls = []
    build(tmp_path, fetch=lambda *a: calls.append(a))
    assert calls == []
    rows = (tmp_path / "manifests" / "m.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 4


def test_build_with_skip_download_fails_when_a_source_is_missing(tmp_path):
    with pytest.raises(pl.PlacesError, match="skip-download"):
        build(tmp_path, skip_download=True)


def test_build_names_a_missing_base_map(tmp_path):
    cfg = H.make_cfg(tmp_path)
    H.write_cell_tables(tmp_path, cfg)
    manifest = Manifest(tmp_path / "manifests" / "m.jsonl", tmp_path / "data")
    with pytest.raises(pl.PlacesError, match="base map"):
        pl.build_places(pl.default_sources(tmp_path / "data" / "raw" / "geonames"), cfg, tmp_path / "none", tmp_path / "out",
                        manifest, tmp_path / "missing.npz", fetch=fake_fetch)


def test_a_replay_store_that_is_absent_adds_no_cells(tmp_path):
    assert len(pl.replay_cell_ids(tmp_path / "none")) == 0


def test_read_table_reports_a_missing_or_foreign_file(tmp_path):
    with pytest.raises(pl.PlacesError, match="cannot be read"):
        pl.read_table(tmp_path / "none.parquet")
    pd.DataFrame({"cell_id": [1]}).to_parquet(tmp_path / "t.parquet")
    with pytest.raises(pl.PlacesError, match="lacks the columns"):
        pl.read_table(tmp_path / "t.parquet")


def test_cli_build_requires_the_subcommand_and_reports_failures(tmp_path, capsys):
    with pytest.raises(SystemExit):
        pl.main([])
    code = pl.main(["build", "--skip-download", "--raw-dir", str(tmp_path / "none"), "--out-dir", str(tmp_path / "o"),
                    "--manifest", str(tmp_path / "m.jsonl")])
    assert code == 1
    assert "places" in capsys.readouterr().err


@pytest.mark.realdata
def test_the_real_geonames_files_give_wayanad_its_name():
    raw = pl.data_root() / "raw" / "geonames"
    cities = pl.read_cities(raw / pl.CITIES_ZIP)
    frame = pl.extract_places(cities, pl.read_admin_names(raw / pl.ADMIN1_FILE), pl.read_admin_names(raw / pl.ADMIN2_FILE))
    with np.load(pl.data_root() / "processed" / "basemap" / "india_basemap.npz") as stored:
        mask = stored["mask"]
    row = pl.label_cells([20295122], frame, mask, bm.INDIA_GRID).iloc[0]
    assert row["state"] == "Kerala" and row["country"] == "India"
