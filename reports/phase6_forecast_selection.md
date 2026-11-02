# Forecast rain selection (spec section 12)

Cells: the seeded sample of the forecast-skill report (2536 cells, seed 20261015); model data/processed/hazard/model_v3_live. Both sides are published levels (point level, `uncertain_high` of the rules, rain cap); the observed-feature level of the target day is the reference. Bias-corrected (`+map`) curves: GFS fitted on June-September 2021-2023, ECMWF on 2023 only, so 2023 is in-sample for every `+map` candidate and for none of the raw ones; 2024 is held out for all. GEFS: not used: its archive carries APCP as 3- and 6-hour buckets without a running total, so an IMD day needs about 29 range requests per member (31 members), about 900 per issue day and about 66 GB for the two seasons, beyond the one-hour effort allowed; GFS and ECMWF remain.

## June-September 2024 (primary, held out)

### Lead D+1 (122 issue days)

| candidate | pairs | agreement (SE) | within one | Watch+ recall | Warning+ recall | Warning+ precision | delta vs GFS (SE) | rain MAE domain (mm) | hit >=50 | FAR >=50 |
|---|---|---|---|---|---|---|---|---|---|---|
| gfs | 309379 | 0.8174 (0.0043) | 0.985 | 0.878 | 0.795 | 0.702 | 0.0000 (0.0000) | 8.29 | 0.163 | 0.606 |
| gfs+map | 309385 | 0.8155 (0.0045) | 0.984 | 0.867 | 0.784 | 0.700 | -0.0019 (0.0007) | 8.83 | 0.293 | 0.671 |
| ecmwf_hres | 309386 | 0.8121 (0.0040) | 0.986 | 0.903 | 0.804 | 0.696 | -0.0053 (0.0015) | 8.06 | 0.187 | 0.574 |
| ecmwf_hres+map | 309385 | 0.8181 (0.0041) | 0.983 | 0.872 | 0.745 | 0.709 | 0.0007 (0.0017) | 8.47 | 0.354 | 0.640 |
| ecmwf_ens_mean | 309386 | 0.8183 (0.0038) | 0.988 | 0.917 | 0.826 | 0.702 | 0.0009 (0.0015) | 7.63 | 0.164 | 0.495 |
| ecmwf_ens_mean+map | 309386 | 0.8272 (0.0040) | 0.984 | 0.879 | 0.763 | 0.716 | 0.0098 (0.0019) | 7.94 | 0.384 | 0.609 |

### Lead D+2 (122 issue days)

| candidate | pairs | agreement (SE) | within one | Watch+ recall | Warning+ recall | Warning+ precision | delta vs GFS (SE) | rain MAE domain (mm) | hit >=50 | FAR >=50 |
|---|---|---|---|---|---|---|---|---|---|---|
| gfs | 309378 | 0.7967 (0.0045) | 0.981 | 0.857 | 0.745 | 0.672 | 0.0000 (0.0000) | 8.66 | 0.141 | 0.663 |
| gfs+map | 309386 | 0.7924 (0.0049) | 0.978 | 0.848 | 0.736 | 0.663 | -0.0044 (0.0007) | 9.22 | 0.257 | 0.706 |
| ecmwf_hres | 309385 | 0.7943 (0.0043) | 0.982 | 0.881 | 0.771 | 0.668 | -0.0024 (0.0020) | 8.36 | 0.154 | 0.612 |
| ecmwf_hres+map | 309385 | 0.7968 (0.0045) | 0.979 | 0.845 | 0.705 | 0.678 | 0.0000 (0.0021) | 8.73 | 0.319 | 0.667 |
| ecmwf_ens_mean | 309386 | 0.8036 (0.0040) | 0.985 | 0.895 | 0.797 | 0.678 | 0.0068 (0.0020) | 7.88 | 0.115 | 0.521 |
| ecmwf_ens_mean+map | 309385 | 0.8068 (0.0043) | 0.980 | 0.850 | 0.732 | 0.684 | 0.0100 (0.0023) | 8.17 | 0.344 | 0.633 |

