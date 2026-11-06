# W2: precision-optimal operating point (pre-declared)

Date: 2026-11-06. Status: pre-declared before any result. Roadmap: `2026-11-02-aetherguard-accuracy-roadmap.md` §4 W2.

## 1. Goal (the user's choice: "the most accurate and precise one")

At each alert level, keep detection at least where v3 is today and make alerts as precise as possible, that is, issue as
few alert cell-days as possible for the same detected events. A uniform threshold change cannot do this (it trades one
for the other); the gain must come from *where and when* alerts are spent.

## 2. Method

- **Strata:** region (Himalaya, Western Ghats) x month (June, July, August, September). October-December keep the
  current thresholds (no development data there).
- **Data:** development out-of-fold panels 2007-2017 (`accuracy_hardening_oof`), universe-sample cells for alert
  cell-days (W0 ruling R11), all development events for detection; cell-exact verification (W0 R12: tolerant
  development detection is a lower bound).
- **Optimisation, per level L (Watch, Warning, Emergency) separately:** for each stratum s and candidate threshold t
  (the v3 risk quantiles 50-99.9% in 200 steps), count hits_s(t) (development events in s whose own-cell point level
  reaches L) and alerts_s(t) (universe-sample cell-days in s at or above t). Choose one threshold per stratum to
  maximise sum_s [hits_s(t_s) - lambda * alerts_s(t_s)], with lambda set by bisection so that total hits equal v3's
  total hits at L (no fewer). This equalises the marginal events-per-alert across strata: the optimal allocation.
  Thresholds are then made non-decreasing across levels within each stratum.
- **Candidates (two, no more):** C1 = region x month thresholds; C2 = C1 plus an Emergency confirmation rule
  (Emergency is published only if the raw point level was at least Warning on the previous day as well, else it
  publishes Warning). The section 11 post-model rules and hysteresis apply unchanged on top of both.
- **Selection on development only:** the candidate with fewer development Warning+ alert cell-days at equal or higher
  development detection at every level; ties to C1.

## 3. Pre-declared adoption criterion (evaluated once on the expanded held-out set)

The selected candidate is adopted into the live run only if, on POOLED 2018-2025 (87 independent slides), tolerant and
cell-exact:

1. independent-slide detection at Warning+ and at Emergency is not lower than v3's by more than 1 slide each, and at
   Watch+ by more than 2 slides; and
2. Warning+ alert cell-days fall, with the paired-bootstrap 95% CI of the reduction (days resampled) excluding 0.

Otherwise it is reported and not adopted. Nothing is tuned after the held-out look.

## 4. Outputs

`reports/phase7_operating_point.{md,json}`; candidate thresholds in `data/processed/alerts/thresholds_w2_candidate.json`
(not read by the live run until adopted and wired in a separate, reviewed step).
