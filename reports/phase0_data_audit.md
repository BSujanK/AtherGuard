# Phase 0 data audit

Generated: 2026-09-30T07:28:38Z

Status meanings: ok = works as planned; partial = works with caveats; fail = does not work; unreachable = network problem; needs_login = free account required; manual_pending = you must place a file; inconclusive = the probe itself could not decide.

'Probe problems' lists every probe that is not ok (including partial) with its reason; 'Needs human action' lists only the probes that need something from you.

## Summary

| probe | status | summary |
|---|---|---|
| geolibs | ok | geospatial stack imports on Python 3.13 |
| disk | ok | 237.1 GB free (need 100 GB) |
| earthdata_credentials | needs_login | no Earthdata credentials found; create a free account at urs.earthdata.nasa.gov and set EARTHDATA_USERNAME / EARTHDATA_PASSWORD (or a .netrc entry) to unlock the HMA catalog and IMERG |
| ghcnd | ok | 140 stations selected, 391 real quality-flagged rain values |
| isd | ok | 414 active ISD stations in IN, NP |
| open_meteo | partial | 2/3 precipitation models with complete data; soil moisture ok; 1 problem(s), first: era5_land precipitation: 96 null hourly values |
| power_api | ok | PRECTOTCORR requested days=4, missing/fill=0, soil wetness ok |
| power_zarr | ok | bulk MERRA-2 store readable; 4/4 requested days have values |
| chirps | ok | grid (2000, 7200) at (0.05, 0.05) deg; ~18.9 GB for the full period |
| imd | ok | IMD 2024 gridded rain readable; grid shape (366, 129, 135) |
| dem | ok | tile Copernicus_DSM_COG_10_N11_00_E076_00_DEM.tif: elevation at point 908 m; ~20.4 GB for the domain |
| worldcover | ok | tile reachable; ~4.8 GB for the domain |
| soilgrids | ok | clay 0-5 cm at point = 280.0 (nodata=-32768.0) |
| osm_roads | ok | Geofabrik extracts reachable, 2.12 GB combined |
| nepal_inventories | ok | Landslide inventories for Nepal: Database 2010 - 2021 \| cc-by-4.0 \| 2 files, 0.00 GB |
| gaolan | ok | Monitoring Dataset of Loess Slopes in Gaolan Mountain(MDLS-GLM) \| cc-by-4.0 \| 10 files, 48.69 GB |
| lithology_search | ok | 5 candidates only (relevance not verified); top: Global landform and lithology class at 250 m based on the USGS global ecosystem map |
| kerala_inventory_search | ok | 5 candidates only (relevance not verified); top: Multi-temporal landslide inventory for southern Sikkim State, India |
| catalog_nasa_glc | manual_pending | file not found: place the CSV export at data/raw/manual/nasa_glc.csv |
| catalog_hma_ls_cat | manual_pending | file not found: place the CSV export at data/raw/manual/hma_ls_cat_v2.csv |
| feasibility | ok | infeasible (>30 days at the free limit): full domain, ERA5 0.25 deg grid, whole period (334.4 d); full domain, 0.05 deg grid, whole period (8,359.6 d); feasible: sampled case-control, 30,000 points x 60 days (12.9 d) |

## Needs human action

| probe | status | what is needed |
|---|---|---|
| earthdata_credentials | needs_login | no Earthdata credentials found; create a free account at urs.earthdata.nasa.gov and set EARTHDATA_USERNAME / EARTHDATA_PASSWORD (or a .netrc entry) to unlock the HMA catalog and IMERG |
| catalog_nasa_glc | manual_pending | file not found: place the CSV export at data/raw/manual/nasa_glc.csv |
| catalog_hma_ls_cat | manual_pending | file not found: place the CSV export at data/raw/manual/hma_ls_cat_v2.csv |

## Probe problems

**earthdata_credentials** - needs_login: no Earthdata credentials found; create a free account at urs.earthdata.nasa.gov and set EARTHDATA_USERNAME / EARTHDATA_PASSWORD (or a .netrc entry) to unlock the HMA catalog and IMERG

- no further detail recorded

**open_meteo** - partial: 2/3 precipitation models with complete data; soil moisture ok; 1 problem(s), first: era5_land precipitation: 96 null hourly values

- problems: era5_land precipitation: 96 null hourly values

**catalog_nasa_glc** - manual_pending: file not found: place the CSV export at data/raw/manual/nasa_glc.csv

- no further detail recorded

**catalog_hma_ls_cat** - manual_pending: file not found: place the CSV export at data/raw/manual/hma_ls_cat_v2.csv

- no further detail recorded

## Rain products at the reference point

Reference point: wayanad_meppadi (11.55 N, 76.13 E). Products use different definitions of a 'day' (last column); the windows do not line up exactly, so totals are indicative only.

