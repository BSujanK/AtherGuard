# Phase 6 live-source probe (Stage A, Task 1)

Generated 2026-10-14T19:51:30.426229+00:00 UTC. Domain bbox {'lat_min': 8.0, 'lat_max': 36.0, 'lon_min': 72.0, 'lon_max': 98.0}. Every number below was measured by `python -m aetherguard.live.probe` and is stored in the JSON report next to this file; `not measured` means the probe could not obtain it.

## Decision table

| source | reachable | decision | basis | latency h | bytes/day (domain) | s/day | history start |
|---|---|---|---|---|---|---|---|
| imerg_late_daily | yes | use | measured | 14.46 | 125295 | 7.823 | 1998-01-01 |
| imerg_early_daily | yes | fallback | measured | 4.539 | 128530 | 7.96 | 1998-01-01 |
| imerg_late_halfhourly | no | drop | not measured | 14.38 | not measured | not measured | 1998-01-01 |
| gfs_nomads_grib_filter | yes | use | measured: live path for the latest cycle | 3.95 | 1.019e+06 | 18.73 | about 10 days back (directory listing shows the last 10 days) |
| gfs_nomads_opendap | no | drop | measured: service answers with a retirement notice | not measured | not measured | not measured | not measured |
| gfs_aws_archive | yes | use | measured: archive path for 2021-2024 (and live fallback) | 3.666 | 2063920 | 34.5 | 2021-01-01 |
| imd_realtime | no | drop | not measured | not measured | not measured | not measured | not measured |
| ghcnd_recent | yes | use | measured: integrity-engine input; coverage and latency are the limits | 115.9 | 306.1 | 0.02204 | 1990 or earlier per station (GHCN-Daily inventory) |

## imerg_late_daily

- URL pattern: CMR discovery https://cmr.earthdata.nasa.gov/search/granules.json?collection_concept_id=..., then https://opendap.earthdata.nasa.gov/collections/<concept id>/granules/<GranuleUR>.dap.nc4?dap4.ce=<constraint> (subset) or https://data.gesdisc.earthdata.nasa.gov/data/GPM_L3/GPM_3IMERGDL.07/<yyyy>/<mm>/<file>.nc4 (full file); the file name carries a version letter (V07B for old days, V07C for new) so it must be taken from CMR, never constructed
- Auth: Earthdata login (netrc) and the account's approval of the GES DISC application
- Format: netCDF4/HDF5, one file per UTC day, global 0.1 degree
- Error class: not measured
- Variables: `{"precipitation": {"dims_order": ["time", "lon", "lat"], "fill_value": -9999.900390625, "lat_ascending": true, "lon_ascending": true, "units": "mm/day", "variable": "precipitation"}}`
- Details: `{"collection_concept_id": "C2723754859-GES_DISC", "data_access": "ok", "days": [{"array": {"dims_order": ["time", "lon", "lat"], "domain_valid_share": 1.0, "engine": "h5netcdf", "fill_value": -9999.900390625, "lat_ascending": true, "lat_range": [8.05, 35.95], "lon_ascending": true, "lon_range": [72.05000305175781, 97.94999694824219], "point_lat": 11.450000000000006, "point_lon": 76.1500015258789, "point_plausible": true, "point_value": 61.00499725341797, "shape_domain": [1, 260, 280], "shape_full": [1, 260, 280], "units": "mm/day", "variable": "precipitation"}, "day": "2018-08-15", "subset": {"bytes": 217922, "constraint": "dap4.ce=/precipitation[0][2520:2779][980:1259];/time;/lon[2520:2779];/lat[980:1259]", "dims_assumed_or_read": ["time", "lon", "lat"], "pattern": "hyrax_cloud_dap4_dap.nc4", "pixels": {"lat": [980, 1259], "lon": [2520, 2779]}, "seconds": 8.032361300000048, "suffix": ".dap.nc4"}, "which": "historical"}, {"array": {"dims_order": ["time", "lon", "lat"], "domain_valid_share": 1.0, "engine": "h5netcdf", "fill_value": -9999.900390625, "lat_ascending": true, "lat_range": [8.05, 35.95], "lon_ascending": true, "lon_range": [72.05000305175781, 97.94999694824219], "point_lat": 11.450000000000006, "point_lon": 76.1500015258789, "point_plausible": true, "point_value": 0.0, "shape_domain": [1, 260, 280], "shape_full": [1, 260, 280], "units": "mm/day", "variable": "precipitation"}, "day": "2026-10-13", "subset": {"bytes": 125295, "constraint": "dap4.ce=/precipitation[0][2520:2779][980:1259];/time;/lon[2520:2779];/lat[980:1259]", "dims_assumed_or_read": ["time", "lon", "lat"], "pattern": "hyrax_cloud_dap4_dap.nc4", "pixels": {"lat": [980, 1259], "lon": [2520, 2779]}, "seconds": 7.823465599998599, "suffix": ".dap.nc4"}, "which": "newest"}], "full_file_bytes_cmr": 28674220, "historical_file": "3B-DAY-L.MS.MRG.3IMERG.20180815-S000000-E235959.V07B.nc4", "latency_basis": "CMR ingest time minus end of the UTC day", "latency_hours_last5": [14.464166944444443, 14.453889166666666, 14.530000277777777, 14.496666944444444, 14.462778055555555], "latency_hours_median": 14.464166944444443, "newest_day": "2026-10-13", "newest_file": "3B-DAY-L.MS.MRG.3IMERG.20261013-S000000-E235959.V07C.nc4", "probe_time_utc": "2026-10-14T19:51:30.426229+00:00", "role": "primary model rain"}`
- Note: CMR first granule of V07 is 1998-01-01 (TRMM era included); the project needs 2006-10-01 onwards

