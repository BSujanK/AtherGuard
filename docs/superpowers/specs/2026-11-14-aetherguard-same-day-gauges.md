# AetherGuard: same-day rain gauges for the integrity engine (SOTA round 2, workstream gauges-isd)

Status: spec, written before any validation number was computed (2026-11-15). Branch `sota-gauges-isd`.
Probe evidence: `reports/phase8_gauge_sources_probe.{json,md}`. Research prototype, not validated for issuing real
public warnings.

## 1. Problem

The integrity engine (`integrity.engine`, trained on the 140 GHCN-Daily stations of `configs/audit.yaml`) sees no
gauge on the run day: GHCN-Daily arrives 3 to 6 days late. The probe found two further facts that change the task:

1. NOAA ISD / Global Hourly and GSOD ended in August 2025 (no 2026 files in `noaa-isd-pds` or
   `noaa-global-hourly-pds`; GSOD 2026 files do not exist). The task's first candidate cannot be used live.
2. Since then GHCN-Daily takes these stations from the Synoptic Summary of the Day v2 (source flag `2`), and for them
   almost every monsoon-2026 value is 0.0 with measurement flag `H` ("station reported 0 or the amount could not be
   calculated, but precipitation was noted"). The live engine has been reading those as dry days.

The raw SYNOP reports of the same stations are on the WMO GTS within about an hour of observation, and the US
National Weather Service republishes the GTS SYNOP bulletins without a key (a ring of 5-minute files kept about 25 h).
India's 03 UTC bulletins arrived there between 03:20 and 04:45 UTC on the probe day, before the 05:30 UTC run.

## 2. Station identity (no new stations in this change)

Every one of the 140 GHCN stations has a WMO index in `ghcnd-stations.txt` (columns 81-85). From 2020 to 2025 every
GHCN PRCP value of these stations has source flag `S` (GSOD), i.e. it is a daily summary of that station's own SYNOP
reports. A SYNOP IMD-day total of WMO station `w` is therefore an early observation of the SAME sensor as GHCN station
`id(w)`, on the same day basis (the day-basis experiment: gauge day = IMD day; ISD 2024 Dehradun: the GHCN value of
day d equals the 24-h amount reported at 03 UTC of d, e.g. 1-5 July 2024: 9.0/4.0/130.0/11.0/45.0 mm in ISD against
8.9/4.1/130.0/10.9/45.0 in GHCN, the differences being GSOD's rounding to 0.01 inch).

The engine needs, per station, the 2007-2015 wet-day climatology, the neighbour table among the 140 and the frozen
station splits. A station outside the 140 has none of these, and adding it changes every neighbour feature of its
neighbours: that is a retraining and a new engine evaluation, not part of this change. The smallest honest route,
taken here: same-day values for the stations GHCN already has, used as early observations of those sensors. The engine,
its thresholds, its climatology and its station set are unchanged. More stations (the probe lists the SYNOP stations
within 100 km of the scored cells) are a separate decision.

## 3. From reports to an IMD-day total (`ingest.synop`)

IMD day D = 03:00 UTC of D-1 to 03:00 UTC of D. Decoded groups: section 0 `AAXX YYGGi_w`, `IIiii`; section 1 `i_R`
and `6RRRt_R`; section 3 `6RRRt_R` and the regional `7R24R24R24R24`. Code tables as in the module doc (RRR 990 = trace
= 0.0 mm; R24 9999 = trace).

Period of a group: its t_R; a regional period (`/` or `0`) at an Indian station (blocks 42, 43) means "since the latest
03 UTC" (24 h at 03 UTC). This is the practice the ISD 2024 decoding shows (AA1 periods 03, 06, ..., 24 h at 06, 09, ...,
03 UTC, amounts cumulative), and V1 below tests it on raw reports. Other blocks get no regional rule: their regional
groups are unused.

Total of station s on IMD day D, in this order:
1. The report of s at 03 UTC of D (highest-priority version: a correction `CCx` outranks the original and its
   retransmissions `RRx`; versions of equal priority that disagree give no value):
   a 24-h amount (`7R24`, `6RRR4`, or a regional India group) is the total; two different 24-h amounts in one report
   give no value; `i_R = 3` (groups omitted because the amount is zero) gives 0.0; `i_R = 4` (not observed) gives no
   value.
2. Without a usable 03 UTC report: the sum over a chain of non-overlapping accumulations with explicit periods that
   covers 03 UTC D-1 to 03 UTC D exactly (fewest pieces). Accumulations that overlap are never added, so nothing is
   counted twice; India's cumulative groups all start at 03 UTC and so never form a chain (their only complete
   period is the 24-h one at 03 UTC). A partial chain gives no value.
