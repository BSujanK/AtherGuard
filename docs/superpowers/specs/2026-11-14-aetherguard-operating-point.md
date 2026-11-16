# AetherGuard operating point: options for the user (round 2, workstream `burden`)

Date: 2026-11-14 (written 2026-11-15/16). Status: the user left the choice to the lead. B_balanced went to its one
held-out look (2026-11-16) and was NOT confirmed: Western Ghats monsoon Emergency burden 3.38% against a limit of
3.30%, and tolerant Watch+ lost 4 slides against A where 2.5 were allowed
(`data/processed/alerts/operating_options/heldout_B_balanced.json`). Today's levels (A) stay live. B is not re-tested or
tuned on these events. Nothing is wired into the live run.
Branch `sota-operating-point`. Results: `reports/phase8_operating_point_options.{json,md}`, rendered from
`data/processed/alerts/operating_options/` by `python -m aetherguard.verify.operating_options report`.

## 1. The problem

Today's levels are set by detection: the v4 card's Watch, Warning and Emergency thresholds caught about 90%, 75% and
50% of the development positives. How often a level fires was never a design input. On the held-out June-December
seasons, 36-44% of cell-days sit at Watch or above, 13-18% at Warning or above and 5-8% at Emergency
(`reports/phase7_static_susceptibility.md`, burden table). A level that fires on one cell-day in fifteen does not
mean "emergency" to the person who receives it. The W2 attempt (`reports/phase7_operating_point.md`) kept detection fixed
and saved under 10%, and was not adopted. A real cut in alerts costs detection. How much detection to trade for how much
less alerting is the user's call (roadmap section 5, "cost ratio of a miss versus a false alarm"). This spec states the
options and how each would be confirmed.

## 2. Data and protocol

- Development only: v4 out-of-fold panels of 2007-2017 on every scored cell (36,792), June-December and January-May
  (`live.oof_v4_full`; the refitted fold models reproduce the card's out-of-fold recall at Watch, 0.917617237008872).
  Events: the in-domain development positives of every month (train and validation samples).
- No held-out event outcome was read to build or choose anything here. The held-out numbers quoted in section 1 come
  from published reports.
- Levels on the panels: the point level is the risk against the thresholds. The published level adds `uncertain_high`,
  the rain cap and hold release of `post_rules_v3.json` and the hysteresis of `alert_config_v3.json`, exactly as the live
  chain does except for the blind-escalation rule, which needs the live IMD comparison.
- Detection: cell-exact (own cell, event day) and tolerant (10 km, 1 day). 95% intervals come from resampling
  independent slides. The chance floor of tolerant matching is reported at every burden.

## 3. The options (fixed on the development trade-off curve, before any held-out number)

Each capped option sets, in every region (Himalaya, Western Ghats) and season (monsoon June-September, post-monsoon
October-December, rest January-May), the lowest risk threshold at which the level fires on at most the declared share of
development cell-days (point level). It is never lower than today's threshold, so a cap only removes alerts.

| option | Watch+ cap | Warning+ cap | Emergency cap |
|---|---|---|---|
| A_detection_first | today's card | today's card | today's card |
| B_balanced | 20% | 6% | 2% |
| C_rare_emergency | 10% | 3% | 1% |

The thresholds are written per option to `data/processed/alerts/operating_options/levels_<option>.json`, in the card
format (`alert_levels.<level>.risk`, `risk_by_region`, one block per season), never into the frozen card.

## 4. District aggregation

Boundaries: geoBoundaries gbOpen. India ADM2: Open Data Commons Open Database License 1.0 (Pathways Data,
lgdirectory.gov.in, 2021). Nepal ADM2: Public Domain (Wikimedia Commons, 2006, the 75 districts in use before 2015).
Bhutan ADM1: Creative Commons Attribution 3.0 (the 20 dzongkhags). The licence lines are copied from the geoBoundaries
API into `data/processed/districts/districts.json`. The files and the cell-to-district table stay under `data/`. A cell
takes the district that holds its centre. Where two countries' polygons overlap, the cell's own country wins. A cell
inside no polygon takes the nearest district of its country within 5 km.

Rule candidates, kept few: a district is at level L when (a) any of its cells is at L or above, (b) at least 3 cells or
10% of its scored cells are, or (c) at least 5 cells or 25% are. Pre-declared choice per option: the candidate with the
fewest Warning+ district-days among those that keep at least 90% of the development events the any-cell rule puts inside
an alerted district, at every level (June-December pooled over the strata). Ties and the no-candidate case go to (a).

## 5. The confirming held-out look (one per study, for the option the user chooses; taken by the lead)

Command: `python -m aetherguard.verify.operating_options heldout --option <name>`. It reads the v4 held-out season panels
(`data/processed/alerts/v4_seasons`, June-December 2018-2025) and the W1 event assembly (87 independent slides). It
refuses if any `heldout_*.json` of this study exists, so only one option is ever looked at.

Pre-declared criterion. The values are written into `reports/phase8_operating_point_options.json`
(`options.<name>.heldout_criterion`) before any look, and the command reads them from there:

1. Burden: in every region, season (monsoon, post-monsoon) and level, the held-out published share is at most 1.5 x the
   development published share of that option.
2. Detection, option A: at every tolerance (tolerant, cell-exact) and level, the held-out independent slides detected
   are at least the pooled June-December development detection share x 87, less 2 binomial standard deviations
   (2 x sqrt(87 p (1 - p))).
   Detection, options B and C (paired with A on the same held-out days, so the regional mix of the held-out events and
   the catalogue bias cancel): at every tolerance and level, the slides the option detects fewer than A are at most the
   development share of events it lost against A x 87, plus 2 binomial standard deviations (2 x sqrt(87 q (1 - q))).
   The look computes A's levels on those days for this comparison only. It is not a separate look at A.

The option is confirmed only if every condition passes. A confirmed option can go to wiring, which is a separate,
reviewed change of the published levels and so a model change. A failed look is reported and nothing is tuned after it.
January-May has no held-out panels, so the rest-of-year rows cannot be confirmed by this look. They stay
development-only and are flagged as outside the validated season, as today.

## 6. Recommendation

See `reports/phase8_operating_point_options.md`, section "Recommendation", rendered from the result files.

## 7. Not in scope

Wiring, any change to `configs/live_run.yaml` or the frozen card, the blind-escalation rule, and the forecast leads
(scored by v3).
