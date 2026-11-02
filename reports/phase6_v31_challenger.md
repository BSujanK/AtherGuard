# v3.1 challenger: label audit and physical constraints

Generated 2026-10-24T15:51:39Z. Design, candidate definitions, selection and adoption criteria: docs/superpowers/specs/2026-10-14-aetherguard-live-global-design.md section 15 (written before any cross-validation or test_2018 number of this study). Analysis only: the frozen v2/v3 artifacts, the live run and the published tables are unchanged and nothing here is wired. Every number is read from the result files of `data/processed/hazard/v31_challenger/` and `data/processed/alerts/v31_replay/`.

## Summary

* Pre-declared selection (spec 15.5): **no challenger adopted**. C1 FA@90 0.2327 (0.0371 vs C0, CI lower end 0.0109), C2 FA@90 0.2309 (0.0353 vs C0, CI lower end 0.0111), C3 FA@90 0.2341 (0.0386 vs C0, CI lower end 0.0128); C0 0.1955 reproduces the frozen v3-live.
* Label audit: 16 of 154 low-terrain positive cell-days are implausible by the pre-declared catalog-field rule (9 of 103 in the in-domain development positives); the rest are ordinary rain-triggered landslide reports.
* test_2018: not read (no candidate selected).
* Live replay: see section 7.
* Exploratory replay of the challengers on the last live day (cell 19625150 is published Emergency, v3_live Emergency, C1 Warning, C2 Warning, C3 Warning; flat_cell_watch_plus (slope_mean < 5 deg): published 773, v3_live 773, C1 871, C2 908, C3 825; low_elevation_watch_plus (elev_mean < 100 m): published 760, v3_live 760, C1 639, C2 658, C3 639; low_terrain_warning_plus: published 565, v3_live 565, C1 352, C2 524, C3 465; low_rain_warning_plus (irain_acc_3 < 20 mm): published 55, v3_live 55, C1 71, C2 115, C3 103).

## 1. Label audit (Step 1, no model)

909 positive cell-days of the development period and test_2018 from 945 catalog records; 154 sit on low-terrain cells (mean slope under 5 degrees or mean elevation under 100 m). The pre-declared rule (spec 15.2) marks 16 cell-days as physically implausible.

| population | positive cell-days | low terrain | implausible | low terrain Himalaya / Western Ghats |
|---|---|---|---|---|
| development in domain | 789 | 103 | 9 | 46 / 57 |
| test 2018 in domain | 80 | 11 | 2 | 6 / 5 |
| out of domain | 40 | 40 | 5 | 18 / 22 |

Catalog fields of the records on low-terrain cells against the records elsewhere:

| field | value | records on low terrain | records elsewhere |
|---|---|---|---|
| category | landslide | 142 | 682 |
| category | mudslide | 14 | 46 |
| category | rock_fall | 4 | 37 |
| category | other | 1 | 1 |
| category | complex | 0 | 2 |
| category | translational_slide | 0 | 2 |
| category | rotational_slide | 0 | 1 |
| category | unknown | 0 | 1 |
| category | debris_flow | 0 | 10 |
| category | riverbank_collapse | 0 | 2 |
| trigger | downpour | 75 | 369 |
| trigger | rain | 48 | 181 |
| trigger | continuous_rain | 29 | 185 |
| trigger | monsoon | 9 | 45 |
| trigger | tropical_cyclone | 0 | 4 |
| accuracy | 5km | 88 | 529 |
| accuracy | 1km | 64 | 222 |
| accuracy | exact | 9 | 33 |
| setting | unknown | 101 | 430 |
| setting | above_road | 28 | 242 |
| setting | urban | 11 | 18 |
| setting | natural_slope | 10 | 51 |
| setting | retaining_wall | 4 | 6 |
| setting | below_road | 2 | 10 |
| setting | mine | 2 | 2 |
| setting | engineered_slope | 1 | 2 |
| setting | deforested_slope | 1 | 13 |
| setting | other | 1 | 1 |
| setting | above_river | 0 | 9 |
| source | coolr_reports | 87 | 82 |
| source | hma | 74 | 702 |

