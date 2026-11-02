import http.server
import pathlib
import threading

import pytest
import requests

from aetherguard.http import DownloadError, download, fetch_json
from aetherguard.manifest import Manifest


class _Handler(http.server.BaseHTTPRequestHandler):
    hits: dict = {}

    def log_message(self, *args):
        pass

    def _send(self, status, body=b"", length=None):
        self.send_response(status)
        self.send_header("Content-Length", str(len(body) if length is None else length))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        _Handler.hits[self.path] = _Handler.hits.get(self.path, 0) + 1
        if self.path == "/ok.bin":
            self._send(200, b"x" * 5000)
        elif self.path == "/truncated.bin":
            self._send(200, b"x" * 100, length=5000)  # promises 5000, sends 100
        elif self.path == "/flaky.json":
            if _Handler.hits[self.path] < 3:
                self._send(503)
            else:
                self._send(200, b'{"ok": true}')
        else:
            self._send(404)


@pytest.fixture
def server():
    _Handler.hits = {}
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", _Handler.hits
    httpd.shutdown()
    httpd.server_close()


def _manifest(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    return root, Manifest(tmp_path / "manifest.jsonl", root)


def test_download_writes_file_and_manifest_entry(server, tmp_path):
    base, hits = server
    root, m = _manifest(tmp_path)
    dest = root / "raw" / "ok.bin"
    assert download(f"{base}/ok.bin", dest, m, "test", "CC0") == dest
    assert dest.stat().st_size == 5000
    assert m.entries()["raw/ok.bin"].size_bytes == 5000


def test_rerun_does_not_download_a_verified_file_again(server, tmp_path):
    base, hits = server
    root, m = _manifest(tmp_path)
    dest = root / "raw" / "ok.bin"
    download(f"{base}/ok.bin", dest, m, "test", "CC0")
    download(f"{base}/ok.bin", dest, m, "test", "CC0")
    assert hits["/ok.bin"] == 1


def test_truncated_download_leaves_no_file_and_no_manifest_entry(server, tmp_path):
    base, hits = server
    root, m = _manifest(tmp_path)
    dest = root / "raw" / "truncated.bin"
    with pytest.raises(DownloadError):
        download(f"{base}/truncated.bin", dest, m, "test", "CC0", retries=2, backoff=0)
    assert not dest.exists()
    assert not (root / "raw" / "truncated.bin.part").exists()
    assert m.entries() == {}
    assert hits["/truncated.bin"] == 2  # retried


def test_client_error_is_not_retried(server, tmp_path):
    base, hits = server
    root, m = _manifest(tmp_path)
    with pytest.raises(DownloadError) as info:
        download(f"{base}/missing", root / "raw" / "m.bin", m, "test", "CC0", retries=3, backoff=0)
    assert info.value.retriable is False
    assert hits["/missing"] == 1


def test_fetch_json_retries_server_errors(server):
    base, hits = server
    assert fetch_json(f"{base}/flaky.json", retries=3, backoff=0) == {"ok": True}
    assert hits["/flaky.json"] == 3


def test_fetch_json_404_raises_immediately(server):
    base, hits = server
    with pytest.raises(DownloadError):
        fetch_json(f"{base}/missing", retries=3, backoff=0)
    assert hits["/missing"] == 1


def test_failed_404_download_leaves_no_file_partial_or_entry(server, tmp_path):
    base, hits = server
    root, m = _manifest(tmp_path)
    dest = root / "raw" / "m.bin"
    with pytest.raises(DownloadError):
        download(f"{base}/missing", dest, m, "test", "CC0", retries=3, backoff=0)
    assert not dest.exists()
    assert not dest.with_name("m.bin.part").exists()
    assert m.entries() == {}


def test_manifest_failure_after_replace_removes_the_data_file(server, tmp_path, monkeypatch):
    base, hits = server
    root, m = _manifest(tmp_path)
    dest = root / "raw" / "ok.bin"

    def _boom(self, *args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Manifest, "add", _boom)
    with pytest.raises(DownloadError) as info:
        download(f"{base}/ok.bin", dest, m, "test", "CC0", retries=3, backoff=0)
    assert info.value.retriable is False
    assert "disk full" in str(info.value)
    assert hits["/ok.bin"] == 1  # not retried
    assert not dest.exists()
    assert not dest.with_name("ok.bin.part").exists()
    assert m.entries() == {}


def test_replace_failure_is_wrapped_and_cleans_up(server, tmp_path, monkeypatch):
    base, hits = server
    root, m = _manifest(tmp_path)
    dest = root / "raw" / "ok.bin"

    def _denied(self, target):
        raise PermissionError("file is in use")

    monkeypatch.setattr(pathlib.Path, "replace", _denied)
    with pytest.raises(DownloadError) as info:
        download(f"{base}/ok.bin", dest, m, "test", "CC0", retries=3, backoff=0)
    assert info.value.retriable is False
    assert "file is in use" in str(info.value)
    assert hits["/ok.bin"] == 1  # not retried
    assert not dest.exists()
    assert not dest.with_name("ok.bin.part").exists()
    assert m.entries() == {}


def test_download_uses_the_given_session(server, tmp_path):
    base, hits = server

    class CountingSession(requests.Session):
        calls = 0

        def get(self, *args, **kwargs):
            CountingSession.calls += 1
            return super().get(*args, **kwargs)

    root, m = _manifest(tmp_path)
    dest = root / "raw" / "ok.bin"
    with CountingSession() as session:
        download(f"{base}/ok.bin", dest, m, "test", "CC0", session=session)
    assert CountingSession.calls == 1 and hits["/ok.bin"] == 1
    assert dest.stat().st_size == 5000
