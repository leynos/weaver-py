from __future__ import annotations

import typing as typ

import msgspec as ms

from .primitives import Range  # ruff: ignore[typing-only-first-party-import]


class CodeEdit(ms.Struct, frozen=True):
    """A text replacement within a file."""

    file: str
    range: Range
    new_text: str
    type: typ.Literal["edit"] = "edit"


__all__ = ["CodeEdit"]
