import pytest

from aetherguard.audit.result import STATUSES, ProbeResult, failure_status


def test_probe_result_validates_status():
    assert ProbeResult("x", "ok", "fine").status == "ok"
    with pytest.raises(ValueError):
        ProbeResult("x", "great", "nope")
    assert "needs_login" in STATUSES and "manual_pending" in STATUSES


def test_as_dict_round_trips_evidence_and_day_definition():
    r = ProbeResult("x", "ok", "s", evidence={"a": 1}, day_definition="UTC day")
    assert r.as_dict() == {"name": "x", "status": "ok", "summary": "s",
                           "evidence": {"a": 1}, "day_definition": "UTC day"}


def test_failure_status_distinguishes_network_from_api_errors():
    class E(Exception):
        def __init__(self, retriable):
            self.retriable = retriable
    assert failure_status([E(True), E(False)]) == "unreachable"
    assert failure_status([E(False)]) == "fail"
    assert failure_status([]) == "fail"
