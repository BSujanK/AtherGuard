# Forecast leads on v4 (W7): development and archive evidence

Spec: docs/superpowers/specs/2026-11-14-aetherguard-leads-v4.md (written before any lead-skill number). Research prototype, not validated for issuing real public warnings. No held-out event was read for this report.

Caveats: ground truth after 2018 is very incomplete; E1 and E2 measure consistency with the model's own later view of the day, not landslides; E2 days are post-monsoon (outside the validated season); ECMWF has no archive before 2023, so 2022 issue days use the GFS fallback at every lead (candidate b equals a there).

## Part 1: what a forecast can supply (Task 1)

### History on disk

- GFS archive folders: 497 cycles 2021060100..2026103000, files kept f003_apcp0h.grib2, f027_apcp0h.grib2, f051_apcp0h.grib2, f075_apcp0h.grib2: IMD-day boundary hours only, no sub-daily rain.
- GFS live raw files: 35 cycles 2026101400..2026111600, 32 3-hourly cumulative files each (f003..f096).
- ECMWF day files: 363 issue days (2023: 80, 2024: 122, 2025: 122, 2026: 39); members kept: no; stored keys ens_cycle, ens_mean, ens_p10, ens_p50, ens_p90, ens_valid, failures, hres, hres_cycle, hres_valid, issued_utc, lats, lead_days, lons, n_members, urls.
- This study's 3-hourly GFS archive (00Z, hours 3..51, public AWS copy, no account): 2021: 122 days, 2022: 122 days, 2023: 122 days, 2024: 122 days.
- Live days on disk: 36 (2026-10-09..2026-11-16).

### Which of v4's six intensity inputs a forecast lead can form

| lead | days read (lag 1) | source of each day | inputs formed |
|---|---|---|---|
| 1 | D-2, D-1, D | Late, Late, Early live window (44 half-hours) | all six, as observed |
| 2 | D-1, D, D+1 | Late, Early, GFS 3-hour | max3h, max6h, wet hours from 3-hour blocks; max1h only as the 3-hour maximum mapped onto IMERG's 1-hour maximum |
| 3 | D, D+1, D+2 | Early, GFS, GFS | as lead 2 |

### Forecast and Early intensities against IMERG Late (same IMD day)

Pixels of the two scored regions. `ratio` = mean forecast / mean Late; p90 / p99 are each side's own percentiles; `Late>=10` = mean of each side where Late's value is at least 10 mm (paired).

