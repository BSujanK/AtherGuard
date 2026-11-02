# AetherGuard accuracy and precision roadmap

Date: 2026-11-02. Status: proposed. Applies to the Stage A pipeline (v3-live model, post-model rules of spec 2026-10-14 §11,
forecast leads §12, integrity audit §13).

## 1. Where the pipeline stands (measured, not estimated)

| quantity | value | source |
|---|---|---|
| 2018 events (56) caught at Watch+ / Warning+ / Emergency | 48 / 40 / 30 | `reports/phase6_accuracy_hardening.json` |
| 2018 June-Sept cell-days at Watch+ / Warning+ / Emergency | 55.5% / 22.4% / 8.7% | `reports/phase6_summary.json` (`alerts_2018`) |
| development (2007-2017) recall at false-alarm share 1% / 5% / ~20% | 30% / 63% / 90% | `phase6_summary.json` (`v3`) |
| events per 1,000 Warning+ cell-days (development, out of fold) | 0.049 | `reports/phase6_v31_challenger.json` |
| held-out positive cell-days, in domain | 85 (2018) + 10 (2019-2024) | `data/processed/splits/positive_cell_days.parquet` |
| computational / geographic errors in published days | 0 on every audited day | `reports/phase6_integrity_audit.md` |
| live days published with all four leads, 2026-10-25..11-02 | 4 of 9 | `data/live/*/run.json` |

Three facts set the plan:
1. **Detection is good, precision is poor.** The operating point is chosen for about 90% detection, which puts a large
   share of monsoon cell-days on alert.
2. **The test set is too small to prove a large gain.** 56 events in one season cannot separate a good model from a
   very good one, and the false-alarm counts are inflated because catalogs miss most landslides. No "top accuracy"
   claim is possible until the ground truth grows.
3. **The inputs, not the learner, limit the model.** v3 sees daily satellite rain (which misses orographic peaks), no
   soil moisture, no lithology, no road cuts; the v3.1 study showed that reshaping the same inputs does not help.

## 2. Definition of "top accurate and precise" (the goal, measurable)

The pipeline may be called top accurate only when every gate below passes on the expanded test set (§4 W1), evaluated
once, with the pre-declared protocol of §3:

- **G1 precision:** at Warning+ event detection not lower than v3's, Warning+ alert cell-days fall by at least 30%
  (paired bootstrap 95% CI of the reduction above 0, point estimate ≥ 30%).
- **G2 detection:** Watch+ event detection not lower than v3's by more than 2 events; Emergency event-based precision at
  least twice v3's.
- **G3 calibration:** expected calibration error not worse than v3's (bootstrap CI), reliability curve inside its CI.
- **G4 benchmark:** better event-based precision than NASA LHASA v2 and than a published rainfall-threshold baseline at
  matched detection, on the same events and days.
- **G5 operations:** ≥ 95% of days published with all four leads over 30 consecutive days.
- **Test-set size:** at least 150 held-out in-domain dated events. Below that the report says "not demonstrated".

## 3. Protocol v3 (applies to every workstream)

- **Verification is event-based with tolerance.** An event is detected when an alert at level ≥ L lies within
  10 km and ±1 day of it. An alert cell-day is verified when an event lies within the same tolerance. Precision =
  verified alert cell-days / alert cell-days. The cell-exact numbers of protocol v2 are reported alongside.
- **Selection only on development data** (year-blocked CV 2007-2017); the held-out set is read once per adopted change.
- **Every change states its adoption criterion in the spec before its first held-out number** (as §14 and §15 did).
- **A change is adopted only if it improves precision without losing more than the declared detection tolerance.** A
  rule that removes alerts at the base event rate is rejected (the lesson of §14).
- Frozen artifacts are never modified; challengers write to new directories; numbers come from result files only.

## 4. Workstreams, in order

