# Post-model rules for model v4 (pre-declared)

Date: 2026-11-13 (written 2026-11-14, before any held-out number of this comparison). Status: pre-declared, development done,
held-out look not taken. Roadmap: `2026-11-02-aetherguard-accuracy-roadmap.md` protocol v3; structure of
`2026-11-06-aetherguard-w2-operating-point.md`.

## 1. Goal

Since 2026-11-13 lead 0 is scored by v4, but the post-model rules of spec 2026-10-14 section 11 (ensemble-agreement
minimum, rain trigger, hold windows, blind-hold limit, `post_rules_v3.json`) were chosen on v3's development out-of-fold
risk. Choose them again for v4 with the same method, and adopt them only if they do not make the published alerts worse
on the held-out set.

## 2. Method (development only, done)

- **Data:** v4's year-blocked cross-validation models, refitted by `burden.fold_models` on v4's development rows (they
  reproduce the v4 card's out-of-fold recall at Watch exactly: 0.917617237008872 on 789 positives,
  `data/processed/alerts/accuracy_hardening_oof_v4/oof_check.json`), scoring June-September 2007-2017 out of fold on the
  cells of the v3 study (every development-event cell plus the same seeded 5,000 universe cells), with v4's own inputs
  (training-style rain, the six intensity inputs at lag 1, the nine static inputs).
- **Rules:** `hardening_dev.run` unchanged (the pre-declared steps, candidates and adoption rules of section 11), with
  the v4 card's thresholds per region and `alert_config_v3.json`. `lead_uncertain_bound` is a forecast-lead parameter
  and the leads stay on v3, so it is copied from the v3 rules.
- **Result** (`reports/phase8_post_rules_v4.md`, `data/processed/alerts/post_rules_v4.json`): every parameter equals v3's
  except the blind-hold limit, H = 1 day for v4 against 2 for v3 (v4's Emergency retention two days later is 0.490, under
  the pre-declared 0.5). On development the two rule sets publish identical levels, because the blind-hold limit acts
  only on cell-days without a score.

## 3. Pre-declared adoption criterion (one held-out look)

Arms: the **incumbent** is v4 with the v3 rules (what is live today); the **candidate** is v4 with the v4 rules. Both use
the section 11 chain of `hardening_dev.season_levels` (uncertain_high on the re-centred bound, rain cap, hold release,
hysteresis, blind-hold limit) on v4's held-out season panels (`data/processed/alerts/v4_seasons`, June-December
2018-2025, training-style features), pooled as the W1 report assembles them (87 independent slides).

The candidate is adopted only if, POOLED, tolerant (10 km, 1 day) and cell-exact:

1. independent-slide detection at Watch+, Warning+ and Emergency is not lower than the incumbent's (a safety rule may
   cost no detection), and
2. Warning+ alert cell-days are not higher than the incumbent's.

**No-difference clause.** The preflight (`python -m aetherguard.live.post_rules_v4 preflight`, no event is joined with a
level) builds both arms on the pooled held-out cell-days and counts the cell-days on which they differ. If that count is
0, the look is NOT taken (the held-out set would be spent on identical levels; `heldout` refuses), the comparison is
reported as "not separable on the held-out panels", and the decision is the lead's on development evidence alone. The
held-out season panels are scored on every cell-day (scored share 1.0 in every `season_<year>_v4.json`), so this clause
is expected to apply: the arms can only differ during input outages, which the training-style panels do not contain.

Otherwise nothing is tuned after the look; the result is written once to `data/processed/alerts/post_rules_v4_heldout.json`
and `reports/phase8_post_rules_v4_heldout.json`.

## 4. Wiring (only after adoption, a separate reviewed step)

The live run reads one `post_rules` file for every lead. Adopting the v4 rules for lead 0 while the forecast leads stay on
v3 needs a `lead0_post_rules` key in the runner (not written) and the audit reading the rules each lead was scored with.
Until then `configs/live_run.yaml` keeps `post_rules_v3.json`.

## 5. Caveats

Ground truth after 2018 is very incomplete; tolerant matching has a high chance floor at Watch+ and Warning+; 87
independent slides is a small sample (one slide is 1.1 points of detection).
