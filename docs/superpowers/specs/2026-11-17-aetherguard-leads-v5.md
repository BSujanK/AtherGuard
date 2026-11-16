# W7b: the forecast leads on v4-static (leads v5)

Status: spec, written 2026-11-17 before any held-out number of this candidate (agent leads-v4, branch `sota-leads-v5`).
Follows `2026-11-14-aetherguard-leads-v4.md`, whose one look (2021-2024) did not adopt v4 leads
(`reports/phase8_leads_v4_heldout.md`). Protocol v3 applies.

## 1. Disclosure: where the idea comes from

The v4-leads look lost one tolerant Warning+ slide at leads 2 and 3 (22 to 21) while gaining Emergency and cell-exact
rows. Leads 2 and 3 are where v4's intensity inputs come from the GFS forecast. The design below removes those inputs. It
also rests on development evidence (section 2), but **the look's pattern suggested looking here**, so any number of this
candidate on 2021-2024 would be a second look at the same events. 2021-2024 is therefore reported beside the decision,
labelled as already looked at, and never decides.

## 2. The candidate (one, pre-declared)

**(s) v4-static at every forecast lead**: the W5 challenger `v4_static` (not frozen; its files are checksummed) (35 inputs: v3-live's 26 plus the nine
physical static inputs; no rain-intensity input), `data/processed/hazard/v4_static/models/v4_static` (fitted 2026-11-11 on
the development years; sha256 of `model.txt` and `card.json` recorded by the preflight), scored on the forecast rain of
the current selection with the run's post-model rules and its own card thresholds. Lead 0 stays v4.

Development and archive evidence behind the choice (no held-out event):
* Year-blocked CV 2007-2017, pooled OOF FA@90 (lower is better; `reports/phase7_static_susceptibility.md`): v3 0.1955,
  v4 0.1773, v4-static 0.1674; v4-static minus v3 -0.0282 [-0.0572, -0.0007]. On observed inputs v4-static is at least as
  good as v4 without any intensity input.
* Forecast intensity is weak (`reports/phase8_leads_v4_measure.json`): 3-hourly GFS max3h against IMERG Late correlates
  0.28-0.40 and, where Late reaches 10 mm, averages about a third of it.
* E1 (`reports/phase8_leads_v4_e1.json`): perfect intensity (a_oracle) instead of forecast intensity (a) raises lead-2
  agreement with the later lead-0 level by only 0.006, so most of a's consistency gain does not come from intensity.

Comparisons reported but not deciding: the incumbent (c, v3 leads) and the v4 leads (a).

## 3. The fresh held-out look: June-September 2025

Checked 2026-11-17 (`v5_feasibility`, counts and availability only, no level read): the GFS archive (AWS) and both ECMWF
open-data copies hold the 2025 June-September cycles the selection uses; IMERG Late 2025 is in the store. The
licence-clean W1 assembly has **3 records in 2025** (1 in June, 2 in August, all `reported`); assembly v2 adds 151 BIPAD
Nepal records in June-September 2025 (no stated licence: numbers only, decides nothing).

**Power.** At most 3 independent slides decide. The incumbent leads alert on about a fifth of the cell-days at Warning+,
so the tolerant rows will most likely tie at 3 of 3; only cell-exact and Emergency rows can move. The most likely outcome
is a tie everywhere, which keeps the incumbent. The look cannot show a small gain; it can only catch a gross loss.

**Criterion (decided on W1, June-September 2025 issue days, one look):** for each lead 1, 2, 3, the candidate's levels
burden-matched per lead to the incumbent's realised 2025 Watch+ / Warning+ / Emergency shares (`hazard.v4_int.match_burden`);
independent-slide detection, tolerant and cell-exact, Warning+ and Emergency (12 rows): not lower than the incumbent's in
any row and higher in at least one. Otherwise the incumbent stays.

Reported beside it, deciding nothing: 2021-2024 W1 (labelled "already looked at, second look on the same events"),
assembly v2 2025 (all records, without BIPAD, India only).

**Recommendation for the lead and the user, before the look:** with 3 slides this look is close to uninformative. The
options are (i) take it as declared (expected: incumbent stays), (ii) wait for a larger fresh set (a ground-truth
expansion of 2025, or the 2026 monsoon once its live forecasts are archived), or (iii) decide that 2025 serves only as a
no-harm check (not lower in any row) and adoption rests on the development evidence. Any change to the criterion must be
made and committed before the look; this spec declares (i).

## 4. Computation (fixed before the look)

* `python -m aetherguard.live.leads_v5_heldout score --years 2025,2021,2022,2023,2024` (heavy, resumable per year): per
  reference cell, issue day and lead, the incumbent's published lead level (v3 point level, `uncertain_high`, rain cap)
  with risk and raw score, and the candidate's risk and raw score, as `leads_v4_heldout` does. No event is read.
* `preflight`: burden matching per season and lead on 2025, event dates counted, panel and model checksums frozen.
* `heldout`: refuses a second look (its own result and started marker, separate from the v4 look's), scores the
  incumbent of each lead first, then marks the look started, then the candidate; decides by section 3 on 2025; then the
  beside sets.
* Inputs to fetch for 2025 (public, no account): the GFS daily archive (`ingest.gfs_build --archive`), the ECMWF
  archive days (HRES and ensemble). No intensity input is needed.

## 5. Live wiring

v4-static is not frozen or promoted. If adopted, `hazard.promote` copies it to a frozen live directory and
`lead_model_config` names it (a model with static but no intensity inputs needs no intensity window; the lead inputs
are then the static table only). Anything that changes published lead levels is a model change and waits for the user's yes.
