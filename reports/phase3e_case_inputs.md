# Phase 3e preparation - case-study inputs

Point series from the Open-Meteo ERA5 archive (timezone=GMT, hourly precipitation, preceding-hour stamps).

## Wayanad point (11.47 N, 76.13 E): UTC day vs IMD day (mm)

| date | ERA5 UTC day | ERA5 IMD day (exact) | ERA5 IMD day (D5 approx.) | ERA5-Land UTC | ERA5-Land IMD (exact) | ERA5-Land D5 |
|---|---|---|---|---|---|---|
| 2024-07-29 | 56.9 | 12.8 | 16.9 | n/a | n/a | n/a |
| 2024-07-30 | 53.3 | 66.9 | 56.5 | n/a | n/a | n/a |
| 2024-07-31 | 26.4 | 42.5 | 49.9 | n/a | n/a | n/a |

## Kerala 2018 points (three wettest positive cells on 15-16 Aug): ERA5 UTC vs IMD-day (mm)

| point | lat, lon | event | date | UTC day | IMD day exact | D5 |
|---|---|---|---|---|---|---|
| kerala_cell_19965138 | 9.825, 76.925 | 2018-08-16 | 2018-08-14 | 108.1 | 23.7 | 30.3 |
| kerala_cell_19965138 | 9.825, 76.925 | 2018-08-16 | 2018-08-15 | 140.3 | 118.2 | 112.1 |
| kerala_cell_19965138 | 9.825, 76.925 | 2018-08-16 | 2018-08-16 | 67.4 | 134.2 | 131.2 |
| kerala_cell_19965138 | 9.825, 76.925 | 2018-08-16 | 2018-08-17 | 36.1 | 62.6 | 63.5 |
| kerala_cell_20065137 | 10.325, 76.875 | 2018-08-16 | 2018-08-14 | 145.5 | 19.1 | 32.5 |
| kerala_cell_20065137 | 10.325, 76.875 | 2018-08-16 | 2018-08-15 | 206.5 | 163.9 | 153.1 |
| kerala_cell_20065137 | 10.325, 76.875 | 2018-08-16 | 2018-08-16 | 102.6 | 200.3 | 193.5 |
| kerala_cell_20065137 | 10.325, 76.875 | 2018-08-16 | 2018-08-17 | 59.5 | 96.0 | 97.2 |
| kerala_cell_20065129 | 10.325, 76.475 | 2018-08-16 | 2018-08-14 | 88.5 | 36.1 | 35.6 |
| kerala_cell_20065129 | 10.325, 76.475 | 2018-08-16 | 2018-08-15 | 138.7 | 90.7 | 94.8 |
| kerala_cell_20065129 | 10.325, 76.475 | 2018-08-16 | 2018-08-16 | 61.0 | 131.4 | 129.0 |
| kerala_cell_20065129 | 10.325, 76.475 | 2018-08-16 | 2018-08-17 | 27.9 | 60.4 | 56.9 |

## D5 approximation error vs the exact IMD-day total (whole windows)

| point | model | days | mean abs err mm | max abs err mm | bias mm | heavy days (>= 10 mm) | heavy mean rel. err | worst day |
|---|---|---|---|---|---|---|---|---|
| wayanad_mundakkai | era5 | 34 | 1.85 | 10.5 | -0.02 | 22 | 0.077 | 2024-07-30: exact 66.9, D5 56.5 |
| kerala_cell_19965138 | era5 | 40 | 1.33 | 6.6 | -0.04 | 21 | 0.073 | 2018-08-14: exact 23.7, D5 30.3 |
| kerala_cell_20065137 | era5 | 40 | 1.72 | 13.4 | -0.03 | 30 | 0.065 | 2018-08-14: exact 19.1, D5 32.5 |
| kerala_cell_20065129 | era5 | 40 | 1.06 | 4.1 | -0.03 | 25 | 0.054 | 2018-08-15: exact 90.7, D5 94.8 |

Unavailable: wayanad_mundakkai|era5_land: every hourly precipitation value is null for era5_land (variable not provided by the model); kerala_cell_19965138|era5_land: every hourly precipitation value is null for era5_land (variable not provided by the model); kerala_cell_20065137|era5_land: every hourly precipitation value is null for era5_land (variable not provided by the model); kerala_cell_20065129|era5_land: every hourly precipitation value is null for era5_land (variable not provided by the model)

## Wayanad focus cell 20295122 (0.8 km from the point): daily comparison (mm)

| date | IMD | CHIRPS aligned | CHIRPS UTC | ERA5 UTC | ERA5 IMD exact | ERA5 D5 | ERA5-Land IMD exact | corr q50 | q90 | q99 | nearest station (km) | its mm | trust |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2024-07-25 | 25.6 | 31.2 | 44.1 | 38.4 | 25.2 | 21.2 | n/a | 8.2 | 35.9 | 88.1 | IN010050700 (45) | 39.1 | 0.99 |
| 2024-07-26 | 53.3 | 38.6 | 0.0 | 23.4 | 33.8 | 36.5 | n/a | 12.3 | 42.4 | 93.1 | IN010050700 (45) | 23.1 | 0.99 |
| 2024-07-27 | 37.8 | 12.4 | 99.4 | 2.4 | 21.3 | 20.8 | n/a | 5.0 | 27.0 | 59.2 | IN010050700 (45) | 30.0 | 0.99 |
| 2024-07-28 | 5.0 | 87.0 | 0.0 | 11.2 | 2.5 | 3.5 | n/a | 23.9 | 65.4 | 109.6 | IN010050700 (45) | 6.1 | 0.99 |
| 2024-07-29 | 6.6 | 6.2 | 49.7 | 56.9 | 12.8 | 16.9 | n/a | 3.5 | 23.7 | 64.2 | IN010050700 (45) | 33.0 | 0.98 |
| 2024-07-30 | 179.2 | 43.5 | 0.0 | 53.3 | 66.9 | 56.5 | n/a | 27.2 | 63.8 | 134.7 | IN010050700 (45) | 154.9 | 0.99 |
| 2024-07-31 | 16.7 | 6.2 | 49.7 | 26.4 | 42.5 | 49.9 | n/a | 3.8 | 19.4 | 49.5 | IN010050700 (45) | 36.1 | 0.99 |
| 2024-08-01 | 31.6 | 43.5 | 0.0 | 26.3 | 25.0 | 26.4 | n/a | 12.2 | 46.1 | 107.9 | IN010050700 (45) | 38.1 | 0.99 |
| 2024-08-02 | 42.5 | 0.0 | 0.0 | 13.2 | 28.0 | 24.7 | n/a | 3.0 | 19.4 | 42.9 | IN010050700 (45) | 34.0 | 0.99 |

API use: this run 0 calls (weight 0.00), 8 responses from the cache; all time 8 cached responses = 8 calls, free-tier weight 23.14 of 10000 per day.

- Open-Meteo hourly precipitation is stamped by the PRECEDING hour; UTC day D = stamps 01:00 D..00:00 D+1, IMD day D = stamps 04:00 D-1..03:00 D (exact), D5 = 0.875 UTC(D-1) + 0.125 UTC(D).
- ERA5 / ERA5-Land are reanalysis point values (about 0.25 / 0.1 degree cells), not gauge data.
- Licence: Open-Meteo CC BY 4.0; ERA5 / ERA5-Land Copernicus (CC BY 4.0).
