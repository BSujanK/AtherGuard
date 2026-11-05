"""Removal of credentials from URLs and from error text that quotes them."""
from __future__ import annotations

import re
from urllib.parse import unquote

REDACTED = "***"
_SENSITIVE_NAMES = frozenset({
    "key", "token", "password", "passwd", "pwd", "secret", "apikey", "api_key", "access_token",
    "sig", "signature", "auth", "code",   # code: OAuth authorization code of an Earthdata redirect
})
_SENSITIVE_SUFFIXES = ("_key", "_token", "_secret", "_password", "_signature", "_sig")
# Parameter name and its value inside free text; the name must follow a '?', '&', ';' or '#'.
_PARAM_IN_TEXT = re.compile(r"(?P<prefix>[?&;#])(?P<name>[^=&#\s'\"<>]+)=(?P<value>[^&#\s'\"<>)]*)")


def _is_sensitive(name: str) -> bool:
    normal = unquote(name).strip().lower().replace("-", "_")
    return normal in _SENSITIVE_NAMES or normal.endswith(_SENSITIVE_SUFFIXES)


def _redact_params(section: str) -> str:
    """Redact the values of sensitive `name=value` pairs in a query string or fragment."""
    pieces = []
    for piece in section.split("&"):
        name, equals, _ = piece.partition("=")
        pieces.append(f"{name}={REDACTED}" if equals and _is_sensitive(name) else piece)
    return "&".join(pieces)


def redact_url(url: str) -> str:
    """Replace the values of sensitive query/fragment parameters and any password with `***`.

    A URL without such parameters is returned unchanged, byte for byte.
    """
    rest, hash_sign, fragment = url.partition("#")
    base, question, query = rest.partition("?")
    scheme, sep, after = base.partition("://")
    if sep:
        authority, slash, path = after.partition("/")
        userinfo, at, host = authority.rpartition("@")
        if at and ":" in userinfo:
            user = userinfo.split(":", 1)[0]
            authority = f"{user}:{REDACTED}@{host}"
        base = f"{scheme}://{authority}{slash}{path}"
    if question:
        query = _redact_params(query)
    if hash_sign:
        fragment = _redact_params(fragment)
    return f"{base}{question}{query}{hash_sign}{fragment}"


def redact_text(text: str) -> str:
    """Redact sensitive parameter values wherever a URL or query string is quoted inside `text`."""
    def replace(match: re.Match) -> str:
        if _is_sensitive(match.group("name")):
            return f"{match.group('prefix')}{match.group('name')}={REDACTED}"
        return match.group(0)
    return _PARAM_IN_TEXT.sub(replace, text)
