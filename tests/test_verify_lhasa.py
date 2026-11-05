from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from aetherguard.grid import latlon_to_cell
from aetherguard.http import DownloadError
from aetherguard.manifest import Manifest
from aetherguard.verify import lhasa
from aetherguard.verify.lhasa import LhasaFormatError, build_year, cell_max, fetch_lhasa, subset_url


def cell_at(lat: float, lon: float) -> int:
    return int(latlon_to_cell(lat, lon))


def write_nc(path: Path, lat, lon, values, *, fill_encoding: bool = True, variable: str = "p_landslide") -> Path:
    """A LHASA-shaped file: `variable` as (time, lat, lon) float32; NaN is stored as -9999 with a _FillValue."""
    values = np.asarray(values, dtype=np.float32)
    data = xr.Dataset({variable: (("time", "lat", "lon"), values[None])},
                      coords={"time": np.array(["2018-06-01"], dtype="datetime64[ns]"), "lat": lat, "lon": lon})
    encoding = {variable: {"_FillValue": np.float32(-9999.0)}} if fill_encoding else {}
    data.to_netcdf(path, engine="h5netcdf", encoding=encoding)
    return path


def pixel_grid(lat0: float, lon0: float, n_cells: int = 2, step: float = 0.01):
    """Pixel-centre axes of an `n_cells` x `n_cells` block of 0.05 degree cells whose south-west corner is (lat0, lon0)."""
    n = int(round(0.05 / step)) * n_cells
    return lat0 + step * (np.arange(n) + 0.5), lon0 + step * (np.arange(n) + 0.5)


def brute_force(lat, lon, values, cell_id: int) -> float:
    found = [values[i, j] for i, la in enumerate(lat) for j, lo in enumerate(lon)
             if cell_at(la, lo) == cell_id and np.isfinite(values[i, j]) and 0 <= values[i, j] <= 1]
    return max(found) if found else np.nan


def test_cell_max_is_the_maximum_of_the_pixels_inside_each_cell(tmp_path):
    lat, lon = pixel_grid(10.0, 80.0)
    values = np.random.default_rng(1).random((lat.size, lon.size))
    path = write_nc(tmp_path / "a.nc4", lat, lon, values)
    cells = np.array([cell_at(10.025, 80.025), cell_at(10.025, 80.075), cell_at(10.075, 80.025), cell_at(10.075, 80.075)])
    got = cell_max(path, cells)
    assert got.dtype == np.float32
    assert got.tolist() == pytest.approx([brute_force(lat, lon, values, c) for c in cells])
    assert got[0] == pytest.approx(values[:5, :5].max())
    assert got[3] == pytest.approx(values[5:, 5:].max())


def test_cell_max_follows_the_order_of_the_cell_ids_and_keeps_duplicates(tmp_path):
    lat, lon = pixel_grid(10.0, 80.0)
    values = np.arange(lat.size * lon.size, dtype=float).reshape(lat.size, lon.size) / 1000.0
    path = write_nc(tmp_path / "a.nc4", lat, lon, values)
    a, b = cell_at(10.025, 80.025), cell_at(10.075, 80.075)
    assert cell_max(path, np.array([b, a, b])).tolist() == pytest.approx(
        [values[5:, 5:].max(), values[:5, :5].max(), values[5:, 5:].max()])


def test_a_cell_without_a_pixel_is_nan_not_zero(tmp_path):
    lat, lon = pixel_grid(10.0, 80.0)
    path = write_nc(tmp_path / "a.nc4", lat, lon, np.full((lat.size, lon.size), 0.2))
    got = cell_max(path, np.array([cell_at(10.025, 80.025), cell_at(20.025, 80.025), cell_at(10.025, 90.025)]))
    assert got[0] == pytest.approx(0.2)
    assert np.isnan(got[1:]).all()


