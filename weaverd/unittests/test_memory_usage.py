from __future__ import annotations

import resource
import sys
import types
import typing as typ

import pytest

from weaverd import server


def test_get_rss_mb_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    usage = types.SimpleNamespace(ru_maxrss=2048)
    monkeypatch.setattr(resource, "getrusage", lambda _: usage)
    monkeypatch.setattr(sys, "platform", "linux", raising=False)
    assert server._get_rss_mb() == pytest.approx(2.0)


def test_get_rss_mb_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    usage = types.SimpleNamespace(ru_maxrss=2 * 1024 * 1024)
    monkeypatch.setattr(resource, "getrusage", lambda _: usage)
    monkeypatch.setattr(sys, "platform", "darwin", raising=False)
    assert server._get_rss_mb() == pytest.approx(2.0)


def test_get_rss_mb_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_error(_: object) -> typ.NoReturn:
        raise OSError()

    monkeypatch.setattr(resource, "getrusage", raise_error)
    assert server._get_rss_mb() == pytest.approx(0.0)
