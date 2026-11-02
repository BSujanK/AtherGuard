# Scenario certainty on 2024 (spec section 12, F1)

Configuration per lead: D+1: gfs, D+2: ecmwf_ens_mean, D+3: ecmwf_ens_mean+map. Each forecast row is scored with no further rain (`dry`), with the forecast and with its heavy-rain bound (`wet`); `firm` = the three published levels agree. Reference: the published level from the observed features of the target day. Standard errors resample issue days.

| lead | group | cells | share | forecast level = observed (SE) | within one | observed inside [min, max] |
|---|---|---|---|---|---|---|
| D+1 | firm | 159496 | 0.516 | 0.961 (0.002) | 0.998 | 0.961 |
| D+1 | depends_on_forecast | 149883 | 0.484 | 0.664 (0.003) | 0.971 | 0.990 |
| D+1 | all | 309379 | 1.000 | 0.817 (0.004) | 0.985 | 0.975 |
| D+2 | firm | 179543 | 0.580 | 0.960 (0.002) | 0.998 | 0.960 |
| D+2 | depends_on_forecast | 129843 | 0.420 | 0.588 (0.004) | 0.967 | 0.970 |
| D+2 | all | 309386 | 1.000 | 0.804 (0.004) | 0.985 | 0.964 |
| D+3 | firm | 178700 | 0.578 | 0.944 (0.002) | 0.996 | 0.944 |
| D+3 | depends_on_forecast | 130685 | 0.422 | 0.571 (0.005) | 0.945 | 0.966 |
| D+3 | all | 309385 | 1.000 | 0.786 (0.005) | 0.975 | 0.953 |
