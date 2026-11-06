# W3: rain-intensity inputs (pre-declared)

Date: 2026-11-06. Status: pre-declared before any result. Roadmap §4 W3 (with the model retrain of W6 limited to the
new inputs). Pilot evidence: half-hourly IMERG V07 domain subsets by OPeNDAP, about 89 KB and 0.63 s each at 4
connections, 0 failures in 56; Early (HHE) lags about 4.6 h, Late (HHL) about 14.6 h; no server-side max product.

## 1. Inputs

- Per 0.1-degree IMERG pixel and IMD day (03-03 UTC): maximum 1-hour, 3-hour and 6-hour rain (mm) from the 48
  half-hourly fields (rolling sums of 2, 6 and 12 half-hours, within the IMD day), and the wet duration
  (half-hours >= 0.1 mm/h). Training and held-out use Late (HHL); the live run uses Early (HHE).
- Features (per 0.05-degree cell, mapped like the daily IMERG): `iint_max1h_1`, `iint_max3h_1`, `iint_max6h_1` (the
  day), `iint_max3h_max3d` and `iint_max6h_max3d` (max over the last 3 IMD days), `iint_wet_hours_1`.
- Live gap: at 11:00 IST the newest HHE half-hour is about 00:30-01:00 UTC, so the IMD day closing at 03:00 UTC lacks
  its last 4 half-hours. The live features use the half-hours available; the train-serve gap is measured on 2024 by
  computing the training-style and the truncated features for the same days, and reported. If the truncated 3-hour
  maximum differs from the full one by more than 20% (median relative error over wet cell-days), the live run uses the
  previous complete IMD day for the intensity features (declared lag 1 day) and the model is trained the same way.

## 2. Model (one challenger)

v4-int = the v3-live configuration (same folds, seeds, 20-member ensemble, per-region isotonic calibration, monotone
constraints) plus the six intensity features, each constrained non-decreasing. No other change.

## 3. Pre-declared adoption criterion

Development (year-blocked CV 2007-2017, protocol v2): pooled out-of-fold FA@90 of v4-int not worse than v3's by the
paired bootstrap (the 95% CI of the difference includes or favours v4-int). If it fails, v4-int is not evaluated on the
held-out set.

Held-out (once, POOLED 2018-2025, 87 independent slides, the W1 assembly), with v4-int's levels burden-matched to v3's
realised shares per season (the W1 rule): v4-int is adopted only if its independent-slide detection at Warning+ and at
Emergency is higher than or equal to v3's, both tolerant and cell-exact, and higher in at least one of the four. Adoption
replaces v3-live in the live run in a separate, reviewed step (new thresholds from v4-int's card; the train-serve rule of
§1 applied).

## 4. Outputs

Half-hourly-derived daily fields under `data/processed/imerg_intensity/`; features in the feature store under a new
group; `reports/phase7_rain_intensity.{md,json}`.
