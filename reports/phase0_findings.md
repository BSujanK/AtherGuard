# Phase 0 findings: interpretation of the data audit

Audience: the person reviewing Phase 0 at the gate. Companion to the generated `reports/phase0_data_audit.md` and `.json` (run 2026-09-30T07:28:38Z), which are not edited by hand. This page is human-written. Every number is traceable to those reports, to files under `data/`, or to a command quoted below. Statements marked **Hypothesis** are interpretations that were not tested.

## 1. Gate summary

Probe statuses (from `reports/phase0_data_audit.json`): 21 result rows, 17 `ok`, 1 `partial`, 1 `needs_login`, 2 `manual_pending`, 0 `inconclusive`/`fail`/`unreachable`.

- `ok`: geolibs, disk (237.1 GB free), ghcnd, isd, power_api, power_zarr, chirps, imd, dem, worldcover, soilgrids, osm_roads, nepal_inventories, gaolan, lithology_search, kerala_inventory_search, feasibility.
- `partial` (the only one): `open_meteo`. ERA5 and ECMWF IFS precipitation are complete, soil moisture is complete, but **era5_land precipitation is null** (96 of 96 hourly values for 28-31 Jul 2024 at the reference point).
- `ok` does not mean "useful": `kerala_inventory_search` and `lithology_search` are `ok` only because candidate records were returned; relevance is not verified (see section 4).

What needs the user:
1. Create a free NASA Earthdata account (`earthdata_credentials` = `needs_login`; no env vars and no netrc found).
2. Export the NASA Global Landslide Catalog to `data/raw/manual/nasa_glc.csv` (`catalog_nasa_glc` = `manual_pending`).
3. Export the HMA landslide catalog v2 to `data/raw/manual/hma_ls_cat_v2.csv` (`catalog_hma_ls_cat` = `manual_pending`; needs the account from step 1).
4. Rerun `.venv/Scripts/python -m aetherguard.audit.run --only earthdata_credentials,manual_catalogs` and approve the Phase 1 source set (section 7). Since the final fix, a partial (`--only`) run writes to `reports/partial/` and no longer overwrites the committed full report in `reports/`; pass `--reports-dir` to choose another folder.

## 2. Rain products at the Wayanad reference point

Reference point: wayanad_meppadi, 11.55 N, 76.13 E (`configs/audit.yaml`). Event: 29-30 Jul 2024 (Meppadi/Mundakkai landslides). All values are mm per "day" as defined in the last column. All rows come from the committed report except the ERA5 IST-day row, which comes from the query below.

| product | 28 Jul | 29 Jul | 30 Jul | 31 Jul | day definition |
|---|---|---|---|---|---|
| ERA5 (Open-Meteo), UTC days | 10.7 | 54.2 | 56.0 | 27.0 | UTC calendar date of hourly stamps (hourly value = preceding hour) |
| ERA5 (Open-Meteo), IST days | 7.4 | 33.2 | 73.9 | 31.2 | IST calendar date (`timezone=Asia/Kolkata`), same hourly data |
| ERA5-Land (Open-Meteo) | null | null | null | null | UTC; all hourly values null |
| ECMWF IFS (Open-Meteo) | 9.9 | 62.2 | 46.6 | 80.6 | UTC calendar date |
| MERRA-2 via NASA POWER API | 7.63 | 52.62 | 27.53 | 19.56 | POWER `time_standard=LST` |
| MERRA-2 via POWER zarr (utc store) | 10.68 | 63.54 | 17.89 | 19.47 | UTC calendar day |
| CHIRPS v2.0 p05 | 0.0 | 28.42 | 0.0 | 85.25 | UTC calendar day per CHIRPS docs (unconfirmed) |
| IMD 0.25 deg gauge-based grid | 4.97 | 6.6 | 179.24 | 16.7 | IMD day 08:30 IST to 08:30 IST (unconfirmed label convention) |

IST re-query (read-only, same Open-Meteo archive endpoint and the same `era5` model as the probe; only the timezone differs):

