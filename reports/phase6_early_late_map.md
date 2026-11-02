# Early -> Late IMERG mapping (rain-only check)

Mapping file: `imerg_early_to_late.json`. Fitted on the June-September overlap of [2019, 2020, 2021, 2022, 2023, 2024] (46592000 pixel-day pairs; days per year {'2019': 122, '2020': 122, '2021': 122, '2022': 122, '2023': 76, '2024': 76}); dry threshold 0.1 mm (Early below it maps to 0). The hold-out year 2018 was not used in the fit.

## Hold-out 2018 June-September (122 days), Early vs Late

| subset | mapping | n | bias (mm) | MAE (mm) | correlation |
|---|---|---|---|---|---|
| all pixel-days | before | 8881600 | 0.169 | 1.801 | 0.969 |
| all pixel-days | after | 8881600 | 0.503 | 1.835 | 0.969 |
| Late >= 1 mm | before | 4478021 | 0.113 | 3.318 | 0.962 |
| Late >= 1 mm | after | 4478021 | 0.800 | 3.403 | 0.962 |

## Curve (every 10th fitted quantile)

| Early (mm) | Late (mm) | Late/Early |
|---|---|---|
| 0.12 | 0.12 | 1.000 |
| 0.41 | 0.39 | 0.951 |
| 0.92 | 0.86 | 0.940 |
| 1.72 | 1.62 | 0.945 |
| 2.92 | 2.80 | 0.961 |
| 4.69 | 4.60 | 0.979 |
| 7.36 | 7.35 | 0.999 |
| 11.56 | 11.78 | 1.019 |
| 18.82 | 19.55 | 1.039 |
| 34.41 | 36.36 | 1.057 |
| 188.32 | 202.13 | 1.073 |

Decision (controller, 2026-10-15): identity used; the fitted map did not improve held-out 2018.
