# GPU requirements for future heavy training

Prepared 2026-10-14. The current AetherGuard pipeline trains on a laptop (16 GB RAM, no GPU) with LightGBM; that is enough for the two-region model. The workloads below are the ones that are not.

## Workloads

| # | Workload | Why it needs more than the laptop | GPU memory | Recommended instance | Estimated hours |
|---|---|---|---|---|---|
| 1 | **Stage B worldwide hazard model.** Gradient-boosted model (LightGBM GPU or CatBoost GPU) over global landslide-prone cells; year- and continent-blocked cross-validation with a hyper-parameter grid | Roughly 5 million land cells at 0.05°; with sampled negatives and a 30-day rain history the training tables reach tens of millions of rows × 40-60 features, beyond 16 GB RAM, and CPU training of a 7-fold grid would take days | 16 GB is enough for histogram GBDT | g4dn.xlarge (1× T4 16 GB, 16 GiB RAM) or g4dn.2xlarge (32 GiB RAM) | 30-60 |
| 2 | **Deep spatio-temporal nowcasting.** ConvLSTM / U-Net on NASA IMERG rain fields (0.1° grids, 30-90-day input sequences) plus terrain channels, predicting 1-3-day landslide risk and extreme rain | Convolutional sequence models over 280 × 260 domain grids (larger for global tiles) are impractical on CPU; batch sizes need 16-24 GB of GPU memory | 24 GB preferred | g5.xlarge (1× A10G 24 GB) | 60-120 |
| 3 | **Hyper-parameter sweeps and seed ensembles** for workloads 1 and 2, and the bootstrap ensembles (20 members) used for uncertainty intervals | Many independent short runs; parallel on one GPU instance | 16-24 GB | g4dn.xlarge / g5.xlarge (Spot) | 30-50 |

CPU-only work in Stage B (global terrain statistics from the Copernicus DEM, catalog cleaning, feature building) runs on compute-optimised CPU instances (for example c7i.4xlarge on Spot) for an estimated 10-20 hours and is not part of the GPU request.

## Data placement
- NASA IMERG archive: NASA Earthdata Cloud, us-west-2, read directly with Earthdata credentials (no cross-region transfer when compute runs in us-west-2).
- NOAA GFS forecast archive: AWS Open Data `noaa-gfs-bdp-pds` (us-east-1), byte-range reads of the precipitation field only.
- Copernicus GLO-90 DEM: AWS Open Data `copernicus-dem-90m` (eu-central-1); read once, statistics stored in S3 in us-west-2.
- Working storage: S3 (about 100 GB) and a gp3 EBS volume per instance (100 GB), deleted after each job.

## What success looks like
Workload 1 produces a worldwide model evaluated with continent-blocked tests; workload 2 is kept only if it beats the gradient-boosted model in the same cross-validation, by more than its standard error (the rule the project already uses for every model choice).