Location accuracy: no record is coarser than the 5.56 km grid cell (0 records), so a coarser-than-cell rule selects nothing.

Flags of the rule (a record can carry several):

| flag | records on low terrain | records elsewhere |
|---|---|---|
| setting | 7 | 10 |
| category | 1 | 4 |
| geocode | 2 | 1 |
| structure | 10 | 9 |

Cell-days whose records are all flagged: 31, of which 15 are not on low terrain; implausible (flagged and on low terrain) 16 by reason {"category": 1, "geocode": 2, "setting": 3, "setting;structure": 4, "structure": 6}, by split {"test_2018": 2, "train": 11, "validation": 3}, by region {"himalaya": 3, "western_ghats": 13}.

Concentration: 154 low-terrain cell-days fall on 116 cells; the largest are 23235435 (9), 21835060 (8), 20575097 (6), 23225434 (5), 23225435 (3).

20 example low-terrain positives with their catalog text (seeded sample):

| cell | date | region | slope | elev m | source | category | trigger | accuracy | setting | flags | text |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 19695140 | 2013-11-13 | western_ghats | 4.5 | 46 | coolr_reports | landslide | downpour | 5km | unknown | - | Karakkamandapam, Kerala / Train services between Kanyakumari and Thiru_va__nanthapuram were cancelled following a landslide on the track at Nemom on ... |
| 19915130 | 2011-08-07 | western_ghats | 2.7 | 12 | coolr_reports | landslide | downpour | 5km | unknown | - | Kottayam / KOTTAYAM: Heavy rain continued to wreak havoc in the district on Sunday. One person died and four houses were completely damaged in the d... |
| 19975127 | 2010-09-24 | western_ghats | 4.3 | 30 | coolr_reports | landslide | downpour | 5km | unknown | - | rail line between Mulanthuruthy and Piravom near Mulanthruth, Kerala / Train services in the Kottayam-Ernakulam route have been cancelled after mud c... |
| 20255124 | 2009-09-19 | western_ghats | 3.5 | 34 | coolr_reports | landslide | downpour | 1km | unknown | - | Nilambur, Malappuram, Kerala State / Heavy rain in parts of Malappuaram has caused landslide near Nilambur. An Anganvadi building collapsed and sever... |
| 20575100 | 2010-11-11 | western_ghats | 3.0 | 24 | coolr_reports | landslide | downpour | 5km | unknown | - | Bantwal Cross (BC) road flyover, NH48, between Mangalore and Beltangady(Belthangady) and Puttur, Bantwal, Karnataka / Bantwal, Nov 12: Heavy rains on... |
| 21085076 | 2007-07-28 | western_ghats | 4.0 | 34 | coolr_reports | landslide | rain | 5km | unknown | geocode | Vasco / closest to predicted location of Alibag (383.81 km) / Vasco / |
| 21805057 | 2013-07-10 | western_ghats | 1.0 | 8 | coolr_reports | landslide | downpour | 1km|5km | unknown | - | Debram Chawl, Antop Hill Near Sheikh Mistry Dargah Road, Central Mumbai / The toll in Wednesday's major landslide in Antop Hill in central Mumbai sho... |
| 21825057 | 2010-06-25 | western_ghats | 2.4 | 32 | coolr_reports | landslide | downpour | 5km | unknown | - | Jeevandaya lane(?), Vijay Nagar, Ghatopar(Ghatkopar) / There were a couple of minor incidents of slab-collapses — one in Goregaon and another in Ghat... |
| 21835060 | 2013-07-24 | western_ghats | 7.0 | 46 | coolr_reports | landslide | downpour | 5km | unknown | - | National Highway 4, Navi Mumbai, Maharashtra / A nearly one km-long stretch of the Mumbra bypass on the outskirts of the city caved in on Wednesday m... |
| 21835060 | 2016-06-21 | western_ghats | 7.0 | 46 | coolr_reports | landslide | downpour | 1km | above_road | - | Parsik Tunnel between Thane and Kalyan railway stations, India / Also, a landslide was witnessed between Thane and Kalyan railway stations in the mor... |
| 21925058 | 2012-09-04 | western_ghats | 6.4 | 69 | coolr_reports | landslide | downpour | 1km | unknown | - | Varai, Maharashtra / The heavy trains over two days triggered a landslide on the Mumbai-Ahmedabad highway at Varai village near Manor on Tuesday morn... |
| 22955459 | 2015-07-22 | himalaya | 1.2 | 24 | hma | landslide | continuous_rain | 5km | urban | - | Lakhipur / Five persons of a family were buried alive when a huge hillock collapsed on their house in Cachar district on Wednesday. The incident took... |
| 22965478 | 2010-10-08 | himalaya | 4.0 | 797 | hma | landslide | downpour | 5km | unknown | - | Tharon(?) and Langol Tarung villages, Thangmeiband constituency, Imphal, Manipur / On the other hand, landslides that occurred along the Langol footh... |
| 23225434 | 2012-06-02 | himalaya | 5.0 | 82 | hma | landslide | downpour | 5km | unknown | - | Guwahati, Assam / South Assam's Barrak valley has been cut off from the rest of the country due to heavy landslides. Northeast Frontier Railway sourc... |
| 23225434 | 2012-06-22 | himalaya | 5.0 | 82 | hma | landslide | downpour | 5km | unknown | - | Lalunggaon near Gorchuk area / On June 22, three people including two children of a family were killed in a landslide incident at Lalunggaon near Gor... |
| 23225435 | 2014-06-26 | himalaya | 2.8 | 68 | hma | landslide | continuous_rain | 5km | unknown | - | Narakasur / At least eight people, including three members of a family, were killed here due to landslides and flash floods triggered by incessant ra... |
| 23225435 | 2017-07-10 | himalaya | 2.8 | 68 | hma | landslide | continuous_rain | 1km | urban | - | Landslide damages house / Temporary house near Srimanta Sankar Academy damaged by landslides amid storms and flooding throughout Assam State / Dispur... |
| 23235433 | 2015-09-01 | himalaya | 2.6 | 57 | hma | rock_fall | rain | 1km | unknown | - | Maligaon / The incessant rains that lashed Guwahati and its adjoining areas are likely to result in landslide soon. Local residents in Amingaon, Thir... |
| 23535308 | 2010-08-23 | himalaya | 4.4 | 1341 | hma | landslide | downpour | 5km | unknown | - | Khadkha Tole(?), Chittapol(Chitpol) VDC(?), Bhaktapur district / 2010-08-24 11:58 AM BHAKTAPUR: A woman was buried alive by a landslide at Khadkha To... |
| 24825091 | 2015-03-15 | himalaya | 3.1 | 1618 | hma | landslide | continuous_rain | 1km | unknown | - | Shirpora / As a result of continuous rains and snowfall during the past few days several areas in Baramulla district including Larridora, Bandibala, ... |