| source | 2024-07-28 | 2024-07-29 | 2024-07-30 | 2024-07-31 | sum (mm) | day definition |
|---|---|---|---|---|---|---|
| era5 | 11 | 54 | 56 | 27 | 148 | UTC calendar date (timezone=UTC requested). Open-Meteo hourly precipitation is the total of the PRECEDING hour, so the stamps 00:00-23:00 UTC of a date cover 23:00 UTC of the previous day to 23:00 UTC of that date |
| era5_land | n/a | n/a | n/a | n/a | n/a | UTC calendar date (timezone=UTC requested). Open-Meteo hourly precipitation is the total of the PRECEDING hour, so the stamps 00:00-23:00 UTC of a date cover 23:00 UTC of the previous day to 23:00 UTC of that date |
| ecmwf_ifs | 10 | 62 | 47 | 81 | 199 | UTC calendar date (timezone=UTC requested). Open-Meteo hourly precipitation is the total of the PRECEDING hour, so the stamps 00:00-23:00 UTC of a date cover 23:00 UTC of the previous day to 23:00 UTC of that date |
| merra2_power_api | 8 | 53 | 28 | 20 | 107 | NASA POWER time_standard=LST (MERRA-2 native daily) |
| merra2_power_zarr_utc | 11 | 64 | 18 | 19 | 112 | NASA POWER analysis-ready 'utc' store: UTC calendar day of MERRA-2 |
| chirps_p05 | 0 | 28 | 0 | 85 | 114 | UTC calendar day (00-24 UTC) per CHIRPS documentation - confirm in review |
| imd_gauge_grid_0p25 | 5 | 7 | 179 | 17 | 208 | IMD rainfall day: 08:30 IST previous day to 08:30 IST (= 03:00 UTC to 03:00 UTC) per IMD convention - confirm in review |

Reported local gauges: about 572 mm in 48 h to 30 Jul 2024 (secondary source - press/papers; not yet checked against a primary source).

## Real fault labels (GHCN-Daily quality flags)

Stations selected: 140 ({'IN': 138, 'NP': 2}). A flag means the value failed an automated NOAA check (the value is kept).

Failed downloads: 0; stations with unknown elevation: 0 (treated as lowland).

| region\|elevation | stations | valid values | flagged | flags |
|---|---|---|---|---|
| himalaya\|lowland | 51 | 1111831 | 240 | D:180, G:13, K:5, O:9, S:33 |
| himalaya\|upland | 17 | 333965 | 28 | G:5, O:5, S:18 |
| outside_domain\|lowland | 35 | 803119 | 81 | D:61, G:5, O:7, S:8 |
| outside_domain\|upland | 1 | 28908 | 1 | S:1 |
| western_ghats\|lowland | 25 | 549245 | 13 | G:3, O:4, S:6 |
| western_ghats\|upland | 11 | 272562 | 28 | G:3, O:16, S:9 |

## Landslide catalogs

**catalog_nasa_glc** - manual_pending: file not found: place the CSV export at data/raw/manual/nasa_glc.csv

**catalog_hma_ls_cat** - manual_pending: file not found: place the CSV export at data/raw/manual/hma_ls_cat_v2.csv

## Ingest feasibility and volumes

| strategy | points | days | call units | days at free limit |
|---|---|---|---|---|
| full domain, ERA5 0.25 deg grid, whole period | 7120 | 6575 | 3343857 | 334.4 |
| full domain, 0.05 deg grid, whole period | 178000 | 6575 | 83596429 | 8359.6 |
| sampled case-control, 30,000 points x 60 days | 30000 | 60 | 128571 | 12.9 |

Estimated download volume for the full domain/period:

| source | GB |
|---|---|
| chirps | 18.9 |
| dem | 20.4 |
| worldcover | 4.8 |

Files downloaded so far (from the manifest):

| source | files | MB | licence recorded |
|---|---|---|---|
| CHIRPS v2.0 daily p05 | 4 | 11.5 | see https://www.chc.ucsb.edu/data/chirps (verify licence in review) |
| Copernicus DEM GLO-30 | 1 | 44.2 | Copernicus DEM licence (free, attribution; verify in review) |
| IMD gridded rainfall 0.25 deg (via imdlib) | 1 | 25.5 | IMD data terms (verify in review) |
| NOAA GHCN-Daily inventory | 1 | 36.0 | NOAA NCEI open data (public domain) |
| NOAA GHCN-Daily station file | 140 | 77.6 | NOAA NCEI open data (public domain) |
| NOAA GHCN-Daily stations | 1 | 11.4 | NOAA NCEI open data (public domain) |
| NOAA ISD station history | 1 | 2.9 | NOAA NCEI open data (public domain) |

