"""The season-of-validity flag (reports/phase8_season_validity.md): every lead dated outside the months the alert chain was
developed and tested on is flagged in run.json and the bulletin, never suppressed."""
import json
from datetime import date, timedelta

import pytest

from aetherguard.live import bulletin, season
from aetherguard.live import run as live_run
from aetherguard.live import season_validity as sv

import live_run_helpers as H


def test_the_declared_season_is_june_to_september_unless_configured():
    assert season.validated_months({}) == (6, 7, 8, 9)
    assert season.validated_months({"season_of_validity": {"months": [6, 7, 8, 9, 10]}}) == (6, 7, 8, 9, 10)
    assert not season.outside(date(2026, 7, 1), (6, 7, 8, 9)) and season.outside(date(2026, 11, 13), (6, 7, 8, 9))
    with pytest.raises(ValueError):
        season.validated_months({"season_of_validity": {"months": [0, 13]}})


def test_each_lead_is_judged_by_its_own_date():
    record = season.season_record(date(2026, 9, 30), {})
    assert record["flag"] == season.FLAG and record["months"] == [6, 7, 8, 9]
    assert record["leads"] == {"0": False, "1": True, "2": True, "3": True}
    assert record["any_outside"] is True


def test_an_in_season_run_carries_the_record_without_a_banner(tmp_path):
    cfg = H.make_cfg(tmp_path)
    summary = live_run.run_day(H.DAY, cfg, deps=H.make_deps())          # 12 August
    assert summary["season_of_validity"]["any_outside"] is False
    assert all(summary["leads"][k]["outside_validated_season"] is False for k in ("0", "1", "2", "3"))
    text = (live_run.project_path(cfg["report_dir"]) / f"{H.DAY}.md").read_text(encoding="utf-8")
    assert "outside the validated season" not in text.lower()


def test_an_out_of_season_run_is_flagged_and_still_published(tmp_path):
    day = date(2026, 11, 13)
    cfg = H.make_cfg(tmp_path)
    now = H.NOW + (day - H.DAY)
    summary = live_run.run_day(day, cfg, deps=H.make_deps(H.healthy_sources(day), now=lambda: now))
    assert summary["season_of_validity"]["any_outside"] is True
    assert all(summary["leads"][k]["outside_validated_season"] is True for k in ("0", "1", "2", "3"))
    assert summary["leads"]["0"]["published"] and summary["leads"]["0"]["levels"]["Emergency"] >= 1   # not suppressed
    text = (live_run.project_path(cfg["report_dir"]) / f"{day}.md").read_text(encoding="utf-8")
    assert "outside the validated season" in text.lower() and "June-September" in text


def test_the_bulletin_line_names_the_flagged_leads():
    summary = {"season_of_validity": season.season_record(date(2026, 9, 30), {})}
    line = " ".join(bulletin.season_lines(summary))
    assert "D+1" in line and "D+3" in line and "outside the validated season" in line.lower()
    assert bulletin.season_lines({}) == []                        # a summary from before the record has no line


def test_live_days_are_tabulated_by_month_and_model(tmp_path):
    for d, model, levels in (("2026-10-30", "m3", {"Normal": 90, "Watch": 6, "Warning": 3, "Emergency": 1}),
                             ("2026-11-13", "m4", {"Normal": 80, "Watch": 10, "Warning": 6, "Emergency": 4})):
        folder = tmp_path / d
        folder.mkdir()
        (folder / "run.json").write_text(json.dumps({"date": d, "model": {"dir": model}, "leads": {"0": {
            "n_cells": 100, "n_scored": 100, "levels": levels}}}), encoding="utf-8")
    rows = sv.live_days(tmp_path)
    table = sv.live_by_month(rows)
    assert table["11|m4"]["share"] == {"watch": 0.2, "warning": 0.1, "emergency": 0.04}
    assert table["10|m3"]["days"] == 1