```
.venv/Scripts/python - <<'EOF'
import collections, requests
p = dict(latitude=11.55, longitude=76.13, start_date="2024-07-27", end_date="2024-07-31",
         hourly="precipitation", models="era5", timezone="Asia/Kolkata")
d = requests.get("https://archive-api.open-meteo.com/v1/archive", params=p, timeout=60).json()
day = collections.OrderedDict()
for t, v in zip(d["hourly"]["time"], d["hourly"]["precipitation"]):
    day[t[:10]] = day.get(t[:10], 0.0) + (v or 0.0)
print("grid cell:", d["latitude"], d["longitude"], "| n_hours:", len(d["hourly"]["time"]))
for k, v in day.items(): print(k, round(v, 1))
EOF
```
Output:
```
grid cell: 11.5 76.25 | n_hours: 120
2024-07-27 3.3
2024-07-28 7.4
2024-07-29 33.2
2024-07-30 73.9
2024-07-31 31.2
```

What the table shows:
- **The peak day moves with the day definition.** ERA5 is roughly equal on the two event days with UTC days (54.2 / 56.0) but clearly peaks on 30 Jul with IST days (33.2 / 73.9). The two-day totals are close (110.2 vs 107.1 mm). The earlier hand check that quoted ERA5 about 33 / 74 mm used IST days; the audit probe deliberately uses UTC days, so the two are not in conflict. Open-Meteo also snaps to the 0.25 deg ERA5 cell centre (11.5 N, 76.25 E), not the requested coordinates.
- **POWER**: the LST product (52.62 / 27.53) and the UTC zarr (63.54 / 17.89) disagree by about 11 mm (29 Jul) and 10 mm (30 Jul) on the event days for the same MERRA-2 source, again a day-boundary effect plus a different time basis. The 48 h totals are 80.2 and 81.4 mm.
- **IMD**: 179.24 mm on 30 Jul is the largest value among all products; on 29 Jul IMD shows only 6.6 mm. **Hypothesis**: IMD's day ends at 08:30 IST, so the 30 Jul IMD value contains the night rain of 29-30 Jul that calendar-day products split across two dates. This matches the IST-day ERA5 shape but has not been checked against IMD documentation or sub-daily data.
  - **IMD is India-only.** Read-only check on the already downloaded `data/raw/audit/imd/rain/2024.grd` (opened in memory with `imdlib.open_data(...).get_xarray()`, nothing written; grid lat 6.5 to 38.5, lon 66.5 to 100.0, shape (366, 129, 135)): `rain` is NaN for all 366 days at **Kathmandu (27.75 N, 85.25 E)** and **Pokhara (28.25 N, 84.0 E)**, so the grid is masked outside India. It has values for all 366 days at **Dehradun** (nearest cell 30.25 N, 78.0 E, maximum 123.6 mm) and at **Wayanad** (nearest cell 11.5 N, 76.25 E, maximum 179.2 mm, the same cell centre Open-Meteo's ERA5 snapped to).
- **CHIRPS** gives 0.0 mm on 28 and 30 Jul and 28.42 mm on 29 Jul at the pixel. The pixel index was checked: the pixel centre is (76.125 E, 11.575 N) and the 5 x 5 neighbourhood is spatially coherent (30 to 120 mm on 29 Jul and 31 Jul, all zeros on 30 Jul). Quoted output (the first line is illustrative pseudo-code for what was run, not a committed script; do not expect to run it verbatim):
  ```
  for each chirps-v2.0.2024.07.2x/3x.tif: rasterio.open(...); r,c = ds.index(76.13, 11.55); read 1 pixel; ds.read(1).min()
  2024.07.28 nodata attr: None pixel centre: (76.125, 11.575) value: 0.0 min over file: -9999.0
  2024.07.29 nodata attr: None pixel centre: (76.125, 11.575) value: 28.42 min over file: -9999.0
  2024.07.30 nodata attr: None pixel centre: (76.125, 11.575) value: 0.0 min over file: -9999.0
  2024.07.31 nodata attr: None pixel centre: (76.125, 11.575) value: 85.25 min over file: -9999.0
  ```
  The files declare `nodata = None` although they use -9999 (over the ocean). The probe masks negative values (`value < 0`); any bulk ingest must do the same explicitly. The zeros on the heaviest days are real pixel values, not nodata.
- **None of the gridded products approaches the ~572 mm in 48 h reported by local gauges.** That figure comes from press and papers (secondary source, unverified, `configs/audit.yaml`). The closest gridded 48 h figure is IMD: 6.6 + 179.24 = 185.8 mm (about a third of 572); the others range from 28 to 111 mm over 29-30 Jul (ERA5 UTC 110.2, ERA5 IST 107.1, IFS 108.8, POWER LST 80.2, POWER UTC 81.4, CHIRPS 28.4). The IMD gauge-based grid is the closest to the reported extreme.
- **Hypothesis**: coarse cells (0.25 deg and larger) average a point maximum in steep orography, and CHIRPS (satellite-infrared based) misses or mis-times orographic warm rain. Neither cause was tested here.

Consequences for Phase 1 (recommendations, not decisions): fix the day definition explicitly in `configs/` and convert every product to one day basis before joining (the IMD 08:30 IST day is the natural basis for Indian cells if IMD is the gauge reference); treat the IMD gauge grid as the gauge-reference candidate for India only (Nepal and other non-Indian parts of the himalaya box need another gauge reference, for example the 2 GHCN-D Nepal stations, or must be evaluated without a gauge grid); treat CHIRPS, ERA5 and MERRA-2 as underestimating orographic extremes at this location and therefore as inputs that a rain-corrector model has to adjust upward, not as ground truth.

## 3. Real fault labels (GHCN-Daily QC flags)

Source: `reports/phase0_data_audit.json`, probe `ghcnd`. A flag means the value failed a NOAA automated quality check; the value is kept and flagged. Cross-check: independently re-parsing the 140 downloaded `data/raw/ghcnd/dly/*.dly` files (PRCP only) gives 3,099,630 valid values and 391 flagged, identical to the report.

- Totals: **391 flagged of 3,099,630 valid PRCP values** across **140 stations (138 India, 2 Nepal)**, 0 failed downloads.
- In-domain versus outside: regions `himalaya` + `western_ghats` hold **309** flags (240 + 28 + 13 + 28); **82** more are at stations outside both region boxes (81 lowland + 1 upland).
- Elevation rule: upland = station elevation >= 500 m (`upland_min_elev_m: 500`); a station with unknown elevation counts as lowland; 0 stations have unknown elevation here.

| region\|elevation | stations | valid values | flagged | flag mix |
|---|---|---|---|---|
| himalaya\|lowland | 51 | 1,111,831 | 240 | D:180 S:33 G:13 O:9 K:5 |
| himalaya\|upland | 17 | 333,965 | 28 | S:18 G:5 O:5 |
| western_ghats\|lowland | 25 | 549,245 | 13 | O:4 S:6 G:3 |
| western_ghats\|upland | 11 | 272,562 | 28 | O:16 S:9 G:3 |
| outside_domain\|lowland | 35 | 803,119 | 81 | D:61 S:8 O:7 G:5 |
| outside_domain\|upland | 1 | 28,908 | 1 | S:1 |

Flag meanings: D duplicate day, S spatial inconsistency, G gap check, O climatological outlier, K streak / frequent-value.

Findings the headline numbers hide (from the same `.dly` files, using an ad-hoc parse of PRCP lines: year = columns 12-15, quality flag = 7th character of each 8-character day block; illustrative, not a committed script, but its totals equal the project parser's):
- **Four stations hold 245 of the 391 flags (63%)**: North Lakhimpur (IN003050401, 64), Siliguri (IN024059900, 63), Puri (IN017110100, 62, outside the region boxes) and Chandigarh IAFB (IN006011400, 56). Their flags are almost all D (62, 62, 61, 56 = 241), and they fall in whole duplicated months in historic years: North Lakhimpur 1930-1931 (62 of 64 flags), Siliguri 1932 (62 of 63), Chandigarh 1961-1962 (56 of 56), Puri 1966 (61 of 62). This is what makes D dominate himalaya\|lowland.
- **Within the modelling period the flag count is tiny.** Counting only 2007-2024 (`period` in `configs/domain.yaml`) the same files give 212,919 valid values and **10 flagged** (himalaya lowland 3 of 68,476; himalaya upland 4 of 30,472; western_ghats lowland 1 of 44,768; western_ghats upland 2 of 18,661; outside_domain lowland 0 of 48,150 and upland 0 of 2,392). Another 6,235 valid values are dated 2025 and are excluded here. Most of the 3.1 million values predate 2007 (about 6.9% of valid values fall in 2007-2024). Recomputed with the project's own `aetherguard.audit.ghcnd.read_dly` and `flag_census` on the existing `.dly` files; the same parser reproduces the all-years totals (3,099,630 valid, 391 flagged). The parsing rule is described in section 8.
- western_ghats upland has 28 flags, mostly O (16 of 28). Nepal: the two stations (Kathmandu Airport 6,086 valid, Dhankuta 3,819 valid) have 0 flags.
- **Caveat on the region boxes**: the boxes in `configs/domain.yaml` are coarse rectangles (himalaya lat 22-36, lon 72-98; western_ghats lat 8-21.5, lon 72.5-78.5). The station list in the JSON shows "himalaya" includes plains stations such as AHMADABAD, NEW DELHI/SAFDARJUN, CALCUTTA/ALIPORE, CALCUTTA/DUM DUM, JAIPUR/SANGANER and JODHPUR, and "western_ghats" includes Deccan-plateau and other non-Ghats stations such as BEGUMPET OBSY, NIZAMABAD, PBO ANANTAPUR and SURAT. The config itself notes that terrain and country filters refine these boxes in Phase 1. Region and "upland" labels in the census therefore do not mean mountain stations.

Consequence: supervised real-fault data is thin. Only 10 real flags fall in the modelling period and Nepal has 2 stations with none. The integrity engine's evaluation will lean on injected faults, which must be reported separately from results on real flags; the real-flag census is best used as a sanity check of realistic fault rates and types (O, S, G in recent years) and, for D, as a historic data-quality note.

## 4. Landslide label availability

- **Kerala** (`kerala_inventory_search`, query "Kerala landslide inventory 2018"): status `ok` only means 5 Zenodo candidates came back. The top hit is "Multi-temporal landslide inventory for southern Sikkim State, India" (CC-BY-4.0, 33 files); the other four are Kaikoura (NZ), Lombok (Indonesia), Turkiye and a Martian inventory. **No Kerala inventory was identified.**
- **Nepal** (`nepal_inventories`, Zenodo 10.5281/zenodo.10410752, CC-BY-4.0): 2 files (`Hexplot.zip`, `LandslideDatabase.xlsx`, 1.93 MB). The record note says it is a database of 117 Nepal landslide inventories (metadata); each inventory is a separate download. It is **not** a set of event polygons.
- **Gaolan** (`gaolan`, Zenodo 10.5281/zenodo.15180387, CC-BY-4.0): 10 files, 48.69 GB (monthly `.7z` archives 2019-08 to 2020-03, terrain data, a format description image). China loess-slope multi-sensor data; the probe notes "no fault labels documented". Not checked beyond the file list.
- **Lithology** (`lithology_search`): 5 candidates, top is a 250 m landform/lithology class (CC-BY-SA-4.0); relevance and suitability unverified. None of the five hits is a lithology map usable as-is; one, "Rainfall Induced Landslide Susceptibility Maps using GIRI model" (CC-BY-4.0, 2 files), is a landslide-susceptibility product worth a look, and the other three are off-topic (water chemistry, a medical study, a geomorphology paper).
- **NASA Global Landslide Catalog** and **HMA landslide catalog v2**: pending the user (section 1).

## 5. Licences and provenance items still open

From `manifests/data_manifest.jsonl` (149 entries, `manifest problems: none`):
- CHIRPS: the licence field holds a pointer ("see https://www.chc.ucsb.edu/data/chirps (verify licence in review)"), not a licence statement.
- Copernicus DEM GLO-30: "Copernicus DEM licence (free, attribution; verify in review)".
- IMD gridded rainfall: "IMD data terms (verify in review)"; additionally the manifest `url` for the IMD file is the homepage `https://imdpune.gov.in`, not the resource actually fetched by `imdlib`.
- NOAA GHCN-Daily and ISD: recorded as "NOAA NCEI open data (public domain)".

Verify these before any redistribution of derived data or artefacts. Zenodo records are CC-BY-4.0 (Nepal, Gaolan) and CC-BY-SA-4.0 (landform/lithology); attribution and share-alike obligations apply.

## 6. Ingest feasibility and volumes

Free-tier Open-Meteo limit assumed in `configs/audit.yaml`: 10,000 call units/day (source and date recorded there). Period 2007-01-01 to 2024-12-31 = 6,575 days, 3 variables.

| strategy | points | call units | days at free limit |
|---|---|---|---|
| full domain, ERA5 0.25 deg grid, whole period | 7,120 | 3,343,857 | 334.4 (infeasible, > 30 days) |
| full domain, 0.05 deg per-cell, whole period | 178,000 | 83,596,429 | 8,359.6 (infeasible) |
| sampled case-control, 30,000 points x 60 days | 30,000 | 128,571 | 12.9 (feasible) |

Bulk alternatives (estimates in the report):
- CHIRPS p05 daily: about 18.9 GB for 2007-2024 is the **compressed `.tif.gz` download** (mean size of the 4 downloaded files x number of days; 2,000 x 7,200 global grid). Each extracted global GeoTIFF is 57,612,616 bytes (measured on the 4 files in `data/raw/audit/chirps/`), so keeping all 6,575 days uncropped would take about 378.8 GB. Phase 1 must crop to the domain on extraction and delete the global files.
- Copernicus DEM: about 20.4 GB for the domain (462 tiles); ESA WorldCover: about 4.8 GB (63 tiles); OSM roads (Geofabrik India + Nepal): 2.12 GB of `.pbf`, which needs an extra reader dependency decided in Phase 1.
- NASA POWER bulk zarr: readable anonymously (dims time 17,898, lat 361, lon 576; 74 variables including GWETTOP, GWETROOT, GWETPROF).
- IMD yearly grid files: about 25 MB each (the 2024 file is 25,495,560 bytes; grid shape (366, 129, 135)).
- SoilGrids: point read works (clay 0-5 cm = 280.0 at the point); nodata -32768.
- Gaolan: 48.69 GB (only if the sensor data is wanted).

Against the spec's raw-data cap of about 60 GB (`docs/superpowers/specs/2026-09-30-aetherguard-design.md`): the recommended sources without Gaolan sum to about 47 GB, all of it compressed or per-file estimates (CHIRPS 18.9 compressed downloads; DEM 20.4 from one tile x 462; WorldCover 4.8 from one tile x 63; OSM 2.12 `.pbf`; IMD about 0.46 from 18 yearly files of about 25.5 MB; GHCN-D about 0.08, the 140 station files already downloaded). Adding Gaolan (48.7 GB) would bring the total to about 95 GB, well over the cap, so Gaolan should be sampled or skipped unless a concrete need appears. The POWER zarr is read remotely in chunks and is not counted. Cropping CHIRPS to the domain would shrink its share substantially, but that figure was not measured.
- Downloaded so far in Phase 0: about 210 MB (manifest).

## 7. Recommended Phase 1 source set (recommendations for the user to approve)

| area | source | recommendation | reason |
|---|---|---|---|
| Rain, gauge reference | IMD 0.25 deg gauge grid | keep as primary reference candidate for India only | closest to the reported extreme (179 mm day); daily, bulk yearly files; NaN outside India (checked at Kathmandu and Pokhara), so Nepal and other non-Indian parts of the himalaya box need another reference (GHCN-D has 2 Nepal stations) or no gauge grid; the 08:30 IST day basis applies to Indian cells; licence and day convention to confirm |
| Rain, gridded input | CHIRPS p05 | keep as bulk input with caveats | ~19 GB compressed download (about 379 GB if extracted uncropped, so crop on extraction); 0 mm on two of the heaviest days at the pixel, so needs the rain corrector |
| Rain, comparison and antecedent | NASA POWER (bulk zarr) | keep for comparison and antecedent wetness | bulk readable, includes GWETTOP/GWETROOT/GWETPROF; underestimates the event |
| Rain, per-cell API | Open-Meteo ERA5 / ERA5-Land / IFS | replace per-cell ingestion with a sampled design; drop ERA5-Land precipitation (provisional) | full-grid ingest infeasible (334 to 8,360 days); ERA5-Land precipitation was null at the one point tested, so dropping it is provisional |
| Soil moisture | Open-Meteo ERA5-Land soil moisture (works) or POWER GWET* | use POWER bulk, or Open-Meteo only in the sampled case-control design | per-cell API calls infeasible at scale |
| Terrain | Copernicus DEM GLO-30 | keep | ~20 GB, reachable, 908 m at the reference point; licence wording to verify |
| Land cover | ESA WorldCover | keep | ~4.8 GB |
| Soil | SoilGrids | keep | point read works |
| Roads | OSM Geofabrik extracts | keep, decide the `.pbf` reader | 2.12 GB; needs extra dependency |
| Real fault labels | GHCN-Daily flags | keep for calibration and sanity only | only 10 flags among 212,919 valid values in 2007-2024; most flags are old duplicate months |
| Station sensors | NOAA ISD (414 active IN/NP stations) | keep as candidate, not yet evaluated | hourly; QC flags live in the full files not fetched in Phase 0 |
| Lithology | GLiM (Global Lithological Map) | not verified; verify manually or drop the lithology feature (spec 7.1) | GLiM is hosted on PANGAEA (not Zenodo), so the Zenodo search could not find it |
| Landslide labels | NASA GLC, HMA v2 | pending the user's export and account | not yet auditable |
| Landslide labels | Zenodo Kerala search, Nepal database | drop the Kerala search hit; Nepal record is metadata only | no Kerala inventory found; Nepal needs per-inventory downloads |
| Sensor physics | Gaolan loess slopes | optional / drop by default | China loess, no fault labels documented, 48.69 GB |

These are recommendations; nothing is approved until the user decides.

## 8. Reproduce

```
.venv/Scripts/python -m aetherguard.audit.run                      # full audit (downloads ~0.2 GB into data/)
.venv/Scripts/python -m aetherguard.audit.run --only earthdata_credentials,manual_catalogs   # after the manual steps; writes to reports/partial/
.venv/Scripts/python -m pytest tests/live -m live -v               # live smoke tests (Open-Meteo, POWER)
```
The IST re-query is the command quoted in section 2. The GHCN-D per-year and per-station counts use the downloaded files under `data/raw/ghcnd/dly/`; the following is an illustrative description of the parsing, not a committed script (the committed parser is `aetherguard.audit.ghcnd.read_dly`): a line with element `PRCP` (columns 18-21), year in columns 12-15, then 31 blocks of 8 characters from column 22 (value 5 characters, measurement flag, quality flag, source flag); a value of `-9999` is missing, and a non-blank quality flag is a flag. Library versions used: `requirements-lock.txt`.

## 9. What this audit did not verify

- All point probes (rain products, DEM, SoilGrids, WorldCover, IMD) ran at **one Western Ghats point (Wayanad, 11.55 N 76.13 E) for 4 days of 2024**. Nothing was probed at a Himalayan point (except the IMD NaN check at Kathmandu, Pokhara and Dehradun in section 2, read from the already downloaded 2024 file).
- Availability over 2007-2024 was not checked for CHIRPS, IMD (only the 2024 file was fetched), Open-Meteo or the DEM.
- The era5_land precipitation null was seen at one point only, so "drop era5_land precipitation" is provisional.
- The HMA v2 catalog distribution format (CSV versus shapefile) is unverified; the audit expects a CSV export.
- The CHIRPS and IMD day definitions are documentation-based and unconfirmed.
- The 48 h ~572 mm local-gauge figure is a secondary source and has not been checked against a primary source.
- Gaolan was checked by its file list only; Zenodo search results were not checked for relevance beyond titles.

## 10. Phase 1 preconditions (from the final review)

Checklist to settle before or at the start of Phase 1 ingest:

- [ ] Catalog timestamp policy first: keep the raw timestamp, whether it carried a UTC offset, and the local date, then convert explicitly to the frozen day basis. The review's probe showed that "2024-07-30T02:00:00+05:30" becomes 2024-07-29 (UTC) while the same time without an offset stays 2024-07-30.
- [ ] URL-query redaction in `download()`, `Manifest.add` and `DownloadError` text before any Earthdata or pre-signed-URL ingest (the manifest is tracked in git).
- [ ] Manifest robustness: handle a torn last JSONL line; `is_current` re-reads the whole file per call (cache entries); a refresh policy for GHCN files; show `retrieved_utc` in the report.
- [ ] `flag_census` period filter (2007-2024), so the real-flag counts match the modelling period (section 3).
- [ ] Record source units and the returned grid-cell lat/lon in evidence (Open-Meteo snapped 11.55 / 76.13 to 11.5 / 76.25; POWER PRECTOTCORR units).
- [ ] Single source of truth for cell size (`grid.CELL_DEG` versus `configs/domain.yaml` versus the literal in feasibility) and a public `period_days` helper instead of `feasibility._period_days`.
- [ ] `grid.neighbours()` range check.
- [ ] Record the `manifest.verify()` result in the generated report.
- [ ] Refine the region boxes by terrain and country (section 3 caveat).
