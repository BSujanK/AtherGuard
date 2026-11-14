# Alert-engine parameters on IMERG-era data (phase 8, development only)

The six data-derived alert-engine parameters again, on the pair of products the live run compares (IMD against IMERG, gauges against IMERG), with the percentiles and weighting of `alerts.derive` unchanged. The hysteresis and `uncertain_high` values are copied from `alert_config_v3.json`.

## Development proxy

- imd: IMD final grid at the live sampling point (nearest 0.25 degree point moved -1 column(s), imd_lon_offset_columns), standing in for the IMD real-time grid (same product family; no real-time archive exists for 2007-2017)
- satellite: IMERG Late on the IMD day at the cell's pixel (irain_acc_1 / irain_acc_3)
- stations: |integ_trw_rain_1 - irain_acc_1| (trust-weighted gauges against IMERG)

Rows: 400,000 weighted universe cell-days, 361,156 with both sources, 90,887 with a usable station, 38,494 wet station cell-days.

## Old and new values

| parameter | v3 (IMD final vs CHIRPS) | v4 (IMD vs IMERG proxy) |
|---|---|---|
| `dis_ratio_lo` | 0.1248 | 0.1483 |
| `dis_ratio_hi` | 13.47 | 5.207 |
| `heavy_acc1_mm` | 32.51 | 31.32 |
| `heavy_acc3_mm` | 79.05 | 80.48 |
| `agree_abs_mm` | 3 | 4.178 |
| `agree_rel` | 0.6834 | 0.7312 |

## Is the proxy valid?

Share of cell-days outside the disagreement range (expected 10% on the data a range was derived on):

| range | development proxy, all months | development proxy, live months | live IMD real-time vs IMERG |
|---|---|---|---|
| v3 | 5.3% | 4.7% | 3.2% |
| v4 | 10.0% | 8.1% | 5.0% |

Live: 563,958 cell-days on 18 published days whose IMD file of day D was there (months [10, 11]).

## Effect on levels

Confidence feeds the blind-escalation rule (a cell that is not High and sees heavy rain in any source is raised to at least Watch), so these values can change levels, not only confidence. The live configuration keeps alert_config_v3.json until that effect has passed its gate; the scratch replays that measure it are in the live-chain ledger.

## Caveats

- IMD final has more gauges than IMD real-time; the live pair can disagree more often than the proxy.
- The live check covers the few published days with a day-D IMD file (afternoon runs), October-November only.
- Development data only; nothing here was evaluated on held-out years.
