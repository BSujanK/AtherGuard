import json
import re

import numpy as np
import pandas as pd
import pytest

from aetherguard.audit import report
from aetherguard.audit.report import collect_secrets, redact, render_markdown, write_reports
from aetherguard.audit.result import ProbeResult

CFG = {"reported_local_gauge_48h_mm": 572,
       "reference_point": {"name": "wayanad_meppadi", "lat": 11.55, "lon": 76.13}}


def _results():
    return [
        ProbeResult("open_meteo", "ok", "3 models",
                    {"event_rows": [{"label": "era5", "daily_mm": {"2024-07-29": 33.2, "2024-07-30": 73.9}}]},
                    "UTC calendar day (hourly values summed 00-23 UTC; timezone=UTC requested)"),
        ProbeResult("imd", "ok", "readable",
                    {"event_rows": [{"label": "imd_gauge_grid_0p25", "daily_mm": {"2024-07-29": 80.0, "2024-07-30": 200.0}}]},
                    "IMD rainfall day: 08:30 IST previous day to 08:30 IST"),
        ProbeResult("earthdata_credentials", "needs_login", "no credentials", {"leak": "hunter2-secret"}),
        ProbeResult("catalog_nasa_glc", "manual_pending", "file not found", {}),
    ]


def test_markdown_shows_day_definition_beside_every_rain_row():
    md = render_markdown(_results(), "2026-09-30T00:00:00Z", CFG)
    assert "UTC calendar day" in md
    assert "08:30 IST" in md
    assert "572" in md and "secondary" in md.lower()
    assert "needs_login" in md and "manual_pending" in md


def test_needs_attention_section_lists_non_ok_probes():
    md = render_markdown(_results(), "2026-09-30T00:00:00Z", CFG)
    section = md.split("## Needs human action")[1].split("\n## ")[0]
    assert "earthdata_credentials" in section and "catalog_nasa_glc" in section
    assert "open_meteo" not in section


def test_redact_replaces_secrets_and_ignores_short_or_empty_ones():
    assert redact("password is hunter2-secret ok", ["hunter2-secret"]) == "password is [REDACTED] ok"
    assert redact("abc", ["", "ab"]) == "abc"  # empty and very short values are never substituted


def test_written_reports_contain_no_secret_and_round_trip(tmp_path):
    md_path, json_path = write_reports(_results(), tmp_path, ["hunter2-secret"], CFG)
    assert "hunter2-secret" not in md_path.read_text(encoding="utf-8")
    text = json_path.read_text(encoding="utf-8")
    assert "hunter2-secret" not in text and "[REDACTED]" in text
    assert json.loads(text)["results"][0]["name"] == "open_meteo"


def test_render_handles_results_without_optional_evidence():
    md = render_markdown([ProbeResult("geolibs", "ok", "fine")], "2026-09-30T00:00:00Z", CFG)
    assert "# Phase 0 data audit" in md


# --- controller rulings beyond the brief -------------------------------------------------------

def _section(md: str, heading: str) -> str:
    return md.split(heading)[1].split("\n## ")[0]


def test_probe_problems_section_shows_reason_for_every_non_ok_probe():
    long_text = "x" * 1000
    results = [
        ProbeResult("open_meteo", "partial", "1/3 complete",
                    {"problems": ["era5_land precipitation: 24 null hourly values"]}),
        ProbeResult("osm_roads", "partial", "size unknown",
                    {"errors": ["africa: Content-Length missing or invalid (size unknown)"]}),
        ProbeResult("ghcnd", "partial", "some failed",
                    {"failed_downloads": [{"id": "IN001", "error": "HTTP 503", "kind": "download"}],
                     "n_selected": 3, "by_country": {"IN": 3}, "n_unknown_elevation": 2,
                     "census_by_group": {}}),
        ProbeResult("geolibs", "fail", "missing libs", {"missing": ["rasterio", "xarray"]}),
        ProbeResult("zenodo_x", "partial", "weak", {"problems": [long_text]}),
        ProbeResult("healthy", "ok", "fine", {"problems": ["should not be listed"]}),
    ]
    md = render_markdown(results, "2026-09-30T00:00:00Z", CFG)
    section = _section(md, "## Probe problems")
    assert "era5_land precipitation: 24 null hourly values" in section
    assert "Content-Length missing" in section
    assert "IN001" in section and "HTTP 503" in section
    assert "rasterio" in section and "xarray" in section
    assert "healthy" not in section and "should not be listed" not in section
    assert long_text not in section and "x" * 250 in section  # truncated, not dropped
    ghcnd = _section(md, "## Real fault labels")
    assert "unknown elevation: 2" in ghcnd.lower()
    assert "failed downloads: 1" in ghcnd.lower()