## 2. Candidates (Step 2)

| candidate | inputs | trees | description | positives dropped from training |
|---|---|---|---|---|
| C0 | 26 | 315 | v3-live refit (reference): the 26 imerg_core inputs with the v3 monotone constraints | 0 |
| C1 | 26 | 220 | C0 plus stat_elev_mean constrained non-decreasing (C0 already carries the rain, slope and relief constraints) | 0 |
| C2 | 25 | 374 | C0 without stat_elev_mean (the C1 constraint set minus the elevation input) | 0 |
| C3 | 25 | 173 | C2 trained without the physically implausible positives of the label audit (training only) | 9 |

All use the frozen v3-live hyper-parameters, folds, seeds and calibration (spec 15.3). The audit lists 16 implausible cell-days; only the in-domain development positives among them can be in the training rows, and those are the ones C3 drops. Every candidate is scored on all 789 development positives.

Reference reproduction: C0 pooled OOF FA@90 0.195541 against the frozen v3-live 0.195541 (difference 0.0e+00), 315 trees against 315.

## 3. Development results (pooled out-of-fold, 2007-2017; bootstrap n=2000, seed 31337, level 0.95)

### FA@90 (primary metric)

| candidate | FA@90 [95% CI] | difference vs C0 [95% paired CI] | CI excludes 0 | PR-AUC |
|---|---|---|---|---|
| C0 | 0.1955 [0.1679, 0.2348] | - | - | 0.005327 |
| C1 | 0.2327 [0.2050, 0.2552] | 0.0371 [0.0109, 0.0555] | yes | 0.005213 |
| C2 | 0.2309 [0.2082, 0.2585] | 0.0353 [0.0111, 0.0576] | yes | 0.002695 |
| C3 | 0.2341 [0.2074, 0.2560] | 0.0386 [0.0128, 0.0598] | yes | 0.002652 |

