# AetherGuard district level with a frequency cap (round 2, workstream `burden`, part 2)

Date: 2026-11-17. Status: declared before any development curve or held-out number was computed. Branch
`sota-district-cap` (from `sota-operating-point`). Nothing is wired into the live run.

## 1. The problem

A warning goes to a district, not to a 5 km cell. With the obvious rule, where a district takes the highest level of any
of its cells, districts are alerted on most days. A district holds a median of 49 scored cells, so one cell at a level is
enough on most days. The options report (`reports/phase8_operating_point_options.md`) shows the result: under the
balanced cell scheme the median Himalayan district would be at Emergency 0.7 days a week in the monsoon, and the busiest
tenth 4.9 days. The live levels (option A, today's card) are the ones aggregated here, because B was not confirmed. This
spec fixes a district rule whose frequency a district officer can act on, keeps the district-days that hold slides, and
states how it would be confirmed.

## 2. Data and protocol

- Development only: the v4 out-of-fold panels of 2007-2017 on every scored cell (`data/processed/alerts/oof_v4_full`,
  June-December and January-May), with the published cell levels of today's chain (card thresholds, `uncertain_high`,
  `post_rules_v3.json`, the hysteresis of `alert_config_v3.json`; `verify.operating_options.chain_levels`).
- Districts: the geoBoundaries table `data/processed/districts/cell_districts.parquet` (India ADM2 under ODbL 1.0, as
  the user accepted; Nepal ADM2; Bhutan ADM1). Attribution: "ODbL 1.0; contains information from geoBoundaries (gbOpen)
  and OpenStreetMap contributors". A district's region is the region of most of its cells. Its season is the day's.
- Statistic: on each district-day, f_L = the share of the district's scored cells at level L or above (L = Watch, Warning,
  Emergency). A district is at level L when f_L >= s_L, where s_L > 0, so at least one cell is always needed. The
  district's level is the highest such L.
- Events: the in-domain development positives of every month, assigned to the district of their cell. An event is
  covered at L when its district is at L or above on the event day (`same_day`), or on the event day or the day before
  or after (`within_1_day`). Intervals resample independent slides (events within 10 km and 1 day of each other).

## 3. Candidate rules (kept few)

- Reference R0: any cell (s_L = the smallest positive share). This is today's natural rule.
- Family F1, stratum share: one s_L per region, season and level. It is the lowest share at which the district-days at L
  or above in that region and season are at most a declared cap (`alerts.frequency_levels.cap_threshold` on the f_L of
  the stratum's district-days), never below R0.
- Family F2, district share: one s_L per district, season and level, set the same way on that district's own days. Every
  district then fires on at most the cap of its own days. This targets the busiest districts.
- Caps per level, the same in every region and season, as a ladder:
  Watch+ 50, 40, 30, 20, 15, 10, 5%; Warning+ 25, 18, 12, 8, 6, 4, 2%; Emergency 10, 6, 4, 3, 2, 1, 0.5% of
  district-days.
- To keep the development numbers honest the shares are fitted leave-one-year-out: every year's district levels use
  shares fitted on the other ten years. The final shares are fitted on all eleven years.

## 4. The choice, declared before the curve

For each family and level: the smallest cap (fewest district-days) at which the `within_1_day` coverage of the
development events (June-December, both regions pooled, leave-one-year-out) is at least 90% of R0's coverage at that level.
Between the two families, the one with the lower 90th-percentile Emergency days per week for Himalayan districts in the
monsoon, at its chosen caps. Ties go to F1, the simpler family. The curve, the cost ratios (district-days saved per
covered event lost against the step before) and the chance floor (the share of district-days at the level within 1 day,
which is the coverage an event placed at random would get) are reported for every step, so the user can choose a sparser
step knowingly.

## 5. Adoption criterion of the one held-out look (declared before any held-out number)

The look runs the chosen rule (final shares) and R0 on the v4 held-out season panels (June-December 2018-2025, every
scored cell), with today's cell levels, and the W1 event assembly (87 independent slides). The rule is confirmed only if
both conditions hold:

1. Burden: in every region, season (monsoon, post-monsoon) and level, the held-out share of district-days at L or above
   is at most 1.5 x its development (leave-one-year-out) share.
2. Coverage: at every level and in both readings (`same_day`, `within_1_day`), the independent slides the rule leaves
   uncovered compared with R0 on the same held-out days are at most q x 87 + 2 x sqrt(87 q (1 - q)), where q is the
   development share of events the rule loses against R0 (June-December pooled).

The declared numbers are written to `reports/phase8_district_cap.json` (`heldout_criterion`) before the look, and the
look reads them from there. The look is the lead's, once. It refuses if its result file exists. A failed look is
reported and nothing is tuned after it. A confirmed rule goes to a reviewed wiring step, a change of the published
district messages, after the user's yes. January-May has no held-out panels and stays development-only.

## 7. Amendment after the development curve, before any held-out number (2026-11-17)

The declared choice of section 4 was applied as written and found no Warning+ or Emergency cap on the ladder that keeps
90% of R0's within-1-day coverage. Even the gentlest caps (Warning+ 25%, Emergency 10% of district-days) lose more. The
chosen rule therefore caps Watch+ only (F1, 50%) and leaves Warning+ and Emergency at any cell
(`data/processed/alerts/district_cap/fit.json`). That rule barely changes what an officer receives. So that the user has a
real choice, one alternative is added now, before any held-out number:

- **alternative**: family F1, caps Watch+ 50%, Warning+ 25%, Emergency 10% of district-days, the gentlest cap of each
  level's ladder. It was picked from the development curve and is labelled so.

Both rules carry the criterion of section 5, with their own development values. `reports/phase8_district_cap.json`
(`heldout_criteria.declared` and `heldout_criteria.alternative`) holds them. The study still has ONE look: the command
`python -m aetherguard.verify.district_cap heldout --rule <declared|alternative>` refuses if any look of this study
exists. Which rule gets the look is the user's choice, through the lead, because it is a cost-ratio choice.

The first step of every curve also gets its cost ratio against R0. That is reporting only and changes no choice.

## 6. Not in scope

Changes to the cell levels, wiring, message text, and the forecast leads.
