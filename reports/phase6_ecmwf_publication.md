# ECMWF open-data publication times

Last-Modified of the last needed step file in the public bucket ecmwf-forecasts (HTTP HEAD), 41 sample days (2023-06-01..2024-09-27, June-September 2023 and 2024). Latency = Last-Modified minus the cycle time; the daily run starts at 05:30 UTC (11:00 IST).

| cycle | product | stream | found | median h | p95 h | max h | newest file at (from max) | out before the run |
|---|---|---|---|---|---|---|---|---|
| 00Z of D | hres | oper | 41/41 | 7.12 | 7.92 | 7.92 | D 07:56 UTC | no |
| 00Z of D | ens | enfo | 41/41 | 7.88 | 8.77 | 8.79 | D 08:47 UTC | no |
| 18Z of D-1 | hres | scda | 41/41 | 7.15 | 7.22 | 7.22 | D 01:13 UTC | yes |
| 18Z of D-1 | ens | enfo | 41/41 | 7.89 | 8.20 | 8.20 | D 02:12 UTC | yes |
| 12Z of D-1 | hres | oper | 41/41 | 7.18 | 7.93 | 7.93 | D-1 19:56 UTC | yes |
| 12Z of D-1 | ens | enfo | 41/41 | 7.91 | 8.81 | 8.82 | D-1 20:49 UTC | yes |

Decision: the live run (05:30 UTC, retries to 07:00 UTC) uses the newest cycle that is out for both products: 18Z of D-1; 00Z of D (D 08:47 UTC) is not out before the run, so it is never waited for. The archive evaluation uses the 12Z run of D-1 (out the evening before on both public copies).