### Warning+ alert level (each candidate's own Warning threshold, re-derived as v3's was; point level, no post-model rules)

| candidate | OOF recall | false-alarm share | Warning+ cell-days (millions) | low-terrain share [95% CI] | difference vs C0 [95% paired CI] | low-rain share [95% CI] | events per 1,000 cell-days [95% CI] |
|---|---|---|---|---|---|---|---|
| C0 | 75.0% | 8.30% | 12.18 | 6.8% [6.4%, 7.1%] | - | 19.7% [19.1%, 20.3%] | 0.0486 [0.0465, 0.0506] |
| C1 | 75.0% | 10.14% | 14.88 | 6.0% [5.7%, 6.2%] | -0.799% [-1.068%, -0.519%] | 19.4% [18.8%, 19.9%] | 0.0398 [0.0381, 0.0413] |
| C2 | 75.0% | 10.73% | 15.74 | 6.3% [6.0%, 6.6%] | -0.453% [-0.722%, -0.169%] | 22.0% [21.5%, 22.6%] | 0.0376 [0.0360, 0.0391] |
| C3 | 75.0% | 11.14% | 16.34 | 5.5% [5.3%, 5.8%] | -1.205% [-1.470%, -0.938%] | 20.5% [20.0%, 21.1%] | 0.0362 [0.0347, 0.0377] |

Low-terrain share of Warning+ cell-days by region:

| candidate | Himalaya | Western Ghats |
|---|---|---|
| C0 | 2.9% | 30.9% |
| C1 | 3.6% | 23.2% |
| C2 | 3.9% | 23.2% |
| C3 | 3.4% | 21.4% |

### Recall and false-alarm share at C0's raw operating thresholds (and at each candidate's own)

| candidate | Watch: recall / FA share | Warning: recall / FA share | Emergency: recall / FA share |
|---|---|---|---|
| C0 | 91.8% / 22.78%; own 91.8% / 22.78% | 75.0% / 8.30%; own 75.0% / 8.30% | 50.1% / 2.60%; own 50.1% / 2.60% |
| C1 | 92.9% / 26.23%; own 91.8% / 25.07% | 71.5% / 8.91%; own 75.0% / 10.14% | 42.7% / 2.44%; own 50.1% / 3.24% |
| C2 | 91.0% / 24.53%; own 91.8% / 25.35% | 70.1% / 8.55%; own 75.0% / 10.73% | 43.1% / 2.42%; own 50.1% / 3.28% |
| C3 | 92.9% / 27.01%; own 91.8% / 25.14% | 71.1% / 9.07%; own 75.0% / 11.14% | 40.9% / 2.38%; own 50.1% / 3.53% |

### Calibration (cross-fitted over the seven folds, deciles of calibrated risk)

| candidate | ECE per-region calibrators | ECE pooled calibrator | ECE / base rate (per-region) |
|---|---|---|---|
| C0 | 4.327e-06 | 2.396e-06 | 0.80 |
| C1 | 7.124e-06 | 4.872e-06 | 1.32 |
| C2 | 1.115e-05 | 1.855e-06 | 2.07 |
| C3 | 1.449e-06 | 1.222e-06 | 0.27 |

Reliability deciles are in `dev_results.json` (`evaluation.candidates.<name>.ece`).

## 4. Pre-declared selection (spec 15.5)

Reference C0 Warning+ low-terrain share 6.75%.

| candidate | FA@90 | difference [95% paired CI] | not worse than reference | Warning+ low-terrain share | below reference share | eligible |
|---|---|---|---|---|---|---|
| C1 | 0.2327 | 0.0371 [0.0109, 0.0555] | no | 5.96% | yes | no |
| C2 | 0.2309 | 0.0353 [0.0111, 0.0576] | no | 6.30% | yes | no |
| C3 | 0.2341 | 0.0386 [0.0128, 0.0598] | no | 5.55% | yes | no |

