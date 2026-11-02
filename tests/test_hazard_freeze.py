import json

import pytest

from aetherguard.hazard import freeze as fz


def _model_dir(tmp_path):
    model = tmp_path / "model"
    (model / "ensemble").mkdir(parents=True)
    for name in fz.MODEL_FILES:
        (model / name).write_text(f"content of {name}")
    for k in range(3):
        (model / "ensemble" / f"member_{k:02d}.txt").write_text(f"member {k}")
    config = tmp_path / "hazard.yaml"
    config.write_text("seed: 1")
    return model, {"config/hazard.yaml": config}


def test_freeze_records_every_file_and_verifies(tmp_path):
    model, external = _model_dir(tmp_path)
    path = fz.write_freeze(model, external)
    record = json.loads(path.read_text())
    assert set(record["sha256"]) == {*fz.MODEL_FILES, "ensemble/member_00.txt", "ensemble/member_01.txt",
                                     "ensemble/member_02.txt", "config/hazard.yaml"}
    assert all(len(v) == 64 for v in record["sha256"].values()) and record["created_utc"].endswith("Z")
    assert fz.verify_freeze(model, external)["sha256"] == record["sha256"]


@pytest.mark.parametrize("victim", ["model.txt", "card.json", "calibrator.json", "ensemble/member_01.txt"])
def test_any_changed_model_file_is_detected(tmp_path, victim):
    model, external = _model_dir(tmp_path)
    fz.write_freeze(model, external)
    (model / victim).write_text("tampered")
    with pytest.raises(fz.FrozenMismatchError, match="differs"):
        fz.verify_freeze(model, external)


def test_changed_config_missing_file_and_new_member_are_detected(tmp_path):
    model, external = _model_dir(tmp_path)
    fz.write_freeze(model, external)
    external["config/hazard.yaml"].write_text("seed: 2")
    with pytest.raises(fz.FrozenMismatchError, match="differs"):
        fz.verify_freeze(model, external)
    external["config/hazard.yaml"].write_text("seed: 1")
    fz.verify_freeze(model, external)
    (model / "ensemble" / "member_03.txt").write_text("extra")
    with pytest.raises(fz.FrozenMismatchError, match="new"):
        fz.verify_freeze(model, external)
    (model / "ensemble" / "member_03.txt").unlink()
    (model / "ensemble" / "member_00.txt").unlink()
    with pytest.raises(fz.FrozenMismatchError):
        fz.verify_freeze(model, external)


def test_unfrozen_model_and_rewrite_are_refused(tmp_path):
    model, external = _model_dir(tmp_path)
    with pytest.raises(fz.FrozenMismatchError, match="not been frozen"):
        fz.verify_freeze(model, external)
    fz.write_freeze(model, external)
    with pytest.raises(fz.FrozenMismatchError, match="never rewritten"):
        fz.write_freeze(model, external)
    with pytest.raises(fz.FrozenMismatchError, match="external files"):
        fz.verify_freeze(model, {})


def test_missing_files_fail_the_freeze(tmp_path):
    model, external = _model_dir(tmp_path)
    (model / "cv_results.json").unlink()
    with pytest.raises(fz.FrozenMismatchError, match="missing"):
        fz.write_freeze(model, external)


def test_jsonable_handles_timestamps_and_nat():
    import numpy as np
    import pandas as pd
    from aetherguard.hazard.jsonio import jsonable
    out = jsonable({"a": pd.Timestamp("2018-08-01"), "b": pd.NaT, "c": np.datetime64("2018-08-02")})
    assert out["a"].startswith("2018-08-01") and out["b"] is None and out["c"].startswith("2018-08-02")


# ------------------------------------------------------------------------------------------------ v3 freeze

def test_region_calibrator_is_part_of_the_freeze(tmp_path):
    model, external = _model_dir(tmp_path)
    (model / "calibrator_regions.json").write_text("per-region calibrators")
    fz.write_freeze(model, external)
    assert "calibrator_regions.json" in fz.verify_freeze(model, external)["sha256"]
    (model / "calibrator_regions.json").write_text("tampered")
    with pytest.raises(fz.FrozenMismatchError, match="calibrator_regions.json"):
        fz.verify_freeze(model, external)


def test_changed_model_is_not_refrozen_without_force_and_the_old_record_is_kept(tmp_path):
    model, external = _model_dir(tmp_path)
    first = json.loads(fz.write_freeze(model, external).read_text())
    (model / "card.json").write_text("retrained")
    with pytest.raises(fz.FrozenMismatchError, match="never rewritten"):
        fz.write_freeze(model, external)
    assert json.loads((model / fz.FROZEN_NAME).read_text()) == first
    second = json.loads(fz.write_freeze(model, external, force=True).read_text())
    assert second["sha256"]["card.json"] != first["sha256"]["card.json"]
    assert second["superseded"] == [{"created_utc": first["created_utc"], "sha256": first["sha256"]}]
    fz.verify_freeze(model, external)
    third = json.loads(fz.write_freeze(model, external, force=True).read_text())
    assert [s["sha256"] for s in third["superseded"]] == [first["sha256"], second["sha256"]]


def test_force_is_refused_once_a_test_evaluation_is_recorded(tmp_path):
    model, external = _model_dir(tmp_path)
    fz.write_freeze(model, external)
    (model / fz.EVALUATION_RECORD).write_text('{"runs": []}')
    (model / "card.json").write_text("retrained")
    with pytest.raises(fz.FrozenMismatchError, match="test evaluation"):
        fz.write_freeze(model, external, force=True)


def test_cli_freezes_the_v3_model_directory_with_its_own_config_and_cv_report(tmp_path, capsys):
    model, _ = _model_dir(tmp_path)
    (model / "calibrator_regions.json").write_text("regions")
    assert fz.main(["--config", str(fz.PROJECT_ROOT / "configs" / "hazard_v3.yaml"), "--model", str(model)]) == 0
    record = json.loads((model / fz.FROZEN_NAME).read_text())
    assert set(record["external_files"]) == {"config/hazard_v3.yaml", "report/phase6_v3_cv_report.json"}
    assert "calibrator_regions.json" in record["sha256"] and "froze" in capsys.readouterr().out
    assert fz.main(["--config", str(fz.PROJECT_ROOT / "configs" / "hazard_v3.yaml"), "--model", str(model)]) == 1
    assert "never rewritten" in capsys.readouterr().err
    assert fz.main(["--config", str(fz.PROJECT_ROOT / "configs" / "hazard_v3.yaml"), "--model", str(model),
                    "--force"]) == 0
