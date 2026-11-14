# Ground-truth source survey (phase 8, W1b)

Survey of 2026-11-13 for dated, located, openly licensed landslide events inside the scored cells (Himalaya and Western Ghats of India, Nepal, Bhutan). How a source found its slides decides its bias: reported events follow roads and settlements; imagery-mapped inventories do not, but the open ones here are dated only to a season. Counts come from the inventory reports under `data/raw/manual/<source>/` and from `reports/phase8_ground_truth_expansion.json`.

Gate (storm clusters): all sources 701 (MET, 551 over); without BIPAD 72 (NOT MET, 78 short); India only 71 (NOT MET, 79 short).

**BIPAD licence.** The BIPAD Nepal register states no licence. Its raw rows (`data/raw/manual/bipad_nepal/`, git-ignored) stay on this machine and are never committed or redistributed; only counts appear in the reports, and the gate is given with and without it.

## Sources

### BIPAD Nepal incident register (NDRRMA)

- URL: https://bipadportal.gov.np/api/v1/incident/?hazard=17
- decision: loaded (licence to be settled by the user)
- licence: No licence or terms stated on the portal or in its API (checked 2026-11-13). Public API, no key or account.
- date precision: day (incidentOn)
- location precision: per-ward point; bounded by the ward box (median bound of admitted rows 3.81 km)
- how found: reported (Nepal Police and agencies)
- years: 2011-2026
- count in domain: 6672 incidents; 2009 admitted at 5 km (4174 over 5 km, 489 same-ward duplicates); in assembly v2: 1331 held-out records on panel days, 142 development
- overlap: HMA catalog (Nepal to 2018) and GFLD: a few cross-source duplicates (expansion report)
- use: raw rows local only, never committed; the gate is reported with and without it

### Global Fatal Landslide Database v2 (Froude and Petley)

- URL: https://services2.arcgis.com/Dn40vzt2R38VJsSS/arcgis/rest/services/Fatal_landslide_points_2004_to_2017/FeatureServer
- decision: loaded (development labels)
- licence: 'The dataset is covered by a University of Sheffield copyright and database rights reserved 2019. For the full license see http://www.nationalarchives.gov.uk/doc/open-government-licence/version/2/' (Landslide Blog, 2019-06-18); public feature service, no account needed to query
- date precision: day
- location precision: polygon of slide or village; radius of equal-area circle
- how found: reported (news, remapped by the authors)
- years: 2004-2017
- count in domain: 1431 points in India, Nepal, Bhutan; 546 admitted at 5 km (260 non-rain trigger, 567 over 5 km); 364 development records added
- overlap: HMA / GLC development positives (repeats dropped)
- use: development labels 2007-2017 only (no held-out years)

### Kerala 2018 monsoon inventory (Hao et al. 2020, ESSD; van Westen 2020, DANS)

- URL: https://doi.org/10.17026/dans-x6c-y7x2
- decision: downloaded, not admitted
- licence: CC-BY-4.0 (DANS record)
- date precision: window 1 June - 26 August 2018 (87 days), no per-slide date
- location precision: point per slide
- how found: imagery (NRSC, GSI) and Google Earth, partly field-checked
- years: 2018
- count in domain: 4,728 slides, 4,726 in scored cells (365 cells)
- overlap: 2018 catalog events of Kerala (August 2018)
- use: over the 7-day window limit: kept for spatial (where) checks, never scored as dated events

### Kodagu 2018 (Meena et al. 2021, Landslides)

- URL: https://doi.org/10.1007/s10346-020-01602-4
- decision: not found openly
- licence: no open dataset located
- date precision: post-event PlanetScope window
- location precision: polygons
- how found: imagery
- years: 2018
- count in domain: n/a
- overlap: 2018 catalog
- use: user decision: ask the authors

### Himachal Pradesh 2023 monsoon (HPSCCC post-monsoon mapping 2025; Sana et al. 2025, Landslides, ~6,500 slides)

- URL: https://www.hpsdma.nic.in/admnis/admin/showimg.aspx?ID=3759
- decision: not obtained
- licence: report PDF; no data licence; paper data availability not open
- date precision: season window
- location precision: polygons
- how found: imagery
- years: 2023
- count in domain: n/a
- overlap: W1 reported 2023 rows
- use: season-dated: not admissible as dated events even if obtained

### Kerala 2019-2021 and Wayanad 2024 named events (Puthumala, Kavalappara, Pettimudi, Koottickal, Mundakkai)

- URL: https://www.nrsc.gov.in/sites/default/files/pdf/DMSP/Charter_1029_VAP_3_31july2024.pdf
- decision: already in W1 reported events (except Mundakkai: no W1 row; NRSC/Charter maps only)
- licence: news facts; Charter/NRSC products without a data licence
- date precision: day
- location precision: village
- how found: reported
- years: 2019-2024
- count in domain: single events
- overlap: W1
- use: no change