## imerg_early_daily

- URL pattern: CMR discovery https://cmr.earthdata.nasa.gov/search/granules.json?collection_concept_id=..., then https://opendap.earthdata.nasa.gov/collections/<concept id>/granules/<GranuleUR>.dap.nc4?dap4.ce=<constraint> (subset) or https://data.gesdisc.earthdata.nasa.gov/data/GPM_L3/GPM_3IMERGDE.07/<yyyy>/<mm>/<file>.nc4 (full file); the file name carries a version letter (V07B for old days, V07C for new) so it must be taken from CMR, never constructed
- Auth: Earthdata login (netrc) and the account's approval of the GES DISC application
- Format: netCDF4/HDF5, one file per UTC day, global 0.1 degree
- Error class: not measured
- Variables: `{"precipitation": {"dims_order": ["time", "lon", "lat"], "fill_value": -9999.900390625, "lat_ascending": true, "lon_ascending": true, "units": "mm/day", "variable": "precipitation"}}`
- Details: `{"collection_concept_id": "C2723754850-GES_DISC", "data_access": "ok", "days": [{"array": {"dims_order": ["time", "lon", "lat"], "domain_valid_share": 1.0, "engine": "h5netcdf", "fill_value": -9999.900390625, "lat_ascending": true, "lat_range": [8.05, 35.95], "lon_ascending": true, "lon_range": [72.05000305175781, 97.94999694824219], "point_lat": 11.450000000000006, "point_lon": 76.1500015258789, "point_plausible": true, "point_value": 44.52499771118164, "shape_domain": [1, 260, 280], "shape_full": [1, 260, 280], "units": "mm/day", "variable": "precipitation"}, "day": "2018-08-15", "subset": {"bytes": 221279, "constraint": "dap4.ce=/precipitation[0][2520:2779][980:1259];/time;/lon[2520:2779];/lat[980:1259]", "dims_assumed_or_read": ["time", "lon", "lat"], "pattern": "hyrax_cloud_dap4_dap.nc4", "pixels": {"lat": [980, 1259], "lon": [2520, 2779]}, "seconds": 8.213801500000045, "suffix": ".dap.nc4"}, "which": "historical"}, {"array": {"dims_order": ["time", "lon", "lat"], "domain_valid_share": 1.0, "engine": "h5netcdf", "fill_value": -9999.900390625, "lat_ascending": true, "lat_range": [8.05, 35.95], "lon_ascending": true, "lon_range": [72.05000305175781, 97.94999694824219], "point_lat": 11.450000000000006, "point_lon": 76.1500015258789, "point_plausible": true, "point_value": 0.0, "shape_domain": [1, 260, 280], "shape_full": [1, 260, 280], "units": "mm/day", "variable": "precipitation"}, "day": "2026-10-13", "subset": {"bytes": 128530, "constraint": "dap4.ce=/precipitation[0][2520:2779][980:1259];/time;/lon[2520:2779];/lat[980:1259]", "dims_assumed_or_read": ["time", "lon", "lat"], "pattern": "hyrax_cloud_dap4_dap.nc4", "pixels": {"lat": [980, 1259], "lon": [2520, 2779]}, "seconds": 7.959619499999462, "suffix": ".dap.nc4"}, "which": "newest"}], "full_file_bytes_cmr": 29262756, "historical_file": "3B-DAY-E.MS.MRG.3IMERG.20180815-S000000-E235959.V07B.nc4", "latency_basis": "CMR ingest time minus end of the UTC day", "latency_hours_last5": [4.538611388888889, 4.445833611111111, 4.509444722222223, 4.482500277777778, 4.456389166666667], "latency_hours_median": 4.482500277777778, "newest_day": "2026-10-13", "newest_file": "3B-DAY-E.MS.MRG.3IMERG.20261013-S000000-E235959.V07C.nc4", "probe_time_utc": "2026-10-14T19:51:30.426229+00:00", "role": "same-morning value for the current UTC day"}`
- Note: CMR first granule of V07 is 1998-01-01 (TRMM era included); the project needs 2006-10-01 onwards

