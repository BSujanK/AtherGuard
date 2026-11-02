import os
import stat

import pytest


@pytest.fixture
def isolated_data_root(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("AETHERGUARD_DATA_DIR", str(root))
    return root


@pytest.fixture
def splits_out_dir(tmp_path):
    """Output directory for frozen splits; files are read-only after a build, so restore write
    permission on teardown to let tmp_path cleanup succeed on Windows."""
    out = tmp_path / "splits"
    yield out
    if out.exists():
        for path in out.rglob("*"):
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
