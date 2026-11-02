"""Resilient JSON fetch and atomic, checksummed file download."""
from __future__ import annotations

import time
from pathlib import Path

import requests

from .manifest import Manifest
from .urlredact import redact_text, redact_url

_JSON_HEADERS = {"User-Agent": "AetherGuard/0.1 (research prototype)"}
_FILE_HEADERS = {**_JSON_HEADERS, "Accept-Encoding": "identity"}  # keeps Content-Length comparable


class DownloadError(RuntimeError):
    """A failed fetch. The message never contains the value of a credential-like query parameter."""

    def __init__(self, message: str, retriable: bool = False, status: int | None = None) -> None:
        super().__init__(redact_text(message))
        self.retriable = retriable
        self.status = status  # HTTP status when the failure was an HTTP response


def _check_status(response: requests.Response, url: str) -> None:
    code = response.status_code
    if code == 429 or code >= 500:
        raise DownloadError(f"HTTP {code} from {redact_url(url)}", retriable=True, status=code)
    if code >= 400:
        raise DownloadError(f"HTTP {code} from {redact_url(url)}", retriable=False, status=code)


def _discard(path: Path) -> None:
    """Best-effort removal of a file we created; never masks the error being handled."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def fetch_json(url: str, params: dict | None = None, retries: int = 3,
               backoff: float = 2.0, timeout: float = 60) -> dict:
    error: DownloadError | None = None
    for attempt in range(retries):
        try:
            response = requests.get(url, params=params, timeout=timeout, headers=_JSON_HEADERS)
            _check_status(response, url)
            try:
                return response.json()
            except ValueError as exc:
                raise DownloadError(f"invalid JSON from {redact_url(url)}: {exc}") from exc
        except requests.RequestException as exc:
            error = DownloadError(f"{type(exc).__name__}: {exc}", retriable=True)
        except DownloadError as exc:
            error = exc
        if not error.retriable:
            raise error
        if attempt < retries - 1:
            time.sleep(backoff * 2 ** attempt)
    raise error


def download(url: str, dest, manifest: Manifest, source: str, licence: str,
             retries: int = 3, backoff: float = 2.0, timeout: float = 120,
             force: bool = False, session: requests.Session | None = None) -> Path:
    """Download to `dest` atomically and record it in the manifest.

    A file already recorded in the manifest with a matching size and checksum is not fetched again.
    A truncated transfer leaves no data file and no manifest entry. `session` (one per thread) lets a
    login-redirect source such as Earthdata reuse its cookies instead of re-authenticating on every request.
    """
    dest = Path(dest)
    if not force and manifest.is_current(dest):
        return dest
    partial = dest.with_name(dest.name + ".part")
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DownloadError(f"cannot create directory {dest.parent}: {exc}") from exc
    error: DownloadError | None = None
    try:
        for attempt in range(retries):
            try:
                with (session or requests).get(url, stream=True, timeout=timeout, headers=_FILE_HEADERS) as response:
                    _check_status(response, url)
                    expected = response.headers.get("Content-Length")
                    received = 0
                    try:
                        with partial.open("wb") as handle:
                            for chunk in response.iter_content(chunk_size=1 << 20):
                                handle.write(chunk)
                                received += len(chunk)
                    except requests.RequestException:
                        raise  # transport failure: retriable, handled below
                    except OSError as exc:
                        raise DownloadError(f"cannot write {partial}: {exc}") from exc
                if expected is not None and received != int(expected):
                    raise DownloadError(
                        f"truncated download from {redact_url(url)}: got {received} of {expected} bytes", retriable=True)
                if received == 0:
                    raise DownloadError(f"empty response from {redact_url(url)}", retriable=True)
                try:
                    partial.replace(dest)
                except OSError as exc:
                    raise DownloadError(f"cannot move {partial} to {dest}: {exc}") from exc
                try:
                    manifest.add(dest, source, url, licence)
                except Exception as exc:
                    # never leave a data file without a manifest entry
                    _discard(dest)
                    raise DownloadError(f"cannot record {dest} in the manifest: {exc}") from exc
                return dest
            except requests.RequestException as exc:
                error = DownloadError(f"{type(exc).__name__}: {exc}", retriable=True)
            except DownloadError as exc:
                error = exc
            _discard(partial)
            if not error.retriable:
                raise error
            if attempt < retries - 1:
                time.sleep(backoff * 2 ** attempt)
        raise error
    finally:
        _discard(partial)  # the .part file never survives any exit
