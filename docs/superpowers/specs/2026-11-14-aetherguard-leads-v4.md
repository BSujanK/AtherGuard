# W7: the forecast leads on the adopted model v4

Status: spec, written 2026-11-15 before any lead-skill number of a candidate (agent leads-v4, branch `sota-leads-v4`).
Roadmap workstream W7 (`2026-11-02-aetherguard-accuracy-roadmap.md`). Protocol v3 applies.

## 1. The problem

Today's alerts (lead 0) are scored by v4 (41 inputs: v3's rain inputs, six rain-intensity inputs lagged one IMD day, nine
static inputs). The forecast leads D+1..D+3 are scored by v3 on forecast rain (`configs/live_run.yaml`: `model_config` v3,
`lead0_model_config` v4). On 2026-11-14 lead 0 had 113 Emergency cells and the day-2 forecast 246 (run.json of that day).
Two defects: the leads use a different and weaker model than today, and the leads score the ensemble-mean rain, although
a nonlinear model applied to a mean is not the mean of the model over the ensemble.

## 2. What a forecast can supply (Task 1, `reports/phase8_leads_v4.md` part 1)

v4 at lead L reads the intensity of IMD days D+L-3..D+L-1. Days before D are complete IMERG Late days (lead 0 reads them
already). Day D has closed at 03:00 UTC but its Late half-hours are not out at 11:00 IST: the first 44 IMERG Early
half-hours are (`imerg_hh --live-window`). Days D+1 and D+2 (leads 2 and 3) must come from forecast rain. The only
sub-daily forecast the project keeps is GFS at 3-hour steps (the live run's cycle files f003..f096). ECMWF is stored as
IMD-day totals (HRES, ensemble mean and 10th/50th/90th percentiles; members not kept). From 3-hour blocks the 3- and 6-hour
maxima and the wet hours can be formed; the 1-hour maximum cannot, and the 3-hour maximum stands in for it before mapping.
v4 never saw a missing intensity input in training (0 NaN in every development table), so no candidate hands it a NaN.

## 3. Candidates (pre-declared; nothing else is compared for adoption)

All three use the forecast rain of the current selection (`reports/forecast_selection.json`: D+1 GFS, D+2 ECMWF ensemble
mean, D+3 ECMWF ensemble mean bias-corrected; GFS when ECMWF is missing), the post-model rules and alert configuration of
the run, and the widening factors of the run.

* **(c) incumbent**: v3 (`model_config`) on that rain, as today.
* **(a) v4 point**: v4 (`model_v4_live`) on the same rain, plus
  - intensity window of lead L from the sources of section 2: Late as it is; the Early day D and the GFS days mapped onto
    IMERG Late's distribution by frequency-matched quantile curves (`forecast_map.fit_curve`) per field, region and day
    offset, fitted on training-only days: Early on June-September of the development years 2016 and 2017; GFS on
    June-September 2021 (GFS has no archive in the development years; 2021 is used for no other purpose);
  - the nine static inputs joined at the cell as for lead 0.
  If any day of any lead's window is missing, every forecast lead of that run is scored by the incumbent and run.json says
  why (no NaN reaches v4).
* **(b) v4 expected risk**: as (a), except that at a lead whose rain is the ECMWF ensemble the published risk, interval and
  ensemble columns are the expectation over the ensemble instead of the model at the ensemble mean. The members are not
  kept, so the expectation is the three-point quadrature over the stored 10th / 50th / 90th percentile fields with weights
  0.3 / 0.4 / 0.3 (Swanson's rule), each scenario mapped as the mean is mapped at that lead; intensity is the same in every
  scenario (GFS is deterministic). The scorer loops over scenarios one at a time (memory-safe); the same loop takes 51
  members once the ingest keeps them (not part of this change). The explanation (`shap_json`) stays that of the mean-rain
  features; the audit re-scores every scenario (`scenarios_D<k>.parquet`).

Diagnostics, never adopted: (a-oracle) v4 with the observed Late intensity of the forecast days, the ceiling of any
intensity forecast; (a-raw) (a) without the quantile maps.

## 4. Comparison on development and archive data (no held-out event is read)

* **E1 archive consistency.** June-September issue days whose GFS 3-hour archive exists and which no fit used (2022 now;
  2023 and 2024 once fetched), a seeded random sample of 2,536 candidate cells (seed 20261115; drawn without any event
  location). Reference: the published v4 level of the target day from observed features (lead 0 as the live run computes
  it: Late lag-1 intensity, static inputs, observed rain; point level, `uncertain_high`, rain cap). Per lead and candidate:
  agreement with the reference level, within one level, recall and precision of reference Warning+ and Emergency, burden
  by level (share of cell-days at Watch, Warning, Emergency, candidate and reference), and calibration of lead risk against
  the later lead-0 risk (mean reference risk by decile of lead risk). The incumbent is also compared with the v3 reference.
* **E2 live replays.** Every archived live day from 2026-10-14 (the first GFS cycle with its 3-hour files) to 2026-11-14,
  backtest mode, scratch live_dir only: lead levels of (c), (a), (b) beside the replay's own lead 0 of the target day and
  beside what was observed; audit violations 0 on every day (the audit re-scores every lead). These days are outside the
  validated season (June-September).
* Caveats stated with every number: E2 is post-monsoon; E1 measures consistency with the model's own later view, not
  slides; ECMWF has no archive before 2023, so E1 on 2022 uses the GFS fallback at every lead.

The candidate for the look is the one with the higher E1 Warning+ recall of the reference at lead 2 among (a) and (b),
provided its burden by level is within 20% of the reference's at every lead; if neither meets that, no look is taken and
the evidence goes to the lead and the user.

## 5. The held-out look (pre-declared, ONE look)

Can the history support it? Held-out slides need archived forecasts of their days. The GFS archive (AWS, public, no
account) exists from 2021; ECMWF open data from 2023. The 2018 season (56 of the held-out records) has no archived forecast
on any source the project uses. The look is therefore restricted to the held-out events (licence-clean W1 assembly) dated
June-September 2021-2024; phase7_heldout_expanded counts 24 records in the June-December panels of those years, so the
look has very little power and ties are the expected outcome. It needs the GFS 3-hour archive for 2022-2024 (fetch
resumable, section 7).

Criterion (decided on the W1 assembly; assembly v2 reported beside it, by country, with and without BIPAD, deciding
nothing): the chosen candidate against the incumbent leads, each lead burden-matched per season to the incumbent's
realised Warning+ and Emergency shares of that lead (the candidate's cell-days ranked by its own risk, tie-broken as in
`hazard.v4_int`), independent-slide detection where lead L detects a slide of day X when the forecast issued on X-L puts
a cell within tolerance at the level: for each lead 1, 2, 3, tolerant and cell-exact, Warning+ and Emergency (12 rows),
not lower in any row and higher in at least one. Otherwise the incumbent stays.

If the look cannot be taken (no archived forecast for an event day, or the fetch is not allowed), the switch rests on the
evidence of section 4 for the lead and the user to judge: v4 leads reproduce the later lead-0 v4 levels better than v3
leads do (E1 agreement and Warning+ recall at every lead, E2 the same on the live days), with burden by level within 20%
of the reference, and audit 0 on every replayed day.

## 6. What changes where

Branch `sota-leads-v4` only. `configs/live_run.yaml` gains `lead_model_config` (absent: the incumbent, `model_config`)
and a `lead_intensity` block (maps file, roots, `expected_risk`). Anything that changes published lead levels is a model
change and is merged by the lead only after the user's yes. The main tree is not touched.

## 7. Resumable commands

* GFS 3-hour archive: `python -m aetherguard.live.lead_intensity fetch-gfs --start 2021-06-01 --end 2024-09-30 --workers 8`
  (skips written days).
* IMERG half-hourly days of the study: `bash tools/leads_v4_fetch_imerg_hh.sh`.

## 8. Amendment 1 (2026-11-16, before any held-out number): how the look is computed

* Code: `python -m aetherguard.live.leads_v4_heldout score | preflight --candidate X | heldout --candidate X`
  (`src/aetherguard/live/leads_v4_heldout.py`, tests `tests/test_live_leads_v4_heldout.py`).
* Panels: one per lead, cells = the held-out reference (the 2018 operational panel's cells, in its order), one column per
  target day T = D + L for every June-September issue day D of 2021-2024; a column is scored where the lead's forecast rain
  and every day of its intensity window exist and both models score the cell. 2021 is the fit season of the GFS intensity
  maps (rain only, no event); it stays in the look and this is stated with the result.
* Levels: the incumbent's published lead level as E1 computes it (v3 point level, `uncertain_high` of the rules, rain cap,
  no widening); the candidate burden-matched per season and lead to those realised shares by `hazard.v4_int.match_burden`
  (risk, then raw score, then the seeded tie key).
* Both a and b are scored by `score` (it reads no event); only the candidate chosen by section 4 enters `preflight` and the
  look. The decision is section 5's 12 rows on the W1 assembly (`verify.heldout.load_event_table`, years 2021-2024);
  assembly v2 beside it (all records, without `bipad_nepal`, India only).
* E1 years: 2022, 2023 and 2024 (2021 is the GFS fit season). The look is taken only by the lead.

## 9. Amendment 2 (2026-11-16, before the full E1): tie-break of the choice

Section 4's choice between (a) and (b): on equal lead-2 Warning+ recall, (a) is chosen (the simpler; (b) equals (a) on
every issue day without the ECMWF ensemble). The burden test is on the Watch, Warning and Emergency shares. The choice is
computed by `leads_v4_study.look_choice` from `reports/phase8_leads_v4_e1.json`, never by hand. Only a 23-issue-day smoke
of E1 (2022, scratch, not reported) had been run when this was written.
