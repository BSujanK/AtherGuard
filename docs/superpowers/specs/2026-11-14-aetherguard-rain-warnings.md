# Probabilistic heavy-rain warnings (pre-declared)

Date: 2026-11-14 (written 2026-11-15 before any skill number). Status: pre-declared. SOTA programme round 2, agent
`rain-warn`, branch `sota-rain-warnings`. Research prototype: nothing here is validated for issuing real public warnings,
and the product never changes a landslide alert level.

## 1. Why

AetherGuard calls itself a landslide and extreme-weather early-warning prototype but publishes only landslide alerts. The
landslide product rests on 87 independent held-out slides; its skill can only be estimated roughly. Rain is observed on
every pixel every day, so a heavy-rain warning can be verified on hundreds of thousands of pixel-days and its reliability
shown, not asserted. This spec fixes the product, its fitting and its verification before any skill number exists.

## 2. What exists locally (probe of 2026-11-15)

| store | what is kept | days |
|---|---|---|
| `data/processed/rain/ecmwf_imdday_<D>.npz` | ECMWF IFS ensemble IMD-day totals for D+1..D+3 on the 0.1 degree IMERG grid: **mean, p10, p50, p90 only** (the members are not stored), plus HRES | 202 monsoon issue days (2023-07-13..09-30, 2024-06-01..09-30; 12Z cycle of D-1, 51 members) and 27 live days 2026-10-09..11-14 (18Z of D-1, 50 members; gaps 10-16..10-21, 10-25, 10-27, 10-29, 10-30) |
| `data/processed/rain/gfs_imdday_<D>.npz` | GFS 00Z deterministic IMD-day totals D+1..D+3, same grid | 488 issue days June-September 2021-2024, 33 live days |
| `data/raw/gfs/{archive,live,tail}` | the GFS GRIB subsets behind the day files, and the 0-3 h tail of the 00Z cycle used for lead 0 | 493 / 33 / 34 cycles |
| `data/live/<D>/` | `features_D0..D3.parquet` (cell rain features; `irain_acc_1` of D0 is the observed IMD-day total of D with the nowcast tail), risk tables, `run.json`, `raw/imd_rt/*.grd` (IMD real-time grids) | 34 run days 2026-10-09..11-14 (10-27, 10-29, 10-30 missing); no ECMWF or GFS GRIB is kept there |
| IMERG V07 Late / Early (`ImergStore`) | UTC daily totals, 0.1 degree | Late 2006-10-01..2026-11-12; Early 2018-06-01..2026-11-13 |
| IMD gridded rainfall 0.25 degree (`imd_<YYYY>.npy`) | IMD-day totals, India only | 2007-2024 |

No ensemble member was kept anywhere, so the exact member fraction above a threshold cannot be recomputed for any archived
day. The product therefore works from the stored quantiles (section 4); storing per-threshold member fractions in the
ECMWF day file is a small change for later (section 10).

**Open, keyless archives that could extend this** (none was fetched for this spec): the ECMWF open-data buckets
(`ecmwf-forecasts` on AWS, `ecmwf-open-data` on Google Cloud, CC BY 4.0, anonymous HTTPS, complete from 2023) hold every
ensemble member; the existing `ingest.ecmwf.fetch_archive` already reads them by byte range, so June-September 2025 (122
monsoon days) and all non-monsoon months since 2023 could be added without an account. That needs about 200 range
requests per issue day (50 members x 4 steps) and an estimated several GB per season; the open-data archive starts in
2023, so no older ECMWF ensemble exists without an account. NOAA GEFS (`noaa-gefs-pds`, keyless) was costed by the
forecast-selection study at about 66 GB for two seasons. ERA5 and TIGGE need an account: that is a decision for the user,
not taken here.

## 3. Quantities

For each assessed 0.05 degree cell (the 36,792 cells of the live run) and each lead k = 0..3 (IMD day D+k, where IMD day X
runs 03 UTC of X-1 to 03 UTC of X), the probability that the IMD-day rain total exceeds:

- the IMD categories `heavy` 64.5 mm, `very_heavy` 115.6 mm, `extremely_heavy` 204.5 mm;
- the pixel's own climatological `p95` and `p99`: the 95th and 99th percentile of IMERG Late IMD-day totals over all
  June-September days of 2007-2022 at that 0.1 degree pixel (all days, dry ones included; 2023 and later are left out so
  no test year enters a threshold).

Probabilities are computed on the 0.1 degree IMERG pixel (the forecasts and the truth live on it); every cell takes the
value of the pixel that holds it. "Exceeds" means strictly greater than.

## 4. How the probability is made

