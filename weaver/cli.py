from __future__ import annotations

import typing as typ
from pathlib import Path  # ruff: ignore[typing-only-standard-library-import] -- Typer evaluates this at runtime

import anyio
import typer

from . import pure
from .client import JSONObject, rpc_call
from .sockets import can_connect

app = typer.Typer(name="weaver")


@app.command()
def hello() -> None:
    """Print a friendly greeting."""
    typer.echo(pure.hello())


@app.command()
def check_socket(path: Path) -> None:
    """Check if a UNIX socket is accepting connections."""
    connected = anyio.run(can_connect, path)
    if connected:
        typer.echo(f"socket available: {path}")
    else:
        typer.echo(f"socket unavailable: {path}")


def _todo(name: str) -> None:
    """Placeholder for unimplemented commands."""
    typer.echo(f"{name} not implemented", err=True)
    raise typer.Exit(1)


def _make_stub(name: str) -> typ.Callable[[], None]:
    def command() -> None:  # pragma: no cover - stub
        _todo(name)

    return command


def _run_rpc(method: str, params: JSONObject | None = None) -> None:
    """Execute an RPC request and handle failures uniformly."""
    try:
        anyio.run(rpc_call, method, params)
    except Exception as exc:
        # We surface the raw error to aid debugging while keeping exit codes
        # consistent for callers that rely on them.
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc


@app.command("project-status")
def project_status() -> None:
    """Check daemon and language server health."""
    _run_rpc("project-status")


@app.command("list-diagnostics")
def list_diagnostics(
    severity: str | None = typer.Option(
        None,
        "--severity",
        "-s",
        help="Filter diagnostics by severity",
    ),
    files: list[Path] = typer.Argument(None, metavar="[FILES...]"),  # ruff: ignore[function-call-in-default-argument]
) -> None:
    """Stream diagnostics for the workspace."""
    params: JSONObject = {}
    if severity:
        params["severity"] = severity
    if files:
        params["files"] = [str(p) for p in files]
    _run_rpc("list-diagnostics", params or None)


@app.command("onboard-project")
def onboard_project() -> None:
    """Perform first-run project analysis."""
    _run_rpc("onboard-project")


@app.command("get-definition")
def get_definition(
    file: Path = typer.Argument(  # ruff: ignore[function-call-in-default-argument]
        ...,
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=False,
    ),
    line: int = typer.Argument(..., min=0),
    char: int = typer.Argument(..., min=0),
) -> None:
    """Locate the symbol definition at the given 0-indexed position.

    Parameters
    ----------
    file : Path
        Path to the source file.
    line : int
        0-indexed line number.
    char : int
        0-indexed character offset within the line.
    """

    params: JSONObject = {"file": str(file), "line": line, "char": char}
    _run_rpc("get-definition", params)


@app.command("list-references")
def list_references(
    file: Path = typer.Argument(  # ruff: ignore[function-call-in-default-argument]
        ...,
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=False,
    ),
    line: int = typer.Argument(..., min=0),
    char: int = typer.Argument(..., min=0),
    include_definition: bool = typer.Option(  # ruff: ignore[boolean-type-hint-positional-argument]
        default=False, help="Include symbol definition in results"
    ),
) -> None:
    """Locate all references to the symbol at the given position."""

    params: JSONObject = {"file": str(file), "line": line, "char": char}
    if include_definition:
        params["include_definition"] = True
    _run_rpc("list-references", params)


STUBS = [
    "find-symbol",
    "summarise-symbol",
    "get-call-graph",
    "get-type-hierarchy",
    "list-memories",
    "analyse-impact",
    "get-code-actions",
    "test",
    "build",
    "with-transient-edit",
    "rename-symbol",
    "apply-edits",
    "format-code",
    "set-active-project",
    "reload-workspace",
]

for name in STUBS:
    app.command(name)(_make_stub(name))
