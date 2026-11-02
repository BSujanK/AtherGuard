"""Result type shared by every audit probe."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

STATUSES = ("ok", "partial", "fail", "unreachable", "needs_login", "manual_pending", "inconclusive")


@dataclass
class ProbeResult:
    name: str
    status: str
    summary: str
    evidence: dict = field(default_factory=dict)
    day_definition: str | None = None

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"unknown status {self.status!r}; expected one of {STATUSES}")

    def as_dict(self) -> dict:
        return asdict(self)


def failure_status(errors) -> str:
    """'unreachable' when any error was a retriable network failure, otherwise 'fail'."""
    return "unreachable" if any(getattr(e, "retriable", False) for e in errors) else "fail"
