# AWS credit usage plan (budget: the existing $140 credit)

Prepared 2026-10-14. Nothing in this plan has been created or launched. Every launch needs the user's explicit yes after the $/hour and $/day are stated for that launch. Prices are approximate on-demand Linux prices for us-east-1 / us-west-2 as last known; **check the current price in the EC2 console before any launch**. Spot prices move daily.

## Before anything runs
1. Confirm the credit balance, expiry date and covered services in **Billing → Credits** (promotional credits usually cover EC2, EBS and S3; some exclude Marketplace and support).
2. Create AWS Budgets alarms at **$100** and **$130** (actual cost, including credits applied as a separate line so the alarm tracks usage, not the net bill).
3. Get the GPU quotas approved (`gpu-quota-request.md`).

## Price reference (approximate, verify)

| Instance | Hardware | On-demand $/h | Typical Spot $/h | $/day on-demand (24 h) |
|---|---|---|---|---|
| g4dn.xlarge | 4 vCPU, 16 GiB, 1× T4 16 GB | ~0.53 | ~0.16-0.22 | ~12.6 |
| g4dn.2xlarge | 8 vCPU, 32 GiB, 1× T4 16 GB | ~0.75 | ~0.23-0.32 | ~18.0 |
| g5.xlarge | 4 vCPU, 16 GiB, 1× A10G 24 GB | ~1.01 | ~0.35-0.45 | ~24.1 |
| c7i.4xlarge (CPU) | 16 vCPU, 32 GiB | ~0.71 | ~0.25-0.35 | ~17.1 |
| S3 standard | per GB-month | ~0.023 | | |
| EBS gp3 | per GB-month | ~0.08 | | |

## Planned spend (inside $140)

| Workload | Instance (mostly Spot) | Hours | Est. cost |
|---|---|---|---|
| Stage B terrain + features (CPU) | c7i.4xlarge Spot | 15 | ~$5 |
| Stage B global GBDT + CV grid | g4dn.xlarge / 2xlarge Spot | 60 | ~$15 |
| Deep nowcasting experiments | g5.xlarge Spot | 80 | ~$36 |
| Sweeps and ensembles | g4dn.xlarge Spot | 40 | ~$9 |
| Storage: S3 100 GB × 3 months, EBS 100 GB during jobs | | | ~$10 |
| Data transfer (DEM cross-region read once, results download) | | | ~$5 |
| **Planned total** | | **~195 instance-hours** | **~$80** |
| Reserve for Spot interruptions, reruns, on-demand fallback | | | ~$40 |
| **Ceiling** | | | **$120, below the $130 alarm** |

If Spot capacity is unavailable and on-demand is used instead, the same hours cost about 2.5× more; the plan then cuts the deep-nowcasting experiments first (they are only adopted if they beat the gradient-boosted model).

## Guardrails
- One instance at a time; tag every resource `project=aetherguard`.
- Each job runs a stop timer (`shutdown -h +N`) sized to the job plus 30 minutes.
- Checkpoints to S3 so a Spot interruption loses at most one epoch / one CV fold.
- After each job: terminate the instance, delete its EBS volume, keep only results in S3.
- A weekly check of Cost Explorer; stop all work at the $130 alarm.