**Leads 1-3 (ensemble).** Raw probability: the exceedance of a CDF rebuilt per pixel from the stored quantiles:
piecewise linear through (0, 0), (p10, 0.1), (p50, 0.5), (p90, 0.9), and above p90 the exponential tail through p50 and
p90, P(X > x) = 0.1 exp(-ln 5 (x - p90) / (p90 - p50)) (zero when p90 = p50). This raw value is reported for comparison
only.

Calibrated probability (the product): a logistic regression fitted per lead and per threshold on fitting days only, with
predictors

- `log1p(max_r(p90)) - log1p(t)`, `log1p(max_r(p50)) - log1p(t)`, `log1p(mean_r(ens_mean)) - log1p(t)`,
- `logit(clim(t))`, the climatological probability of the event at that pixel and day of year (section 6),
- `log1p(t)` for the two percentile thresholds only (it is constant for a fixed threshold),

where `max_r` and `mean_r` are the maximum and mean over the (2r+1) x (2r+1) pixel neighbourhood (the displacement
option). r is chosen from {0, 1, 2, 3} per lead and threshold by the log loss on the fitting days (five coefficients on
about a million pixel-days: in-sample and out-of-sample log loss differ negligibly). Fitting: Newton iterations with a
ridge of 1e-6 per sample on standardised predictors; pixel-days where any input or the truth is missing are dropped and
counted.

**Lead 0 (today).** At the run time (05:30 UTC of D) IMD day D has just ended. Its rain is IMERG Early through 00 UTC of D
plus the 0-3 h tail: in the live run the GFS 00Z 0-3 h forecast (`nowcast_tail` in `run.json`, the value is
`features_D0.irain_acc_1`). The probability is the same logistic form with predictors `log1p(max_r(obs0)) - log1p(t)`,
`log1p(obs0) - log1p(t)`, `logit(clim(t))` (and `log1p(t)` for percentiles), fitted on IMERG Early against IMERG Late. In
the archive the tail is not kept, so the fitting input is persistence, obs0 = UTC day D-1 of Early (0.875 + 0.125 of the
same day); on the 2026 live days the study reads the live `irain_acc_1` itself.

A lead whose ensemble day is missing or flagged invalid is not published (probabilities NaN, level `unavailable`, reason
recorded); it is never filled from another source.

## 5. Splits (time-blocked; nothing is tested on a day it was fitted on)

| test set | fitted on | role |
|---|---|---|
| June-September 2024 (122 issue days) | June-September 2023 (80) | **primary**: the headline statements rest on it |
| June-September 2023 (80) | June-September 2024 (122) | secondary (second fold) |
| October-November 2026 live days (27) | June-September 2023 + 2024 | out of season, the inputs the live run really had |

The model shipped for the daily run is the 2023 + 2024 fit. Target days need an IMERG Late truth; issue days whose target
day is not yet in the store are dropped for that lead and counted.

## 6. Verification (declared in advance)

Truth: IMERG Late IMD-day totals, 0.875 UTC(d-1) + 0.125 UTC(d), on the same pixel. Domain: the 11,354 pixels that hold at
least one assessed cell; regions `himalaya` and `western_ghats` are the pixels with at least two of their four cells in
that region (`forecast_skill.pixel_region_labels`).

Reference climatology `clim(t)`: per pixel and day of year, the share of IMD days within plus or minus 15 days of that day
of year, over 2007-2022, whose total exceeds t (IMERG Late). It is also a predictor (section 4), floored at 1e-4.

Per test set, lead, threshold and region:

- Brier score (BS) and Brier skill score against `clim` (BSS = 1 - BS / BS_clim);
- reliability table on the bins [0, 0.05, 0.1, 0.2, ..., 0.9, 1.0] with counts, mean probability and observed frequency;
  the Murphy terms REL, RES, UNC on those bins; calibration in the large = mean probability / observed frequency;
- ROC area (from a 1001-bin histogram of probabilities; ties count one half);
- event counts: event pixel-days and distinct event days (days with at least one event pixel in the group);
- deterministic baselines turned into 0/1 forecasts by the same threshold: lead 0 the observed obs0; leads 1-3 GFS, the
  ECMWF ensemble mean and ECMWF HRES; the raw quantile probability is shown beside them;
- 95% intervals from 1000 bootstrap resamples of test days (each day keeps all its pixels, because neighbouring pixels on
  one day are not independent), seed 20261114.

Second opinion: IMD gridded 0.25 degree for the 2023 and 2024 test sets, India only (IMD coverage mask), each 0.1 degree
pixel read against the IMD cell whose centre is nearest, fixed thresholds only (the percentile thresholds are IMERG
quantities). Reported: BS, BSS against the test-set base rate (sample climatology, a reference that favours the reference),
ROC area, calibration in the large. The IMD day convention in the local store is marked unconfirmed by its index; the
second opinion is read with that caveat.