def test_probe_problems_section_says_none_when_all_ok():
    md = render_markdown([ProbeResult("geolibs", "ok", "fine")], "2026-09-30T00:00:00Z", CFG)
    assert "## Probe problems" in md
    assert "no probe problems" in _section(md, "## Probe problems").lower()


def test_unknown_volume_renders_na_not_none():
    results = [ProbeResult("worldcover", "ok", "tile reachable", {"est_total_gb": None}),
               ProbeResult("dem", "ok", "tile", {"est_total_gb": 1.5})]
    md = render_markdown(results, "2026-09-30T00:00:00Z", CFG)
    volumes = _section(md, "## Ingest feasibility and volumes")
    assert "| worldcover | n/a |" in volumes and "| dem | 1.5 |" in volumes
    assert "None" not in volumes


def test_json_is_strictly_valid_and_numpy_types_become_plain_python(tmp_path):
    evidence = {"nan": float("nan"), "inf": float("inf"), "ninf": float("-inf"),
                "f": np.float64(1.5), "i": np.int64(3), "b": np.bool_(True),
                "arr": np.array([1.0, np.nan, 2.0]), "tup": (1, 2), "nested": {"x": [np.float32(2.5)]},
                "when": pd.Timestamp("2024-07-30"), 7: "int key", "nan32": np.float32("nan")}
    results = [ProbeResult("probe", "ok", "s", evidence)]
    _, json_path = write_reports(results, tmp_path, [], CFG)

    def reject(token):
        raise AssertionError(f"non-finite token {token} in JSON")

    data = json.loads(json_path.read_text(encoding="utf-8"), parse_constant=reject)
    ev = data["results"][0]["evidence"]
    assert ev["nan"] is None and ev["inf"] is None and ev["ninf"] is None and ev["nan32"] is None
    assert ev["f"] == 1.5 and ev["i"] == 3 and ev["b"] is True
    assert ev["arr"] == [1.0, None, 2.0]
    assert ev["tup"] == [1, 2] and ev["nested"] == {"x": [2.5]}
    assert ev["when"].startswith("2024-07-30")
    assert ev["7"] == "int key"


def test_collect_secrets_reads_env_and_netrc_from_a_redirected_home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    for var in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(var, str(home))
    monkeypatch.delenv("EARTHDATA_USERNAME", raising=False)
    monkeypatch.delenv("EARTHDATA_PASSWORD", raising=False)
    assert collect_secrets() == []
    monkeypatch.setenv("EARTHDATA_USERNAME", "some-user")
    monkeypatch.setenv("EARTHDATA_PASSWORD", "some-pass-word")
    (home / ".netrc").write_text("machine urs.earthdata.nasa.gov login netrcuser password netrcpass1\n",
                                 encoding="utf-8")
    got = collect_secrets()
    assert {"some-user", "some-pass-word", "netrcuser", "netrcpass1"} <= set(got)


# --- review fixes: escaping, resilience, secret coverage ----------------------------------------

_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")
_GENERATED = "2026-09-30T00:00:00Z"
_ALL_HEADINGS = ("## Summary", "## Needs human action", "## Probe problems", "## Rain products",
                 "## Real fault labels", "## Landslide catalogs", "## Ingest feasibility and volumes")


def _markdown_tables(md: str) -> list[list[str]]:
    tables, current = [], []
    for line in md.splitlines():
        if line.startswith("|"):
            current.append(line)
        elif current:
            tables.append(current)
            current = []
    if current:
        tables.append(current)
    return tables


