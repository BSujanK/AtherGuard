"""The bulletin (aetherguard.live.bulletin) is rendered from the run summary alone."""
import copy

import pandas as pd
import pytest

from aetherguard.live import bulletin, run as live_run
from aetherguard.serve import places as pl

import live_run_helpers as H


@pytest.fixture(scope="module")
def summary(tmp_path_factory):
    cfg = H.make_cfg(tmp_path_factory.mktemp("bulletin"))
    return live_run.run_day(H.DAY, cfg, deps=H.make_deps())


def test_every_section_is_present(summary):
    text = bulletin.render(summary)
    for heading in ("# AetherGuard live bulletin, 2026-08-12", "## Sources", "## Rain behind the last two IMD days",
                    "## Failed / missing sources", "## Alerts by lead", "## Top cells", "## Notes"):
        assert heading in text
    for name in bulletin.SOURCE_ORDER:
        assert f"`{name}`" in text
    assert "11:00+05:30" in text


def test_numbers_come_from_the_summary(summary):
    text = bulletin.render(summary)
    lead0 = summary["leads"]["0"]
    assert f"| D | 2026-08-12 | {lead0['n_cells']} | {lead0['n_scored']} | {lead0['levels']['Normal']} | " in text
    top = lead0["top_cells"][0]
    assert str(top["cell_id"]) in text and top["level_name"] in text and f"{top['lat']:.3f}, {top['lon']:.3f}" in text
    assert any(reason.split("=")[0] in text for reason in top["reasons"])
    changed = copy.deepcopy(summary)
    changed["leads"]["0"]["levels"]["Warning"] = 777
    assert "777" in bulletin.render(changed) and "777" not in text


def test_a_clean_run_reports_no_failures_except_the_missing_widening(summary):
    section = bulletin.render(summary).split("## Failed / missing sources")[1].split("## Alerts by lead")[0]
    assert "FAILED" not in section and "LATE" not in section
    assert "Forecast intervals not widened" in section


def test_failed_and_missing_things_are_named(summary):
    broken = copy.deepcopy(summary)
    broken["sources"]["imd_rt"].update(state="failed", ok=False, valid_through=None, error="TimeoutError: slow")
    broken["sources"]["gfs"].update(state="late", ok=False, error="forecast days D+3 are missing")
    broken["imerg_gaps"] = ["2026-08-11"]
    broken["integrity"].update(ran=False, reason="GHCN-Daily gauges unavailable")
    broken["leads"]["2"].update(published=False, reason="GFS forecast day D+2 not available")
    broken["forecast_widening"].update(applied=True, reason=None)
    broken["retry_recommended"], broken["retry_reason"] = True, "the rain of IMD day D could not be assembled"
    section = bulletin.render(broken).split("## Failed / missing sources")[1].split("## Alerts by lead")[0]
    assert "**IMD real-time rain** (`imd_rt`) FAILED: TimeoutError: slow" in section
    assert "(`gfs`) LATE or partial: forecast days D+3 are missing" in section
    assert "UTC day(s) 2026-08-11" in section and "Insufficient" in section
    assert "Integrity engine did not run" in section and "GHCN-Daily gauges unavailable" in section
    assert "Forecast lead D+2 not published" in section and "Retry recommended" in section
    assert "Forecast intervals not widened" not in section
    assert "| D+2 | 2026-08-14 | not published" in bulletin.render(broken)


def test_a_run_without_failures_says_so(summary):
    clean = copy.deepcopy(summary)
    clean["forecast_widening"].update(applied=True)
    section = bulletin.render(clean).split("## Failed / missing sources")[1].split("## Alerts by lead")[0]
    assert "None. Every source delivered" in section


def test_backtest_runs_say_so(summary):
    backtest = copy.deepcopy(summary)
    backtest["backtest"] = True
    assert "backtest (inputs issued before the data cut-off only)" in bulletin.render(backtest)


def test_the_cell_set_is_stated(summary):
    text = bulletin.render({**summary, "cell_set": {"assessed": 36792, "in_scope": 91290, "not_assessed": 54498,
                                                      "slope_floor_deg": 2.544, "definition": "the model's candidate cells"}})
    assert "Cells assessed: 36792 of 91290" in text and "not assessed: 54498" in text and "2.54" in text
    assert "not written to the risk tables" in text
    unknown = bulletin.render({**summary, "cell_set": {"assessed": 4, "in_scope": None, "not_assessed": None,
                                                         "slope_floor_deg": None, "definition": "injected"}})
    assert "Cells assessed: 4" in unknown


