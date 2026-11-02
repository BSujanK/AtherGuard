"""Build the replay store: score a frozen feature table, run the alert engine, write per-day tables.

    python -m aetherguard.alerts.replay [--sets NAME ...] [--out DIR] [--features DIR] [--label TEXT]

Before anything is read the hazard model's freeze record is verified (`hazard.freeze.verify_freeze`); on a mismatch
or a missing record the build refuses to run, permanently. For each set (default: the case sets, the 2023 window and
the test_2018 sample and universe) the feature table is joined with its `integ_` and `corr_` columns (case sets via
`cases.series.load_case_frame`), scored with the saved hazard model, explained
(SHAP top 5), run through `engine.run_alerts` with the out-of-fold integrity engine outputs (causal flags, see
`integrity.hazard_features.causal_flags`) and written under `<out>/<set>/alerts|sensors/<date>.parquet`. The manifest
records the model card hash, the Watch/Warning/Emergency thresholds with their source, the alert config and the inputs.
`--label` marks a store as provisional (e.g. built from a model that is not the frozen one).
"""
from __future__ import annotations

import argparse
import logging
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd

from ..cases import series as cases
from ..hazard import data as hd
from ..hazard import model as hm
from ..hazard.freeze import verify_freeze
from ..integrity.common import integrity_dir
from ..integrity.hazard_features import causal_flags
from ..integrity.stations import select_station_meta
from ..manifest import sha256_file
from . import levels as lv
from .config import AlertConfig, alerts_settings, default_config_path, load_config_file
from .engine import run_alerts
from .frames import load_feature_frame
from .stations import station_states
from .store import default_store_dir, sensor_table, write_manifest, write_set

REPLAY_SETS = ("case_kerala_2018_samples", "case_wayanad_2024_samples", "window_2023_samples", "universe_test_2018",
               "test_2018_samples")
OOF_OUTPUTS = "engine_outputs_2007_oof.parquet"
CASE_OF_SET = {spec["features"]: case for case, spec in cases.CASES.items()}

log = logging.getLogger(__name__)


def load_station_outputs(path: Path | None = None) -> pd.DataFrame:
    """Out-of-fold engine outputs on the real series with the causal flags substituted for `flagged`."""
    path = Path(path or integrity_dir() / OOF_OUTPUTS)
    if not path.is_file():
        raise FileNotFoundError(f"{path} not found; build the integrity engine outputs first")
    outputs = pd.read_parquet(path)
    return outputs.assign(flagged=causal_flags(outputs).astype(bool))


def load_set_frame(name: str, features_dir: Path, model_columns) -> pd.DataFrame:
    """The scorer frame of a set: case sets through `cases.series.load_case_frame` (features + integ + corr), the others
    through `frames.load_feature_frame`."""
    if name in CASE_OF_SET:
        return cases.load_case_frame(CASE_OF_SET[name], features_dir)
    return load_feature_frame(name, features_dir, model_columns)


def replay_set(features: pd.DataFrame, scorer: Callable, explainer: Callable | None, station_outputs: pd.DataFrame,
               stations: pd.DataFrame, thresholds: lv.Thresholds, config: AlertConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(alerts, sensor table) of one feature frame. Station outputs are cut to the trailing window before the
    first date so the out-of-distribution states of the replayed days are complete."""
    first = features["date"].min() - pd.Timedelta(days=config.ood_window_days)
    window = station_outputs[(station_outputs["date"] >= first) & (station_outputs["date"] <= features["date"].max())]
    alerts = run_alerts(features, scorer(features), window, stations=stations, thresholds=thresholds, config=config,
                        contributions=explainer(features) if explainer else None)
    days = pd.DatetimeIndex(alerts["date"].unique())
    states = station_states(window, config)
    sensors = sensor_table(states[states["date"].isin(days)], stations)
    return alerts, sensors


def build_replay(set_names, out_dir: Path, *, features_dir: Path, model_columns, scorer: Callable,
                 explainer: Callable | None, thresholds: lv.Thresholds, config: AlertConfig,
                 station_outputs: pd.DataFrame, stations: pd.DataFrame, freeze: dict,
                 manifest_fields: dict | None = None) -> dict:
    """Write the replay store for `set_names` and return its manifest. `freeze` is the verified freeze record of the
    hazard model (the result of `verify_freeze`); it is stored in the manifest."""
    if not freeze or "sha256" not in freeze:
        raise ValueError("a verified freeze record of the hazard model is required to build a replay store")
    entries = {}
    for name in set_names:
        features = load_set_frame(name, features_dir, model_columns)
        alerts, sensors = replay_set(features, scorer, explainer, station_outputs, stations, thresholds, config)
        entries[name] = write_set(out_dir, name, alerts, sensors)
        entries[name]["features_sha256"] = sha256_file(Path(features_dir) / f"{name}_features.parquet")
        log.info("replay set %s: %d rows, %d days", name, entries[name]["n_rows"], len(entries[name]["dates"]))
    return write_manifest(out_dir, entries, freeze={"created_utc": freeze.get("created_utc"),
                                                    "card_sha256": freeze["sha256"].get("card.json")},
                          **(manifest_fields or {}))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sets", nargs="+", default=list(REPLAY_SETS), help="feature table names to replay")
    parser.add_argument("--out", type=Path, default=None, help="replay store directory")
    parser.add_argument("--features", type=Path, default=None, help="feature store directory")
    parser.add_argument("--model", type=Path, default=None, help="hazard model directory")
    parser.add_argument("--config", type=Path, default=None, help="alert_config.json")
    parser.add_argument("--no-shap", action="store_true", help="skip the SHAP explanations")
    parser.add_argument("--label", default=None, help="mark the store as provisional with this text")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    model_dir = Path(args.model or hm.default_model_dir())
    freeze = verify_freeze(model_dir)          # raises FrozenMismatchError: nothing is built from an unfrozen model
    model = hm.load_cached(model_dir)
    config_path = Path(args.config or default_config_path())
    config = load_config_file(config_path)
    thresholds = lv.thresholds_from_card(model.card, alerts_settings()["v1_card_fallback"])
    features_dir = Path(args.features or hd.features_dir())
    oof_path = integrity_dir() / OOF_OUTPUTS
    out_dir = Path(args.out or default_store_dir())
    fields = {"created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "provisional": args.label,
              "model": {"card_path": hm.display_path(model_dir / hm.CARD_FILE),
                        "card_sha256": sha256_file(model_dir / hm.CARD_FILE), "n_columns": len(model.columns)},
              "thresholds": thresholds.to_dict(),
              "alert_config": {"path": hm.display_path(config_path), "sha256": sha256_file(config_path),
                               "parameters": config.to_dict()},
              "station_outputs": {"path": hm.display_path(oof_path), "sha256": sha256_file(oof_path),
                                  "flags": "causal (integrity.hazard_features.causal_flags)"},
              "python": platform.python_version()}
    manifest = build_replay(args.sets, out_dir, features_dir=features_dir, model_columns=model.columns,
                            scorer=model.score, explainer=None if args.no_shap else model.contributions,
                            thresholds=thresholds, config=config, station_outputs=load_station_outputs(),
                            stations=select_station_meta(), freeze=freeze, manifest_fields=fields)
    print(f"replay store written to {out_dir}: " + ", ".join(
        f"{n} ({e['n_rows']} rows, {len(e['dates'])} days)" for n, e in manifest["sets"].items()))
    print(f"thresholds: {thresholds.to_dict()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
