from __future__ import annotations

import typing as typ

import msgspec as ms

from .primitives import Location  # ruff: ignore[typing-only-first-party-import]


class Symbol(ms.Struct, frozen=True):
    """A named code symbol."""

    name: str
    kind: str
    location: Location
    type: typ.Literal["symbol"] = "symbol"


class Reference(ms.Struct, frozen=True):
    """A reference to a symbol."""

    location: Location
    type: typ.Literal["reference"] = "reference"


__all__ = ["Reference", "Symbol"]