**Result: no challenger adopted.**

## 5. Descriptive follow-up: alerts and events on low-terrain cells (not used for the selection)

Added after the selection result was known, from the same OOF rows: how often each candidate alerts at Warning on low-terrain cells against other cells, and the events per 1,000 alerted cell-days there. The base event rate is the positives per 1,000 cell-days of each terrain class.

| candidate | Warning+ rate on low terrain | on other cells | events / 1,000 Warning+ cell-days: low terrain | other cells | base events / 1,000 cell-days: low terrain | other cells |
|---|---|---|---|---|---|---|
| C0 | 2.23% | 10.34% | 0.0924 | 0.0454 | 0.0028 | 0.0062 |
| C1 | 2.40% | 12.75% | 0.0745 | 0.0376 | 0.0028 | 0.0062 |
| C2 | 2.69% | 13.43% | 0.0655 | 0.0357 | 0.0028 | 0.0062 |
| C3 | 2.46% | 14.06% | 0.0662 | 0.0345 | 0.0028 | 0.0062 |

## 6. test_2018 (Step 4, one look)

Not run: the pre-declared selection (spec 15.5) named no candidate: test_2018 was not read and no selected-candidate replay was made.

## 7. Offline live replay (spec 15.7)

Days 2026-10-09..2026-10-24 from the stored `features_D0.parquet` (reported from 2026-10-16); nothing was written to `data/live`. Replayed candidates C1, C2, C3 are EXPLORATORY (C1, C2, C3): the pre-declared selection did not choose them, no test_2018 is involved, and the replay is context for a decision, not a result of the selection.

Check of the replay chain: the frozen v3-live replay equals the published level on 588,672 of 588,672 cell-days (100.000%); 0 cell-days differ from the report start.

Cells at each level on the last day (published table, then replays):

| levels | Normal | Watch | Warning | Emergency |
|---|---|---|---|---|
| published | 33132 | 1711 | 914 | 1035 |
| v3_live | 33132 | 1711 | 914 | 1035 |
| C1 | 33156 | 1829 | 1135 | 672 |
| C2 | 33056 | 1536 | 1338 | 862 |
| C3 | 33198 | 1493 | 950 | 1151 |

Last-day alert counts in the descriptive classes:

| class | published | v3_live | C1 | C2 | C3 |
|---|---|---|---|---|---|
| flat_cell_watch_plus (slope_mean < 5 deg) | 773 | 773 | 871 | 908 | 825 |
| low_elevation_watch_plus (elev_mean < 100 m) | 760 | 760 | 639 | 658 | 639 |
| low_terrain_warning_plus | 565 | 565 | 352 | 524 | 465 |
| low_rain_warning_plus (irain_acc_3 < 20 mm) | 55 | 55 | 71 | 115 | 103 |

Named areas on the last day (cells at each level):

| area | cells | levels | Watch | Warning | Emergency |
|---|---|---|---|---|---|
| kanyakumari | 1 | published | 0 | 0 | 1 |
| kanyakumari | 1 | v3_live | 0 | 0 | 1 |
| kanyakumari | 1 | C1 | 0 | 1 | 0 |
| kanyakumari | 1 | C2 | 0 | 1 | 0 |
| kanyakumari | 1 | C3 | 0 | 1 | 0 |
| jammu | 95 | published | 17 | 16 | 0 |
| jammu | 95 | v3_live | 17 | 16 | 0 |
| jammu | 95 | C1 | 13 | 13 | 0 |
| jammu | 95 | C2 | 18 | 11 | 0 |
| jammu | 95 | C3 | 12 | 16 | 0 |
| manipur | 85 | published | 26 | 4 | 0 |
| manipur | 85 | v3_live | 26 | 4 | 0 |
| manipur | 85 | C1 | 25 | 4 | 0 |
| manipur | 85 | C2 | 22 | 8 | 0 |
| manipur | 85 | C3 | 24 | 5 | 0 |
| south_ghats | 401 | published | 20 | 109 | 272 |
| south_ghats | 401 | v3_live | 20 | 109 | 272 |
| south_ghats | 401 | C1 | 22 | 133 | 245 |
| south_ghats | 401 | C2 | 20 | 116 | 265 |
| south_ghats | 401 | C3 | 10 | 70 | 321 |

