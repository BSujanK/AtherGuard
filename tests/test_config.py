from aetherguard import config


def test_project_root_contains_pyproject():
    assert (config.PROJECT_ROOT / "pyproject.toml").exists()


def test_data_dir_honours_override_and_creates(isolated_data_root):
    path = config.data_dir("raw", "x")
    assert path == isolated_data_root / "raw" / "x"
    assert path.is_dir()


def test_load_config_domain_has_regions_and_period():
    cfg = config.load_config("domain")
    assert cfg["cell_size_deg"] == 0.05
    assert set(cfg["regions"]) == {"himalaya", "western_ghats"}
    assert cfg["period"] == {"start": "2007-01-01", "end": "2024-12-31"}