def _rich_results():
    return [
        ProbeResult("pipey", "fail", "a | b\nsecond line", {"problems": ["x | y\nz"]}),
        ProbeResult("open_meteo", "ok", "fine",
                    {"event_rows": [{"label": "era5 | land", "daily_mm": {"2024-07-29": 1.0}}]},
                    "UTC | day\ndefinition"),
        ProbeResult("ghcnd", "ok", "fine",
                    {"n_selected": 2, "by_country": {"IN": 2}, "n_unknown_elevation": 0, "failed_downloads": [],
                     "census_by_group": {"western_ghats|upland": {"n_stations": 1, "n_valid": 5, "n_flagged": 1,
                                                                  "by_flag": {"G": 1}}}}),
        ProbeResult("catalog_nasa_glc", "ok", "fine",
                    {"summary": {"kerala|x": {"n_total": 1, "n_located": 1, "n_unknown_accuracy": 0,
                                              "first_date": "2020-01-01", "last_date": "2020-01-02"}}}),
        ProbeResult("feasibility", "ok", "fine",
                    {"scenarios": [{"name": "full | domain", "points": 1, "days": 2, "call_units": 3,
                                    "days_at_free_limit": 4.0}]}),
        ProbeResult("dem", "ok", "tile", {"est_total_gb": 1.5}),
    ]


def test_pipes_and_newlines_in_cells_are_escaped_and_collapsed():
    md = render_markdown(_rich_results(), _GENERATED, CFG)
    for heading in ("## Summary", "## Needs human action"):
        section = _section(md, heading)
        assert "a \\| b second line" in section
    assert "a | b\nsecond line" not in md
    assert "region\\|elevation" in md


def test_every_table_row_has_as_many_unescaped_pipes_as_its_header():
    md = render_markdown(_rich_results(), _GENERATED, CFG)
    tables = _markdown_tables(md)
    assert len(tables) >= 6
    for table in tables:
        expected = len(_UNESCAPED_PIPE.findall(table[0]))
        for line in table:
            assert len(_UNESCAPED_PIPE.findall(line)) == expected, line


def _rendered_with(bad: ProbeResult) -> str:
    md = render_markdown([bad] + [r for r in _rich_results() if r.name != bad.name], _GENERATED, CFG)
    for heading in _ALL_HEADINGS:
        assert heading in md, heading
    return md


@pytest.mark.parametrize("bad", [
    ProbeResult("open_meteo", "partial", "s", {"event_rows": None}),
    ProbeResult("open_meteo", "partial", "s", {"event_rows": [{"label": "no values"}]}),
    ProbeResult("open_meteo", "partial", "s", {"event_rows": ["not a dict", {"label": "x", "daily_mm": "str"}]}),
    ProbeResult("open_meteo", "partial", "s",
                {"event_rows": [{"label": "x", "daily_mm": {"2024-07-29": "abc", "2024-07-30": None}}]}),
    ProbeResult("ghcnd", "partial", "s", {"census_by_group": {}}),
    ProbeResult("ghcnd", "partial", "s", {"census_by_group": {"g|upland": {"n_valid": 1}}}),
    ProbeResult("ghcnd", "partial", "s", {"census_by_group": {"g": "oops"}, "failed_downloads": None,
                                           "by_country": None}),
    ProbeResult("catalog_nasa_glc", "partial", "s", {"summary": "not a dict"}),
    ProbeResult("catalog_nasa_glc", "partial", "s", {"summary": {"r": {"n_total": 1}}}),
    ProbeResult("catalog_nasa_glc", "partial", "s", {"summary": {"r": None}}),
    ProbeResult("feasibility", "fail", "s", {}),
    ProbeResult("feasibility", "fail", "s", {"scenarios": [{"name": "only a name"}, "junk"]}),
    ProbeResult("dem", "partial", "s", {"est_total_gb": "weird"}),
])
def test_render_survives_malformed_or_partial_evidence(bad):
    _rendered_with(bad)


def test_non_numeric_and_non_finite_values_render_na_never_nan():
    nan = float("nan")
    results = [
        ProbeResult("open_meteo", "ok", "s",
                    {"event_rows": [{"label": "x", "daily_mm": {"2024-07-29": nan, "2024-07-30": 5.0}},
                                    {"label": "y", "daily_mm": {"2024-07-29": float("inf"), "2024-07-30": "abc"}}]},
                    "UTC day"),
        ProbeResult("dem", "ok", "s", {"est_total_gb": nan}),
        ProbeResult("worldcover", "ok", "s", {"est_total_gb": float("inf")}),
    ]
    md = render_markdown(results, _GENERATED, CFG)
    table_lines = [line.lower() for line in md.splitlines() if line.startswith("|")]
    assert table_lines and not any("nan" in line or "inf" in line for line in table_lines)
    assert "| dem | n/a |" in md and "| worldcover | n/a |" in md
    rows = [line for line in md.splitlines() if line.startswith("| x ") or line.startswith("| y ")]
    assert len(rows) == 2 and all("n/a" in row for row in rows)