Highest cells of each area (levels on the last day):

kanyakumari:

| cell | lat | lon | slope | elev m | 3-day rain mm | published | v3_live | C1 | C2 | C3 |
|---|---|---|---|---|---|---|---|---|---|---|
| 19625150 | 8.12 | 77.53 | 2.8 | 31 | 82.9 | Emergency | Emergency | Warning | Warning | Warning |

jammu:

| cell | lat | lon | slope | elev m | 3-day rain mm | published | v3_live | C1 | C2 | C3 |
|---|---|---|---|---|---|---|---|---|---|---|
| 24615097 | 33.08 | 74.88 | 18.3 | 771 | 16.3 | Warning | Warning | Warning | Warning | Warning |
| 24625092 | 33.12 | 74.62 | 14.2 | 791 | 13.6 | Warning | Warning | Warning | Warning | Warning |
| 24625093 | 33.12 | 74.68 | 26.4 | 1031 | 13.6 | Warning | Warning | Warning | Warning | Warning |
| 24625094 | 33.12 | 74.73 | 27.8 | 1288 | 19.2 | Warning | Warning | Warning | Warning | Warning |
| 24625095 | 33.12 | 74.78 | 31.1 | 1001 | 19.2 | Warning | Warning | Watch | Warning | Warning |
| 24635092 | 33.18 | 74.62 | 21.2 | 1308 | 13.6 | Warning | Warning | Warning | Watch | Warning |
| 24635093 | 33.18 | 74.68 | 25.7 | 1304 | 13.6 | Warning | Warning | Warning | Warning | Warning |
| 24635094 | 33.18 | 74.73 | 24.8 | 956 | 19.2 | Warning | Warning | Warning | Warning | Warning |
| 24645092 | 33.23 | 74.62 | 23.6 | 1486 | 14.8 | Warning | Warning | Warning | Watch | Warning |
| 24645093 | 33.23 | 74.68 | 25.6 | 1172 | 14.8 | Warning | Warning | Warning | Warning | Warning |
| 24655092 | 33.28 | 74.62 | 24.1 | 1599 | 14.8 | Warning | Warning | Warning | Watch | Warning |
| 24655093 | 33.28 | 74.68 | 27.3 | 1804 | 14.8 | Warning | Warning | Watch | Watch | Watch |

manipur:

| cell | lat | lon | slope | elev m | 3-day rain mm | published | v3_live | C1 | C2 | C3 |
|---|---|---|---|---|---|---|---|---|---|---|
| 22805465 | 24.03 | 93.28 | 23.4 | 807 | 25.0 | Warning | Warning | Warning | Warning | Warning |
| 22825466 | 24.12 | 93.32 | 19.6 | 690 | 20.2 | Warning | Warning | Warning | Warning | Warning |
| 22825467 | 24.12 | 93.38 | 21.1 | 1031 | 20.2 | Warning | Warning | Warning | Warning | Watch |
| 22835464 | 24.18 | 93.23 | 19.4 | 1060 | 17.9 | Warning | Warning | Watch | Watch | Watch |
| 22805464 | 24.03 | 93.23 | 23.2 | 879 | 25.0 | Watch | Watch | Watch | Warning | Warning |
| 22815464 | 24.08 | 93.23 | 27.4 | 769 | 25.0 | Watch | Watch | Warning | Warning | Warning |
| 22815465 | 24.08 | 93.28 | 21.5 | 719 | 25.0 | Watch | Watch | Watch | Warning | Watch |
| 22815466 | 24.08 | 93.32 | 19.1 | 627 | 26.2 | Watch | Watch | Watch | Warning | Watch |
| 22815467 | 24.08 | 93.38 | 21.8 | 885 | 26.2 | Watch | Watch | Watch | Watch | Warning |
| 22825462 | 24.12 | 93.12 | 23.9 | 670 | 16.7 | Watch | Watch | Watch | Watch | Watch |
| 22825463 | 24.12 | 93.18 | 23.8 | 1004 | 16.7 | Watch | Watch | Watch | Watch | Watch |
| 22825464 | 24.12 | 93.23 | 23.3 | 932 | 17.9 | Watch | Watch | Watch | Watch | Watch |

