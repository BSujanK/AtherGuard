"""Locating and reading the report sources of the final report (JSON, markdown companions, design docs)."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

from ..manifest import sha256_file

MISSING = object()
_DRIVE = re.compile(r"[A-Za-z]:[\\/]")


def get(data, path: str, default=MISSING):
    """Value at a dotted path through dicts and lists (list indices as digits). A dict key may itself contain dots
    ("0.9", "0.005"): the longest matching key wins. `default` when anything is absent."""
    return _walk(data, path.split("."), default)


def _walk(node, parts: list[str], default):
    if not parts:
        return node
    if isinstance(node, dict):
        for k in range(len(parts), 0, -1):
            key = ".".join(parts[:k])
            if key in node:
                found = _walk(node[key], parts[k:], MISSING)
                if found is not MISSING:
                    return found
        return default
    head = parts[0]
    if isinstance(node, list) and head.lstrip("-").isdigit() and -len(node) <= int(head) < len(node):
        return _walk(node[int(head)], parts[1:], default)
    return default


def is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def sanitize(text: str, root: Path) -> str:
    """Remove absolute paths: the project root becomes empty and any other drive path is shortened to <path>/."""
    for variant in {str(root), str(root.resolve()), root.as_posix(), root.resolve().as_posix()}:
        text = text.replace(variant + "\\", "").replace(variant + "/", "").replace(variant, ".")
    return _DRIVE.sub("<path>/", text)


class Sources:
    """The configured report sources, resolved against a project root, data root and reports directory."""

    def __init__(self, cfg: dict, root: Path, data: Path, reports: Path) -> None:
        self.root, self.data, self.reports = Path(root), Path(data), Path(reports)
        fr = cfg["finalreport"]
        self._candidates = {name: list(files) for name, files in fr["sources"].items()}
        self._distinct = dict(fr.get("distinct_from") or {})
        self._cache: dict[str, Path | None] = {}
        self._json: dict[str, object] = {}
        self.unreadable: dict[str, str] = {}

    def resolve(self, template: str) -> Path:
        path = Path(template.replace("{data}", str(self.data)).replace("{reports}", str(self.reports)))
        return path if path.is_absolute() else self.root / path

    def rel(self, path: Path) -> str:
        for base in (self.root, self.root.resolve()):
            try:
                return Path(path).resolve().relative_to(base.resolve()).as_posix()
            except ValueError:
                continue
        return Path(path).name

    def path(self, name: str) -> Path | None:
        """The first existing candidate (skipping one identical to its `distinct_from` source), else None."""
        if name not in self._cache:
            other = self.path(self._distinct[name]) if name in self._distinct else None
            found = None
            for template in self._candidates[name]:
                candidate = self.resolve(template)
                if candidate.is_file() and not (other is not None and sha256_file(candidate) == sha256_file(other)):
                    found = candidate
                    break
            self._cache[name] = found
        return self._cache[name]

    def label(self, name: str) -> str:
        """The file name shown for a source: the chosen file, else the first candidate."""
        chosen = self.path(name)
        return self.rel(chosen) if chosen else self.rel(self.resolve(self._candidates[name][0]))

    def pending(self, name: str) -> str:
        return f"pending: {self.label(name)}"

    def json(self, name: str):
        if name not in self._json:
            path = self.path(name)
            value = None
            if path is not None and path.suffix == ".json":
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    self.unreadable[name] = str(exc)
            self._json[name] = value
        return self._json[name]

    def markdown(self, name: str) -> str | None:
        """The markdown companion (same stem, .md) of a JSON source, or the file itself when it is markdown."""
        path = self.path(name)
        if path is None:
            return None
        md = path if path.suffix == ".md" else path.with_suffix(".md")
        return md.read_text(encoding="utf-8") if md.is_file() else None

    def sha256(self, name: str) -> str | None:
        path = self.path(name)
        return sha256_file(path) if path else None


def headings(text: str) -> list[tuple[int, int, str]]:
    """(line index, level, title) of every markdown heading outside code fences."""
    out, fenced = [], False
    for i, line in enumerate(text.splitlines()):
        if line.startswith("```"):
            fenced = not fenced
        match = None if fenced else re.match(r"^(#{1,6})\s+(.*\S)\s*$", line)
        if match:
            out.append((i, len(match.group(1)), match.group(2)))
    return out


def extract_sections(text: str, pattern: str, demote_to: int | None = None) -> list[tuple[str, str]]:
    """[(title, body)] of every heading whose title matches `pattern` (case-insensitive); the body runs until the next
    heading of the same or a higher level. With `demote_to`, nested headings are shifted so the section heading is that level."""
    lines = text.splitlines()
    found = headings(text)
    out = []
    for k, (index, level, title) in enumerate(found):
        if not re.search(pattern, title, re.IGNORECASE):
            continue
        end = next((j for j, lv, _ in found[k + 1:] if lv <= level), len(lines))
        body = lines[index + 1:end]
        if demote_to is not None:
            shift = demote_to - level
            body = [re.sub(r"^(#{1,6})", lambda m: "#" * max(1, min(6, len(m.group(1)) + shift)), line)
                    if re.match(r"^#{1,6}\s", line) else line for line in body]
        out.append((title, "\n".join(body).strip("\n")))
    return out


def bold_block(text: str, label: str) -> str | None:
    """Lines from a line starting with `**label**` up to the next blank-line-separated paragraph that is not a list."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(f"**{label}"):
            block = [line]
            for follow in lines[i + 1:]:
                if follow.startswith("#") or (follow.startswith("**") and not follow.startswith("- ")):
                    break
                block.append(follow)
            return "\n".join(block).strip()
    return None
