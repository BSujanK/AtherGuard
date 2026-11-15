# Same-day rain gauges: source probe (phase 8, gauges-isd)

Measured 2026-11-15T18:33:01+00:00 (and during 15-16 Nov 2026 for the evidence files). Research prototype, not validated for issuing real public warnings. Every number is read from `phase8_gauge_sources_probe.json`.

## Findings

1. **NOAA ISD / Global Hourly and GSOD have ended.** isd-history.csv last modified Sat, 30 Aug 2025 00:02:02 GMT; newest year prefix in `noaa-isd-pds`: data/2025/, in `noaa-global-hourly-pds`: 2025/; GSOD 2026 files: HTTP [404]. NCEI's successor products are GHCNh (hourly) and the Synoptic Summary of the Day v2 (SSOD, GHCN-Daily source flag 2).
2. **The engine's current gauge source carries no rain in 2026.** GHCN-Daily for the 140 project stations, June-September 2026: 3861 station-days from 69 stations, source flags {'2': 3861}, measurement flags {'H': 3856, 'G': 5}; share >= 1 mm 0.0010 against 0.6328 in June-September 2024 (10234 station-days, source S). Flag H means the amount 'could not be calculated, but at least one occurrence of precipitation was noted': these are not measured zeros, yet the live run reads them as dry days.
3. **The same stations' own SYNOP reports are on the WMO GTS within the hour.** In the NWS ring on 15 Nov 2026, 137 of 140 stations had a non-NIL 03 UTC report, 137 of them before 05:30 UTC (the run), p95 delay 0.53 h, maximum 1.75 h.

## Candidates

| source | data end (measured) | latency | precipitation for our stations | licence | verdict |
|---|---|---|---|---|---|
| NOAA ISD / Global Hourly (buckets, NCEI) | newest year 2025/; last records ['"42111099999","2025-08-24T21:00:00","4","30.3166666","78.0333333","682.0","DEHRADUN, IN","FM-12","99999","V020","050,1,N'] | - | AA1 groups up to Aug 2025 | public domain | ended; used for the V1 diagnostic only |
| NOAA GSOD | 2025 files end Aug 2025; 2026 absent | - | - | public domain | ended |
| GHCN-Daily (current) | newest value of any station 2026-11-07 when queried on 15 Nov 2026 (window to 14 Nov) | 115-308 h (phase 6 probe) | 0.998 of monsoon-2026 values are flag-H zeros | public domain | keep only as history; flag-H zeros are not rain data |
| GHCNh (ISD successor) | by-year 2026 files: [('42111', 200, 'Thu, 12 Nov 2026 03:51:27 GMT'), ('43371', 404, None), ('42182', 404, None)] | days (file updates not daily) | 42111: Jun-Sep 2026 24-h groups 0, positive hourly values 0; 42083: Jun-Sep 2026 24-h groups 0, positive hourly values 0 | public domain | 74 of 140 stations listed; not usable same-day |
| Meteostat bulk | Last-Modified ['Tue, 10 Mar 2026 07:45:18 GMT', 'Fri, 20 Mar 2026 00:42:37 GMT', 'Fri, 20 Mar 2026 00:42:12 GMT'] | stale since March 2026 | - | CC BY 4.0 | stale |
| OGIMET getsynop | real time (archive) | minutes | raw SYNOP, all groups | informational only, not mission-critical | validation and replays only (21 requests) |
| NWS tgftp SYNOP ring | 301 files, 10151858 bytes, Nov 14 17:15 .. Nov 15 18:30 UTC | 03 UTC p95 0.53 h | raw SYNOP, all groups | public domain (NWS) | **chosen live source** |

## Stations near the scored cells

SYNOP stations within 100 km of the 36792 live-scored cells (isd-history.csv (last modified 2025-08-30), WMO-format ids, END >= 2024): 365 by country {'PK': 13, 'BG': 21, 'BD': 1, 'IN': 303, 'BT': 1, 'NP': 15, 'BM': 7, 'CH': 4}; 107 of them are among the engine's 140 stations. In the NWS ring of 14-15 Nov, 301 reported; 277 gave an IMD-day total for 15 Nov ({'no_03utc_report': 88, '24h_group': 53, 'ir3_zero': 224}), 172 of them outside the engine's station set (they need a climatology and an engine evaluation before use).

Precipitation in Indian SYNOPs: section 1 `i_R` (3 = omitted because zero, 4 = not observed) and section 3 `6RRR/`, the amount since 03 UTC (24 h at 03 UTC), plus `7R24R24R24R24` at some stations; trace is RRR 990 or R24 9999. ISD 2024 (Dehradun) decodes the same groups with periods 3, 6, ..., 24 h, cumulative since 03 UTC.

## OGIMET usage

21 requests in all, 58342052 bytes (1 test request (42111, 1-3 Jul 2024), then one request per block and period, >= 30 s apart; one block-43 month request returned 0 bytes and was split in two halves); terms read before the first request: True. Raw responses are kept under data/raw/synop/ogimet (July 2024 in the workstream's scratch directory), never committed.

## Licences (quoted)

- noaa_ncei: NOAA NCEI open data (public domain); ISD, GSOD, GHCN-Daily, GHCNh
- nws: weather.gov disclaimer: information on NWS Web servers 'is in the public domain, unless specifically noted otherwise' and 'may be used freely by the public' (the page does not name the tgftp server); coded SYNOP reports are WMO essential data (Resolution 40)
- ogimet: ogimet.com footer/licence: text tables may be used 'siempre que se incluya el enlace al sitio de origen Ogimet'; 'Estas paginas deben utilizarse a titulo informativo'; 'Los productos de este sitio no deben utilizarse en ninguna mision critica'; coded reports are copyright of each national service, WMO Resolution 40. getsynop help: 'No more than 200000 synops in a petition', 'please, don't abuse'
- meteostat: dev.meteostat.net/license: Creative Commons Attribution 4.0 International (CC BY 4.0); credit Meteostat and its data providers

## Decisions for the user

- Live use of OGIMET (terms: informational use only, not mission-critical). Used here only for validation and scratch replays.
- India-WRIS and the IMD AWS/ARG portals need registration: not signed up, not probed.
- Wiring synop.enabled and/or ghcn.h_zero_as_missing into the live run (levels can change: a model change).
- More stations than the 140 (SYNOP stations near the scored cells that the engine has no climatology for): needs an engine retraining and evaluation.

## Caveats

- Latency of the ring was measured on one 03 UTC cycle (15 Nov 2026) and the hours around it; the collection job keeps measuring (ledger).
- The station list near the scored cells comes from isd-history.csv, frozen since August 2025.
