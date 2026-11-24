from __future__ import annotations

import typing as typ

import anyio
import msgspec as ms
from pytest_bdd import given, scenarios, then, when
from typer.testing import CliRunner

from tests._stubs import injected_modules, make_fake_module
from weaver import client
from weaver.cli import app
from weaver_schemas.diagnostics import Diagnostic
from weaver_schemas.primitives import Location, Position, Range
from weaverd import serena_tools, server
from weaverd.serena_tools import SerenaTool, ToolClassNotFoundError

from .helpers import raise_serena_agent_not_found

if typ.TYPE_CHECKING:
    import pytest

    from features.types import Context
    from weaverd.rpc import RPCDispatcher

scenarios("../list_diagnostics.feature")


@given("a temporary runtime dir", target_fixture="context")
def runtime_dir(runtime_dir: Context, monkeypatch: pytest.MonkeyPatch) -> Context:
    class StubTool:
        def list_diagnostics(self) -> list[Diagnostic]:
            return [
                Diagnostic(
                    location=Location(
                        file="foo.py",
                        range=Range(start=Position(1, 0), end=Position(1, 1)),
                    ),
                    severity="Error",
                    code="E1",
                    message="boom",
                )
            ]

    monkeypatch.setattr(server, "create_serena_tool", lambda _: StubTool())

    def setup(dispatcher: RPCDispatcher) -> None:
        @dispatcher.register("list-diagnostics")
        def handler(
            severity: str | None = None,
            files: list[str] | None = None,
        ) -> typ.Iterator[Diagnostic]:  # pragma: no cover - stub
            tool = typ.cast(
                typ.Any,  # ruff: ignore[runtime-cast-value]
                server.create_serena_tool(SerenaTool.LIST_DIAGNOSTICS),
            )
            yield from (
                d
                for d in tool.list_diagnostics()
                if (not severity or d.severity == severity)
                and (not files or d.location.file in files)
            )

    runtime_dir["register"](setup)
    return runtime_dir


@given("the daemon is already running")
def daemon_running(context: Context) -> None:
    anyio.run(client.spawn_daemon, context["sock"])


@given("serena-agent is missing")
def missing_dep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "create_serena_tool", raise_serena_agent_not_found)


@given("the tool attribute is unknown")
def unknown_tool(context: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_error(_: SerenaTool) -> typ.NoReturn:
        raise ToolClassNotFoundError("NoSuchTool")

    monkeypatch.setattr(server, "create_serena_tool", raise_error)


@given("the server returns malformed output")
def server_malformed(context: Context) -> None:
    def setup(dispatcher: RPCDispatcher) -> None:
        @dispatcher.register("list-diagnostics")
        def malformed() -> ms.Raw:  # pragma: no cover - stub
            return ms.Raw(b"MALFORMED OUTPUT")

    context["register"](setup)


@when("I invoke the list-diagnostics command")
def invoke(context: Context) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["list-diagnostics"])
    context["result"] = result


@when('I invoke the list-diagnostics command with severity "Error"')
def invoke_severity(context: Context) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["list-diagnostics", "--severity", "Error"])
    context["result"] = result


@when('I invoke the list-diagnostics command for file "foo.py"')
def invoke_file(context: Context) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["list-diagnostics", "foo.py"])
    context["result"] = result


@then("the output includes a diagnostic line")
def check(context: Context) -> None:
    result = context["result"]
    assert result.exit_code == 0
    out = result.stdout
    assert '"message": "boom"' in out or "diagnostic" in out


@then("the daemon is not ready")
def check_not_ready(context: Context) -> None:
    result = context["result"]
    assert result.exit_code == 1
    out = (result.stdout + result.stderr).lower()
    assert "serena" in out or "missing" in out


@then("the tool attribute is reported missing")
def check_unknown_tool(context: Context) -> None:
    result = context["result"]
    assert result.exit_code == 0
    out = (result.stdout + result.stderr).lower()
    assert "not found" in out or "unknown" in out


@then("the output is malformed")
def check_malformed(context: Context) -> None:
    result = context["result"]
    assert result.exit_code == 0
    assert "malformed output" in result.stdout.lower()


def test_create_serena_tool_string_enum_equivalence() -> None:
    """create_serena_tool accepts both enum and string names."""

    class _ListDiagnosticsTool:  # pragma: no cover - simple stub
        def __init__(self, _: object) -> None:  # pragma: no cover - stub
            pass

    class _SerenaPromptFactory:  # pragma: no cover - simple stub
        def __call__(self) -> None:  # pragma: no cover - stub
            return None

    mods = {
        "serena.tools.workflow_tools": make_fake_module(
            "serena.tools.workflow_tools", ListDiagnosticsTool=_ListDiagnosticsTool
        ),
        "serena.prompt_factory": make_fake_module(
            "serena.prompt_factory", SerenaPromptFactory=_SerenaPromptFactory
        ),
    }

    serena_tools.clear_serena_imports()
    with injected_modules(**mods):
        tool_enum = server.create_serena_tool(SerenaTool.LIST_DIAGNOSTICS)

    serena_tools.clear_serena_imports()
    with injected_modules(**mods):
        tool_str = server.create_serena_tool("LIST_DIAGNOSTICS")

    serena_tools.clear_serena_imports()
    with injected_modules(**mods):
        tool_attr = server.create_serena_tool("ListDiagnosticsTool")

    assert type(tool_enum) is type(tool_str)
    assert type(tool_enum) is type(tool_attr)