## imerg_late_halfhourly

- URL pattern: CMR discovery for GPM_3IMERGHHL.07 (48 granules per UTC day), then https://opendap.earthdata.nasa.gov/collections/<concept id>/granules/<GranuleUR>.dap.nc4?dap4.ce=/Grid/precipitation[...] (subset)
- Auth: Earthdata login (netrc) and the account's approval of the GES DISC application
- Format: HDF5 (group /Grid), one file per half hour, global 0.1 degree
- Error class: OSError
- Variables: `{}`
- Details: `{"collection_concept_id": "C2723754845-GES_DISC", "data_access": "ok", "full_files_bytes_per_day": 372494360, "full_files_extrapolation": {"days_all": 4475, "days_monsoon": 1464, "gb_all": 1666.912261, "gb_monsoon": 545.33174304, "hours_all": null, "hours_monsoon": null}, "granules_on_2018_08_15": 48, "latency_basis": "CMR ingest time minus end of the half hour", "newest_file": "3B-HHR-L.MS.MRG.3IMERG.20261014-S043000-E045959.0270.V07C.HDF5", "probe_time_utc": "2026-10-14T19:51:30.426229+00:00"}`
- Note: Without a subset every half-hourly file is global (about 7.4 MiB): 545 GB for the June-September days of 2007-2018 and 1667 GB for every day, so the full-file route cannot meet the 20 GB limit
- Note: probe failed with OSError; anything not listed below was not measured

## gfs_nomads_grib_filter