| source | day offset | year | days | field | region | ratio | p90 fcst / Late | p99 fcst / Late | r | Late>=10: fcst / Late |
|---|---|---|---|---|---|---|---|---|---|---|
| early_live | 0 | 2016 | 121 | max1h | himalaya | 1.12 | 7.3 / 6.7 | 20.5 / 19.4 | 0.90 | 15.1 / 15.8 |
| early_live | 0 | 2016 | 121 | max1h | western_ghats | 1.11 | 4.9 / 4.7 | 13.6 / 12.6 | 0.91 | 14.7 / 15.1 |
| early_live | 0 | 2016 | 121 | max3h | himalaya | 1.01 | 14.0 / 14.3 | 40.1 / 42.4 | 0.92 | 19.5 / 21.1 |
| early_live | 0 | 2016 | 121 | max3h | western_ghats | 1.01 | 9.6 / 10.1 | 26.4 / 27.2 | 0.94 | 16.0 / 17.4 |
| early_live | 0 | 2016 | 121 | max6h | himalaya | 0.98 | 18.1 / 19.0 | 52.5 / 58.2 | 0.93 | 22.7 / 25.0 |
| early_live | 0 | 2016 | 121 | max6h | western_ghats | 0.98 | 12.8 / 13.8 | 36.8 / 39.4 | 0.95 | 18.8 / 21.0 |
| early_live | 0 | 2016 | 121 | wet_hours | himalaya | 0.92 | 10.5 / 12.5 | 18.0 / 21.0 | 0.96 | - |
| early_live | 0 | 2016 | 121 | wet_hours | western_ghats | 0.95 | 10.5 / 12.0 | 18.5 / 21.5 | 0.96 | - |
| early_live | 0 | 2017 | 122 | max1h | himalaya | 1.11 | 6.8 / 6.4 | 19.5 / 18.6 | 0.90 | 14.9 / 15.7 |
| early_live | 0 | 2017 | 122 | max1h | western_ghats | 1.13 | 5.8 / 5.4 | 16.3 / 14.8 | 0.91 | 15.5 / 15.6 |
| early_live | 0 | 2017 | 122 | max3h | himalaya | 1.01 | 12.9 / 13.2 | 36.8 / 38.1 | 0.93 | 18.6 / 20.1 |
| early_live | 0 | 2017 | 122 | max3h | western_ghats | 1.03 | 11.0 / 11.3 | 30.8 / 31.1 | 0.93 | 17.3 / 18.4 |
| early_live | 0 | 2017 | 122 | max6h | himalaya | 0.99 | 16.7 / 17.3 | 48.7 / 52.0 | 0.93 | 21.9 / 23.8 |
| early_live | 0 | 2017 | 122 | max6h | western_ghats | 1.01 | 14.7 / 15.4 | 43.1 / 45.0 | 0.94 | 20.4 / 22.1 |
| early_live | 0 | 2017 | 122 | wet_hours | himalaya | 0.92 | 10.5 / 12.0 | 18.5 / 21.0 | 0.96 | - |
| early_live | 0 | 2017 | 122 | wet_hours | western_ghats | 0.97 | 10.5 / 11.5 | 18.0 / 21.0 | 0.96 | - |
| early_live | 0 | 2024 | 122 | max1h | himalaya | 1.01 | 6.5 / 6.4 | 19.4 / 19.5 | 0.87 | 14.2 / 16.1 |
| early_live | 0 | 2024 | 122 | max1h | western_ghats | 0.98 | 6.9 / 7.0 | 21.8 / 21.6 | 0.90 | 15.3 / 17.1 |
| early_live | 0 | 2024 | 122 | max3h | himalaya | 0.98 | 12.9 / 13.3 | 39.5 / 41.7 | 0.90 | 18.8 / 20.9 |
| early_live | 0 | 2024 | 122 | max3h | western_ghats | 0.97 | 13.9 / 14.4 | 43.7 / 45.0 | 0.93 | 20.2 / 22.0 |
| early_live | 0 | 2024 | 122 | max6h | himalaya | 0.96 | 17.2 / 18.0 | 53.9 / 58.5 | 0.91 | 22.4 / 24.9 |
| early_live | 0 | 2024 | 122 | max6h | western_ghats | 0.96 | 19.3 / 20.0 | 61.9 / 64.5 | 0.94 | 24.3 / 26.4 |
| early_live | 0 | 2024 | 122 | wet_hours | himalaya | 0.91 | 11.0 / 12.0 | 18.5 / 20.5 | 0.94 | - |
| early_live | 0 | 2024 | 122 | wet_hours | western_ghats | 0.93 | 13.0 / 14.0 | 21.5 / 23.5 | 0.95 | - |
| early_live | 0 | 2026 | 32 | max1h | himalaya | 1.19 | 0.6 / 0.5 | 10.6 / 9.0 | 0.88 | 14.7 / 14.7 |
| early_live | 0 | 2026 | 32 | max1h | western_ghats | 1.13 | 2.1 / 1.8 | 13.3 / 11.5 | 0.95 | 18.5 / 17.5 |
| early_live | 0 | 2026 | 32 | max3h | himalaya | 1.06 | 0.8 / 0.7 | 17.0 / 16.2 | 0.89 | 18.1 / 19.2 |
| early_live | 0 | 2026 | 32 | max3h | western_ghats | 1.05 | 3.3 / 3.2 | 24.6 / 23.0 | 0.96 | 22.1 / 21.9 |
| early_live | 0 | 2026 | 32 | max6h | himalaya | 1.04 | 0.9 / 0.8 | 21.5 / 21.4 | 0.90 | 20.7 / 21.7 |
| early_live | 0 | 2026 | 32 | max6h | western_ghats | 1.04 | 4.0 / 3.7 | 31.3 / 30.6 | 0.96 | 24.5 / 24.5 |
| early_live | 0 | 2026 | 32 | wet_hours | himalaya | 0.91 | 1.5 / 1.5 | 13.5 / 15.5 | 0.97 | - |
| early_live | 0 | 2026 | 32 | wet_hours | western_ghats | 0.98 | 5.0 / 5.0 | 12.5 / 14.0 | 0.97 | - |
| gfs3h_archive | 1 | 2021 | 122 | max1h | himalaya | 1.26 | 6.4 / 6.4 | 25.1 / 19.4 | 0.31 | 7.3 / 16.0 |
| gfs3h_archive | 1 | 2021 | 122 | max1h | western_ghats | 1.25 | 5.8 / 5.6 | 23.1 / 15.3 | 0.37 | 8.5 / 15.6 |
| gfs3h_archive | 1 | 2021 | 122 | max3h | himalaya | 0.63 | 6.4 / 13.5 | 25.1 / 40.9 | 0.32 | 6.3 / 20.7 |
| gfs3h_archive | 1 | 2021 | 122 | max3h | western_ghats | 0.62 | 5.8 / 12.1 | 23.1 / 32.7 | 0.40 | 6.7 / 18.7 |
| gfs3h_archive | 1 | 2021 | 122 | max6h | himalaya | 0.74 | 10.3 / 17.9 | 37.4 / 55.9 | 0.34 | 9.4 / 24.3 |
| gfs3h_archive | 1 | 2021 | 122 | max6h | western_ghats | 0.72 | 9.6 / 16.9 | 35.2 / 48.2 | 0.42 | 10.0 / 22.7 |
| gfs3h_archive | 1 | 2021 | 122 | wet_hours | himalaya | 2.11 | 24.0 / 12.5 | 24.0 / 20.5 | 0.51 | - |
| gfs3h_archive | 1 | 2021 | 122 | wet_hours | western_ghats | 1.84 | 21.0 / 13.0 | 24.0 / 22.5 | 0.56 | - |
| gfs3h_archive | 1 | 2022 | 122 | max1h | himalaya | 1.15 | 6.0 / 6.6 | 22.3 / 19.2 | 0.34 | 6.9 / 15.7 |
| gfs3h_archive | 1 | 2022 | 122 | max1h | western_ghats | 1.39 | 6.8 / 5.9 | 24.3 / 15.5 | 0.36 | 8.4 / 15.0 |
| gfs3h_archive | 1 | 2022 | 122 | max3h | himalaya | 0.59 | 6.0 / 13.5 | 22.3 / 39.6 | 0.36 | 6.2 / 20.7 |
| gfs3h_archive | 1 | 2022 | 122 | max3h | western_ghats | 0.68 | 6.8 / 12.9 | 24.3 / 33.3 | 0.39 | 7.3 / 18.6 |
| gfs3h_archive | 1 | 2022 | 122 | max6h | himalaya | 0.71 | 9.7 / 17.5 | 32.6 / 53.7 | 0.39 | 9.2 / 24.2 |
| gfs3h_archive | 1 | 2022 | 122 | max6h | western_ghats | 0.79 | 11.3 / 18.3 | 36.7 / 47.6 | 0.42 | 11.0 / 22.5 |
| gfs3h_archive | 1 | 2022 | 122 | wet_hours | himalaya | 2.20 | 21.0 / 11.5 | 24.0 / 20.0 | 0.57 | - |
| gfs3h_archive | 1 | 2022 | 122 | wet_hours | western_ghats | 1.89 | 24.0 / 14.5 | 24.0 / 23.5 | 0.60 | - |
| gfs3h_archive | 1 | 2023 | 122 | max1h | himalaya | 1.38 | 6.8 / 6.2 | 28.3 / 20.0 | 0.33 | 8.2 / 16.4 |
| gfs3h_archive | 1 | 2023 | 122 | max1h | western_ghats | 1.45 | 5.6 / 4.7 | 25.1 / 12.6 | 0.38 | 9.4 / 14.8 |
| gfs3h_archive | 1 | 2023 | 122 | max3h | himalaya | 0.70 | 6.8 / 12.6 | 28.3 / 41.3 | 0.34 | 7.4 / 21.3 |
| gfs3h_archive | 1 | 2023 | 122 | max3h | western_ghats | 0.73 | 5.6 / 10.0 | 25.1 / 26.9 | 0.42 | 7.9 / 17.5 |
| gfs3h_archive | 1 | 2023 | 122 | max6h | himalaya | 0.84 | 11.0 / 16.5 | 42.3 / 55.5 | 0.37 | 11.1 / 24.9 |
| gfs3h_archive | 1 | 2023 | 122 | max6h | western_ghats | 0.84 | 9.2 / 14.1 | 39.1 / 40.8 | 0.45 | 11.6 / 21.3 |
| gfs3h_archive | 1 | 2023 | 122 | wet_hours | himalaya | 2.20 | 24.0 / 12.0 | 24.0 / 20.5 | 0.60 | - |
| gfs3h_archive | 1 | 2023 | 122 | wet_hours | western_ghats | 1.83 | 21.0 / 13.0 | 24.0 / 23.0 | 0.62 | - |
| gfs3h_archive | 1 | 2024 | 122 | max1h | himalaya | 1.42 | 7.1 / 6.4 | 30.1 / 19.5 | 0.32 | 8.5 / 16.1 |
| gfs3h_archive | 1 | 2024 | 122 | max1h | western_ghats | 1.16 | 6.9 / 7.0 | 26.5 / 21.6 | 0.31 | 8.0 / 17.1 |
| gfs3h_archive | 1 | 2024 | 122 | max3h | himalaya | 0.71 | 7.1 / 13.4 | 30.1 / 41.7 | 0.34 | 7.6 / 20.9 |
| gfs3h_archive | 1 | 2024 | 122 | max3h | western_ghats | 0.59 | 6.9 / 14.4 | 26.5 / 45.1 | 0.34 | 7.1 / 22.0 |
| gfs3h_archive | 1 | 2024 | 122 | max6h | himalaya | 0.83 | 11.5 / 18.0 | 45.1 / 58.5 | 0.37 | 11.3 / 24.9 |
| gfs3h_archive | 1 | 2024 | 122 | max6h | western_ghats | 0.68 | 11.5 / 20.0 | 40.6 / 64.6 | 0.37 | 10.8 / 26.4 |
| gfs3h_archive | 1 | 2024 | 122 | wet_hours | himalaya | 2.29 | 24.0 / 12.0 | 24.0 / 20.5 | 0.55 | - |
| gfs3h_archive | 1 | 2024 | 122 | wet_hours | western_ghats | 1.88 | 24.0 / 14.0 | 24.0 / 23.5 | 0.58 | - |
| gfs3h_archive | 2 | 2021 | 122 | max1h | himalaya | 1.26 | 6.5 / 6.4 | 23.9 / 19.4 | 0.27 | 6.5 / 16.0 |
| gfs3h_archive | 2 | 2021 | 122 | max1h | western_ghats | 1.16 | 5.6 / 5.7 | 23.7 / 15.4 | 0.35 | 8.3 / 15.6 |
| gfs3h_archive | 2 | 2021 | 122 | max3h | himalaya | 0.63 | 6.5 / 13.5 | 23.9 / 40.9 | 0.28 | 5.8 / 20.7 |
| gfs3h_archive | 2 | 2021 | 122 | max3h | western_ghats | 0.57 | 5.6 / 12.2 | 23.7 / 32.9 | 0.37 | 6.2 / 18.7 |
| gfs3h_archive | 2 | 2021 | 122 | max6h | himalaya | 0.74 | 10.4 / 17.9 | 35.6 / 55.8 | 0.30 | 8.7 / 24.3 |
| gfs3h_archive | 2 | 2021 | 122 | max6h | western_ghats | 0.66 | 9.3 / 17.1 | 36.0 / 48.3 | 0.39 | 9.1 / 22.7 |
| gfs3h_archive | 2 | 2021 | 122 | wet_hours | himalaya | 2.15 | 24.0 / 12.5 | 24.0 / 20.6 | 0.47 | - |
| gfs3h_archive | 2 | 2021 | 122 | wet_hours | western_ghats | 1.69 | 21.0 / 13.0 | 24.0 / 22.5 | 0.51 | - |
| gfs3h_archive | 2 | 2022 | 122 | max1h | himalaya | 1.23 | 6.4 / 6.6 | 25.0 / 19.2 | 0.31 | 7.0 / 15.7 |
| gfs3h_archive | 2 | 2022 | 122 | max1h | western_ghats | 1.26 | 6.4 / 5.9 | 23.4 / 15.5 | 0.33 | 7.4 / 15.0 |
| gfs3h_archive | 2 | 2022 | 122 | max3h | himalaya | 0.63 | 6.4 / 13.5 | 25.0 / 39.6 | 0.32 | 6.2 / 20.7 |
| gfs3h_archive | 2 | 2022 | 122 | max3h | western_ghats | 0.62 | 6.4 / 12.9 | 23.4 / 33.3 | 0.35 | 6.5 / 18.6 |
| gfs3h_archive | 2 | 2022 | 122 | max6h | himalaya | 0.75 | 10.3 / 17.4 | 36.0 / 53.7 | 0.35 | 9.3 / 24.2 |
| gfs3h_archive | 2 | 2022 | 122 | max6h | western_ghats | 0.72 | 10.6 / 18.3 | 34.9 / 47.6 | 0.38 | 9.8 / 22.5 |
| gfs3h_archive | 2 | 2022 | 122 | wet_hours | himalaya | 2.23 | 21.0 / 11.5 | 24.0 / 20.0 | 0.55 | - |
| gfs3h_archive | 2 | 2022 | 122 | wet_hours | western_ghats | 1.76 | 24.0 / 14.5 | 24.0 / 23.5 | 0.53 | - |
| gfs3h_archive | 2 | 2023 | 122 | max1h | himalaya | 1.35 | 6.8 / 6.2 | 27.0 / 20.0 | 0.31 | 7.5 / 16.3 |
| gfs3h_archive | 2 | 2023 | 122 | max1h | western_ghats | 1.13 | 4.5 / 4.7 | 18.0 / 12.6 | 0.34 | 6.3 / 14.8 |
| gfs3h_archive | 2 | 2023 | 122 | max3h | himalaya | 0.69 | 6.8 / 12.7 | 27.0 / 41.3 | 0.31 | 6.8 / 21.3 |
| gfs3h_archive | 2 | 2023 | 122 | max3h | western_ghats | 0.57 | 4.5 / 10.0 | 18.0 / 26.9 | 0.37 | 5.9 / 17.5 |
| gfs3h_archive | 2 | 2023 | 122 | max6h | himalaya | 0.82 | 11.0 / 16.6 | 39.9 / 55.5 | 0.34 | 10.3 / 24.9 |
| gfs3h_archive | 2 | 2023 | 122 | max6h | western_ghats | 0.66 | 7.5 / 14.1 | 28.4 / 40.9 | 0.42 | 8.6 / 21.3 |
| gfs3h_archive | 2 | 2023 | 122 | wet_hours | himalaya | 2.23 | 24.0 / 12.0 | 24.0 / 20.5 | 0.57 | - |
| gfs3h_archive | 2 | 2023 | 122 | wet_hours | western_ghats | 1.62 | 21.0 / 13.0 | 24.0 / 23.0 | 0.57 | - |
| gfs3h_archive | 2 | 2024 | 122 | max1h | himalaya | 1.51 | 7.6 / 6.4 | 32.2 / 19.5 | 0.29 | 8.3 / 16.2 |
| gfs3h_archive | 2 | 2024 | 122 | max1h | western_ghats | 0.93 | 5.7 / 6.9 | 22.9 / 20.8 | 0.27 | 6.2 / 16.8 |
| gfs3h_archive | 2 | 2024 | 122 | max3h | himalaya | 0.76 | 7.6 / 13.3 | 32.2 / 41.7 | 0.30 | 7.6 / 20.9 |
| gfs3h_archive | 2 | 2024 | 122 | max3h | western_ghats | 0.47 | 5.7 / 14.2 | 22.9 / 43.4 | 0.29 | 5.5 / 21.6 |
| gfs3h_archive | 2 | 2024 | 122 | max6h | himalaya | 0.88 | 12.3 / 17.9 | 47.8 / 58.4 | 0.33 | 11.3 / 24.9 |
| gfs3h_archive | 2 | 2024 | 122 | max6h | western_ghats | 0.55 | 9.5 / 19.8 | 35.2 / 62.6 | 0.32 | 8.3 / 25.9 |
| gfs3h_archive | 2 | 2024 | 122 | wet_hours | himalaya | 2.35 | 24.0 / 12.0 | 24.0 / 20.5 | 0.52 | - |
| gfs3h_archive | 2 | 2024 | 122 | wet_hours | western_ghats | 1.63 | 24.0 / 14.0 | 24.0 / 23.5 | 0.52 | - |
| gfs3h_live | 1 | 2026 | 28 | max1h | himalaya | 0.81 | 0.5 / 0.2 | 4.5 / 7.2 | 0.38 | 2.1 / 15.1 |
| gfs3h_live | 1 | 2026 | 28 | max1h | western_ghats | 1.33 | 3.3 / 1.9 | 9.3 / 10.6 | 0.38 | 4.6 / 17.3 |
| gfs3h_live | 1 | 2026 | 28 | max3h | himalaya | 0.47 | 0.5 / 0.3 | 4.5 / 12.6 | 0.39 | 2.7 / 19.3 |
| gfs3h_live | 1 | 2026 | 28 | max3h | western_ghats | 0.71 | 3.3 / 3.2 | 9.3 / 20.9 | 0.36 | 4.6 / 20.8 |
| gfs3h_live | 1 | 2026 | 28 | max6h | himalaya | 0.59 | 0.7 / 0.3 | 7.1 / 16.0 | 0.44 | 5.1 / 21.0 |
| gfs3h_live | 1 | 2026 | 28 | max6h | western_ghats | 0.91 | 5.3 / 3.8 | 15.6 / 27.4 | 0.38 | 7.7 / 22.8 |
| gfs3h_live | 1 | 2026 | 28 | wet_hours | himalaya | 2.12 | 3.0 / 1.0 | 18.0 / 11.0 | 0.66 | - |
| gfs3h_live | 1 | 2026 | 28 | wet_hours | western_ghats | 2.69 | 15.0 / 5.0 | 24.0 / 13.5 | 0.70 | - |
| gfs3h_live | 2 | 2026 | 27 | max1h | himalaya | 0.75 | 0.5 / 0.2 | 3.9 / 7.4 | 0.43 | 2.4 / 14.5 |
| gfs3h_live | 2 | 2026 | 27 | max1h | western_ghats | 1.39 | 3.2 / 2.0 | 12.7 / 11.9 | 0.40 | 6.7 / 17.8 |
| gfs3h_live | 2 | 2026 | 27 | max3h | himalaya | 0.43 | 0.5 / 0.3 | 3.9 / 13.4 | 0.44 | 3.0 / 19.3 |
| gfs3h_live | 2 | 2026 | 27 | max3h | western_ghats | 0.73 | 3.2 / 3.4 | 12.7 / 23.9 | 0.39 | 5.7 / 22.4 |
| gfs3h_live | 2 | 2026 | 27 | max6h | himalaya | 0.53 | 0.7 / 0.3 | 6.0 / 17.1 | 0.47 | 5.0 / 22.0 |
| gfs3h_live | 2 | 2026 | 27 | max6h | western_ghats | 0.91 | 5.2 / 4.0 | 19.9 / 32.0 | 0.41 | 9.2 / 25.0 |
| gfs3h_live | 2 | 2026 | 27 | wet_hours | himalaya | 1.99 | 3.0 / 0.5 | 18.0 / 11.0 | 0.64 | - |
| gfs3h_live | 2 | 2026 | 27 | wet_hours | western_ghats | 2.69 | 15.0 / 5.0 | 24.0 / 14.5 | 0.69 | - |

