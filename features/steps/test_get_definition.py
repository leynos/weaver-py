import collections.abc as cabc
import json
import typing as typ
from pathlib import Path

import pytest
from pytest_bdd import given, scenarios, then, when
from typer.testing import CliRunner

from features.types import Context
from weaver.cli import app
from weaver_schemas.primitives import Location, Position, Range
from weaver_schemas.references import Symbol
from weaverd import server
from weaverd.rpc import RPCDispatcher
from weaverd.serena_tools import SerenaTool

from .helpers import raise_serena_agent_not_found

scenarios("../get_definition.feature")


def _create_runtime_fixture(
    get_definition_impl: cabc.Callable[[str, int, int], list[Symbol]],
) -> cabc.Callable[[Context, pytest.MonkeyPatch], Context]:
    """Return a fixture that configures a stubbed get-definition tool."""

    def _fixture(runtime_dir: Context, monkeypatch: pytest.MonkeyPatch) -> Context:
        class StubTool:
            def get_definition(
                self, *, file: str, line: int, char: int
            ) -> list[Symbol]:
                return get_definition_impl(file, line, char)

        monkeypatch.setattr(server, "create_serena_tool", lambda _: StubTool())

        def setup(dispatcher: RPCDispatcher) -> None:
            @dispatcher.register("get-definition")
            def handler(
                file: str, line: int, char: int
            ) -> cabc.Iterable[Symbol]:  # pragma: no cover - stub
                tool = typ.cast(
                    typ.Any,  # ruff: ignore[runtime-cast-value]
                    server.create_serena_tool(SerenaTool.GET_DEFINITION),
                )
                return tool.get_definition(file=file, line=line, char=char)

        runtime_dir["register"](setup)
        return runtime_dir

    return _fixture


def _return_foo_symbol(file: str, line: int, char: int) -> list[Symbol]:
    loc = Location(
        file=file, range=Range(start=Position(line, char), end=Position(line, char + 1))
    )
    return [Symbol(name="foo", kind="function", location=loc)]


def _return_no_symbols(file: str, line: int, char: int) -> list[Symbol]:
    return []


@given("a temporary runtime dir", target_fixture="context")
def runtime_dir(runtime_dir: Context, monkeypatch: pytest.MonkeyPatch) -> Context:
    return _create_runtime_fixture(_return_foo_symbol)(runtime_dir, monkeypatch)


@given("a temporary runtime dir with no symbols", target_fixture="context")
def runtime_dir_empty(runtime_dir: Context, monkeypatch: pytest.MonkeyPatch) -> Context:
    return _create_runtime_fixture(_return_no_symbols)(runtime_dir, monkeypatch)


@given("serena-agent is missing")
def missing_dep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "create_serena_tool", raise_serena_agent_not_found)


@when("I invoke the get-definition command")
def invoke(context: Context, tmp_path: Path) -> None:
    file = tmp_path / "foo.py"
    file.write_text("pass")
    runner = CliRunner()
    result = runner.invoke(app, ["get-definition", str(file), "0", "0"])
    context["result"] = result


@when("I invoke the get-definition command with a missing file")
def invoke_missing(context: Context, tmp_path: Path) -> None:
    file = tmp_path / "nope.py"  # intentionally not created
    runner = CliRunner()
    result = runner.invoke(app, ["get-definition", str(file), "0", "0"])
    context["result"] = result


@then("the output includes a symbol line")
def check(context: Context) -> None:
    result = context["result"]
    assert result.exit_code == 0
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines
    record = json.loads(lines[0])
    symbol = record.get("symbol", record)
    assert symbol.get("name") == "foo"
    assert symbol.get("kind") == "function"


@then("no output is produced")
def check_empty(context: Context) -> None:
    result = context["result"]
    assert result.exit_code == 0
    assert result.stdout.strip() == ""


@then("the daemon is not ready")
def check_not_ready(context: Context) -> None:
    result = context["result"]
    assert result.exit_code == 1
    out = (result.stdout + result.stderr).lower()
    assert "serena" in out or "missing" in out


@then("the command fails with a missing file error")
def check_missing_file(context: Context) -> None:
    result = context["result"]
    assert result.exit_code != 0
    out = (result.stdout + result.stderr).lower()
    assert "no such file" in out or "does not exist" in out
