"""Checksummed, append-only record of every file downloaded into the data tree."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .urlredact import redact_url


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


_EXTENDED_PREFIX = "\\\\?\\"  # two backslashes, '?', backslash: starts a Windows extended-length path


def _resolved(path) -> Path:
    """Absolute path without symlinks. On Windows `resolve()` intermittently returns the extended-length
    form for a file another thread is renaming, which would not compare equal to the plain form."""
    resolved = Path(path).resolve()
    text = str(resolved)
    if text.startswith(_EXTENDED_PREFIX) and not text.startswith(_EXTENDED_PREFIX + "UNC"):
        return Path(text[len(_EXTENDED_PREFIX):])
    return resolved


@contextmanager
def _process_lock(manifest_path: Path, timeout_s: float = 120.0, stale_s: float = 300.0):
    """Cross-process lock for appends: an exclusively created `<manifest>.lock` file. Two builders appending at
    once (different processes) would otherwise interleave lines. A lock older than `stale_s` is treated as left
    behind by a crashed process and removed. On Windows, creating (or reading) a lock file that another process is
    deleting is refused with PermissionError, not FileExistsError: that is the lock being busy too, so it waits."""
    lock = manifest_path.with_name(manifest_path.name + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except (FileExistsError, PermissionError) as busy:
            try:
                if time.time() - lock.stat().st_mtime > stale_s:
                    lock.unlink(missing_ok=True)
            except OSError:
                pass                                   # gone or being deleted: try to take it again
            if time.monotonic() > deadline:
                raise TimeoutError(f"manifest lock {lock} not obtained within {timeout_s:.0f} s "
                                   f"({type(busy).__name__})") from busy
            time.sleep(0.05)
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        lock.unlink(missing_ok=True)


class ManifestCorruptError(ValueError):
    """A manifest line other than a torn final line is not a valid entry."""

    def __init__(self, path, line_number: int) -> None:
        super().__init__(f"manifest {path} is corrupt: line {line_number} is not a valid entry")
        self.path = Path(path)
        self.line_number = line_number


@dataclass(frozen=True)
class ManifestEntry:
    path: str  # relative to the data root, POSIX separators
    source: str
    url: str
    licence: str
    retrieved_utc: str
    size_bytes: int
    sha256: str


class Manifest:
    """Append-only JSONL manifest. Safe to share between threads.

    Parsed entries are cached and re-read only when the file's mtime or size changed. A final line that is
    invalid JSON and lacks a newline (an interrupted append) is ignored, flagged in `torn_last_line`, and
    truncated away by the next `add`; any other invalid line raises `ManifestCorruptError`.
    """

    def __init__(self, manifest_path: Path, data_root: Path) -> None:
        self.manifest_path = Path(manifest_path)
        self.data_root = Path(data_root)
        self.torn_last_line = False
        self._lock = threading.RLock()
        self._cache: dict[str, ManifestEntry] = {}
        self._signature: tuple[int, int] | None = None  # (mtime_ns, size) the cache was built from
        self._torn_offset: int | None = None  # byte offset of the torn fragment, when there is one
        self._needs_newline = False  # file ends with a valid line lacking its newline

    def relpath(self, file_path) -> str:
        return _resolved(file_path).relative_to(_resolved(self.data_root)).as_posix()

    def _current_signature(self) -> tuple[int, int] | None:
        try:
            stat = self.manifest_path.stat()
        except FileNotFoundError:
            return None
        return stat.st_mtime_ns, stat.st_size

    def _refresh(self) -> dict[str, ManifestEntry]:
        """Return the cache, re-reading the file first if it changed since the last read. Lock held."""
        signature = self._current_signature()
        if signature == self._signature:
            return self._cache
        latest: dict[str, ManifestEntry] = {}
        self.torn_last_line = False
        self._torn_offset = None
        self._needs_newline = False
        if signature is not None:
            with self.manifest_path.open("rb") as handle:
                content = handle.read()
            ends_with_newline = content.endswith(b"\n")
            offset = 0
            lines = content.split(b"\n")
            for number, raw in enumerate(lines, start=1):
                start, offset = offset, offset + len(raw) + 1
                if not raw.strip():
                    continue
                try:
                    entry = ManifestEntry(**json.loads(raw.decode("utf-8")))
                except (ValueError, TypeError):
                    if number == len(lines) and not ends_with_newline:
                        self.torn_last_line = True
                        self._torn_offset = start
                        continue
                    raise ManifestCorruptError(self.manifest_path, number) from None
                latest[entry.path] = entry
                if number == len(lines) and not ends_with_newline:
                    self._needs_newline = True
        self._cache = latest
        self._signature = signature
        return latest

    def entries(self) -> dict[str, ManifestEntry]:
        with self._lock:
            return dict(self._refresh())

    def add(self, file_path, source: str, url: str, licence: str) -> ManifestEntry:
        file_path = Path(file_path)
        entry = ManifestEntry(
            path=self.relpath(file_path),
            source=source,
            url=redact_url(url),
            licence=licence,
            retrieved_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            size_bytes=file_path.stat().st_size,
            sha256=sha256_file(file_path),
        )
        record = (json.dumps(asdict(entry), sort_keys=True) + "\n").encode("utf-8")
        with self._lock, _process_lock(self.manifest_path):
            self._refresh()  # also validates the existing file and locates a torn tail
            self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
            with self.manifest_path.open("ab") as handle:
                if self._torn_offset is not None:
                    handle.truncate(self._torn_offset)
                    handle.seek(self._torn_offset)
                elif self._needs_newline:
                    handle.write(b"\n")
                handle.write(record)
                handle.flush()
                os.fsync(handle.fileno())
            self.torn_last_line = False
            self._torn_offset = None
            self._needs_newline = False
            self._cache[entry.path] = entry
            self._signature = self._current_signature()
        return entry

    def is_current(self, file_path) -> bool:
        path = Path(file_path)
        rel = self.relpath(path)
        with self._lock:
            entry = self._refresh().get(rel)
        if entry is None or not path.exists():
            return False
        return path.stat().st_size == entry.size_bytes and sha256_file(path) == entry.sha256

    def verify(self) -> list[str]:
        problems: list[str] = []
        for rel, entry in sorted(self.entries().items()):
            path = self.data_root / rel
            if not path.exists():
                problems.append(f"missing: {rel}")
            elif path.stat().st_size != entry.size_bytes:
                problems.append(f"size mismatch: {rel}")
            elif sha256_file(path) != entry.sha256:
                problems.append(f"checksum mismatch: {rel}")
        return problems
