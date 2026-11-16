# Forecast leads on v4: preflight of the held-out look (no outcome computed)

Spec: docs/superpowers/specs/2026-11-14-aetherguard-leads-v4.md, sections 4-5 and amendments 1-2. Research prototype, not validated for issuing real public warnings. The preflight joins no event with a level: it burden-matches the candidate and counts event dates only.

Candidate: **a** (chosen by `look_choice` in reports/phase8_leads_v4.json). Years 2021, 2022, 2023, 2024, June-September issue days. Generated 2026-11-16T16:17:09+00:00.

## Panels (frozen by checksum; the look refuses other panels)

| year | sha256 |
|---|---|
| 2021 | `33c7b7fbd1a7182c26a0082e0e0c4cbda384bb0e0480213e4892e660e8e94666` |
| 2022 | `730af37458f8c719dbe84be34349d52fa11c139660dfb36bf57a8b2637912b8a` |
| 2023 | `bc55f74bffa3aacf22970caf33355bdcc115f20be42cb11ce3f0a7792333fe0c` |
| 2024 | `ede396ecd5f95d562c8337f8370168ec7d64c8af739f25c750c5e422299ed93f` |

## Burden matching per season and lead

Target = the incumbent's realised Watch+ / Warning+ / Emergency shares of scored cell-days; realised = the candidate's after `hazard.v4_int.match_burden`. Straddle = tied cell-days left out at a cut.

| lead | season | scored cell-days | issue days scored | target W+ / Wa+ / E | realised W+ / Wa+ / E | straddle (W+, Wa+, E) |
|---|---|---|---|---|---|---|
| 1 | 2021 | 4,488,565 | 122 | 55.6956% / 22.0588% / 7.9884% | 55.6956% / 22.0588% / 7.9884% | 0, 0, 0 |
| 1 | 2022 | 4,488,587 | 122 | 55.5494% / 21.6305% / 7.7405% | 55.5494% / 21.6305% / 7.7405% | 1, 0, 0 |
| 1 | 2023 | 4,488,566 | 122 | 51.8888% / 20.5727% / 7.7754% | 51.8888% / 20.5727% / 7.7754% | 1, 0, 2 |
| 1 | 2024 | 4,488,547 | 122 | 56.9661% / 24.4168% / 10.3410% | 56.9661% / 24.4168% / 10.3410% | 0, 0, 0 |
| 2 | 2021 | 4,488,505 | 122 | 55.6039% / 21.3470% / 7.4491% | 55.6039% / 21.3470% / 7.4491% | 0, 0, 0 |
| 2 | 2022 | 4,488,539 | 122 | 55.5018% / 21.3467% / 7.5959% | 55.5018% / 21.3467% / 7.5959% | 0, 0, 0 |
| 2 | 2023 | 4,488,575 | 122 | 52.7335% / 20.4629% / 7.1739% | 52.7335% / 20.4629% / 7.1739% | 1, 0, 0 |
| 2 | 2024 | 4,488,624 | 122 | 58.5029% / 25.3749% / 10.4940% | 58.5029% / 25.3749% / 10.4940% | 0, 0, 1 |
| 3 | 2021 | 4,488,219 | 122 | 56.1284% / 21.5637% / 7.3685% | 56.1284% / 21.5637% / 7.3685% | 0, 0, 0 |
| 3 | 2022 | 4,488,214 | 122 | 55.7567% / 21.3166% / 7.6800% | 55.7567% / 21.3166% / 7.6800% | 0, 0, 0 |
| 3 | 2023 | 4,488,456 | 122 | 49.0387% / 18.2511% / 7.0795% | 49.0387% / 18.2511% / 7.0795% | 0, 0, 0 |
| 3 | 2024 | 4,488,624 | 122 | 53.0970% / 22.2681% / 10.5083% | 53.0970% / 22.2681% / 10.5083% | 0, 0, 0 |

| lead | target days | scored cell-days |
|---|---|---|
| 1 | 488 | 17,954,265 |
| 2 | 488 | 17,954,243 |
| 3 | 488 | 17,953,513 |

## Events dated on the target days (dates only)

| set | lead | events on days | events outside the days | independent slides |
|---|---|---|---|---|
| w1 | 1 | 22 | 2 | 22 |
| w1 | 2 | 22 | 2 | 22 |
| w1 | 3 | 22 | 2 | 22 |
| v2_all | 1 | 568 | 96 | 517 |
| v2_all | 2 | 568 | 96 | 517 |
| v2_all | 3 | 569 | 95 | 518 |
| v2_without_bipad | 1 | 22 | 2 | 22 |
| v2_without_bipad | 2 | 22 | 2 | 22 |
| v2_without_bipad | 3 | 22 | 2 | 22 |
| v2_india | 1 | 22 | 2 | 22 |
| v2_india | 2 | 22 | 2 | 22 |
| v2_india | 3 | 22 | 2 | 22 |

## Checks

- lead 1: burden matched within tolerance every season: passed
- lead 2: burden matched within tolerance every season: passed
- lead 3: burden matched within tolerance every season: passed
- W1 counts of the preflight equal the dates-only recount: True

## Caveats

- 22 independent W1 slides fall on the target days of each lead (2 records outside). One slide moves a row; ties are the expected outcome of the 12-row rule.
- The incumbent leads' burden is high (see the target shares), so tolerant matching has a high chance floor; the cell-exact rows are the stronger test.
- 2021 is the fit season of the GFS intensity maps (rain only, no event). Leads 2-3 use the GFS fallback on every issue day of 2021-2022 and on part of 2023 (no ECMWF archive), as the live run does when ECMWF fails.
- Assembly v2 without the BIPAD register, and v2 India only, hold the same events as W1 on these days; v2 with all records adds the BIPAD Nepal register (no stated licence: numbers only, local rows, decides nothing).
- Ground truth after 2018 is very incomplete.
