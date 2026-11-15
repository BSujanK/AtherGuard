"""SYNOP store: ring collection, OGIMET backfill, cut-off and station-day totals (fakes and recorded fixtures only)."""
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from aetherguard.ingest import synop_store as T

FIX = Path(__file__).parent / "fixtures" / "synop"
UTC = timezone.utc
RING = (FIX / "nws_ring_20261115_0300.txt").read_bytes()
LISTING = ("-rwxrwxr-x    1 7001     sshd     6626 Nov 15 03:20 sn.0216.txt\n"
           "-rwxrwxr-x    1 7001     sshd     1824 Dec 31 23:55 sn.0001.txt\n"
           "drwxr-xr-x    2 7001     sshd     4096 Nov 15 03:20 subdir\n")


def test_listing_years_and_entries():
    now = datetime(2026, 11, 15, 5, 30, tzinfo=UTC)
    entries = T.parse_listing(LISTING, now)
    assert entries == [("sn.0216.txt", 6626, datetime(2026, 11, 15, 3, 20, tzinfo=UTC)),
                       ("sn.0001.txt", 1824, datetime(2025, 12, 31, 23, 55, tzinfo=UTC))]


def test_collect_is_idempotent_and_records_arrival(tmp_path):
    calls = []

    def fetch(url):
        calls.append(url)
        return LISTING.encode() if url.endswith("ls-l") else RING
    now = datetime(2026, 11, 15, 5, 30, tzinfo=UTC)
    first = T.collect(tmp_path, fetch=fetch, now=now, blocks=("42", "43"))
    assert first["new_files"] == 2 and first["reports_added"] > 0
    second = T.collect(tmp_path, fetch=fetch, now=now, blocks=("42", "43"))
    assert second["new_files"] == 0 and second["reports_added"] == 0
    assert sum(not u.endswith("ls-l") for u in calls) == 2
    store = T.load_store(T.store_path(tmp_path))
    row = store[store["station"] == "42170"].sort_values("arrival").iloc[0]
    assert row["arrival"] == pd.Timestamp("2025-12-31 23:55", tz="UTC") or row["arrival"] == pd.Timestamp(
        "2026-11-15 03:20", tz="UTC")
    assert (T.raw_root(tmp_path) / "nws" / "20261115" / "0320_sn.0216.txt").is_file()


def test_cutoff_and_totals(tmp_path):
    def fetch(url):
        return b"-rwxrwxr-x 1 7001 sshd 6626 Nov 15 03:20 sn.0216.txt\n" if url.endswith("ls-l") else RING
    T.collect(tmp_path, fetch=fetch, now=datetime(2026, 11, 15, 5, 30, tzinfo=UTC), blocks=("42", "43"))
    store = T.load_store(T.store_path(tmp_path))
    assert T.usable_at(store, datetime(2026, 11, 15, 3, 0, tzinfo=UTC), 2.5).empty
    usable = T.usable_at(store, datetime(2026, 11, 15, 5, 30, tzinfo=UTC), 2.5)
    days = pd.date_range("2026-11-14", "2026-11-15", freq="D")
    values, how = T.station_day_totals(T.to_reports(usable), {"IN_A": "42170", "IN_B": "43177", "IN_C": "42111"}, days)
    assert values.loc["2026-11-15", "IN_A"] == 1.0 and values.loc["2026-11-15", "IN_B"] == 0.0
    assert pd.isna(values.loc["2026-11-15", "IN_C"]) and how.loc["2026-11-15", "IN_C"] == "no_03utc_report"
    assert pd.isna(values.loc["2026-11-14", "IN_A"])


def test_backfill_reuses_raw_files_and_has_no_arrival(tmp_path):
    lines = (FIX / "ogimet_42111_20240701.txt").read_bytes()
    calls = []

    def fetch(params):
        calls.append(params)
        return lines if params["block"] == "42" else b""
    T.backfill_ogimet(date(2024, 7, 1), date(2024, 7, 3), tmp_path, blocks=("42", "44"), fetch=fetch, pause_s=0)
    T.backfill_ogimet(date(2024, 7, 1), date(2024, 7, 3), tmp_path, blocks=("42", "44"), fetch=fetch, pause_s=0)
    assert [c["block"] for c in calls] == ["42", "44", "44"]      # the empty block is asked again, the stored one not
    store = T.load_store(T.store_path(tmp_path))
    assert store["arrival"].isna().all() and set(store["source"]) == {"ogimet"}
    usable = T.usable_at(store, datetime(2024, 7, 2, 5, 30, tzinfo=UTC), 2.5)
    values, _ = T.station_day_totals(T.to_reports(usable), {"IN023160900": "42111"},
                                     pd.date_range("2024-07-01", "2024-07-03", freq="D"))
    assert list(values["IN023160900"].fillna(-1)) == [9.0, 4.0, -1.0]   # 3 July's 03 UTC report is not due yet
