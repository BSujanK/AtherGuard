# AetherGuard W8 - always-on host: decision document

Date: 2026-11-07. Status: DECISION DOCUMENT ONLY. Nothing has been launched, created or configured in any cloud, and no
cloud CLI was run. Every price below was read from a web page on 2026-11-07 (sources in section 9); anything I could not
confirm on an official page is marked **[unverified]**. Roadmap context: W8 in
`2026-11-02-aetherguard-accuracy-roadmap.md` (gate G5; "nothing launched without the user's yes on $/hour and $/day").

## 1. Problem and what "fixed" means

The daily run (`python -m aetherguard.live run --date today`, Windows Task Scheduler "AetherGuard daily" at 11:00 IST,
`scripts/install_daily_task.ps1`) only fires when the laptop is on, awake and online. In 2026-10-25..11-07 several days were
missed or ran without inputs. A missed day is a missed warning. The task script already encodes the retry contract that any
new host must keep: exit 1 = error, retry; exit 3 = published but the IMD rain of the day was not yet assembled, retry;
up to 3 retries, 30 minutes apart, last attempt 12:30; the run uses the IST date, so the host clock must be IST.

## 2. Requirements (measured where I could, from the repo on 2026-11-07)

| Item | Requirement | Basis |
|---|---|---|
| Uptime | The host must be able to run a job at 10:50-12:45 IST every day. A 24x7 dashboard is a want, not the need that caused the losses | Section 1 |
| CPU / RAM | 2 vCPU / 8 GB. Peak RAM of the run is about 4-6 GB (your figure), so 4 GB hosts are unsafe | Brief |
| Runtime | 2-5 min compute; budget 20 min typical (downloads with retries); worst case about 1.9 h when the retry window is used | Brief + task script |
| Disk | Footprint the daily run needs, measured: `data/live` 1.4 GB (about 55 MB per day, 28 days), `data/processed/rain` 6.5 GB (IMERG store the run reads), `data/processed` total 11 GB incl. `alerts` 2.8 GB. `data/raw` was too large to size in the time available (not measured). Your 60-80 GB total includes research data the daily run does not need. Plan **50 GB** on the server, raw downloads purged after processing, daily outputs rotated to object storage. Output growth about 20 GB/year if never rotated | Measured with `du`; raw not measured |
| Inbound data | 0.5-1 GB/day IMERG/GFS/ECMWF/IMD. Inbound is free on AWS **[unverified on the pricing page today]** | Brief |
| Outbound data | Tiny (results sync, dashboard JSON). Far below every provider's allowance except GCP's 1 GB free-tier egress | - |
| Dashboard | Today local-only on 127.0.0.1:8790. Needs: either stay local (reads synced results) or a small always-on read-only page (public or behind auth). Not required for the daily run | Brief |
| Secrets | Earthdata netrc (and any other tokens) must never be baked into an image, committed (the repo is public) or placed in user-data. Pulled at run time from a secrets store into a mode-600 netrc | Repo is public (memory note) |
| Code portability | `AETHERGUARD_DATA_DIR` already overrides the data root (`config.py`). Python 3.13.5 lock file; `eccodes` needs the native ECMWF library on Linux (GRIB2 decode of GFS); the lock file contains Windows-only pins such as `colorama` (harmless). The deployment scripts are PowerShell only | Repo |

## 3. Options with cost

