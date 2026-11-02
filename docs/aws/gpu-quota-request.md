# AWS Service Quotas request: GPU instances for AetherGuard

Prepared 2026-10-14. This document is for the user to submit; nothing has been requested or launched.

## What to request

Submit in the AWS console: **Service Quotas → AWS services → Amazon Elastic Compute Cloud (Amazon EC2)**, in the region you will use (recommended: **us-west-2, US West (Oregon)**, next to NASA Earthdata Cloud where the IMERG rain archive lives).

| Quota name (search for it) | Quota code (verify in console) | Requested value | Why this value |
|---|---|---|---|
| Running On-Demand G and VT instances | L-DB2E81BA | **8 vCPUs** | One g4dn.2xlarge or g5.2xlarge (8 vCPUs), or two xlarge instances for parallel cross-validation folds |
| All G and VT Spot Instance Requests | L-3819A6DF | **8 vCPUs** | Same capacity on Spot, which is how most training will run (60-70% cheaper) |

New accounts usually start at 0 vCPUs for these families, so no GPU instance can be launched until these are raised.

## Use-case description (paste into the request form)

> I am building AetherGuard, an open-data AI early-warning system for rain-triggered landslides in the Himalaya and the Western Ghats (India, Nepal, Bhutan). The current prototype runs on a laptop and is fully evaluated: a sensor-integrity engine that detects faulty rain gauges (macro recall 0.70 versus 0.30 for the best rule-based checks on unseen stations) and a calibrated LightGBM landslide model that, on an unseen test year, alerts on 21% of cell-days against 32-41% for standard rainfall-threshold and susceptibility methods at similar detection. The pipeline uses 166,728 terrain cells, 140 rain gauges, 68,738 landslide catalog records and 15 GB of satellite rain, with 1,323 automated tests.
>
> The next stage extends the model to worldwide coverage (global NASA landslide catalog, NASA IMERG rain, Copernicus global terrain) and adds deep spatio-temporal nowcasting models on daily and half-hourly rain fields. These workloads exceed a 16 GB laptop: gradient-boosted training on tens of millions of rows with GPU acceleration, and ConvLSTM/U-Net models that need 16-24 GB of GPU memory. I request 8 vCPUs of G-family capacity (On-Demand and Spot) to run one g4dn or g5 instance at a time. Jobs are batch training runs of a few hours, run on Spot where possible, with AWS Budgets alarms, automatic stop on completion and teardown after each job. Data is read in place from AWS Open Data (Copernicus DEM, NOAA GFS) and NASA Earthdata Cloud in us-west-2 to avoid transfer costs. The work is funded by my existing AWS promotional credit.

(Length about 1,500 characters; trim the first paragraph if the form limits you.)

## If AWS asks follow-up questions

- **Instance types:** g4dn.xlarge (1× NVIDIA T4, 16 GB) for gradient boosting and small CNNs; g5.xlarge (1× NVIDIA A10G, 24 GB) for ConvLSTM/U-Net training. One instance at a time.
- **Expected usage:** about 300 instance-hours over the next 3 months, mostly Spot (see `credit-usage-plan.md`).
- **Cost control:** AWS Budgets alarms at $100 and $130 against a $140 credit; instances stop themselves when a job ends; nothing runs unattended overnight without a stop timer.
- **Why not CPU only:** see `gpu-requirements.md`; the CPU workloads (terrain processing) do run on CPU instances and are not part of this request.