**Statements, with criteria fixed now.** For each lead, threshold and region of the primary test set:

- *enough events*: at least 100 event pixel-days on at least 10 distinct event days; with fewer, the report says "too few
  events to conclude" and makes no skill or reliability statement;
- *skilful*: BSS > 0 with the lower bound of its 95% interval above 0;
- *beats the deterministic baselines*: BS(product) - BS(baseline) has its 95% interval below 0 for every baseline of the
  lead;
- *reliable*: REL / UNC at most 0.10 and calibration in the large between 0.8 and 1.25;
- *discriminates*: ROC area with the lower bound of its interval above 0.5.

The secondary and out-of-season sets are reported with the same tests and do not change the headline statements; a
disagreement between them is stated.

## 7. Warning levels

From the calibrated probabilities of one pixel-day (P_h, P_vh, P_eh for the IMD categories, P_95, P_99 for the
percentiles), first match wins:

| level | rule |
|---|---|
| red | P_vh >= 0.5 or P_eh >= 0.25 |
| orange | P_h >= 0.5 or P_vh >= 0.2 or P_99 >= 0.4 |
| yellow | P_h >= 0.2 or P_95 >= 0.4 |
| none | otherwise |

The thresholds are fixed here, not tuned. Expected frequency: the report states the share of domain pixel-days at each
level on the fitting days of the shipped model (June-September 2023 + 2024, in sample) as the expected frequency, and the
share on each test set beside it. Intent, before any number: red rare (well under 1% of monsoon pixel-days), orange a few
tenths of a percent to about 1%, yellow a few percent; if the fitted frequencies are far from that, the report says so and
the levels are not changed in this study. Each level is verified by the observed frequency of `heavy`, `very_heavy` and
`extremely_heavy` among its pixel-days and by the share of observed events that fell under each level.

## 8. Outputs

- `python -m aetherguard.rainwarn climatology` builds `data/processed/rainwarn/climatology.npz` (pixel p95, p99, and
  `clim(t)` per day of year for the domain pixels).
- `python -m aetherguard.rainwarn study` fits the calibrations, writes `data/processed/rainwarn/calibration_<fit>.json` and
  `reports/phase8_rain_warnings.json`, and renders `reports/phase8_rain_warnings.md` from the JSON (`report` re-renders).
- `python -m aetherguard.rainwarn run --date D --live-dir <run dir> [--out-dir <dir>]` reads the run directory of day D
  (`features_D0.parquet`, `run.json`) and the ECMWF day file of D from the rain store, and writes
  `rain_warnings.parquet` (one row per cell and lead: probabilities, level, inputs used) and `rain_warnings.md` (a short
  bulletin section) into the out directory (default: the run directory). The archive runs go to
  `AtherGuard-backups/scratch/rain-warn/runs/<D>/`, never to `data/live`.
- `GET /api/rain-warnings?date=&lead=` in `serve/dash_api.py`, read-only.
- Wiring (branch only): `rain_warnings.enabled: false` in `configs/live_run.yaml`; the live run is not changed in this
  study.

## 9. What does not change

No landslide input, model, threshold, post rule or level changes. The command reads the landslide outputs of a run
directory only for the cell list and the lead-0 rain; a test checks that `alerts.parquet` and `risk_D*.parquet` are
byte-identical before and after it runs.

## 10. Honest limits

- The ensemble archive is two monsoon seasons (202 issue days) plus 27 post-monsoon live days. Pixel-days number in the
  millions but they are strongly correlated within a day; the effective sample is closer to the number of days, which is
  why the intervals resample days. Extremely heavy (204.5 mm) pixel-days are rare at 0.1 degree, and may be too few for a
  statement in a region.
- Probabilities come from four stored statistics of the ensemble, not the members; the rebuilt CDF is an approximation
  that the calibration has to correct.
- The truth is a satellite estimate. IMERG Late underestimates orographic rain in the Western Ghats and the Himalaya and
  overestimates some convective totals; skill against IMERG is not skill against rain gauges. The IMD grid is a second
  opinion at a coarser scale with an unconfirmed day convention.
- The 2026 set is October-November, outside the monsoon: heavy rain is rare there, so it tests mainly that the product
  stays quiet and calibrated when the base rate falls, not detection.
- Lead 0 is fitted with a persistence tail and run with the GFS tail; the tail is 3 of 24 hours.
- The archive cycle (12Z of D-1) is 6 hours older than the live cycle (18Z of D-1), so archive skill slightly
  underestimates live skill at the same lead.
- A longer archive (2025 and the non-monsoon months from the open buckets, section 2) would give a third monsoon season for
  testing, seasonal calibration, and enough extremely heavy events per region.

