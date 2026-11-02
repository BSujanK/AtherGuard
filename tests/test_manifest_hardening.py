import http.server
import json
import threading

import pytest

from aetherguard.http import DownloadError, download, fetch_json, redact_url
from aetherguard.manifest import Manifest, ManifestCorruptError

SECRET = "s3cr3t-VALUE-42"


def _setup(tmp_path, name="a.txt", content=b"hello"):
    root = tmp_path / "data"
    f = root / "raw" / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(content)
    return root, f, Manifest(tmp_path / "manifest.jsonl", root)


def _line(path="raw/x.txt", source="s"):
    return json.dumps({"path": path, "source": source, "url": "http://x", "licence": "CC0",
                       "retrieved_utc": "2026-01-01T00:00:00Z", "size_bytes": 1, "sha256": "0" * 64},
                      sort_keys=True)


# ---------- in-memory cache ----------

def test_entries_are_cached_until_the_file_changes(tmp_path, monkeypatch):
    root, f, m = _setup(tmp_path)
    m.add(f, "t", "http://x/a", "CC0")
    reads = []
    real_open = type(m.manifest_path).open

    def counting_open(self, *args, **kwargs):
        if self == m.manifest_path and (not args or "r" in args[0]):
            reads.append(1)
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(type(m.manifest_path), "open", counting_open)
    for _ in range(5):
        assert m.is_current(f)
        assert "raw/a.txt" in m.entries()
    assert reads == []  # the add() populated the cache; nothing re-read the file


def test_second_manifest_object_sees_entries_and_cache_refreshes_on_external_append(tmp_path):
    root, f, m1 = _setup(tmp_path)
    m1.add(f, "t", "http://x/a", "CC0")
    m2 = Manifest(m1.manifest_path, root)
    assert set(m2.entries()) == {"raw/a.txt"}
    g = root / "raw" / "b.txt"
    g.write_bytes(b"other")
    m1.add(g, "t", "http://x/b", "CC0")  # external to m2
    assert set(m2.entries()) == {"raw/a.txt", "raw/b.txt"}
    assert m2.is_current(g)


def test_entries_returns_a_copy(tmp_path):
    root, f, m = _setup(tmp_path)
    m.add(f, "t", "http://x/a", "CC0")
    m.entries().clear()
    assert "raw/a.txt" in m.entries()


def test_add_fsyncs(tmp_path, monkeypatch):
    import os
    calls = []
    real = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (calls.append(fd), real(fd))[1])
    root, f, m = _setup(tmp_path)
    m.add(f, "t", "http://x/a", "CC0")
    assert len(calls) == 1


