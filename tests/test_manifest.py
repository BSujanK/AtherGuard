import hashlib

from aetherguard.manifest import Manifest


def _setup(tmp_path):
    root = tmp_path / "data"
    f = root / "raw" / "a.txt"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"hello")
    return root, f, Manifest(tmp_path / "manifest.jsonl", root)


def test_add_records_size_hash_and_relative_path(tmp_path):
    root, f, m = _setup(tmp_path)
    e = m.add(f, "test", "http://x/a.txt", "CC0")
    assert e.path == "raw/a.txt"
    assert e.size_bytes == 5
    assert e.sha256 == hashlib.sha256(b"hello").hexdigest()
    assert m.is_current(f)
    assert m.verify() == []


def test_verify_detects_checksum_size_and_missing(tmp_path):
    root, f, m = _setup(tmp_path)
    m.add(f, "test", "http://x/a.txt", "CC0")
    f.write_bytes(b"jello")  # same size, different content
    assert m.verify() == ["checksum mismatch: raw/a.txt"]
    assert not m.is_current(f)
    f.write_bytes(b"longer content")
    assert m.verify() == ["size mismatch: raw/a.txt"]
    f.unlink()
    assert m.verify() == ["missing: raw/a.txt"]


def test_later_entry_for_the_same_path_wins(tmp_path):
    root, f, m = _setup(tmp_path)
    m.add(f, "first", "http://x/1", "CC0")
    f.write_bytes(b"new content")
    m.add(f, "second", "http://x/2", "CC0")
    assert m.entries()["raw/a.txt"].source == "second"
    assert m.verify() == []
