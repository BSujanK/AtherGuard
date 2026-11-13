# W4 source probe: soil moisture and antecedent wetness (phase 8)

Probed 2026-11-13T14:55:17Z (metadata) and on 54 days of June-December 2025 (mapping). Anonymous HTTPS only; no credential was read. **Chosen: the bucket water balance on the IMERG Late store**, state at the end of IMD day D-2, identical in training and live by construction. No external product passed all five criteria.

Criteria: (a) history over 2007-2017 and 2018-2025; (b) available by 11:00 IST with a declared, measured lag; (c) the same quantity in training and live, or a mapping that passes a check fixed before it is measured; (d) feasible download; (e) no new account, key or licence.

| candidate | coverage | latency (how measured) | size | access | verdict |
|---|---|---|---|---|---|
| SMAP L4 surface and root-zone soil moisture (SPL4SMGP / SPL4SMAU) | from 2015-03-31: 2015-2017 only of the development years | newest granule ended 63 h before the probe (CMR) | 143 MB per 3-hourly global granule; needs spatial subsetting | Earthdata login (existing) | fails (a): 8 of the 11 development years have no data; 347 of the 789 development positives fall after its start, and a model would treat the absence as a year effect |
| ERA5 volumetric soil water, ARCO-ERA5 public store (training) with ERA5T (live) | 1940-01-01 on; final ERA5 to 2026-06-30, ERA5T to 2026-11-07 | ERA5T ends 6 days before the probe day (store attribute, last updated 2026-11-13 04:20 UTC) | 1.2 MB per global hourly field and layer (measured on 324 chunks) | anonymous (Google public bucket); the CDS route needs an account (not used) | passes (a), (c), (d), (e); (b) only with a declared lag of at least 7 days, measured once: not chosen: a week-old state, an update schedule nobody guarantees, one latency observation; kept as a possible later study if the bucket shows that wetness matters |
| ERA5 (training) with ECMWF IFS open-data analysis `vsw` (live, 12 UTC of D-1) | IFS open data carries `vsw` from 2024-11-13 (measured by index), so only as the live side | the 12z run of D-1 is published by about 20 UTC of D-1 (ingest.ecmwf, phase6_ecmwf_publication) | about 0.3-0.5 MB per layer by byte range | anonymous | fails (c): mapping check against ERA5 on 54 days of 2025: root zone Spearman 0.80, rank difference 0.140; surface Spearman 0.85, rank difference 0.119 (criterion 0.80 and 0.10) |
| ERA5 (training) with NOAA GFS analysis SOILW (live, 00 UTC of D) | GFS analyses on the public bucket from 2021 (2018 absent), so only as the live side | the 00z f000 file is out by about 04 UTC (live GFS ingest) | about 0.5 MB per layer by byte range | anonymous | fails (c): mapping check: root zone Spearman 0.85, rank difference 0.114; surface Spearman 0.86, rank difference 0.112; ERA5 00 UTC against its own 12 UTC, the reference a usable stand-in should approach: Spearman 0.99, rank difference 0.022 |
| GLDAS Noah 2.1 (main and Early Product), GLDAS CLSM 2.2, FLDAS | 2000 / 2003 / 1982 on | newest granule ended 105 / 29 / 74 / 44 days before the probe (CMR) | 21 MB per 3-hourly granule | Earthdata login (existing) | fails (b): weeks to months behind real time; no live product of the same quantity |
| MERRA-2 land (NASA POWER GWETTOP / GWETROOT, already on disk for v2) | 1980 on (the local copy 2007-2024) | newest M2T1NXLND granule ended 43 days before the probe (CMR) | already local | anonymous / Earthdata | fails (b): weeks behind; and in v2 dropping these inputs changed development FA@90 by less than its SE (history below) |
| Bucket water balance on the IMERG Late store (this project's data), state at the end of IMD day D-2 | IMERG Late from 2006-10-01, complete (0 missing days) | lag 2 IMD days: in 32 of 33 published live runs the UTC day D-2 came from the Late store (run.json imd_day_inputs) | no download | none new | passes (a)-(e); identical in training and live by construction: chosen: the baseline any external product must beat, and no external product passed |
| Snow cover, MODIS MOD10C1 v061 (0.05 degree daily) | from 2000-02-24 | newest granule ended 39 h before the probe (CMR): lag 3 days at 11:00 IST | 4.1 MB per global day | Earthdata login (existing; NSIDC download not tested) | not pursued here: 7,619 of the 36,792 panel cells but only 40 of the 789 development positives lie at 3000 m or more; monsoon cloud cover over the snow map is not measured here; kept out to hold the candidate count small. A later study for the high cells, where October-December rain may fall as snow |

## Mapping check (criterion fixed before the first measurement)

over the 0.25-degree pixels that hold panel cells, on the probe days (June-December 2025, every 4th day), for the root zone (0-100 cm, depth-weighted layers) and the surface layer: (i) median over pixels of the per-pixel Spearman rank correlation across days >= 0.80, and (ii) median over pixels of the mean absolute difference of per-pixel percentile ranks (each product ranked within its own series at that pixel, the per-cell quantile transform) <= 0.10. Both must hold for the live product to stand in for ERA5.

| pair | pixels | median Spearman [p10, p90] | median rank difference (p90) | passes |
|---|---|---|---|---|
| ifs_vs_era5_root_12utc | 2,512 | 0.803 [0.396, 0.928] | 0.140 (0.256) | no |
| ifs_vs_era5_surface_12utc | 2,512 | 0.852 [0.630, 0.919] | 0.119 (0.189) | no |
| gfs_vs_era5_root_00utc | 2,509 | 0.855 [0.572, 0.944] | 0.114 (0.217) | no |
| gfs_vs_era5_surface_00utc | 2,508 | 0.861 [0.487, 0.925] | 0.112 (0.233) | no |
| era5_00_vs_12_root_reference | 2,525 | 0.992 [0.979, 0.997] | 0.022 (0.037) | yes |

Median root-zone level difference (m3/m3): IFS - ERA5 -0.008, GFS - ERA5 -0.087. The first run of the check mapped the IFS grid with a 180-degree longitude error (its first longitude is 180, i.e. -180); it was rerun with the same criterion and only the corrected numbers are shown.

## What a late start does to SMAP

SMAP L4 begins on 2015-03-31. The development years are 2007-2017, so 2007-2014 would have no value: either the development set shrinks to 2015-2017 (347 of the 789 positives, three of the seven folds, so v3's year-blocked folds and its frozen reference no longer apply), or the model sees a wetness input that is missing in most years and learns the missingness as a year effect. Neither is the comparison protocol v3 asks for, so SMAP fails (a).

## Lag of the bucket (measured on the published live runs)

In 32 of 33 live runs (`data/live/<day>/run.json`, `imd_day_inputs`), the UTC day D-2 came from the IMERG Late store, so IMD day D-2 (0.875 of UTC D-3 and 0.125 of UTC D-2) is all Late at 11:00 IST. The bucket at the end of IMD day D-2 therefore reads exactly the files training reads; the rain of IMD days D-1 and D stays in the rain inputs. Runs without it: 2026-10-25 (started 2026-10-25T07:00:07+00:00, UTC D-2 from early). On such a day the live adapter, reading the Late store only, finds IMD day D-2 missing and returns NaN (the strict rule); what the live run does then is decided when it is wired.

## Snow

Panel cells with mean elevation of 3000 m or more: 7,619 of 36,792; development positives there: 40 of 789.

## What earlier development studies said

- v2 (IMD rain) with MERRA-2 wetness: FA@90 0.1982 (SE 0.0138); without the wetness group 0.2017 (SE 0.0141) (`reports/phase3_hazard_cv_report.json`).
- v3 group selection: imerg_core 0.1955; with the antecedent precipitation index 0.1988 (`reports/phase6_v3_cv_report.json`).
- Both differences are within one bootstrap SE: a linear antecedent index and a coarse reanalysis wetness added little to the 1-90 day rain accumulations. The bucket differs from both (it saturates and dries with the season), which is what this study tests; a small or no gain is a plausible outcome.

## Decisions for the user

- ERA5-Land through the Copernicus CDS would need a CDS account and licence acceptance: not done. The anonymous ARCO-ERA5 store gives ERA5 (not ERA5-Land, 0.25 degree) without an account.