def test_concurrent_adds_lose_nothing_and_leave_valid_lines(tmp_path):
    root = tmp_path / "data"
    (root / "raw").mkdir(parents=True)
    m = Manifest(tmp_path / "manifest.jsonl", root)
    files = []
    for i in range(60):
        p = root / "raw" / f"f{i}.txt"
        p.write_bytes(f"content {i}".encode())
        files.append(p)
    threads = [threading.Thread(target=lambda chunk=files[k::6]: [m.add(p, "t", "http://x", "CC0") for p in chunk])
               for k in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(m.entries()) == 60
    assert len(Manifest(m.manifest_path, root).entries()) == 60
    assert all(m.is_current(p) for p in files)
    assert m.verify() == []


# ---------- torn / corrupt lines ----------

def test_torn_last_line_is_ignored_flagged_and_repaired_on_next_add(tmp_path):
    root, f, m = _setup(tmp_path)
    good = _line("raw/a.txt")
    m.manifest_path.write_text(good + "\n" + '{"path": "raw/b.tx', encoding="utf-8")
    m = Manifest(m.manifest_path, root)
    assert set(m.entries()) == {"raw/a.txt"}
    assert m.torn_last_line is True
    g = root / "raw" / "c.txt"
    g.write_bytes(b"ccc")
    m.add(g, "t", "http://x/c", "CC0")
    assert m.torn_last_line is False
    lines = m.manifest_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and all(json.loads(line) for line in lines)
    assert set(Manifest(m.manifest_path, root).entries()) == {"raw/a.txt", "raw/c.txt"}


def test_clean_manifest_is_not_flagged_torn(tmp_path):
    root, f, m = _setup(tmp_path)
    m.add(f, "t", "http://x/a", "CC0")
    assert Manifest(m.manifest_path, root).torn_last_line is False
    assert m.torn_last_line is False


def test_invalid_last_line_with_trailing_newline_is_corrupt(tmp_path):
    root, f, m = _setup(tmp_path)
    m.manifest_path.write_text(_line() + "\n" + "not json\n", encoding="utf-8")
    with pytest.raises(ManifestCorruptError) as info:
        Manifest(m.manifest_path, root).entries()
    assert info.value.line_number == 2
    assert info.value.path == m.manifest_path
    assert "2" in str(info.value)


def test_invalid_middle_line_is_corrupt_even_if_last_line_is_torn(tmp_path):
    root, f, m = _setup(tmp_path)
    m.manifest_path.write_text(_line() + "\n" + "garbage\n" + _line("raw/y.txt") + "\n" + '{"pa',
                               encoding="utf-8")
    with pytest.raises(ManifestCorruptError) as info:
        Manifest(m.manifest_path, root).entries()
    assert info.value.line_number == 2


def test_line_with_wrong_fields_is_corrupt(tmp_path):
    root, f, m = _setup(tmp_path)
    m.manifest_path.write_text(json.dumps({"path": "x"}) + "\n", encoding="utf-8")
    with pytest.raises(ManifestCorruptError) as info:
        Manifest(m.manifest_path, root).is_current(f)
    assert info.value.line_number == 1


def test_valid_last_line_without_newline_is_kept_and_add_starts_a_new_line(tmp_path):
    root, f, m = _setup(tmp_path)
    m.manifest_path.write_text(_line("raw/a.txt"), encoding="utf-8")  # no trailing newline
    m = Manifest(m.manifest_path, root)
    assert m.torn_last_line is False and set(m.entries()) == {"raw/a.txt"}
    g = root / "raw" / "c.txt"
    g.write_bytes(b"ccc")
    m.add(g, "t", "http://x/c", "CC0")
    assert set(Manifest(m.manifest_path, root).entries()) == {"raw/a.txt", "raw/c.txt"}


def test_blank_lines_are_ignored(tmp_path):
    root, f, m = _setup(tmp_path)
    m.manifest_path.write_text("\n" + _line() + "\n\n", encoding="utf-8")
    assert set(Manifest(m.manifest_path, root).entries()) == {"raw/x.txt"}


# ---------- URL redaction ----------

@pytest.mark.parametrize("name", ["key", "token", "password", "secret", "apikey", "api_key",
                                  "access_token", "sig", "signature", "API_KEY", "ApiKey",
                                  "X-Amz-Signature", "client_secret"])
def test_redact_url_hides_sensitive_values(name):
    out = redact_url(f"https://h.example/p?a=1&{name}={SECRET}&b=2")
    assert SECRET not in out
    assert out == f"https://h.example/p?a=1&{name}=***&b=2"


def test_redact_url_leaves_ordinary_urls_unchanged():
    for url in ("https://h.example/p", "https://h.example/p?a=1&b=two%20words#frag",
                "https://h.example/chirps-v2.0.2024.07.28.tif.gz", "https://h.example/p?monkey=1&keyboard=2"):
        assert redact_url(url) == url


def test_redact_url_handles_blank_value_fragment_and_userinfo():
    assert redact_url("https://h/p?token=&a=1") == "https://h/p?token=***&a=1"
    assert SECRET not in redact_url(f"https://h/p#access_token={SECRET}&state=x")
    assert SECRET not in redact_url(f"https://user:{SECRET}@h/p")
    assert redact_url(f"https://user:{SECRET}@h/p").startswith("https://user:***@h/p")


def test_manifest_add_stores_a_redacted_url(tmp_path):
    root, f, m = _setup(tmp_path)
    entry = m.add(f, "t", f"https://h/a.txt?key={SECRET}&x=1", "CC0")
    assert SECRET not in entry.url
    assert SECRET not in m.manifest_path.read_text(encoding="utf-8")
    assert entry.url == "https://h/a.txt?key=***&x=1"


def test_manifest_add_stores_ordinary_urls_unchanged(tmp_path):
    root, f, m = _setup(tmp_path)
    assert m.add(f, "t", "https://h/a.txt?x=1", "CC0").url == "https://h/a.txt?x=1"


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        body = b"x" * 100
        if self.path.startswith("/ok"):
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404 if self.path.startswith("/gone") else 503)
            self.send_header("Content-Length", "0")
            self.end_headers()