3. Otherwise no value. A missing report, a NIL report or an unreadable group is missing, never zero.

Every value carries `how` (24h_group, ir3_zero, partition) and every missing day its reason, in the store.

## 4. Merge with GHCN-Daily, and the GHCN `H` zeros

Per station-day of the engine window: the SYNOP total when there is one, else the GHCN value. A GHCN value of 0.0 with
measurement flag `H` is not a measured zero; with `ghcn.h_zero_as_missing: true` it is treated as missing. Both keys
default to off on this branch; the replays report each separately.

## 5. Ingest and live source

* Ingest `python -m aetherguard.ingest.synop_store collect` (resumable, logged to `logs/synop_collect.log`,
  manifest-tracked): downloads the NWS ring files not yet stored (name + time from the ring's `ls-l`), keeps them under
  `data/raw/synop/nws/<YYYYMMDD>/`, appends the decoded reports with their arrival time (the ring file time) to
  `data/processed/synop/reports.parquet` (deduplicated). Run it at least once a day (the ring keeps about 25 h).
  `backfill-ogimet` fills past days from OGIMET's archive for validation and replays only (section 8).
* Live source `synop` (optional source, never a failed run): reads the ring at run time plus the local store, and
  returns IMD-day totals for the 140 stations over the engine window. Declared latency `latency_h` (hours after the
  end of IMD day D that its total exists), set from the probe's measured arrivals. In backtest mode a report is usable
  only if its arrival time is at or before the cut-off; a report without an arrival time (OGIMET backfill) is treated
  as arriving at the end of its IMD day plus `latency_h`.
* Wiring (`configs/live_run.yaml`, key `synop.enabled`, default false): the engine gets the merged gauges; run.json
  `integrity` reports stations observed on D before and after the merge.

## 6. Validation (declared before measuring)

Metrics, on station-days where both values exist: n; bias = mean(SYNOP - reference); Pearson r; wet-day hit rate =
share of reference days >= 1 mm that SYNOP also has >= 1 mm; false-wet share = share of reference days < 1 mm that
SYNOP has >= 1 mm; share within the engine's station-agreement tolerance, |a - b| <= max(3.0 mm, 0.683 x max(a, b))
(`alert_config_v3.json` agree_abs_mm, agree_rel).

* V1 (decides whether the rule is fit to wire): raw SYNOP reports of July 2024 (OGIMET archive) through section 3,
  against GHCN-Daily of the same station and day (source `S`, the period when GHCN-Daily is a SYNOP summary).
  Criterion: within tolerance >= 0.95 AND r >= 0.95 AND wet-day hit rate >= 0.95 AND |bias| <= 0.5 mm. Coverage
  (share of GHCN station-days that get a SYNOP total) is reported, not a criterion.
* V2 (descriptive, the replayed days): the same metrics against GHCN-Daily 2026 (source `2`; expected to fail on wet
  days because of the `H` zeros, which is the finding, not a defect of the rule) and against the IMD real-time grid at
  the station's nearest point (the engine's own live `imd` reference). No criterion: November is dry and the reference
  is gridded.
* Run-day coverage: stations of the 140 with a total for IMD day D at the 05:30 UTC cut-off, per replayed day.

If V1 fails, nothing is wired (the key stays off) and the report says why.

## 7. Replays (Task 3)

At least 6 recent real days in backtest mode, scratch live_dir (never `data/live`), code of this branch: `before`
(synop off) and `after` (synop on), and `after_h` (synop on + `ghcn.h_zero_as_missing`). Per day: stations observed on
D, engine flags and trust, confidence counts, levels, blind escalations, audit violations. Station information enters
the alert engine through the confidence logic (station agreement can make a cell High; flagged stations make it
Degraded; a heavy station reading feeds the blind-escalation rule, which raises a level to Watch): **if any published
level changes, it is a model change**, stated as such; the lead decides.

## 8. Licences and decisions for the user

NWS: US Government work (public domain); coded reports remain subject to WMO Resolution 40. OGIMET: "for informational
purposes", "not to be used in any mission-critical application", link to the source required: used here for validation
and scratch replays only; using it live is the user's decision. India-WRIS and IMD AWS/ARG portals need registration:
listed, not used.