Conversions at **1 USD = Rs 96** (assumption: the latest dated figure I found was 96.48 on 2026-07-25 per Tradersunion;
other sources said 94.7-95.7, undated; I could not confirm today's rate **[unverified]**). 1 month = 730 h = 30.44 days.
AWS bills in USD; Indian GST and card forex fees are extra and not included **[unverified rate]**. EBS storage assumes
50 GB gp3 at $0.0912/GB-month (a May 2021 third-party figure for Mumbai; the official EBS page I read lists only a generic
$0.08/GB-month and no region table **[Mumbai gp3 unverified]**) = $0.00625/h. Public IPv4 is $0.005/h
(AWS announcement; applies to any public IPv4 address, in use or idle).

EC2 Mumbai rates (Linux, on demand) come from a third-party aggregator updated 2026-11-07 (aws-pricing.com):
**t3.large $0.0896/h**, t4g.large $0.0448/h. I trust the first (plausible vs. the US rate of $0.0832) and **do not trust the
second**: the Vantage page lists t4g.large at $0.067/h for what looks like the default US region, so a Mumbai price of
$0.0448 would be cheaper than the US price, which is implausible. For t4g.large I plan on about $0.072/h (my estimate,
t3 x 0.8, **[unverified]**). Verify both in the AWS Pricing Calculator for ap-south-1 before approving.

| # | Option | $/hour | $/day | $/month | Rs/hour | Rs/day | Rs/month |
|---|---|---|---|---|---|---|---|
| a1 | EC2 t3.large always on, 50 GB gp3, 1 public IPv4 | 0.1009 | 2.42 | 73.6 | 9.68 | 232 | 7,070 |
| a2 | EC2 t4g.large always on (price est. $0.072) | 0.0829 | 1.99 | 60.5 | 7.96 | 191 | 5,810 |
| b1 | Lightsail 8 GB / 2 vCPU / 160 GB, IPv4 plan | 0.0603 | 1.45 | 44.00 | 5.79 | 139 | 4,224 |
| b2 | Lightsail 8 GB, IPv6-only plan | 0.0548 | 1.31 | 40.00 | 5.26 | 126 | 3,840 |
| b3 | Lightsail 4 GB / 2 vCPU / 80 GB (too little RAM) | 0.0329 | 0.79 | 24.00 | 3.16 | 76 | 2,304 |
| **c** | **EC2 t3.large scheduled-only, 20 min/day, 50 GB gp3, results in S3** | **0.0946 while running; 0.0063 storage always; 0.0089 averaged** | **0.215** | **6.5** | **9.08 / 0.60 / 0.85** | **21** | **627** |
| c-worst | same, retry window used (instance up 10:50-12:45, 1.9 h) | - | 0.37 | up to 11 if every day | - | 36 | up to 1,070 |
| d | GitHub Actions scheduled workflow, public repo, state in object storage | 0 compute | 0.01-0.03 | 0.3-1 | - | 1-3 | 30-100 |
| e | Raspberry Pi 5 8 GB or mini PC at home | one-off Rs 14,000-20,000 (est.) | about Rs 1-2 power | about Rs 30-60 power | - | - | - |
| f1 | Oracle Always Free Ampere A1 (2 OCPU / 12 GB / 200 GB) | 0 | 0 | 0 | 0 | 0 | 0 |
| f2 | Google e2-micro free tier | 0 | 0 | 0 | does not fit | | |

Row notes:

* **a**: t3.large is 2 vCPU / 8 GiB. 730 h x $0.0896 = $65.4 + IPv4 $3.65 + EBS $4.56 = $73.6. t3 default "unlimited" credit
  mode could add up to $0.05 per vCPU-hour above baseline **[unverified, from memory]**; negligible for a 5-min daily job.
* **b**: Lightsail prices are flat bundles read from the official page: 8 GB $44 (IPv4) / $40 (IPv6-only); 4 GB $24 / $20.
  The page states Mumbai plans carry half the listed transfer allowance (still about 2.5 TB). Instance is billed even when
  stopped. Block storage, if the 160 GB bundled SSD were not enough, is $0.10/GB-month.
* **c**: typical day = compute 20 min x $0.0896 = $0.030; IPv4 20 min = $0.002; allowance for unlimited-mode surplus credits
  <= $0.025 **[unverified]**; EBS 50 GB $0.150; S3 for results and backups (10 GB at about $0.025/GB-month
  **[unverified]**) about $0.01. Total $0.215/day. With an 80 GB disk: $0.26/day, $7.9/month.
* **d**: GitHub-hosted runners, read 2026-11-07: public repo `ubuntu-latest` 4 vCPU / 16 GB / 14 GB SSD; private repo
  2 vCPU / 8 GB / 14 GB SSD (so your "7 GB" is outdated; both exceed the 4-6 GB peak). Job limit 6 h. Cache 10 GB per repo,
  entries evicted after 7 days unused. Standard runners being free for public repos is GitHub policy I did not re-verify
  today **[unverified]**. The $0.01-0.03/day is the object store that holds state between runs, not Actions itself.
* **e**: Pi 5 8 GB retail listings in India ranged from about Rs 6,955 to Rs 9,500 (several out of stock; some listings
  Rs 14,950+), plus PSU, cooler, case and a 256-512 GB SSD, hence the Rs 14-20k total **[estimate]**. Power 4-8 W average
  **[unverified, general knowledge]** at Rs 8-10/kWh **[assumption]**. Amortised over 36 months the hardware alone is
  Rs 390-560/month, i.e. about the same as option c.
* **f1**: Oracle's official Always Free page (read today) says 1,500 OCPU-hours and 9,000 GB-hours per month, equal to
  **2 OCPU / 12 GB** (not the older 4 / 24), 200 GB combined block and boot storage, 10 TB/month outbound, 2 AMD micro
  VMs (1/8 OCPU, 1 GB), home-region only. It fits on paper. See the idle-reclaim risk below.
* **f2**: Google's page: one e2-micro, only in us-west1 / us-central1 / us-east1, 30 GB standard disk, 1 GB/month egress.
  e2-micro has 1 GB RAM **[from general knowledge, not on the page]**, far below the 4-6 GB peak. Rejected.

## 4. What changes per option (code, ops, risk, effort)

Common to every remote option: a Linux install (`uv` + Python 3.13.5 from `requirements-lock.txt`, native `libeccodes`
from the distro packages), `TZ=Asia/Kolkata`, `AETHERGUARD_DATA_DIR` pointing at the data volume, a bash/systemd
replacement for `install_daily_task.ps1` with the same retry contract, a one-time seed of the model, terrain and
`processed/rain` stores (rsync/S3 from the laptop, or rebuild), and **one writer only**: disable the laptop task after a
week of parallel running so two hosts never publish the same day.

**(a) EC2 always on.** Adds: uvicorn + the React build behind Caddy/nginx or a tunnel, EBS snapshots (snapshots $0.05/GB-month,
generic figure, **[Mumbai unverified]**). Dashboard can be public read-only or auth. Risk: pays 24 h for 20 min of work;
patching and disk-full ownership; arm64 (t4g) adds wheel risk for `lightgbm`, `rasterio`, `eccodes`, `h5py` on Python 3.13
**[unverified]**. Effort 1.5-2 days. Dominated by Lightsail on price for the same shape.

**(b) Lightsail 8 GB.** Same code changes as (a) but with a fixed bill, bundled static IP/transfer, and a one-click snapshot
feature. Dashboard public read-only is simplest here. Risks: fixed cost whether used or not; 4 GB plan cannot take the 4-6 GB
peak; plans are burstable **[from memory, unverified]**, fine for a 5-minute job but not for heavy research jobs (keep those
on the laptop). Effort 1.5-2 days. This is the best choice **if a live server-hosted dashboard is a requirement**.

**(c) Scheduled-only EC2.** Adds, in addition to the common list:
1. EventBridge Scheduler rule at 10:50 Asia/Kolkata (time-zone support **[unverified]**) that starts the instance (direct
   `ec2:StartInstances` target, no Lambda).
2. A systemd unit on boot: fetch the Earthdata netrc from SSM Parameter Store SecureString into `~/.netrc` (mode 600) using the
   instance role; run the live job with the existing retry loop; copy `data/live/<date>` and logs to S3; on final failure
   publish an SNS/email alert (this is also the W8 "failure notification"); then `shutdown -h now` with
   instance-initiated shutdown behaviour = stop. A watchdog caps uptime at 13:00 IST.
3. No inbound security-group rules, access via SSM Session Manager, IMDSv2 required, EBS encrypted, least-privilege role
   (one parameter, one bucket).
4. Dashboard stays on the laptop and reads results synced from S3 (`aws s3 sync` of a few hundred MB, run when the laptop is
   on). Optional phase 2: publish a static read-only export (S3 + CloudFront or GitHub Pages; your decision whether forecasts
   go public).
Risks: (i) not a live dashboard; (ii) a start failure or a stuck instance silently loses a day unless the alert also fires on
"no result by 11:30" (a dead-man check, in scope); (iii) cold start of about 1-2 min and EBS first-read latency; (iv) the
`eccodes`/Linux port is the main technical unknown; (v) the one-time seed of about 10-15 GB from home broadband. Effort
**1.5-2.5 days** (matches the roadmap's 1-2 days plus the dead-man check).

**(d) GitHub Actions.** `schedule` cron in UTC (`37 5 * * *` is about 11:07 IST; docs say runs at the top of the hour are delayed
under load, so avoid minute 0; shortest interval 5 min). Secrets in repo secrets (the repo is public, so never echo them and
mind that workflow logs are public). Problems: the runner has only **14 GB SSD**, so `processed/rain` (6.5 GB) plus fresh
downloads is tight; cache is 10 GB and evicts after 7 days unused; artifacts are quota-limited (500 MB on Free per the docs I
read), so state must live in an external store (object storage, a private repo release, or similar) and be pulled each run.
Scheduled workflows in public repos are **disabled after 60 days without repository activity** (docs quote), needing a
keep-alive. Job timeout 6 h is not a problem. No live dashboard (static export only). Any publish step that commits results
would make them public. Feasible only after trimming the daily state to under about 10 GB. Effort 2-3 days; cheapest
compute, most moving parts. Retry semantics (30 min apart) become one long job or several cron entries.

**(e) Home Pi / mini PC.** Same Linux port as above plus systemd, a UPS or accepting power cuts, and a tunnel (Tailscale or
Cloudflare Tunnel) for the dashboard. It removes the cloud cost but **keeps the exact failure class that caused the losses**
(home power, router, ISP, a reboot at the wrong time), only less often than a laptop. arm64 wheel risk for Pi **[unverified]**;
an x86 mini PC avoids it. One-time purchase is a spend decision of its own. Effort 2-3 days including setup.

**(f1) Oracle Always Free.** Same Linux/arm64 port. Honest risks: (i) idle reclamation: Oracle may reclaim an Always Free
instance if over any 7 days the CPU 95th percentile < 20%, network < 20% and (A1 only) memory < 20%; a 5-minute daily job on
an otherwise idle VM matches that profile, so reclaim is a realistic threat; (ii) A1 capacity is commonly "out of host
capacity" at signup **[third-party reports, unverified]**; (iii) the allowance was reduced from 4 OCPU / 24 GB to
2 / 12 in 2026 per third parties, and the official page now shows 2 / 12, so terms can still change; (iv) a new account needs
card verification and a fixed home region; (v) it is a different vendor and credential set for a safety-relevant pipeline.
Effort 2-3 days. Fine as a secondary/experimental mirror, not as the only host.

**(f2) Google e2-micro.** Does not fit: 1 GB RAM, 30 GB disk, 1 GB/month egress, US regions only. Not considered further.

## 5. Comparison against the need

| Option | Fixes lost days | Live dashboard | Monthly Rs | Ops burden | Main risk |
|---|---|---|---|---|---|
| a1/a2 EC2 always on | yes | yes | 5,800-7,100 | medium | pays for idle time |
| b1 Lightsail 8 GB | yes | yes | 4,224 | low | fixed cost |
| c scheduled EC2 | yes | no (local, synced) | about 630 | medium (more parts) | silent start failure without dead-man alert |
| d GitHub Actions | mostly | no | 30-100 | high | 14 GB disk, 60-day disable, public logs |
| e home device | partly | yes (via tunnel) | 30-60 + hardware | medium | same class of outage as today |
| f1 Oracle free | yes if not reclaimed | yes | 0 | medium | idle reclaim, capacity, terms |

## 6. Recommendation

**Option (c): scheduled-only EC2, with option (b) Lightsail 8 GB as the upgrade if you decide you want a live
server-hosted dashboard.**

Reasoning:
1. The thing that is being lost is the daily run, not dashboard uptime. A 20-minute job needs 20 minutes of compute; paying
   for 24 hours (a1/b1) buys a live dashboard at 7-11 times the price. At about Rs 630/month it is cheaper than the home
   device's amortised hardware and avoids the home-power failure class.
2. It is a real VM with the same 8 GB, so the 4-6 GB peak is safe, unlike GitHub's 14 GB disk or Google's 1 GB micro tier.
3. The worst case is bounded: a watchdog stops the instance at 13:00 IST, so the daily ceiling is about $0.37-0.45, and the
   only continuous cost is the 50 GB disk.
4. It is reversible: the same image/scripts move to Lightsail or an always-on EC2 if needed. Choose x86 `t3.large` over
   `t4g.large` because the saving is under $0.01/day while arm64 wheels for Python 3.13 are an unverified risk.
5. Free Oracle looks tempting but its idle-reclaim rule is aimed at exactly this workload, so it is a mirror at most.

### What you would be approving - NOT LAUNCHED; needs your yes

| Item | Value |
|---|---|
| Account / profile | An existing AWS account (project memory records profile `amazon-ml`; I did not check it). Nothing created |
| Region | ap-south-1 (Mumbai) |
| Compute | 1 x EC2 **t3.large** (2 vCPU, 8 GiB), Linux, on demand, no Spot, no reservation |
| Disk | 1 x **50 GB gp3** EBS, encrypted (80 GB if you want to keep more history on the box: +$0.04/day) |
| Other | 1 S3 bucket (results, logs, backups), 1 SSM SecureString (Earthdata netrc), 1 SNS email topic, 1 EventBridge schedule; all inside tiny usage |
| Schedule | Start 10:50 IST, self-stop on completion, hard stop 13:00 IST |
| **Rate while running** | **$0.0946/hour** (about Rs 9.1/h): instance $0.0896 + public IPv4 $0.005 |
| Rate always (disk) | $0.00625/hour (about Rs 0.60/h) |
| **Expected cost** | **about $0.215/day (Rs 21/day), about $6.5/month (Rs 627/month)** with a 20 min run |
| **Ceiling** | **$0.45/day (Rs 43/day), $13.7/month (Rs 1,300/month)** if every day used the full retry window plus margin; the watchdog enforces it |
| Not included | GST and card forex fees; Mumbai gp3 and S3 rates are unverified; confirm all three in the AWS Pricing Calculator for ap-south-1 before launch |
| Billing guard | A Budgets alert at $10/month so a stuck-running instance is visible within a day |

Under the project's AWS rule, I will not launch anything until you reply with an explicit yes to these exact numbers
(instance type, region, disk, $/hour, $/day). If you instead want a live dashboard, the equivalent request would be:
Lightsail 8 GB, $0.0603/h, $1.45/day, $44/month (Rs 4,224).

## 7. Implementation plan once approved (1.5-2.5 days, builder-sized)

1. Linux port and test on the laptop's WSL or a throwaway container: lock install on Python 3.13, `libeccodes`, one `--date today` dry run with `AETHERGUARD_DATA_DIR` on a scratch dir; compare outputs to the Windows run for the same date (parity check).
2. Write `scripts/run_daily.sh`, a systemd unit and a boot-time secrets fetch that reproduce the exit-code retry contract; unit tests for the retry wrapper.
3. Seed data volume with only what the daily run needs (model, terrain, `processed/rain`, `hazard`); measure the true footprint and set the purge/rotation policy.
4. After your yes: create the resources by infrastructure-as-code in a reviewed change; parallel-run one week with the laptop task still on but not publishing; then disable the laptop task.
5. Dead-man alert if no result for the day by 11:30 IST; failure e-mail on final non-zero exit; this closes the W8 notification item. The input-latency monitor can log the IMD/IMERG/ECMWF arrival time on each run into the same bucket.
6. Backups: S3 versioning on results; weekly copy of `reports/` and the model. The disk itself is rebuildable, so no EBS snapshots by default.

## 8. Open items and what I could not verify

* Mumbai gp3 price and S3 price: unverified; EC2 Mumbai rates are from a third-party aggregator dated 2026-11-07.
* t4g.large Mumbai price: sources disagree ($0.0448 vs $0.0483 vs my $0.072 estimate); not needed for the recommendation.
* USD/INR on the day of launch, GST on AWS India invoices, and the card forex fee.
* Lightsail burst behaviour and EventBridge Scheduler time-zone support: from memory, unverified.
* Pi 5 and SSD prices and power draw: retailer listings and estimates only.
* `data/raw` size and the exact set of files the daily run reads were not measured; the 50 GB figure should be confirmed in step 3.
* GitHub Actions free minutes for public repos and AWS inbound-transfer pricing were not re-read from an official page today.

## 9. Sources (all read 2026-11-07)

* AWS Lightsail pricing (official): https://aws.amazon.com/lightsail/pricing/ - plans 8 GB $44 / $40 IPv6-only, 4 GB $24 / $20, block storage $0.10/GB-month, Mumbai half transfer.
* AWS EBS pricing (official): https://aws.amazon.com/ebs/pricing/ - generic gp3 $0.08/GB-month and snapshot $0.05/GB-month examples; no Mumbai table.
* AWS EC2 on-demand pricing page (official): https://aws.amazon.com/ec2/pricing/on-demand/ - no per-region instance table available to me.
* EC2 Mumbai rates, third party, updated 2026-11-07: https://aws-pricing.com/t3.large.html ($0.0896) and https://aws-pricing.com/t4g.large.html ($0.0448, doubtful); cross-check https://instances.vantage.sh/aws/ec2/t4g.large (default-region $0.067).
* Mumbai gp3 $0.0912, May 2021, third party: https://zesty.co/blog/guide-to-ebs-pricing/
* AWS public IPv4 charge $0.005/h: https://aws.amazon.com/blogs/aws/new-aws-public-ipv4-address-charge-public-ip-insights
* GitHub-hosted runner specs: https://docs.github.com/en/actions/reference/runners/github-hosted-runners
* GitHub Actions limits (6 h job, 10 GB cache, artifact quota): https://docs.github.com/en/actions/reference/limits
* GitHub cache eviction (7 days, 10 GB): https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching
* GitHub `schedule` event (UTC, 5 min minimum, load delays, 60-day public-repo disable): https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
* Oracle Always Free resources (official): https://docs.oracle.com/en-us/iaas/Content/FreeTier/resourceref.htm
* Google Cloud free-tier features (official): https://docs.cloud.google.com/free/docs/free-cloud-features
* India Raspberry Pi 5 retail listings (retailer content, not official): https://thinkrobotics.com/blogs/learn/raspberry-pi-5-8gb-price-in-india-complete-buying-guide-2025
* USD/INR snapshots: https://tradersunion.com/currencies/price/usd-inr/ (96.48 on 2026-07-25), https://wise.com/in/currency-converter/usd-to-inr-rate
* Repo facts: `scripts/install_daily_task.ps1`, `src/aetherguard/config.py` (`AETHERGUARD_DATA_DIR`), `requirements-lock.txt`, `configs/live_run.yaml`, `du` of `data/`.