### Lead D+3 (122 issue days)

| candidate | pairs | agreement (SE) | within one | Watch+ recall | Warning+ recall | Warning+ precision | delta vs GFS (SE) | rain MAE domain (mm) | hit >=50 | FAR >=50 |
|---|---|---|---|---|---|---|---|---|---|---|
| gfs | 309362 | 0.7726 (0.0050) | 0.976 | 0.839 | 0.705 | 0.644 | 0.0000 (0.0000) | 9.00 | 0.130 | 0.703 |
| gfs+map | 309385 | 0.7655 (0.0056) | 0.973 | 0.831 | 0.699 | 0.629 | -0.0072 (0.0009) | 9.56 | 0.229 | 0.739 |
| ecmwf_hres | 309385 | 0.7765 (0.0046) | 0.978 | 0.865 | 0.749 | 0.641 | 0.0039 (0.0023) | 8.65 | 0.134 | 0.660 |
| ecmwf_hres+map | 309385 | 0.7786 (0.0046) | 0.974 | 0.826 | 0.686 | 0.650 | 0.0060 (0.0024) | 9.04 | 0.274 | 0.690 |
| ecmwf_ens_mean | 309385 | 0.7846 (0.0044) | 0.981 | 0.879 | 0.781 | 0.652 | 0.0120 (0.0023) | 8.07 | 0.082 | 0.549 |
| ecmwf_ens_mean+map | 309385 | 0.7863 (0.0048) | 0.975 | 0.827 | 0.707 | 0.649 | 0.0137 (0.0026) | 8.39 | 0.302 | 0.641 |

## June-September 2023 (secondary; `+map` in-sample)

### Lead D+1 (80 issue days)

| candidate | pairs | agreement (SE) | within one | Watch+ recall | Warning+ recall | Warning+ precision | delta vs GFS (SE) | rain MAE domain (mm) | hit >=50 | FAR >=50 |
|---|---|---|---|---|---|---|---|---|---|---|
| gfs | 202872 | 0.8359 (0.0048) | 0.988 | 0.893 | 0.789 | 0.649 | 0.0000 (0.0000) | 7.33 | 0.156 | 0.655 |
| gfs+map | 202877 | 0.8358 (0.0051) | 0.986 | 0.882 | 0.771 | 0.644 | -0.0001 (0.0008) | 7.80 | 0.285 | 0.718 |
| ecmwf_hres | 202878 | 0.8382 (0.0049) | 0.991 | 0.909 | 0.788 | 0.677 | 0.0023 (0.0019) | 6.69 | 0.153 | 0.562 |
| ecmwf_hres+map | 202878 | 0.8487 (0.0050) | 0.989 | 0.876 | 0.715 | 0.703 | 0.0128 (0.0021) | 6.88 | 0.355 | 0.645 |
| ecmwf_ens_mean | 202878 | 0.8403 (0.0048) | 0.992 | 0.921 | 0.815 | 0.679 | 0.0044 (0.0020) | 6.42 | 0.122 | 0.506 |
| ecmwf_ens_mean+map | 202877 | 0.8555 (0.0049) | 0.990 | 0.881 | 0.736 | 0.709 | 0.0196 (0.0021) | 6.47 | 0.382 | 0.618 |

### Lead D+2 (80 issue days)

