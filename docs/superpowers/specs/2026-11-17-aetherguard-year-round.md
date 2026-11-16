# AetherGuard year-round alerts: per-season treatment outside June-September (round 2, workstream `year-round`)

Date: 2026-11-17. Status: development study; held-out look declared here, not taken. Branch `sota-year-round` (from
`w5-static-susceptibility` 18955b2 with `sota-operating-point` e6b96bc merged in for its full-year development panels).
Code: `src/aetherguard/verify/year_round.py`. Results: `data/processed/alerts/year_round/`, rendered into
`reports/phase8_year_round.{json,md}`. Nothing is wired into the live run. Any change of the out-of-season levels is a
model change and needs the look below, a reviewed wiring step and the user's yes.

## 1. The problem

The v4 model was trained on every month, but the alert levels (absolute risk thresholds, the same in every month), the
post-model rules (rain cap, `uncertain_high`, hold release) and the hysteresis were chosen and tested on June-September
only. Since 2026-11 every lead outside June-September carries `outside_validated_season`
(`reports/phase8_season_validity.md`). The live burden outside the monsoon looked high and the operating-point study found
that frequency caps do not explain it (`reports/phase8_operating_point_options.md`, "Outside the monsoon"). Two questions:

1. Why is the out-of-season burden high, and does a level mean the same thing outside the monsoon as inside it?
2. Is there a per-season treatment, chosen on development data only, that makes the out-of-season levels trustworthy
   (fewer alerts that do not verify) without losing detection, and can the held-out data decide it?

## 2. Data and protocol

- Development only for every choice: the out-of-fold v4 panels of 2007-2017 on every scored cell (36,792), January-May
  and June-December (`data/processed/alerts/oof_v4_full/`, written by `live.oof_v4_full`), and the in-domain development
  positives of every month (train and validation samples).
- Levels on the panels: the live chain as the live run reads it (`alert_config_v3.json` hysteresis, `post_rules_v3.json`
  rain cap and hold release, `uncertain_high` on the ensemble upper bound), without the blind-escalation rule (it needs
  the live IMD comparison). January-May starts each year cold.
- Seasons: monsoon June-September, post-monsoon October-December, rest January-May (`alerts.frequency_levels.SEASONS`).
- Detection: cell-exact (own cell, event day) and tolerant (10 km, 1 day), counted in independent slides (records
  within 10 km and a day merged, `verify.heldout.event_clusters`).
- The live days (`data/live/*/alerts.parquet`, read only) and the replays of `reports/phase8_live_replays.json` are
  described, never used to choose anything.
- Exploration before this spec: scratch runs on the same development panels (2026-11-17, `ops/scratch/year-round/`) showed
  the size of the effects and set the candidate grid. No held-out outcome was read.

## 3. Diagnosis (`year_round panels`, `summarise`)

Per region and season, under today's chain: the share of cell-days at each stage (point level, `uncertain_high` added
after the rain cap, hold inflation by the hysteresis), the share of cell-days whose 7-day rain passes the rain cap, the
share of development events under the rain minimum, the development hits per 100,000 alert cell-days at each level
(precision against the catalogues), and the tail calibration E/O (summed risk of the alert cell-days over the cell-exact
hits). The Himalaya also by elevation band (snow at altitude would show as a fall of precision at high bands only), and
the per-year monthly shares to place the live months among the development years.

## 4. Candidates and the selection rule (declared before the selection was run)

Out of season only. June-September is today's chain in every candidate, cell-day by cell-day.

- Per-season risk scale `m` in {1, 1.25, 1.5, 2, 3}: the Watch, Warning and Emergency thresholds of both regions are
  multiplied by `m` in that season (the same as dividing the risk by `m`: a per-season recalibration). One scale per
  season, shared by the regions (the Western Ghats have too few out-of-season events to fit their own).
- `uncertain_high` out of season: on (today) or off (the raw level is the point level).

Ten candidates per season; October-December and January-May are chosen separately (their levels do not interact: the
January-May panels start cold, and the October-December levels depend only on their own thresholds after a monsoon that
no candidate changes).

Rule, per season, on all 11 development years: a candidate passes when, against today, it loses at most
`max(1, floor(0.03 x the season's development slides))` independent slides at every level (Watch+, Warning+, Emergency)
and both tolerances. Of the passing candidates the one with the fewest Emergency, then Warning+, then Watch+ published
cell-days wins; ties go to the smaller scale, then to `uncertain_high` on. If none passes, today's levels stay. The rule
is coded in `year_round.choose` (constants `LOSS_MIN = 1`, `LOSS_SHARE = 0.03`), committed in 4fc6ce4 before the
selection was run.

Honest estimate: leave one development year out (the rule re-chosen on the other ten years, applied to the year left
out), summed over the years. The chosen treatment is written to `year_round/levels_year_round.json` (thresholds per
season and region; never the frozen card).

## 5. Ground truth outside the monsoon

The W1 held-out assembly (2018 catalogue, W1 reported, `test_sparse`; licence-clean, deciding) has 87 independent
slides, almost all in June-September. The counts per region and season are computed by `summarise` (dates and cells only)
and printed in the report, beside assembly v2 (frozen, `data/processed/heldout_v2`) with and without the Nepal BIPAD
register (no stated licence: local only, never deciding). The report also states what a look can decide: the one-sided
95% upper bound of the loss share when no W1 slide is lost, and the chance that a treatment losing 10% of slides loses
at least one W1 slide.

January-May has no held-out panels: `alerts/v4_seasons` covers June-December 2018-2025, and the half-hourly IMERG files
for January-May 2018-2025 are not on disk (1 January to 21 May missing, 141 of 151 days, in each of the years checked: 2018, 2021, 2025). Scoring them would need about 1,100 days
of downloads, for one W1 slide. January-May therefore stays development-only.

## 6. The held-out look (declared here; the lead's, once)

Command: `python -m aetherguard.verify.year_round heldout` (after `preflight`). Season: October-December 2018-2025 on the
v4 held-out season panels. The treatment is the selected one, identified by the sha256 of `levels_year_round.json`
written into `reports/phase8_year_round.json` (`heldout_criterion`) and checked again before the look. The command
writes a started marker first and refuses a second look.

Criterion (the development values are filled in by `report` from the result files before the look):

1. Burden (decides). For every region and level whose development published share falls by at least 10% under the
   treatment, the held-out published share of October-December, paired with today's levels on the same days, falls by
   at least half the development reduction.
2. June-September published levels are identical to today's on every held-out cell-day (0 differing).
3. Detection veto (W1). Every W1 October-December slide that today's levels detect at a level and tolerance is detected
   by the treatment at that level and tolerance. With the few W1 slides this veto cannot show that detection is not
   worse; it can only stop adoption. The report gives its power.
4. Beside, not deciding: the same paired detection on assembly v2 with and without BIPAD.

Adopt only if 1, 2 and 3 pass. If the selection keeps today's levels in a season, that season has nothing to look at.

## 7. Not in scope

Wiring, `configs/live_run.yaml`, the frozen card, retraining v4, the blind-escalation rule, the forecast leads (v3),
and the monsoon levels (the operating-point study owns them).