- URL pattern: https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl?dir=/gfs.{YYYYMMDD}/{HH}/atmos&file=gfs.t{HH}z.pgrb2.0p25.f{FFF}&var_APCP=on&lev_surface=on&subregion=&leftlon=72&rightlon=98&toplat=36&bottomlat=8
- Auth: none
- Format: GRIB2 (simple packing), cropped to the domain by the server, 0.25 degree
- Error class: not measured
- Variables: `{"APCP": {"messages_per_file": 2, "note": "bucket accumulation (e.g. 6-9) and cumulative 0-H; use the 0-H one", "units": "kg m-2 (mm)"}}`
- Details: `{"bytes_total": 1018587, "cumulative_domain_mean_mm_by_hour": {"12": 2.2574009692372523, "15": 2.646486514959966, "18": 3.0553466076696165, "21": 3.5661925832279815, "24": 4.125616308470291, "27": 4.621281078803203, "3": 0.5276864728192162, "30": 5.047213442899284, "33": 5.45212810788032, "36": 5.840107458912769, "39": 6.194806152549515, "42": 6.564691319005478, "45": 6.974762958280658, "48": 7.37587968815845, "51": 7.691851032448378, "54": 7.966018752633797, "57": 8.275426675094817, "6": 1.096602402022756, "60": 8.570870206489676, "63": 8.840286557100717, "66": 9.153160556257902, "69": 9.582416772018542, "72": 10.018979140328698, "75": 10.40887589549094, "78": 10.838411293721029, "81": 11.325705857564264, "84": 11.778998103666245, "87": 12.161672987779182, "9": 1.7281131479140328, "90": 12.562747576906869, "93": 13.006837336704594, "96": 13.362031184155079}, "cumulative_mean_non_decreasing": true, "cycle_utc": "2026-10-14T12:00:00+00:00", "f096_published_utc": "2026-10-14T15:57:00+00:00", "failed_hours": [], "hourly_request_extrapolation": {"bytes": 3055761.0, "requests": 96, "seconds": 56.204421299993555}, "hours_requested": "3..96 step 3", "latency_basis": "publication of f096 minus cycle time", "mean_seconds_per_request": 0.5854627218749329, "messages_f003": [{"j_scans_positively": 1, "lat_first": 8.0, "lat_last": 36.0, "lon_first": 72.0, "lon_last": 98.0, "max": 82.1875, "mean": 0.5276864728192162, "min": 0.0, "ni": 105, "nj": 113, "packing": "grid_simple", "short_name": "tp", "step_range": "0-3", "units": "kg m**-2"}, {"j_scans_positively": 1, "lat_first": 8.0, "lat_last": 36.0, "lon_first": 72.0, "lon_last": 98.0, "max": 82.1875, "mean": 0.5276864728192162, "min": 0.0, "ni": 105, "nj": 113, "packing": "grid_simple", "short_name": "tp", "step_range": "0-3", "units": "kg m**-2"}], "messages_f024": [{"j_scans_positively": 1, "lat_first": 8.0, "lat_last": 36.0, "lon_first": 72.0, "lon_last": 98.0, "max": 27.1875, "mean": 1.069295195954488, "min": 0.0, "ni": 105, "nj": 113, "packing": "grid_simple", "short_name": "tp", "step_range": "18-24", "units": "kg m**-2"}, {"j_scans_positively": 1, "lat_first": 8.0, "lat_last": 36.0, "lon_first": 72.0, "lon_last": 98.0, "max": 109.75, "mean": 4.125616308470291, "min": 0.0, "ni": 105, "nj": 113, "packing": "grid_simple", "short_name": "tp", "step_range": "0-24", "units": "kg m**-2"}], "messages_f096": [{"j_scans_positively": 1, "lat_first": 8.0, "lat_last": 36.0, "lon_first": 72.0, "lon_last": 98.0, "max": 27.375, "mean": 0.7982827644332069, "min": 0.0, "ni": 105, "nj": 113, "packing": "grid_simple", "short_name": "tp", "step_range": "90-96", "units": "kg m**-2"}, {"j_scans_positively": 1, "lat_first": 8.0, "lat_last": 36.0, "lon_first": 72.0, "lon_last": 98.0, "max": 213.8125, "mean": 13.362031184155079, "min": 0.0, "ni": 105, "nj": 113, "packing": "grid_simple", "short_name": "tp", "step_range": "0-96", "units": "kg m**-2"}], "published_by_hour": {"24": "2026-10-14T15:39:00+00:00", "3": "2026-10-14T15:32:00+00:00", "96": "2026-10-14T15:57:00+00:00"}, "rate_limit_note": "NOMADS asks for at most 120 requests per minute", "requests_made": 32, "seconds_total": 18.73480709999785}`
- Note: bytes/s per day are for ONE cycle, forecast hours 3..96 step 3 (32 requests); f000 has no APCP
- Note: each file holds two APCP messages: the running bucket (resets every 6 h) and the cumulative 0-H total
- Note: the grid is south-to-north (jScansPositively=1), latitude 8.0 first, longitude 72.0 first, 113 x 105 points