## Part 2a: E1 archive consistency (development and archive data, no event read)

Years 2022, 2023, 2024, months [6, 7, 8, 9], 2536 cells (seed 20261115), issue days per lead {'1': 366, '2': 366, '3': 366}; forecast rain used per lead {'1': {'NOAA GFS': 366}, '2': {'GFS fallback': 164, 'ECMWF IFS ensemble mean (CC BY 4.0)': 202}, '3': {'GFS fallback': 164, 'ECMWF IFS ensemble mean (CC BY 4.0), bias-corrected': 202}}. Reference: published level of the target day from observed features (lead 0 as the live run scores it): v4 with Late lag-1 intensity and static inputs; v3 for the incumbent's own consistency.

| lead | candidate | reference | pairs | agreement | within one | Warning+ recall | Warning+ precision | Emergency recall | Emergency precision | Warning share lead / ref | Emergency share lead / ref |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | a | v4 | 928155 | 0.823 | 0.991 | 0.805 | 0.707 | 0.621 | 0.567 | 11.1% / 9.6% | 4.3% / 3.9% |
| 1 | a_oracle | v4 | 928155 | 0.824 | 0.991 | 0.806 | 0.707 | 0.622 | 0.568 | 11.1% / 9.6% | 4.3% / 3.9% |
| 1 | a_raw | v4 | 928155 | 0.823 | 0.991 | 0.802 | 0.707 | 0.615 | 0.566 | 11.1% / 9.6% | 4.3% / 3.9% |
| 1 | b | v4 | 928155 | 0.823 | 0.991 | 0.805 | 0.707 | 0.621 | 0.567 | 11.1% / 9.6% | 4.3% / 3.9% |
| 1 | c | v3 | 928155 | 0.770 | 0.980 | 0.813 | 0.708 | 0.643 | 0.583 | 13.0% / 11.0% | 8.5% / 7.7% |
| 1 | c | v4 | 928155 | 0.655 | 0.948 | 0.753 | 0.475 | 0.569 | 0.264 | 13.0% / 9.6% | 8.5% / 3.9% |
| 2 | a | v4 | 928152 | 0.802 | 0.990 | 0.783 | 0.690 | 0.588 | 0.551 | 11.2% / 9.6% | 4.2% / 3.9% |
| 2 | a_oracle | v4 | 928152 | 0.808 | 0.990 | 0.789 | 0.697 | 0.599 | 0.560 | 11.1% / 9.6% | 4.2% / 3.9% |
| 2 | a_raw | v4 | 928152 | 0.794 | 0.989 | 0.799 | 0.674 | 0.612 | 0.532 | 11.6% / 9.6% | 4.5% / 3.9% |
| 2 | b | v4 | 928152 | 0.807 | 0.990 | 0.742 | 0.713 | 0.536 | 0.574 | 10.4% / 9.6% | 3.7% / 3.9% |
| 2 | c | v3 | 928152 | 0.748 | 0.978 | 0.800 | 0.691 | 0.616 | 0.569 | 13.4% / 11.1% | 8.3% / 7.7% |
| 2 | c | v4 | 928152 | 0.643 | 0.945 | 0.744 | 0.464 | 0.548 | 0.259 | 13.4% / 9.6% | 8.3% / 3.9% |
| 3 | a | v4 | 928120 | 0.786 | 0.985 | 0.716 | 0.681 | 0.537 | 0.501 | 10.1% / 9.6% | 4.2% / 3.9% |
| 3 | a_oracle | v4 | 928120 | 0.792 | 0.986 | 0.722 | 0.688 | 0.546 | 0.510 | 10.0% / 9.6% | 4.2% / 3.9% |
| 3 | a_raw | v4 | 928120 | 0.779 | 0.984 | 0.731 | 0.664 | 0.557 | 0.483 | 10.4% / 9.6% | 4.6% / 3.9% |
| 3 | b | v4 | 928120 | 0.783 | 0.985 | 0.703 | 0.681 | 0.517 | 0.511 | 10.0% / 9.6% | 4.0% / 3.9% |
| 3 | c | v3 | 928120 | 0.730 | 0.968 | 0.727 | 0.684 | 0.563 | 0.522 | 11.7% / 11.1% | 8.3% / 7.7% |
| 3 | c | v4 | 928120 | 0.645 | 0.939 | 0.678 | 0.461 | 0.506 | 0.240 | 11.7% / 9.6% | 8.3% / 3.9% |

