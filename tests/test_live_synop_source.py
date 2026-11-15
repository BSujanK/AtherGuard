"""The live `synop` source, the GHCN flag-H zeros and the gauge merge (recorded ring fixture; no network)."""
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from aetherguard.ingest import synop_store as T
from aetherguard.live import sources as src
from aetherguard.live.run import synop_summary

FIX = Path(__file__).parent / "fixtures" / "synop"
UTC = timezone.utc
DAY = date(2026, 11, 15)
META = pd.DataFrame({"id": ["IN_A", "IN_B", "IN_C"], "lat": [30.0, 12.0, 25.0], "lon": [77.0, 75.0, 80.0]})
WMO = {"IN_A": "42170", "IN_B": "43177", "IN_C": "42111"}


def _store(tmp_path) -> Path:
    ring = (FIX / "nws_ring_20261115_0300.txt").read_bytes()
    listing = b"-rwxrwxr-x 1 7001 sshd 6626 Nov 15 03:20 sn.0216.txt\n"
    T.collect(tmp_path, fetch=lambda url: listing if url.endswith("ls-l") else ring,
              now=datetime(2026, 11, 15, 5, 30, tzinfo=UTC), blocks=("42", "43"))
    return T.store_path(tmp_path)


def _ctx(tmp_path, cutoff):
    return src.FetchContext(day=DAY, cfg={}, raw_dir=tmp_path / "raw", now=datetime(2026, 11, 16, tzinfo=UTC),
                            cutoff=cutoff)


def _source(store):
    return src.SynopSource(look_back_days=5, latency_h=2.0, store=store, stations=lambda: META.copy(),
                           wmo=lambda: dict(WMO), collector=lambda: (_ for _ in ()).throw(AssertionError("no fetch")))


def test_h_zero_rows_are_missing_only_when_asked():
    rows = [{"DATE": "2026-11-10", "STATION": "S1", "PRCP": "0.0", "PRCP_ATTRIBUTES": "H,,2"},
            {"DATE": "2026-11-10", "STATION": "S2", "PRCP": "0.0", "PRCP_ATTRIBUTES": ",,S"},
            {"DATE": "2026-11-10", "STATION": "S3", "PRCP": "4.0", "PRCP_ATTRIBUTES": "H,,2"}]
    index = pd.date_range("2026-11-10", "2026-11-10")
    kept = src.ghcn_rows_to_frame(rows, index, ["S1", "S2", "S3"])
    dropped = src.ghcn_rows_to_frame(rows, index, ["S1", "S2", "S3"], h_zero_as_missing=True)
    assert kept.iloc[0].tolist() == [0.0, 0.0, 4.0]
    assert np.isnan(dropped.iloc[0, 0]) and dropped.iloc[0, 1:].tolist() == [0.0, 4.0]


def test_synop_source_in_backtest_reads_only_what_had_arrived(tmp_path):
    store = _store(tmp_path)
    source = _source(store)
    status = source.fetch(_ctx(tmp_path, datetime(2026, 11, 15, 5, 30, tzinfo=UTC)))
    assert status.ok and status.valid_through == datetime(2026, 11, 15, 3, tzinfo=UTC)
    data = source.load(None)
    assert data.values.loc["2026-11-15", "IN_A"] == 1.0 and data.values.loc["2026-11-15", "IN_B"] == 0.0
    assert np.isnan(data.values.loc["2026-11-15", "IN_C"]) and data.how.loc["2026-11-15", "IN_C"] == "no_03utc_report"
    early = _source(store).fetch(_ctx(tmp_path, datetime(2026, 11, 15, 3, 10, tzinfo=UTC)))
    assert not early.usable and "no SYNOP" in early.error


