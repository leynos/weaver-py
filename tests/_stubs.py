from __future__ import annotations

import contextlib
import sys
import types as _types
import typing as typ


def make_fake_module(name: str, **attrs: object) -> _types.ModuleType:
    """Return a simple module with ``attrs`` assigned."""
    mod = _types.ModuleType(name)
    # Best-effort metadata for dotted names to aid import machinery and debugging.
    pkg, _, _ = name.rpartition(".")
    if pkg:
        mod.__package__ = pkg
    if not getattr(mod, "__file__", None):
        mod.__file__ = f"<fake:{name}>"
    mod.__dict__.update(attrs)
    return mod


@contextlib.contextmanager
def injected_modules(**mods: _types.ModuleType) -> typ.Generator[None, None, None]:
    """Temporarily inject ``mods`` into ``sys.modules`` for test isolation."""

    prev: dict[str, _types.ModuleType | None] = {}
    try:
        for name, mod in mods.items():
            prev[name] = sys.modules.get(name)
            sys.modules[name] = mod
        yield
    finally:
        for name, prior in prev.items():
            if prior is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = prior