Differences from the incumbent (v4 reference; standard errors resample issue days):

| lead | candidate | agreement delta (SE) | Warning+ recall delta (SE) |
|---|---|---|---|
| 1 | a | 0.1679 (0.0023) | 0.0523 (0.0031) |
| 1 | a_oracle | 0.1690 (0.0023) | 0.0533 (0.0031) |
| 1 | a_raw | 0.1674 (0.0022) | 0.0493 (0.0031) |
| 1 | b | 0.1679 (0.0023) | 0.0523 (0.0031) |
| 2 | a | 0.1592 (0.0022) | 0.0389 (0.0032) |
| 2 | a_oracle | 0.1650 (0.0022) | 0.0454 (0.0031) |
| 2 | a_raw | 0.1514 (0.0021) | 0.0558 (0.0029) |
| 2 | b | 0.1645 (0.0022) | -0.0021 (0.0039) |
| 3 | a | 0.1405 (0.0021) | 0.0381 (0.0031) |
| 3 | a_oracle | 0.1462 (0.0022) | 0.0444 (0.0030) |
| 3 | a_raw | 0.1339 (0.0020) | 0.0535 (0.0030) |
| 3 | b | 0.1373 (0.0021) | 0.0257 (0.0033) |

Calibration of lead risk against the later lead-0 risk (v4 reference), by decile of lead risk, lead 2:

| candidate | decile | n | mean lead risk | mean lead-0 risk |
|---|---|---|---|---|
| a | 2 | 163448 | 6.82e-13 | 2.85e-08 |
| a | 3 | 91086 | 1.85e-07 | 3.32e-07 |
| a | 4 | 49346 | 3.75e-07 | 2.98e-07 |
| a | 5 | 87735 | 5.15e-07 | 6.74e-07 |
| a | 6 | 157619 | 1.54e-06 | 1.85e-06 |
| a | 7 | 21016 | 3.03e-06 | 3.07e-06 |
| a | 8 | 158931 | 4.55e-06 | 6.54e-06 |
| a | 9 | 98114 | 1.41e-05 | 1.67e-05 |
| a | 10 | 100857 | 0.000158 | 0.000275 |
| a_oracle | 2 | 163700 | 6.21e-13 | 2.59e-08 |
| a_oracle | 3 | 90940 | 1.86e-07 | 3.02e-07 |
| a_oracle | 4 | 49402 | 3.75e-07 | 2.94e-07 |
| a_oracle | 5 | 87605 | 5.15e-07 | 6.57e-07 |
| a_oracle | 6 | 157597 | 1.54e-06 | 1.81e-06 |
| a_oracle | 7 | 21057 | 3.03e-06 | 3.03e-06 |
| a_oracle | 8 | 159204 | 4.55e-06 | 6.4e-06 |
| a_oracle | 9 | 97878 | 1.41e-05 | 1.67e-05 |
| a_oracle | 10 | 100769 | 0.000169 | 0.000275 |
| a_raw | 2 | 158264 | 6.42e-13 | 2.59e-08 |
| a_raw | 3 | 115381 | 2.25e-07 | 2.94e-07 |
| a_raw | 4 | 24092 | 3.87e-07 | 3.36e-07 |
| a_raw | 5 | 159813 | 7.99e-07 | 9.09e-07 |
| a_raw | 6 | 96590 | 2.03e-06 | 2.32e-06 |
| a_raw | 7 | 7813 | 3.27e-06 | 3.13e-06 |
| a_raw | 8 | 160013 | 4.55e-06 | 6.16e-06 |
| a_raw | 9 | 110890 | 1.52e-05 | 1.72e-05 |
| a_raw | 10 | 95296 | 0.000184 | 0.000289 |
| b | 2 | 164416 | 6.8e-09 | 2.83e-08 |
| b | 3 | 113496 | 2.1e-07 | 2.87e-07 |
| b | 4 | 90410 | 4.29e-07 | 5.34e-07 |
| b | 5 | 95369 | 1.06e-06 | 1.21e-06 |
| b | 6 | 93123 | 1.98e-06 | 2.34e-06 |
| b | 7 | 36750 | 3.19e-06 | 3.56e-06 |
| b | 8 | 143058 | 5.11e-06 | 6.97e-06 |
| b | 9 | 98697 | 1.54e-05 | 1.84e-05 |
| b | 10 | 92833 | 0.000185 | 0.000296 |
| c | 1 | 32090 | 0 | 7.74e-08 |
| c | 2 | 93411 | 1.08e-07 | 2.07e-07 |
| c | 3 | 139143 | 1.67e-07 | 4.15e-07 |
| c | 4 | 32523 | 3.91e-07 | 8e-07 |
| c | 5 | 154649 | 1.01e-06 | 1.72e-06 |
| c | 6 | 84233 | 2.66e-06 | 3.81e-06 |
| c | 7 | 98994 | 4.54e-06 | 6.8e-06 |
| c | 8 | 106740 | 9.19e-06 | 1.27e-05 |
| c | 9 | 82637 | 2.01e-05 | 4.05e-05 |
| c | 10 | 103732 | 8.44e-05 | 0.000239 |

