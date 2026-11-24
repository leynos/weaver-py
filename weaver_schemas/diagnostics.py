from __future__ import annotations

import typing as typ

import msgspec as ms

from .primitives import Location  # ruff: ignore[typing-only-first-party-import]


class Diagnostic(ms.Struct, frozen=True):
    """A compiler or linter message."""

    location: Location
    severity: typ.Literal["Error", "Warning", "Info", "Hint"]
    code: str | None
    message: str
    type: typ.Literal["diagnostic"] = "diagnostic"


__all__ = ["Diagnostic"]
