import pytest

from aetherguard.audit import feasibility as f


def test_call_units_follow_the_published_weighting():
    assert f.open_meteo_call_units(1, 14, 10) == 1.0
    assert f.open_meteo_call_units(1, 7, 3) == 1.0            # never below one call
    assert f.open_meteo_call_units(1, 14, 15) == pytest.approx(1.5)   # provider's 2-week/15-var example
    assert f.open_meteo_call_units(1, 28, 15) == pytest.approx(3.0)   # provider's 4-week example
    assert f.open_meteo_call_units(10, 28, 10) == pytest.approx(20.0)


def test_scenarios_show_full_grid_is_infeasible_and_sampling_is_not():
    domain = {"period": {"start": "2007-01-01", "end": "2024-12-31"}}
    audit = {"open_meteo": {"free_calls_per_day": 10_000, "days_per_call_unit": 14, "vars_per_call_unit": 10}}
    by_name = {s["name"]: s for s in f.scenarios(domain, audit)}
    full_025 = by_name["full domain, ERA5 0.25 deg grid, whole period"]
    assert full_025["points"] == 7_120 and full_025["days"] == 6_575
    assert full_025["days_at_free_limit"] > 300
    full_005 = by_name["full domain, 0.05 deg grid, whole period"]
    assert full_005["days_at_free_limit"] > 5_000   # about 8,360 days: hopeless on the free tier
    sampled = by_name["sampled case-control, 30,000 points x 60 days"]
    assert sampled["days_at_free_limit"] < 30


def test_probe_feasibility_is_ok_and_carries_scenarios():
    res = f.probe_feasibility({"period": {"start": "2007-01-01", "end": "2024-12-31"}},
                              {"open_meteo": {"free_calls_per_day": 10_000, "days_per_call_unit": 14,
                                              "vars_per_call_unit": 10}})
    assert res.status == "ok"
    assert len(res.evidence["scenarios"]) == 3


DOMAIN = {"period": {"start": "2007-01-01", "end": "2024-12-31"}}
AUDIT = {"open_meteo": {"free_calls_per_day": 10_000, "days_per_call_unit": 14, "vars_per_call_unit": 10}}


def _with(domain=None, **open_meteo):
    audit = {"open_meteo": {**AUDIT["open_meteo"], **open_meteo}}
    return (domain if domain is not None else DOMAIN), audit


@pytest.mark.parametrize("domain, open_meteo, reason", [
    ({"period": {"start": "2024-12-31", "end": "2007-01-01"}}, {}, "end"),
    ({"period": {"start": "2007-01-01", "end": "2007-01-01"}}, {}, None),  # one day is valid
    ({"period": {"start": "not-a-date", "end": "2024-12-31"}}, {}, "period"),
    ({"period": {"start": "2007-01-01"}}, {}, "end"),
    ({}, {}, "period"),
    (None, {"free_calls_per_day": 0}, "free_calls_per_day"),
    (None, {"free_calls_per_day": -5}, "free_calls_per_day"),
    (None, {"days_per_call_unit": 0}, "days_per_call_unit"),
    (None, {"vars_per_call_unit": -1}, "vars_per_call_unit"),
])
def test_invalid_config_fails_instead_of_fabricating_numbers(domain, open_meteo, reason):
    d, a = _with(domain, **open_meteo)
    res = f.probe_feasibility(d, a)
    if reason is None:
        assert res.status == "ok"
        return
    assert res.status == "fail"
    assert reason in res.summary
    assert "scenarios" not in res.evidence


def test_missing_open_meteo_keys_fail():
    res = f.probe_feasibility(DOMAIN, {"open_meteo": {"free_calls_per_day": 10_000}})
    assert res.status == "fail"
    assert "days_per_call_unit" in res.summary
    assert f.probe_feasibility(DOMAIN, {}).status == "fail"


def test_summary_is_derived_from_the_scenarios():
    res = f.probe_feasibility(DOMAIN, AUDIT)
    assert res.status == "ok"
    assert res.evidence["threshold_days"] == 30
    assert res.evidence["infeasible"] == ["full domain, ERA5 0.25 deg grid, whole period",
                                          "full domain, 0.05 deg grid, whole period"]
    assert res.evidence["feasible"] == ["sampled case-control, 30,000 points x 60 days"]
    assert "infeasible (>30 days at the free limit): full domain, ERA5 0.25 deg grid, whole period" in res.summary
    assert "feasible: sampled case-control, 30,000 points x 60 days (12.9 d)" in res.summary


def test_summary_does_not_claim_infeasibility_when_everything_fits():
    d, a = _with(free_calls_per_day=10**9)
    res = f.probe_feasibility(d, a)
    assert res.status == "ok"
    assert res.evidence["infeasible"] == []
    assert "infeasible" not in res.summary
    assert len(res.evidence["feasible"]) == 3