south_ghats:

| cell | lat | lon | slope | elev m | 3-day rain mm | published | v3_live | C1 | C2 | C3 |
|---|---|---|---|---|---|---|---|---|---|---|
| 19815144 | 9.08 | 77.23 | 17.0 | 466 | 59.5 | Emergency | Emergency | Warning | Emergency | Emergency |
| 19825142 | 9.12 | 77.12 | 17.7 | 307 | 55.1 | Emergency | Emergency | Emergency | Emergency | Emergency |
| 19825144 | 9.12 | 77.23 | 23.0 | 933 | 55.7 | Emergency | Emergency | Warning | Emergency | Emergency |
| 19835144 | 9.18 | 77.23 | 21.6 | 1182 | 55.7 | Emergency | Emergency | Emergency | Emergency | Emergency |
| 19835145 | 9.18 | 77.28 | 24.2 | 1051 | 55.7 | Emergency | Emergency | Emergency | Emergency | Emergency |
| 19835146 | 9.18 | 77.32 | 19.2 | 543 | 67.3 | Emergency | Emergency | Warning | Emergency | Emergency |
| 19845142 | 9.23 | 77.12 | 19.1 | 906 | 49.7 | Emergency | Emergency | Warning | Emergency | Emergency |
| 19845143 | 9.23 | 77.18 | 14.6 | 1194 | 49.7 | Emergency | Emergency | Emergency | Warning | Emergency |
| 19845144 | 9.23 | 77.23 | 14.5 | 1258 | 55.8 | Emergency | Emergency | Emergency | Emergency | Emergency |
| 19845145 | 9.23 | 77.28 | 21.3 | 1199 | 55.8 | Emergency | Emergency | Emergency | Emergency | Emergency |
| 19845146 | 9.23 | 77.32 | 13.9 | 423 | 55.3 | Emergency | Emergency | Warning | Emergency | Emergency |
| 19855144 | 9.28 | 77.23 | 14.7 | 1239 | 55.8 | Emergency | Emergency | Emergency | Warning | Emergency |

Last-day transitions from the v3-live replay to each candidate (cells):

* C1: Normal->Watch 309, Normal->Warning 2, Watch->Normal 327, Watch->Warning 174, Watch->Emergency 3, Warning->Normal 8, Warning->Watch 288, Warning->Emergency 23, Emergency->Watch 25, Emergency->Warning 364
* C2: Normal->Watch 366, Normal->Warning 13, Watch->Normal 297, Watch->Warning 435, Watch->Emergency 8, Warning->Normal 6, Warning->Watch 185, Warning->Emergency 97, Emergency->Watch 14, Emergency->Warning 264
* C3: Normal->Watch 281, Normal->Warning 4, Watch->Normal 339, Watch->Warning 346, Watch->Emergency 18, Warning->Normal 12, Warning->Watch 186, Warning->Emergency 263, Emergency->Watch 18, Emergency->Warning 147

Forecast leads of the last day (point level and rain cap, no hysteresis): the frozen v3 replay equals the published level on D+1: 36,792, D+2: 36,792, D+3: 36,792 cells. Cells at Watch / Warning / Emergency:

| lead | published | v3_live | C1 | C2 | C3 |
|---|---|---|---|---|---|
| D+1 | 3243 / 827 / 672 | 3243 / 827 / 672 | 2727 / 1091 / 293 | 3505 / 1334 / 536 | 3413 / 872 / 816 |
| D+2 | 1850 / 520 / 1194 | 1850 / 520 / 1194 | 1836 / 811 / 818 | 2727 / 907 / 1000 | 2478 / 577 / 1230 |
| D+3 | 2199 / 432 / 833 | 2199 / 432 / 833 | 2280 / 663 / 529 | 2329 / 714 / 716 | 2229 / 465 / 863 |