## gfs_nomads_opendap

- URL pattern: https://nomads.ncep.noaa.gov/dods/gfs_0p25/gfs{YYYYMMDD}/gfs_0p25_{HH}z.{das|dds|ascii}
- Auth: none
- Format: OPeNDAP (DAP2)
- Error class: not measured
- Variables: `{}`
- Details: `{"cycle_utc": "2026-10-14T12:00:00+00:00", "http_status": 301, "page_says_retired": true}`
- Note: NOMADS OPeNDAP is retired (the response cites NWS Service Change Notice 25-81); the grib filter is the replacement

## gfs_aws_archive

- URL pattern: https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.{YYYYMMDD}/{HH}/atmos/gfs.t{HH}z.pgrb2.0p25.f{FFF} (+ .idx; HTTP Range for the APCP records only); before 2021-03-23 the path has no 'atmos/' level
- Auth: none (public bucket)
- Format: GRIB2 (complex packing, spatial differencing), global 0.25 degree
- Error class: not measured
- Variables: `{"APCP": {"domain_crop_mean_mm": 9.156652970922883, "domain_crop_shape": [113, 105], "global_grid": [721, 1440], "j_scans_positively": 0, "lat_first": 90.0, "lon_first": 0.0, "records": [{"bytes": 367302, "step": "18-24 hour acc fcst"}, {"bytes": 515980, "step": "0-1 day acc fcst"}], "records_per_file": 2, "units": "kg m-2 (mm)"}}`
- Details: `{"decoded_messages": [{"j_scans_positively": 0, "lat_first": 90.0, "lat_last": -90.0, "lon_first": 0.0, "lon_last": 359.75, "max": 180.1875, "mean": 0.5976905026776083, "min": 0.0, "ni": 1440, "nj": 721, "packing": "grid_complex_spatial_differencing", "short_name": "tp", "step_range": "18-24", "units": "kg m**-2"}, {"j_scans_positively": 0, "lat_first": 90.0, "lat_last": -90.0, "lon_first": 0.0, "lon_last": 359.75, "max": 391.4375, "mean": 2.389069663565264, "min": 0.0, "ni": 1440, "nj": 721, "packing": "grid_complex_spatial_differencing", "short_name": "tp", "step_range": "0-24", "units": "kg m**-2"}], "file": "gfs.20230715/00/atmos/gfs.t00z.pgrb2.0p25.f024", "files_per_day_for_imd_day_totals": [3, 27, 51, 75], "full_file_bytes": 544764486, "idx_records_apcp": [{"end": 431487085, "start": 431119784, "step": "18-24 hour acc fcst"}, {"end": 432003065, "start": 431487086, "step": "0-1 day acc fcst"}], "latency_basis": "S3 Last-Modified of the file minus cycle time (availability delay, not a valid-time lag)", "seconds_one_file": 8.626010800000586}`
- Note: the archive cannot be cropped server-side: each APCP record is a global field (about 0.4-0.5 MB) cropped after decoding to rows 216..328 and columns 288..392 of the 721 x 1440 grid
- Note: bytes/s per day assume the 00Z cycle and the four files whose cumulative totals bound the IMD days (f003, f027, f051, f075); the cumulative record is the one whose step starts with '0-' (named '0-1 day acc fcst' at f024); seconds are measured for the idx plus both APCP records, so slightly high
- Note: the grid is north-to-south (jScansPositively=0), longitude 0..359.75

