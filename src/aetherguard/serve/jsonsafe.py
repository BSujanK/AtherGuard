"""JSON responses that never fail on NaN or infinity: a non-finite number is sent as null (strict JSON has no NaN)."""
from __future__ import annotations

import math
from typing import Any

from starlette.responses import JSONResponse


def finite_or_none(value: Any) -> Any:
    """`value` with every NaN / +-inf float, at any depth of dicts, lists and tuples, replaced by None."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: finite_or_none(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [finite_or_none(item) for item in value]
    return value


class NullNaNJSONResponse(JSONResponse):
    """JSONResponse that renders NaN and infinity as null instead of raising (a 500) on them."""

    def render(self, content: Any) -> bytes:
        try:
            return super().render(content)
        except ValueError:                                # json.dumps(allow_nan=False): out of range float values
            return super().render(finite_or_none(content))