### Candidate for the held-out look (spec section 4)

| candidate | lead-2 Warning+ recall | burden within 20% | outside it |
|---|---|---|---|
| a | 0.783 | yes | - |
| b | 0.742 | yes | - |

Chosen: **a**. Rule: higher lead-2 Warning+ recall of the v4 reference among a and b (a on a tie: the simpler), burden by level within 20% of the reference at every lead; none qualifies: no look.

## Part 2b: E2 live replays (archived live days, scratch live_dir)

Reference: the same set's published lead 0 of the target day (replayed, backtest mode). October-November 2026: outside the validated season (June-September).

| set | days | audit violations | by check | leads with their own intensity (days) | leads scored as an expectation |
|---|---|---|---|---|---|
| c | 32 | 0 | - | 0 | 0 |
| a | 32 | 0 | - | 29 | 0 |
| b | 32 | 0 | - | 29 | 32 |

| lead | candidate | pairs | agreement | within one | Warning+ recall | Warning+ precision | Emergency recall | Emergency precision | Warning share lead / ref | Emergency share lead / ref |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | c | 1140497 | 0.883 | 0.990 | 0.508 | 0.478 | 0.360 | 0.244 | 2.3% / 2.5% | 1.2% / 0.8% |
| 1 | a | 1140497 | 0.921 | 0.996 | 0.521 | 0.716 | 0.295 | 0.521 | 1.9% / 2.5% | 0.4% / 0.8% |
| 1 | b | 1140497 | 0.920 | 0.996 | 0.521 | 0.716 | 0.295 | 0.521 | 1.9% / 2.5% | 0.4% / 0.8% |
| 2 | c | 1103681 | 0.874 | 0.988 | 0.470 | 0.455 | 0.384 | 0.251 | 2.2% / 2.5% | 1.2% / 0.8% |
| 2 | a | 1103681 | 0.914 | 0.994 | 0.476 | 0.748 | 0.308 | 0.565 | 1.6% / 2.5% | 0.4% / 0.8% |
| 2 | b | 1103681 | 0.912 | 0.994 | 0.432 | 0.759 | 0.281 | 0.554 | 1.5% / 2.5% | 0.4% / 0.8% |
| 3 | c | 1066877 | 0.872 | 0.984 | 0.392 | 0.423 | 0.288 | 0.182 | 1.7% / 2.4% | 1.2% / 0.7% |
| 3 | a | 1066877 | 0.904 | 0.990 | 0.400 | 0.654 | 0.236 | 0.392 | 1.5% / 2.4% | 0.4% / 0.7% |
| 3 | b | 1066877 | 0.901 | 0.990 | 0.377 | 0.641 | 0.187 | 0.342 | 1.4% / 2.4% | 0.4% / 0.7% |