@pytest.fixture
def server():
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def test_download_records_a_redacted_url(server, tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    m = Manifest(tmp_path / "manifest.jsonl", root)
    dest = root / "raw" / "ok.bin"
    download(f"{server}/ok.bin?api_key={SECRET}&v=1", dest, m, "t", "CC0")
    assert SECRET not in m.manifest_path.read_text(encoding="utf-8")
    assert m.entries()["raw/ok.bin"].url.endswith("/ok.bin?api_key=***&v=1")


@pytest.mark.parametrize("path", ["/gone", "/bad"])
def test_download_error_text_has_no_secret(server, tmp_path, path):
    root = tmp_path / "data"
    root.mkdir()
    m = Manifest(tmp_path / "manifest.jsonl", root)
    with pytest.raises(DownloadError) as info:
        download(f"{server}{path}?token={SECRET}", root / "raw" / "x.bin", m, "t", "CC0",
                 retries=2, backoff=0)
    assert SECRET not in str(info.value)
    assert "token=***" in str(info.value)


def test_fetch_json_error_text_has_no_secret(server):
    with pytest.raises(DownloadError) as info:
        fetch_json(f"{server}/gone?password={SECRET}", retries=1, backoff=0)
    assert SECRET not in str(info.value)


def test_transport_error_text_has_no_secret(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    m = Manifest(tmp_path / "manifest.jsonl", root)
    with pytest.raises(DownloadError) as info:
        download(f"http://127.0.0.1:9/x.bin?key={SECRET}", root / "raw" / "x.bin", m, "t", "CC0",
                 retries=1, backoff=0, timeout=2)
    assert SECRET not in str(info.value)
    with pytest.raises(DownloadError) as info:
        fetch_json("http://127.0.0.1:9/x.json", params={"key": SECRET}, retries=1, backoff=0, timeout=2)
    assert SECRET not in str(info.value)


def test_download_error_carries_the_http_status(server, tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    m = Manifest(tmp_path / "manifest.jsonl", root)
    with pytest.raises(DownloadError) as info:
        download(f"{server}/gone", root / "raw" / "x.bin", m, "t", "CC0", retries=1, backoff=0)
    assert info.value.status == 404
    with pytest.raises(DownloadError) as info:
        download(f"{server}/bad", root / "raw" / "y.bin", m, "t", "CC0", retries=1, backoff=0)
    assert info.value.status == 503


def test_two_processes_appending_at_once_keep_every_line_valid(tmp_path):
    """Regression: two builders (separate processes) once interleaved a line and corrupted the manifest."""
    import subprocess
    import sys
    import textwrap
    data = tmp_path / "data"
    data.mkdir()
    for i in range(80):
        (data / f"f{i}.bin").write_bytes(bytes([i % 251]) * 64)
    script = textwrap.dedent(f"""
        import sys
        from pathlib import Path
        from aetherguard.manifest import Manifest
        m = Manifest(Path(r"{tmp_path / 'm.jsonl'}"), Path(r"{data}"))
        start = int(sys.argv[1])
        for i in range(start, 80, 2):
            m.add(Path(r"{data}") / f"f{{i}}.bin", source="t", url="https://example.org/x", licence="l")
    """)
    procs = [subprocess.Popen([sys.executable, "-c", script, str(k)]) for k in (0, 1)]
    assert all(p.wait(timeout=120) == 0 for p in procs)
    m = Manifest(tmp_path / "m.jsonl", data)
    entries = m.entries()
    assert len(entries) == 80
    assert m.verify() == []
    assert not (tmp_path / "m.jsonl.lock").exists()