def test_merge_prefers_synop_and_keeps_ghcn_elsewhere(tmp_path):
    store = _store(tmp_path)
    source = _source(store)
    source.fetch(_ctx(tmp_path, datetime(2026, 11, 15, 5, 30, tzinfo=UTC)))
    index = pd.date_range("2026-11-11", "2026-11-15")
    ghcn_values = pd.DataFrame(np.nan, index=index, columns=META["id"], dtype=np.float32)
    ghcn_values.loc["2026-11-11"] = [2.0, 3.0, 4.0]
    ghcn = src.GhcnData(values=ghcn_values, meta=META)
    merged = src.merge_gauges(ghcn, source.load(None))
    assert merged.values.loc["2026-11-11"].tolist() == [2.0, 3.0, 4.0]
    assert merged.values.loc["2026-11-15", "IN_A"] == 1.0 and np.isnan(merged.values.loc["2026-11-15", "IN_C"])
    assert src.merge_gauges(ghcn, None) is ghcn
    summary = synop_summary({"synop": {"enabled": True}, "ghcn": {}}, ghcn, source.load(None), DAY)
    assert summary["stations_on_day_ghcn"] == 0 and summary["stations_on_day_merged"] == 2
    assert synop_summary({"ghcn": {}}, ghcn, source.load(None), DAY) is None


def test_default_sources_register_synop_only_when_enabled(monkeypatch):
    from aetherguard.config import PROJECT_ROOT, load_config_file
    cfg = load_config_file(PROJECT_ROOT / "configs" / "live_run.yaml")
    assert cfg["synop"]["enabled"] is False and cfg["ghcn"]["h_zero_as_missing"] is False
    monkeypatch.setattr("aetherguard.ingest.imerg.ImergStore", lambda *a, **k: None)
    assert "synop" not in src.default_sources(cfg)
    on = {**cfg, "synop": {**cfg["synop"], "enabled": True}}
    assert isinstance(src.default_sources(on)["synop"], src.SynopSource)
    assert src.expected_valid_through("synop", DAY, cfg) == datetime(2026, 11, 15, 3, tzinfo=UTC)


def test_replay_configs_stay_in_scratch_and_set_the_flags(tmp_path):
    import yaml
    from aetherguard.live.gauges_replay import set_config
    for name, synop, h in (("before", False, False), ("after", True, False), ("after_h", True, True)):
        cfg = yaml.safe_load(set_config(tmp_path, name).read_text(encoding="utf-8"))
        assert Path(cfg["live_dir"]).is_relative_to(tmp_path) and Path(cfg["replay_dir"]).is_relative_to(tmp_path)
        assert Path(cfg["report_dir"]).is_relative_to(tmp_path)
        assert cfg["synop"]["enabled"] is synop and cfg["synop"]["collect"] is False
        assert cfg["ghcn"]["h_zero_as_missing"] is h


class FakeSynop:
    """A synop source that delivers one same-day total for the first helper station."""
    name = "synop"

    def __init__(self, day):
        import live_run_helpers as H
        index = pd.date_range(pd.Timestamp(day) - pd.Timedelta(days=29), pd.Timestamp(day))
        values = pd.DataFrame(np.nan, index=index, columns=H.STATIONS["id"], dtype=np.float32)
        values.loc[pd.Timestamp(day), "GH000001"] = 12.0
        how = pd.DataFrame("no_03utc_report", index=index, columns=H.STATIONS["id"])
        how.loc[pd.Timestamp(day), "GH000001"] = "24h_group"
        self.data = src.SynopData(values=values, how=how, meta=H.STATIONS.copy())
        self.day = day

    def fetch(self, ctx):
        end = src.imd_day_end(self.day)
        return src.SourceStatus("synop", True, end, end, 0.0)

    def load(self, ctx):
        return self.data


def test_run_merges_same_day_synop_gauges(tmp_path):
    import json
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    import live_run_helpers as H
    from aetherguard.live import run as live_run
    cfg = H.make_cfg(tmp_path)
    cfg["synop"] = {**cfg["synop"], "enabled": True}
    sources = {**H.healthy_sources(), "synop": FakeSynop(H.DAY)}
    summary = live_run.run_day(H.DAY, cfg, deps=H.make_deps(sources))
    run = json.loads((Path(cfg["live_dir"]) / H.DAY.isoformat() / "run.json").read_text(encoding="utf-8"))
    assert run["integrity"]["ran"] and run["integrity"]["n_stations_observed"] == 1
    assert run["integrity"]["synop"]["stations_on_day_ghcn"] == 0
    assert run["integrity"]["synop"]["stations_on_day_merged"] == 1
    assert run["integrity"]["synop"]["how_on_day"]["24h_group"] == 1
    assert "synop" not in run["failed_sources"] and summary["audit"]["total_violations"] == 0