def test_fill_and_masked_pixels_are_invalid_and_a_cell_of_only_invalid_pixels_is_nan(tmp_path):
    lat, lon = pixel_grid(10.0, 80.0)
    values = np.full((lat.size, lon.size), 0.3)
    values[:5, :5] = np.nan            # whole first cell masked (stored as the fill value)
    values[5:, :5] = np.nan
    values[7, 2] = 0.9                 # one valid pixel among masked ones
    path = write_nc(tmp_path / "a.nc4", lat, lon, values)
    cells = np.array([cell_at(10.025, 80.025), cell_at(10.075, 80.025), cell_at(10.025, 80.075)])
    got = cell_max(path, cells)
    assert np.isnan(got[0])
    assert got[1] == pytest.approx(0.9)
    assert got[2] == pytest.approx(0.3)


def test_raw_fill_value_without_a_declared_fill_attribute_is_still_invalid(tmp_path):
    lat, lon = pixel_grid(10.0, 80.0, n_cells=1)
    values = np.full((lat.size, lon.size), -9999.0)
    values[0, 0] = 0.05
    path = write_nc(tmp_path / "a.nc4", lat, lon, values, fill_encoding=False)
    assert cell_max(path, np.array([cell_at(10.025, 80.025)])).tolist() == pytest.approx([0.05])
    values[0, 0] = -9999.0
    path = write_nc(tmp_path / "b.nc4", lat, lon, values, fill_encoding=False)
    assert np.isnan(cell_max(path, np.array([cell_at(10.025, 80.025)]))).all()


def test_latitude_ascending_or_descending_gives_the_same_result(tmp_path):
    lat, lon = pixel_grid(10.0, 80.0)
    values = np.random.default_rng(2).random((lat.size, lon.size))
    cells = np.array([cell_at(10.025, 80.025), cell_at(10.075, 80.075)])
    south_up = cell_max(write_nc(tmp_path / "up.nc4", lat, lon, values), cells)
    north_up = cell_max(write_nc(tmp_path / "down.nc4", lat[::-1], lon, values[::-1]), cells)
    assert south_up.tolist() == north_up.tolist()


def test_real_lattice_six_pixels_per_cell_with_float_jitter_in_the_coordinates(tmp_path):
    step = 1 / 120                      # the LHASA pixel: 6 per 0.05 degree cell, edges on the cell edges
    lat = 10.0 + step * (np.arange(12) + 0.5) + np.random.default_rng(3).uniform(-6e-5, 6e-5, 12)
    lon = 80.0 + step * (np.arange(12) + 0.5) + np.random.default_rng(4).uniform(-6e-5, 6e-5, 12)
    values = np.random.default_rng(5).random((12, 12))
    path = write_nc(tmp_path / "a.nc4", lat, lon, values)
    cells = np.array([cell_at(10.025, 80.025), cell_at(10.075, 80.025), cell_at(10.025, 80.075), cell_at(10.075, 80.075)])
    assert cell_max(path, cells).tolist() == pytest.approx([values[:6, :6].max(), values[6:, :6].max(),
                                                           values[:6, 6:].max(), values[6:, 6:].max()])


def test_a_partly_covered_cell_uses_the_pixels_it_has(tmp_path):
    lat, lon = pixel_grid(10.0, 80.0, n_cells=1)
    values = np.random.default_rng(6).random((lat.size, lon.size))
    path = write_nc(tmp_path / "a.nc4", lat[:3], lon, values[:3])      # only the three southern rows
    got = cell_max(path, np.array([cell_at(10.025, 80.025)]))
    assert got.tolist() == pytest.approx([values[:3].max()])


