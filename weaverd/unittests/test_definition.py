from __future__ import annotations

import builtins
import typing as typ
from dataclasses import dataclass  # ruff: ignore[banned-import-from] -- simpler decorator usage

import pytest

from weaver_schemas.primitives import Location, Position, Range
from weaver_schemas.references import Symbol
from weaverd import server
from weaverd.serena_tools import SerenaAgentNotFoundError, SerenaTool

if typ.TYPE_CHECKING:
    import collections.abc as cabc

try:
    _anext = builtins.anext  # type: ignore[attr-defined]
except AttributeError:  # Python < 3.10
    T = typ.TypeVar("T")

    async def _anext(it: cabc.AsyncIterator[T]) -> T:
        return await it.__anext__()


globals()["anext"] = _anext


class StubTool:
    def get_definition(self, *, file: str, line: int, char: int) -> list[Symbol]:
        loc = Location(
            file=file,
            range=Range(start=Position(line, char), end=Position(line, char + 1)),
        )
        return [Symbol(name="foo", kind="function", location=loc)]


class EmptyTool:
    def get_definition(self, *, file: str, line: int, char: int) -> list[Symbol]:
        return []


class MultiTool:
    def get_definition(self, *, file: str, line: int, char: int) -> list[Symbol]:
        loc1 = Location(
            file=file,
            range=Range(start=Position(line, char), end=Position(line, char + 1)),
        )
        loc2 = Location(
            file=file,
            range=Range(start=Position(line, char + 2), end=Position(line, char + 3)),
        )
        return [
            Symbol(name="foo", kind="function", location=loc1),
            Symbol(name="bar", kind="class", location=loc2),
        ]


class DummyTool:
    def get_definition(self, *, file: str, line: int, char: int) -> list[Symbol]:
        return []


@dataclass
class FilePosition:
    file: str
    line: int
    char: int


def _setup_and_call_get_definition(
    monkeypatch: pytest.MonkeyPatch,
    tool_class: type[object],
    position: FilePosition,
) -> cabc.AsyncIterator[Symbol]:
    """Helper to setup mock and call handle_get_definition."""
    monkeypatch.setattr(server, "create_serena_tool", lambda _: tool_class())
    return server.handle_get_definition(position.file, position.line, position.char)


async def _collect_symbols_from_results(
    results: cabc.AsyncIterator[Symbol], expected_count: int
) -> list[Symbol]:
    """Helper to collect symbols from async iterator and verify count."""
    symbols: list[Symbol] = []
    try:
        for _ in range(expected_count):
            symbols.append(await anext(results))
        # Verify no more symbols remain
        with pytest.raises(StopAsyncIteration):
            await anext(results)
    except StopAsyncIteration:
        if len(symbols) != expected_count:
            pytest.fail(f"Expected {expected_count} symbols, got {len(symbols)}")
        raise
    return symbols


def _assert_symbol_location(symbol: Symbol, expected_location: Location) -> None:
    """Helper to assert symbol location properties."""
    assert symbol.location.file == expected_location.file
    assert symbol.location.range.start.line == expected_location.range.start.line
    assert (
        symbol.location.range.start.character == expected_location.range.start.character
    )
    assert symbol.location.range.end.line == expected_location.range.end.line
    assert symbol.location.range.end.character == expected_location.range.end.character


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_handle_get_definition(monkeypatch: pytest.MonkeyPatch) -> None:
    results = _setup_and_call_get_definition(
        monkeypatch, StubTool, FilePosition("foo.py", 1, 0)
    )
    sym = (await _collect_symbols_from_results(results, 1))[0]
    assert sym.name == "foo"
    assert sym.kind == "function"
    _assert_symbol_location(
        sym,
        Location(
            file="foo.py",
            range=Range(
                start=Position(1, 0),
                end=Position(1, 1),
            ),
        ),
    )


@pytest.mark.anyio
async def test_handle_get_definition_no_symbols(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = _setup_and_call_get_definition(
        monkeypatch, EmptyTool, FilePosition("foo.py", 1, 0)
    )
    await _collect_symbols_from_results(results, 0)


@pytest.mark.anyio
async def test_handle_get_definition_multiple_symbols(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = _setup_and_call_get_definition(
        monkeypatch, MultiTool, FilePosition("foo.py", 1, 0)
    )
    first, second = await _collect_symbols_from_results(results, 2)
    assert [first.name, second.name] == ["foo", "bar"]
    assert [first.kind, second.kind] == ["function", "class"]
    _assert_symbol_location(
        first,
        Location(
            file="foo.py",
            range=Range(
                start=Position(1, 0),
                end=Position(1, 1),
            ),
        ),
    )
    _assert_symbol_location(
        second,
        Location(
            file="foo.py",
            range=Range(
                start=Position(1, 2),
                end=Position(1, 3),
            ),
        ),
    )


@pytest.mark.anyio
async def test_handle_get_definition_missing_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_error(_: SerenaTool) -> typ.NoReturn:
        raise SerenaAgentNotFoundError()

    monkeypatch.setattr(server, "create_serena_tool", raise_error)

    with pytest.raises(SerenaAgentNotFoundError, match="serena-agent not found"):
        await anext(server.handle_get_definition("foo.py", 1, 0))


@pytest.mark.anyio
@pytest.mark.parametrize(("line", "char"), [(-1, 0), (1, -5), (-2, -3)])
async def test_handle_get_definition_invalid_position(
    monkeypatch: pytest.MonkeyPatch, line: int, char: int
) -> None:
    monkeypatch.setattr(server, "create_serena_tool", lambda _: DummyTool())
    with pytest.raises(
        ValueError,
        match="non-negative",
    ):
        await anext(server.handle_get_definition("foo.py", line, char))