| # | workstream | why it moves accuracy or precision | depends on | effort |
|---|---|---|---|---|
| W0 | **Verification foundation**: tolerance matching, precision / POD / CSI / Brier with bootstrap, rain-threshold and susceptibility-only baselines, live verification ledger, baseline report | without it no later gain can be measured or trusted | none | 1-2 days |
| W1 | **Ground-truth expansion**: refresh NASA COOLR / Landslide Reporter to 2025; survey and load openly licensed dated Indian inventories (state disaster authorities, GSI, published event inventories such as Kerala 2018-2021, Himachal 2023, Wayanad 2024) with licence check; re-freeze an expanded test split 2019-2025 | gates G1-G4 need ≥ 150 held-out events; more labels also sharpen training | W0 | 3-5 days |
| W2 | **Operating point and alert logic**: thresholds chosen by event-based precision targets per level and region, region-season calibration (south-India north-east monsoon Oct-Dec, Himalayan western disturbances), Emergency confirmation (two consecutive days or rain-intensity confirm), district aggregation for messages | cheapest precision gain; makes the trade-off explicit | W0 | 1-2 days, needs the user's cost ratio |
| W3 | **Rain-intensity inputs**: half-hourly IMERG maxima (3 h, 6 h, 24 h), GSMaP-NRT as a second satellite source, IMD real-time grid (offset-corrected) merged by quantile mapping; the Himalayan low-rain Warning study | landslides answer short intense bursts that daily totals hide; addresses the 10-26 mm Jammu / Manipur Warnings | W0 | 4-6 days |
| W4 | **Soil moisture / antecedent wetness**: SMAP L4 root-zone (Earthdata, 2-3 day latency) or ERA5-Land with a latency-aware lag; added as features | wet soil is the best-documented precondition for rain-triggered failures | W0 | 3-4 days |
| W5 | **Static susceptibility upgrade**: within-cell steep fraction from the 30 m DEM, road density and road-cut proximity (OpenStreetMap), lithology (GSI 1:2M), soil depth and texture (SoilGrids), land cover (ESA WorldCover); optional two-stage model (susceptibility from undated inventories x dynamic trigger) | explains urban / road cut-slope failures and lowland false alarms that elevation alone mislearned | W0, W1 | 4-6 days |
| W6 | **Model v4**: retrain with W3-W5 inputs under protocol v3; pre-declared candidates; region-season calibration | where the inputs pay off | W1, W3-W5 | 3-5 days |
| W7 | **Forecast leads**: ECMWF ensemble exceedance probabilities instead of the mean, per-lead calibration, forecast precision reported per lead | D+1..D+3 precision | W0, W6 | 2-3 days |
| W8 | **Operations**: an always-on host so no day is lost (cost estimate as a document first; nothing launched without the user's yes on $/hour and $/day), failure notification, input-latency monitor | G5; missed days are missed warnings | none | 1-2 days |
| W9 | **Reporting**: dashboard shows verified precision and detection per level and region; overview PDF and report refreshed | the user and readers see measured skill, not claims | W0, then each workstream | ongoing |

Parallelism: W0 first. Then W1, W2, W3, W4, W8 can run in parallel (separate modules). W5 follows W1. W6 waits for
W1 and W3-W5. W7 follows W6.

## 5. Decisions the user owns

- **Cost ratio of a miss vs a false alarm** for W2 (example: a missed Emergency costs as much as 50 false Emergency
  cell-days). Without it W2 reports the full trade-off curve and recommends nothing.
- **Always-on hosting** for W8 (cost stated first, per the project's AWS rule).
- **Licences** of any inventory in W1 that restricts redistribution (used locally, never committed).

## 6. Risks

- Ground truth may stay too small even after W1; the report then says so rather than claiming G1-G4.
- New inputs add latency; every feature must be available by the 11:00 IST run or carry a declared lag.
- Selection on many candidates inflates development scores; protocol v3 limits the candidate count per workstream and
  reports all of them.