def test_a_file_without_the_variable_or_with_the_wrong_dimensions_is_refused(tmp_path):
    lat, lon = pixel_grid(10.0, 80.0, n_cells=1)
    values = np.zeros((lat.size, lon.size))
    cells = np.array([cell_at(10.025, 80.025)])
    with pytest.raises(LhasaFormatError, match="p_landslide"):
        cell_max(write_nc(tmp_path / "a.nc4", lat, lon, values, variable="other"), cells)
    flat = xr.Dataset({"p_landslide": (("lat", "lon"), values.astype(np.float32))}, coords={"lat": lat, "lon": lon})
    flat.to_netcdf(tmp_path / "b.nc4", engine="h5netcdf")
    with pytest.raises(LhasaFormatError, match="dimensions"):
        cell_max(tmp_path / "b.nc4", cells)
    (tmp_path / "c.nc4").write_bytes(b"not a netcdf file")
    with pytest.raises(LhasaFormatError):
        cell_max(tmp_path / "c.nc4", cells)


def test_a_non_monotone_latitude_axis_is_refused(tmp_path):
    lat, lon = pixel_grid(10.0, 80.0, n_cells=1)
    lat = lat[[0, 2, 1, 3, 4]]
    path = write_nc(tmp_path / "a.nc4", lat, lon, np.zeros((lat.size, lon.size)))
    with pytest.raises(LhasaFormatError, match="monotone"):
        cell_max(path, np.array([cell_at(10.025, 80.025)]))


# ------------------------------------------------------------------------------------------ download


class FakeResponse:
    def __init__(self, status: int, body: bytes = b"") -> None:
        self.status_code, self.body, self.headers = status, body, {"Content-Length": str(len(body))}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_content(self, chunk_size):
        yield self.body


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response, self.urls = response, []

    def get(self, url, **kwargs):
        self.urls.append(url)
        return self.response


def test_subset_url_names_the_granule_of_the_day_and_the_domain_box():
    url = subset_url(date(2018, 6, 1))
    assert "Global_Landslide_Nowcast_v2.0.0_20180601.nc4.dap.nc4?" in url
    assert "C2654319036-GES_DISC" in url
    assert "/p_landslide[0][2880:6239][30240:33359]" in url
    assert "/lat[2880:6239]" in url and "/lon[30240:33359]" in url


def test_fetch_lhasa_downloads_into_the_cache_and_records_the_manifest(tmp_path):
    manifest = Manifest(tmp_path / "manifest.jsonl", tmp_path)
    session = FakeSession(FakeResponse(200, b"netcdf bytes"))
    path = fetch_lhasa(date(2018, 6, 1), tmp_path / "raw" / "lhasa", manifest=manifest, session=session)
    assert path.name == "Global_Landslide_Nowcast_v2.0.0_20180601.subset.nc4"
    assert path.read_bytes() == b"netcdf bytes"
    assert manifest.is_current(path)
    entry = manifest.entries()[manifest.relpath(path)]
    assert "LHASA" in entry.source and "Stanley" in entry.licence
    assert len(session.urls) == 1
    fetch_lhasa(date(2018, 6, 1), tmp_path / "raw" / "lhasa", manifest=manifest, session=session)
    assert len(session.urls) == 1          # manifest-current: not fetched again


def test_fetch_lhasa_reports_a_missing_granule_with_its_status(tmp_path):
    manifest = Manifest(tmp_path / "manifest.jsonl", tmp_path)
    with pytest.raises(DownloadError) as caught:
        fetch_lhasa(date(2021, 3, 1), tmp_path / "raw", manifest=manifest, session=FakeSession(FakeResponse(404)))
    assert caught.value.status == 404 and not caught.value.retriable


# ------------------------------------------------------------------------------------------ one year