def test_a_crashing_section_builder_does_not_stop_the_rest(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(report, "_rain_section", boom)
    md = render_markdown(_rich_results(), _GENERATED, CFG)
    assert "_section could not be rendered: RuntimeError_" in md
    assert "kaboom" not in md
    for heading in _ALL_HEADINGS:
        assert heading in md
    assert "western_ghats" in md


def test_probes_that_ran_and_failed_are_not_reported_as_not_run():
    results = [ProbeResult("ghcnd", "unreachable", "network error: offline"),
               ProbeResult("feasibility", "fail", "missing config key"),
               ProbeResult("manual_catalogs", "inconclusive", "probe raised KeyError")]
    md = render_markdown(results, _GENERATED, CFG)
    for heading in ("## Real fault labels", "## Landslide catalogs", "## Ingest feasibility and volumes"):
        section = _section(md, heading)
        assert "probe did not return data" in section and "Not run" not in section
    none_run = render_markdown([ProbeResult("geolibs", "ok", "fine")], _GENERATED, CFG)
    assert "_Not run._" in _section(none_run, "## Real fault labels")


def test_header_explains_difference_between_problems_and_needs_action():
    md = render_markdown([ProbeResult("geolibs", "ok", "fine")], _GENERATED, CFG)
    header = md.split("## Summary")[0]
    assert "Probe problems" in header and "partial" in header and "Needs human action" in header


SECRET = "hunter2-secret"
AWKWARD = 'p"sséword99'


def _secret_results():
    return [
        ProbeResult("a", "fail", f"login failed for {SECRET}", {"problems": [f"bad token {SECRET}"],
                                                               "traceback": f"Traceback ... {SECRET}"}),
        ProbeResult("b", "partial", f"awkward {AWKWARD} here",
                    {"problems": [f"pw={AWKWARD}"], "traceback": f"File x: {AWKWARD}"}),
        ProbeResult("c", "fail", "pa|ss  wo\nrd99 leaked", {"problems": ["pa|ss  wo\nrd99 again"]}),
    ]


def test_secrets_in_summary_problems_and_traceback_never_reach_either_file(tmp_path):
    awkward_pipe = "pa|ss  wo\nrd99"
    secrets = [SECRET, AWKWARD, awkward_pipe]
    md_path, json_path = write_reports(_secret_results(), tmp_path, secrets, CFG)
    md, js = md_path.read_text(encoding="utf-8"), json_path.read_text(encoding="utf-8")
    for text in (md, js):
        assert SECRET not in text and AWKWARD not in text and awkward_pipe not in text
        assert json.dumps(AWKWARD)[1:-1] not in text and json.dumps(awkward_pipe)[1:-1] not in text
        assert "pa\\|ss" not in text and "rd99" not in text.replace("[REDACTED]", "")
    assert "[REDACTED]" in md and "[REDACTED]" in js
    assert "Traceback" in js  # the surrounding text is kept, only the secret is replaced


def test_collect_secrets_never_raises_on_unreadable_netrc(monkeypatch):
    def boom():
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad byte")

    monkeypatch.setattr(report.netrc, "netrc", boom)
    monkeypatch.setenv("EARTHDATA_USERNAME", "some-user")
    monkeypatch.delenv("EARTHDATA_PASSWORD", raising=False)
    assert collect_secrets() == ["some-user"]


def test_collect_secrets_ignores_a_too_short_token(monkeypatch, tmp_path):
    for var in ("EARTHDATA_USERNAME", "EARTHDATA_PASSWORD", "EARTHDATA_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    for var in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(var, str(tmp_path))
    monkeypatch.setenv("EARTHDATA_TOKEN", "ab")  # shorter than the minimum length: never redacted
    assert collect_secrets() == []