### NASA COOLR / Landslide Reporter refresh

- URL: https://gis.earthdata.nasa.gov/portal/rest/services/Landslides/COOLR_Reports_Points/FeatureServer/0
- decision: no new records
- licence: NASA open data
- date precision: day
- location precision: stated per record
- how found: reported
- years: to 2025-05-18
- count in domain: 0 new: the service's max event_date (2025-05-18) equals the loaded export
- overlap: is the loaded source
- use: none

### NASA High Mountain Asia multitemporal inventories (HMA_MTLI, HMA2_MTLI, NSIDC)

- URL: https://nsidc.org/data/hma_mtli
- decision: not admissible
- licence: NASA open data; Earthdata login (the existing account would do)
- date precision: year
- location precision: points / polygons
- how found: imagery
- years: 2009-2020
- count in domain: three Nepal highways and the Arun basin
- overlap: BIPAD
- use: annual dating, not scoreable

### GSI Bhukosh national landslide inventory

- URL: https://bhukosh.gsi.gov.in
- decision: user decision (account and terms)
- licence: download needs a registered account and acceptance of Terms and Conditions
- date precision: partly dated (post-disaster studies by year)
- location precision: polygons
- how found: field and imagery
- years: to 2025
- count in domain: largest Indian source (tens of thousands)
- overlap: unknown
- use: not used

### NRSC Landslide Atlas of India (2023)

- URL: https://www.isro.gov.in/media_isro/pdf/LandslideAtlas_2023.pdf
- decision: user decision (request to NRSC)
- licence: atlas PDF; no data licence; data via Bhuvan login
- date precision: event inventories by event, mostly undated per slide
- location precision: polygons
- how found: imagery
- years: 1998-2022
- count in domain: about 80,000
- overlap: Kerala 2018 (NRSC part of Hao)
- use: not used

### State disaster authority situation reports (KSDMA, HPSDMA, USDMA)

- URL: https://www.hpsdma.nic.in
- decision: not done (manual extraction)
- licence: government PDFs, no stated data licence
- date precision: day
- location precision: district / village
- how found: reported
- years: varies
- count in domain: not counted
- overlap: news
- use: candidate for a future manual pass

### ReliefWeb API

- URL: https://apidoc.reliefweb.int/
- decision: user decision (registration)
- licence: a pre-approved appname is required on every call since 1 November 2025
- date precision: report day
- location precision: country / region
- how found: reported
- years: all
- count in domain: n/a
- overlap: news
- use: not used

### EM-DAT

- URL: https://doc.emdat.be/docs/legal/terms-of-use/
- decision: not admissible (and needs registration)
- licence: free for non-commercial use after registration; national governments counted as commercial users
- date precision: event
- location precision: admin area
- how found: reported
- years: all
- count in domain: n/a
- overlap: n/a
- use: location far coarser than 5 km

### GDACS / Copernicus EMS

- URL: https://emergency.copernicus.eu/mapping/list-of-components/EMSR049
- decision: nothing to load
- licence: open
- date precision: n/a
- location precision: n/a
- how found: imagery
- years: n/a
- count in domain: no Indian landslide activation found (EMSR049 Uttarakhand 2013 is a flood activation)
- overlap: n/a
- use: none

### Global ML landslide datasets (DLR Landslide Reference Data, GLaD4CD, GBMT-SLID; Zenodo)

- URL: https://zenodo.org/records/17007637
- decision: not loaded
- licence: CC BY 4.0
- date precision: event day (from reports) / image pair
- location precision: polygons
- how found: reported then imagery-verified
- years: 2015-2025
- count in domain: a handful of Indian events expected; event lists sit inside 6 GB archives
- overlap: W1 large events
- use: low yield for the cost

### GDELT DOC 2.0

- URL: https://api.gdeltproject.org/api/v2/doc/doc
- decision: used for the live harvester (review queue only)
- licence: open, no key; one request per 5 s
- date precision: report day
- location precision: from title (geocoded)
- how found: reported
- years: live
- count in domain: see the harvest summary
- overlap: news
- use: candidates, never auto-admitted

## Decisions for the user (nothing was signed up for or requested)

- BIPAD Nepal register: no licence stated. Confirm its terms with NDRRMA or accept local-only use. Until then its raw rows stay local, are never committed, and every gate count is given with and without it (without it the gate is not met).
- GSI Bhukosh: an account and acceptance of its terms (the largest Indian inventory).
- NRSC Landslide Atlas / Bhuvan event inventories: a data request to NRSC.
- ReliefWeb: an appname registration.
- Authors of the Kodagu 2018 and Himachal 2023 inventories: a data request (they would still be window-dated).