| candidate | pairs | agreement (SE) | within one | Watch+ recall | Warning+ recall | Warning+ precision | delta vs GFS (SE) | rain MAE domain (mm) | hit >=50 | FAR >=50 |
|---|---|---|---|---|---|---|---|---|---|---|
| gfs | 202865 | 0.8249 (0.0051) | 0.985 | 0.870 | 0.731 | 0.635 | 0.0000 (0.0000) | 7.54 | 0.130 | 0.684 |
| gfs+map | 202877 | 0.8215 (0.0056) | 0.983 | 0.858 | 0.712 | 0.624 | -0.0034 (0.0008) | 7.99 | 0.244 | 0.737 |
| ecmwf_hres | 202878 | 0.8250 (0.0051) | 0.988 | 0.890 | 0.756 | 0.641 | 0.0001 (0.0019) | 7.09 | 0.127 | 0.640 |
| ecmwf_hres+map | 202877 | 0.8323 (0.0055) | 0.986 | 0.850 | 0.678 | 0.662 | 0.0074 (0.0020) | 7.32 | 0.301 | 0.699 |
| ecmwf_ens_mean | 202878 | 0.8284 (0.0047) | 0.990 | 0.900 | 0.780 | 0.649 | 0.0035 (0.0020) | 6.73 | 0.095 | 0.555 |
| ecmwf_ens_mean+map | 202877 | 0.8386 (0.0054) | 0.986 | 0.851 | 0.697 | 0.663 | 0.0137 (0.0023) | 6.78 | 0.346 | 0.654 |

### Lead D+3 (80 issue days)

| candidate | pairs | agreement (SE) | within one | Watch+ recall | Warning+ recall | Warning+ precision | delta vs GFS (SE) | rain MAE domain (mm) | hit >=50 | FAR >=50 |
|---|---|---|---|---|---|---|---|---|---|---|
| gfs | 202853 | 0.8092 (0.0055) | 0.983 | 0.846 | 0.697 | 0.617 | 0.0000 (0.0000) | 7.89 | 0.118 | 0.726 |
| gfs+map | 202878 | 0.8039 (0.0060) | 0.980 | 0.831 | 0.677 | 0.602 | -0.0053 (0.0010) | 8.35 | 0.218 | 0.765 |
| ecmwf_hres | 202878 | 0.8073 (0.0053) | 0.984 | 0.874 | 0.729 | 0.607 | -0.0018 (0.0023) | 7.37 | 0.114 | 0.688 |
| ecmwf_hres+map | 202878 | 0.8145 (0.0057) | 0.981 | 0.830 | 0.645 | 0.622 | 0.0053 (0.0024) | 7.62 | 0.269 | 0.731 |
| ecmwf_ens_mean | 202878 | 0.8092 (0.0050) | 0.987 | 0.887 | 0.762 | 0.616 | 0.0001 (0.0026) | 6.94 | 0.067 | 0.581 |
| ecmwf_ens_mean+map | 202878 | 0.8203 (0.0058) | 0.981 | 0.827 | 0.666 | 0.622 | 0.0112 (0.0028) | 7.08 | 0.318 | 0.682 |

Rain MAE is also the CRPS of a single-valued forecast; the member totals of the ensemble are not stored, so no ensemble CRPS is computed.

## Decision (primary period, pre-declared rule)

| lead | chosen | eligible | reason |
|---|---|---|---|
| D+1 | gfs | none | no candidate beats GFS by more than the bootstrap SE of the difference without lowering Warning+ recall |
| D+2 | ecmwf_ens_mean | ecmwf_ens_mean | agreement 0.8036 vs GFS 0.7967 (+0.0068, bootstrap SE 0.0020); Warning+ recall 0.797 vs 0.745 |
| D+3 | ecmwf_ens_mean+map | ecmwf_hres, ecmwf_ens_mean, ecmwf_ens_mean+map | agreement 0.7863 vs GFS 0.7726 (+0.0137, bootstrap SE 0.0026); Warning+ recall 0.707 vs 0.705 |

## Widening factors of the chosen configuration (2024 issue days)

| lead | chosen | informative cell-days | lo | hi | GFS raw lo | GFS raw hi |
|---|---|---|---|---|---|---|
| D+1 | gfs | 149308 | 0.176 | 4.238 | 0.176 | 4.238 |
| D+2 | ecmwf_ens_mean | 154529 | 0.176 | 3.672 | 0.176 | 5.675 |
| D+3 | ecmwf_ens_mean+map | 149695 | 0.151 | 5.917 | 0.165 | 6.071 |
