"""SYNOP decoding and IMD-day totals (recorded NWS ring and OGIMET fixtures; no network)."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from aetherguard.ingest import synop as S

FIX = Path(__file__).parent / "fixtures" / "synop"
UTC = timezone.utc


def _ogimet_reports():
    lines = (FIX / "ogimet_42111_20240701.txt").read_text(encoding="ascii").splitlines()
    return [r for r in (S.parse_ogimet_line(line) for line in lines) if r is not None]


def test_code_tables():
    assert S.rrr_mm("009") == 9.0 and S.rrr_mm("990") == 0.0 and S.rrr_mm("992") == 0.2
    assert S.rrr_mm("989") == 989.0 and S.rrr_mm("///") is None
    assert S.r24_mm("1234") == 123.4 and S.r24_mm("9999") == 0.0 and S.r24_mm("12/4") is None


def test_ring_bulletins_decode_india_reports():
    text = (FIX / "nws_ring_20261115_0300.txt").read_text(encoding="ascii")
    reports = S.parse_bulletins(text, datetime(2026, 11, 15, 4, 0, tzinfo=UTC), ("42", "43"))
    by_station = {r.station: r for r in reports}
    assert "40582" not in by_station                       # other blocks filtered out
    assert all(r.time == datetime(2026, 11, 15, 3, tzinfo=UTC) for r in reports)
    assert by_station["42170"].ir == "2"
    assert by_station["42170"].accumulations == (S.Accumulation(1.0, None, "6s3"),)
    assert by_station["42027"].accumulations[0].trace and by_station["42027"].accumulations[0].amount_mm == 0.0
    assert by_station["42044"].accumulations[0].amount_mm == 0.2
    assert by_station["43177"].ir == "3" and by_station["43177"].accumulations == ()
    assert by_station["42328"].bulletin.endswith("CCA")


def test_ring_imd_day_totals():
    text = (FIX / "nws_ring_20261115_0300.txt").read_text(encoding="ascii")
    versions = S.latest_versions(S.parse_bulletins(text, datetime(2026, 11, 15, 4, tzinfo=UTC), ("42", "43")))
    day = date(2026, 11, 15)
    assert S.imd_day_total(versions, "42170", day) == (1.0, "24h_group")     # regional '/' at 03 UTC = 24 h
    assert S.imd_day_total(versions, "43177", day) == (0.0, "ir3_zero")
    assert S.imd_day_total(versions, "42328", day) == (7.0, "24h_group")
    assert S.imd_day_total(versions, "99999", day) == (None, "no_03utc_report")


def test_ogimet_line_and_regional_since_03utc_periods():
    reports = _ogimet_reports()
    first = reports[1]                       # 2024-07-01 03 UTC
    assert first.station == "42111" and first.time == datetime(2024, 7, 1, 3, tzinfo=UTC)
    acc = first.accumulations[0]
    assert acc.amount_mm == 9.0 and S.resolve_period(first, acc) == 24
    noon = next(r for r in reports if r.time.hour == 12)
    assert S.resolve_period(noon, noon.accumulations[0]) == 9
    assert S.resolve_period(noon, noon.accumulations[0], since_03utc_blocks=()) is None


def test_ogimet_imd_days_match_ghcn_values():
    """GHCN-Daily (GSOD) has 8.9, 4.1, 130.0 mm for IMD days 1-3 July 2024 at this station: the 03 UTC amounts,
    never the sum of the cumulative intermediate groups."""
    versions = S.latest_versions(_ogimet_reports())
    totals = [S.imd_day_total(versions, "42111", date(2024, 7, d))[0] for d in (1, 2, 3)]
    assert totals == [9.0, 4.0, 130.0]


def _report(station, time, ir="1", accs=(), bulletin="SMXX01 TEST 010000"):
    return S.Report(station, time, ir, tuple(accs), bulletin)


def test_missing_and_not_observed_are_not_zero():
    end = datetime(2026, 7, 2, 3, tzinfo=UTC)
    versions = S.latest_versions([_report("10001", end, ir="4"), _report("10002", end - timedelta(hours=3), ir="3")])
    assert S.imd_day_total(versions, "10001", date(2026, 7, 2)) == (None, "ir4_not_observed")
    assert S.imd_day_total(versions, "10002", date(2026, 7, 2)) == (None, "no_03utc_report")


def test_partition_never_double_counts_overlaps():
    day = date(2026, 7, 2)
    end = datetime(2026, 7, 2, 3, tzinfo=UTC)
    accs = {
        end - timedelta(hours=12): [S.Accumulation(5.0, 12, "6")],        # 03-15 UTC
        end - timedelta(hours=6): [S.Accumulation(4.0, 6, "6")],          # 15-21 (overlaps the 18 h group below)
        end - timedelta(hours=3): [S.Accumulation(2.0, 3, "6")],          # 21-00 ... with the 00-03 group
        end: [S.Accumulation(1.0, 3, "6")],
    }
    reports = [_report("20001", t, accs=a) for t, a in accs.items()]
    reports.append(_report("20001", end - timedelta(hours=9), accs=[S.Accumulation(50.0, 15, "6")]))  # 03-18, overlaps
    # 03 UTC report exists but carries only a 3-hour group: chain 03-15 (5) + 15-21 (4) + 21-00 (2) + 00-03 (1)
    total, how = S.imd_day_total(S.latest_versions(reports), "20001", day, since_03utc_blocks=())
    assert (total, how) == (12.0, "partition")


def test_partial_chain_gives_no_value():
    end = datetime(2026, 7, 2, 3, tzinfo=UTC)
    reports = [_report("20002", end - timedelta(hours=12), accs=[S.Accumulation(5.0, 12, "6")])]
    assert S.imd_day_total(S.latest_versions(reports), "20002", date(2026, 7, 2), since_03utc_blocks=()) == \
        (None, "no_03utc_report")


def test_corrections_outrank_and_equal_versions_must_agree():
    end = datetime(2026, 7, 2, 3, tzinfo=UTC)
    original = _report("42001", end, accs=[S.Accumulation(10.0, 24, "6")], bulletin="SIIN20 DEMS 020300")
    retrans = _report("42001", end, accs=[S.Accumulation(12.0, 24, "6")], bulletin="SIIN20 DEMS 020300 RRA")
    corrected = _report("42001", end, accs=[S.Accumulation(11.0, 24, "6")], bulletin="SIIN20 DEMS 020300 CCA")
    day = date(2026, 7, 2)
    assert S.imd_day_total(S.latest_versions([original, retrans]), "42001", day) == (None, "conflicting_versions")
    assert S.imd_day_total(S.latest_versions([original, retrans, corrected]), "42001", day) == (11.0, "24h_group")


def test_two_different_24h_groups_in_one_report_give_no_value():
    end = datetime(2026, 7, 2, 3, tzinfo=UTC)
    rep = _report("42002", end, accs=[S.Accumulation(10.0, 24, "6s3"), S.Accumulation(20.0, 24, "7s3")])
    assert S.imd_day_total(S.latest_versions([rep]), "42002", date(2026, 7, 2)) == (None, "conflicting_24h_groups")


@pytest.mark.parametrize("ref_day,expected", [(15, (2026, 11)), (1, (2026, 11))])
def test_month_from_reference(ref_day, expected):
    assert S._month_of(ref_day, datetime(2026, 11, 15, tzinfo=UTC)) == expected


def test_month_rolls_back_at_month_start():
    assert S._month_of(31, datetime(2026, 11, 1, 2, tzinfo=UTC)) == (2026, 10)


def test_agreement_metrics_and_criterion():
    from aetherguard.ingest.synop_eval import agreement, criterion_met
    a = [0.0, 10.0, 20.0, 0.5, float("nan")]
    b = [0.0, 10.0, 22.0, 3.0, 5.0]
    m = agreement(a, b, 3.0, 0.68)
    assert m["n"] == 4 and abs(m["wet_hit_rate"] - 2 / 3) < 1e-9 and m["false_wet_share"] == 0.0
    assert m["within_tolerance"] == 1.0 and abs(m["bias_mm"] - (-1.125)) < 1e-9
    assert not criterion_met(m)          # bias -1.125 mm is beyond 0.5 mm
    assert criterion_met(agreement([0.0, 10.0, 20.0], [0.0, 10.0, 20.0], 3.0, 0.68))