def test_without_place_names_the_top_tables_have_no_place_column(summary):
    text = bulletin.render(summary)
    assert "| cell | lat, lon |" in text and "| place |" not in text


def test_place_names_add_a_column_to_the_top_tables(summary):
    top = summary["leads"]["0"]["top_cells"][0]["cell_id"]
    text = bulletin.render(summary, {top: "Mananthavady, Wayanad, Kerala"})
    assert "| cell | place | lat, lon |" in text
    assert f"| {top} | Mananthavady, Wayanad, Kerala |" in text
    other = [c["cell_id"] for c in summary["leads"]["0"]["top_cells"][1:2]]
    if other:
        assert f"| {other[0]} | - |" in text


def write_table(path, rows):
    pd.DataFrame(rows, columns=pl.TABLE_COLUMNS).to_parquet(path, index=False)


def test_place_labels_read_the_table_and_name_far_cells_with_their_distance(tmp_path):
    write_table(tmp_path / "t.parquet", [(1, "Mananthavady", "Wayanad", "Kerala", "India", 8, 11.8, 76.0, 41000),
                                         (2, "Kathmandu", None, "Bagmati Province", "Nepal", 40, 27.7, 85.3, 10 ** 6)])
    assert bulletin.place_labels(tmp_path / "t.parquet", [1, 2, 3]) == {
        1: "Mananthavady, Wayanad, Kerala", 2: "Kathmandu, Bagmati Province, Nepal (40 km)"}


def test_place_labels_are_empty_when_the_table_is_absent_or_unreadable(tmp_path):
    assert bulletin.place_labels(None, [1]) == {}
    assert bulletin.place_labels(tmp_path / "none.parquet", [1]) == {}
    (tmp_path / "bad.parquet").write_bytes(b"x")
    assert bulletin.place_labels(tmp_path / "bad.parquet", [1]) == {}
    pd.DataFrame({"cell_id": [1]}).to_parquet(tmp_path / "thin.parquet")
    assert bulletin.place_labels(tmp_path / "thin.parquet", [1]) == {}


def test_a_run_writes_the_place_column_when_the_table_exists(tmp_path):
    cfg = H.make_cfg(tmp_path)
    probe = live_run.run_day(H.DAY, cfg, deps=H.make_deps())
    top = probe["leads"]["0"]["top_cells"][0]["cell_id"]
    (tmp_path / "second").mkdir()
    cfg = H.make_cfg(tmp_path / "second")
    write_table(tmp_path / "second" / "cell_places.parquet", [(top, "Mananthavady", "Wayanad", "Kerala", "India", 8, 11.8, 76.0, 41000)])
    live_run.run_day(H.DAY, cfg, deps=H.make_deps())
    text = (live_run.project_path(cfg["report_dir"]) / f"{H.DAY}.md").read_text(encoding="utf-8")
    assert f"| {top} | Mananthavady, Wayanad, Kerala |" in text


def test_the_forecast_rain_section_names_the_source_and_the_certainty_counts(summary):
    text = bulletin.render(summary)
    assert "## Forecast rain and certainty" in text
    lead = summary["leads"]["2"]
    assert f"| D+2 | NOAA GFS | 2026-08-12 00:00 | forecast x high widening factor | {lead['certainty']['firm']} | " \
           f"{lead['certainty']['depends_on_forecast']} |" in text
    assert "CC BY 4.0" not in text                                  # no ECMWF in this run


def test_ecmwf_is_attributed_and_listed_when_a_lead_uses_it(summary):
    changed = copy.deepcopy(summary)
    for info in changed["forecast_rain"]["leads"].values():
        info.update(source="ecmwf_hres", label="ECMWF IFS HRES (CC BY 4.0)", wet_bound="ensemble_spread")
    changed["sources"]["ecmwf"] = {"name": "ecmwf", "ok": False, "valid_through": None, "issued": None, "latency_h": None,
                                   "error": "ensemble has no data", "state": "late"}
    text = bulletin.render(changed)
    assert "ECMWF IFS HRES (CC BY 4.0) | 2026-08-12 00:00 | ensemble upper spread" in text
    assert "Contains ECMWF open data (IFS), licensed CC BY 4.0" in text
    assert "(`ecmwf`) LATE or partial: ensemble has no data" in text and "use GFS" in text


def test_a_summary_from_before_section_12_has_no_forecast_rain_section(summary):
    old = copy.deepcopy(summary)
    del old["forecast_rain"]
    assert "Forecast rain and certainty" not in bulletin.render(old)
