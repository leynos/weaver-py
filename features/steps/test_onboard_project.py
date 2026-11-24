from __future__ import annotations

import json
import os
import typing as typ

import anyio
import msgspec as ms
from pytest_bdd import given, scenarios, then, when
from typer.testing import CliRunner

from weaver.cli import app
from weaver_schemas.reports import OnboardingReport
from weaverd.serena_tools import (
    SerenaAgentNotFoundError,
    SerenaTool,
    create_serena_tool,
)

if typ.TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from features.types import Context
    from weaverd.rpc import RPCDispatcher

scenarios("../onboard_project.feature")


@given("a temporary runtime dir", target_fixture="context")
def runtime_dir(runtime_dir: Context) -> Context:
    def setup(dispatcher: RPCDispatcher) -> None:
        @dispatcher.register("onboard-project")
        def onboard() -> OnboardingReport:  # pragma: no cover - stub
            if os.environ.get("WEAVER_TEST_MISSING_SERENA"):
                raise SerenaAgentNotFoundError()
            tool = typ.cast(typ.Any, create_serena_tool(SerenaTool.ONBOARDING))  # ruff: ignore[runtime-cast-value]
            return OnboardingReport(details=tool.apply())

    runtime_dir["register"](setup)
    return runtime_dir


@given("an invalid project structure")
def invalid_project(context: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail_spawn(_: Path) -> None:  # pragma: no cover - stub
        await anyio.sleep(0)

    monkeypatch.setattr("weaver.client.spawn_daemon", fail_spawn)


@given("the server is unavailable")
def server_unavailable(context: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    async def noop(_: Path) -> None:  # pragma: no cover - stub
        await anyio.sleep(0)

    monkeypatch.setattr("weaver.client.spawn_daemon", noop)


@given("the server returns malformed output")
def server_malformed(context: Context) -> None:
    def setup(dispatcher: RPCDispatcher) -> None:
        @dispatcher.register("onboard-project")
        def malformed() -> ms.Raw:
            # Return raw bytes that do not form valid JSON so the
            # client hits a decode error.
            return ms.Raw(b"MALFORMED OUTPUT")

    context["register"](setup)


@given("the onboarding tool raises an error")
def tool_error(context: Context, monkeypatch: pytest.MonkeyPatch) -> None:
    def setup(dispatcher: RPCDispatcher) -> None:
        class ToolApplyError(RuntimeError):
            """Test-only error to simulate tool failure."""

        class FailingTool:
            def apply(self) -> str:  # pragma: no cover - stub
                raise ToolApplyError("boom")

        @dispatcher.register("onboard-project")
        def onboard() -> OnboardingReport:  # pragma: no cover - stub
            tool = FailingTool()
            return OnboardingReport(details=tool.apply())

    context["register"](setup)


@given("serena-agent is missing")
def missing_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEAVER_TEST_MISSING_SERENA", "1")


@then("the command fails with a missing dependency message")
def check_missing_dep(context: Context) -> None:
    result = context["result"]
    # When a required dependency like serena-agent is absent, the command
    # should fail with exit code 1.
    assert result.exit_code == 1
    out = (result.stdout + result.stderr).lower()
    assert "serena-agent" in out or "missing dependency" in out


@when("I invoke the onboard-project command")
def invoke(context: Context) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["onboard-project"])
    context["result"] = result


@then("the output includes onboarding details")
def check(context: Context) -> None:
    result = context["result"]
    assert result.exit_code == 0
    assert result.stdout.strip()
    out = result.stdout.lower()
    assert "project" in out
    assert "viewing" in out or "onboarding" in out


@then("the command fails with an error message")
def check_error(context: Context) -> None:
    result = context["result"]
    assert result.exit_code != 0
    err = result.stderr.lower()
    assert "daemon" in err or "server" in err or "connection" in err


@then("an error report is produced")
def check_report(context: Context) -> None:
    result = context["result"]
    assert result.exit_code == 0
    line = result.stdout.splitlines()[0]
    rec = json.loads(line)
    assert rec.get("type") == "error"


@then("the output indicates the server is unavailable")
def check_unavailable(context: Context) -> None:
    result = context["result"]
    assert result.exit_code != 0
    out = result.stderr.lower()
    assert "daemon" in out


@then("the output is malformed")
def check_malformed(context: Context) -> None:
    result = context["result"]
    assert result.exit_code == 0
    assert "malformed output" in result.stdout.lower()