## imd_realtime

- URL pattern: POST https://imdpune.gov.in/cmpg/Realtimedata/Rainfall/rain.php with form field rain=DDMMYYYY (what imdlib.get_real_data('rain', 'YYYY-MM-DD', 'YYYY-MM-DD', file_dir=...) does), then imdlib.open_real_data(...).get_xarray()
- Auth: none
- Format: IMD binary .grd: little-endian float32, 129 lat x 135 lon, 0.25 degree, -999 = missing
- Error class: TimeoutError
- Variables: `{}`
- Note: probe failed with TimeoutError; anything not listed below was not measured

## ghcnd_recent

- URL pattern: https://www.ncei.noaa.gov/access/services/data/v1?dataset=daily-summaries&stations=<ids>&dataTypes=PRCP&startDate=YYYY-MM-DD&endDate=YYYY-MM-DD&format=json&includeAttributes=true&units=metric
- Auth: none
- Format: JSON array, one object per station-day: DATE, STATION, PRCP (string), PRCP_ATTRIBUTES
- Error class: not measured
- Variables: `{"PRCP": {"fill_value": null, "missing": "row has no PRCP key", "units_default": "tenths of mm (raw .dly scale)", "units_with_units_metric": "mm"}}`
- Details: `{"attributes_field": "PRCP_ATTRIBUTES = 'measurement flag,quality flag,source flag'", "inventory_stations_selected": 140, "latency_hours_max": 307.8584517302778, "latency_hours_min": 115.85845173027776, "newest_date_by_station": {"IN001020700": "2026-10-09", "IN005090100": "2026-10-03", "IN011140700": "2026-10-09", "IN012081300": "2026-10-09", "IN017060500": "2026-10-01"}, "probe_time_utc": "2026-10-14T19:51:30.426229+00:00", "qflag_counts_nonblank": {}, "request_seconds": 2.644360099999176, "response_bytes": 36738, "rows": 492, "rows_with_prcp": 289, "stations_requested": ["IN001020700", "IN003030100", "IN005090100", "IN009012800", "IN011140700", "IN012081300", "IN017060500", "IN019180500", "IN021010100", "IN023550300"], "stations_with_prcp": 5, "window": ["2026-06-16", "2026-10-13"]}`
- Note: 5 of 10 requested stations returned any PRCP in the window; the others returned rows without PRCP or nothing
- Note: latency_hours is the MEDIAN over stations with data of (probe time minus the end of the newest reported day)
- Note: quality flags come back in PRCP_ATTRIBUTES (second field); an empty flag means the value passed the checks
- Note: without `units=metric` the service returns tenths of mm, space-padded (for example '   10' for 1.0 mm)
- Note: bytes/s per day are the whole 10-station, 120-day request divided by 120

## Extras

```json
{
  "chosen_paths": {
    "gauges": "ghcnd_recent",
    "gfs_archive": "gfs_aws_archive",
    "gfs_live": "gfs_nomads_grib_filter",
    "imd_second_opinion": null,
    "imerg_intensity_group_decision": "drop",
    "imerg_primary": "imerg_late_daily",
    "imerg_same_day_decision": "fallback"
  },
  "grib_decoder_decision": {
    "cfgrib": "drop: eccodes reads the messages directly; cfgrib only adds an xarray layer",
    "eccodes": "use"
  },
  "grib_decoders": {
    "cfgrib": {
      "error_class": "ModuleNotFoundError",
      "importable": false
    },
    "eccodes": {
      "importable": true,
      "version": "2.49.0"
    }
  },
  "grib_decoding_worked": true,
  "netcdf_readers": {
    "h5netcdf": {
      "importable": true,
      "version": "1.8.1"
    },
    "h5py": {
      "importable": true,
      "version": "3.16.0"
    },
    "netCDF4": {
      "error_class": "ModuleNotFoundError",
      "importable": false
    },
    "scipy": {
      "importable": true,
      "version": "1.18.1"
    }
  }
}
```