## 11. Amendment (2026-11-15, after the climatology table was built and before any forecast or skill number)

In the driest pixels the June-September 95th percentile is a few millimetres (512 domain pixels below 5 mm, 1,208 below
15.6 mm, almost all in the Himalaya rain shadow), so "exceeds its own p95" would warn of light rain. Both percentile
thresholds are floored at 15.6 mm, the lower bound of the IMD category "moderate": `p95 = max(p95, 15.6)`, likewise
`p99`. The floor applies to the thresholds, `clim(t)` and the product alike. No other part of the spec changes.

## 12. Amendment v2 (2026-11-16): shipped calibration, re-derived levels and the one test on June-September 2025

Written and committed before the June-September 2025 ECMWF days are fetched and before any 2025 number is computed. The
lead's decisions of 2026-11-16: fetch JJAS 2025 from the open ECMWF buckets (no account), re-derive the warning levels so
they fire at stated frequencies, and test the shipped product once on 2025.

**12.1 Data.** The 12Z run of D-1 for every issue day 2025-06-01..2025-09-30, fetched with `ingest.ecmwf.fetch_archive`
(`ecmwf_build --archive --start 2025-06-01 --end 2025-09-30`, a 2025 window added to `configs/live.yaml` on this branch),
the same cycle and product as 2023 and 2024. Truth: IMERG Late, as in section 6. No GFS and no IMD grid exist locally for
2025, so the 0/1 baselines and the IMD second opinion are not part of the 2025 test (they are shown where they exist).
Lead 0 (observation, section "How much of the D skill is observation" of the report) is reported but not tested.

**12.2 Shipped calibration.** Two candidates, both fitted on all of June-September 2023 + 2024 (the pooled fit):

- A: the predictors of section 4, as shipped now;
- B: A plus one season-state predictor `s`, the same column for every threshold. For issue day D and the pixel's group g
  (`himalaya`, `western_ghats`, or all domain pixels for a pixel in neither), over the window W of IMD days D-31..D-2
  (30 days that IMERG Late has observed by the run time): count = pixel-days of g x W whose IMERG Late IMD-day total
  exceeds 64.5 mm, expected = the sum of `clim(heavy)` over the same pixel-days (missing pixel-days leave both),
  `s = ln((count + 1) / (expected + 1))`. With fewer than 20 days of W in the store, `s = 0`. It says whether the recent
  weeks were wetter or drier than usual, the season-to-season swing behind the "NOT reliable" rows.

Choice, on development data only: the cross-season log loss (fit on 2023, score 2024; fit on 2024, score 2023), summed
over leads 1-3 and the five thresholds and weighted by pixel-days. B is shipped if its sum is lower than A's, else A.
Lead 0 keeps A in both cases. The neighbourhood radius is re-chosen per lead and threshold by the rule of section 4.

**12.3 Warning levels v2.** Per lead (0 to 3 separately), from the shipped calibration's probabilities on the pooled
2023 + 2024 days (in sample), first match wins:

| level | rule |
|---|---|
| red | P_vh >= c_r |
| orange | max(P_h, P_99) >= c_o |
| yellow | max(P_h, P_95) >= c_y |
| none | otherwise |

The cutoffs are set so that, on the 2023 + 2024 domain pixel-days of that lead, red fires on 0.3%, orange or red on 1.5%,
and yellow or above on 6.0% of pixel-days (c_r is the 99.7th percentile of P_vh; c_o and c_y are found by bisection on
the cumulative share). These are the target frequencies; the 2023 + 2024 base rate of heavy rain is about 2% of
pixel-days, so yellow or above is about three times the event frequency. The section 7 rules stay in the report for
comparison only; the product uses v2.

**12.4 The pass rule on June-September 2025, tested once.** Domain, shipped calibration, v2 levels. The product PASSES
when all of these hold:

1. at least 90 issue days of 2025 have an ECMWF day file and a truth for every tested lead;
2. BSS against climatology with the lower bound of its 95% day-bootstrap interval above 0 for `heavy` at D+1, D+2 and D+3
   and for `very_heavy` at D+1 and D+2;
3. mean probability / base rate between 0.67 and 1.5 for the same five rows;
4. the share of observed heavy pixel-days (IMERG Late above 64.5 mm) that fell under level `none`: at most 40% at D+1 and
   at most 50% at D+2 and D+3.

The enough-events rule of section 6 applies; a row without enough events counts as a failed row. Every other number
(the other thresholds, regions, reliability tables, level frequencies against their targets) is reported beside the
verdict and does not change it. The 2025 scoring writes a started marker before it computes anything and refuses a
second run. If the product fails, it is reported as failed and nothing is re-tuned on 2025.