def test_build_year_aligns_days_and_cells_and_leaves_missing_days_nan(tmp_path):
    lat, lon = pixel_grid(10.0, 80.0)
    cells = np.array([cell_at(10.025, 80.025), cell_at(10.075, 80.075), cell_at(30.025, 80.025)])
    present = {date(2020, 6, 1): 0.4, date(2020, 6, 3): 0.7, date(2020, 12, 31): 0.1}
    files = {}

    def fetch(day, cache):
        if day not in files:
            files[day] = write_nc(tmp_path / f"{day}.nc4", lat, lon, np.full((lat.size, lon.size), present[day]))
        return files[day]

    out = build_year(2020, cells, tmp_path / "out", tmp_path / "raw", say=lambda m: None,
                     available=set(present), fetch=fetch, workers=2)
    assert out.name == "lhasa_2020.npz"
    with np.load(out) as data:
        assert data["cell_id"].tolist() == cells.tolist()
        days = data["days"].tolist()
        assert len(days) == 214 and days[0] == "2020-06-01" and days[-1] == "2020-12-31"
        prob = data["prob"]
        assert prob.dtype == np.float32 and prob.shape == (3, 214)
        assert data["fetched"].tolist() == [d in {x.isoformat() for x in present} for d in days]
    assert prob[0, 0] == pytest.approx(0.4) and prob[1, 2] == pytest.approx(0.7) and prob[0, -1] == pytest.approx(0.1)
    assert np.isnan(prob[2]).all()                       # a cell outside the file is never 0
    assert np.isnan(prob[:, 1]).all()                    # a day the archive lacks stays a NaN column
    assert not np.isnan(prob[:2, [0, 2, 213]]).any()


def test_build_year_records_a_failed_day_and_does_not_drop_it(tmp_path):
    lat, lon = pixel_grid(10.0, 80.0, n_cells=1)
    cells = np.array([cell_at(10.025, 80.025)])
    days = {date(2019, 6, 1), date(2019, 6, 2)}

    def fetch(day, cache):
        if day == date(2019, 6, 2):
            raise DownloadError("HTTP 500 from somewhere", retriable=True, status=500)
        return write_nc(tmp_path / f"{day}.nc4", lat, lon, np.full((lat.size, lon.size), 0.5))

    out = build_year(2019, cells, tmp_path / "out", tmp_path / "raw", say=lambda m: None,
                     available=days, fetch=fetch, workers=1)
    with np.load(out) as data:
        assert data["fetched"].tolist()[:3] == [True, False, False]
        assert data["prob"].shape == (1, 214) and np.isnan(data["prob"][0, 1])
    sidecar = out.with_suffix(".json").read_text(encoding="utf-8")
    assert "2019-06-02" in sidecar and "failed" in sidecar


def test_build_year_aborts_when_every_request_fails(tmp_path):
    def fetch(day, cache):
        raise DownloadError("HTTP 401", status=401)

    cells = np.array([cell_at(10.025, 80.025)])
    with pytest.raises(DownloadError, match="consecutive"):
        build_year(2020, cells, tmp_path / "out", tmp_path / "raw", say=lambda m: None,
                   available={date(2020, 6, 1) + timedelta(k) for k in range(60)},
                   fetch=fetch, workers=1)


def test_available_days_reads_the_granule_dates_from_cmr(monkeypatch):
    def fake_fetch_json(url, params=None, **kwargs):
        assert params["collection_concept_id"] == lhasa.CONCEPT_ID
        titles = [f"Global_Landslide_Nowcast.2.0.0:Global_Landslide_Nowcast_v2.0.0_{stamp}.nc4"
                  for stamp in ("20180531", "20180601", "20180602", "20190101")]
        return {"feed": {"entry": [{"title": t} for t in titles]}}

    monkeypatch.setattr(lhasa, "fetch_json", fake_fetch_json)
    assert lhasa.available_days(date(2018, 6, 1), date(2018, 12, 31)) == {date(2018, 6, 1), date(2018, 6, 2)}


def test_parse_years_accepts_the_archive_years_only():
    assert lhasa.parse_years("2018-2020") == (2018, 2019, 2020)
    assert lhasa.parse_years("2019") == (2019,)
    with pytest.raises(ValueError):
        lhasa.parse_years("2021")
    with pytest.raises(ValueError):
        lhasa.parse_years("2017")
