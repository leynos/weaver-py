from __future__ import annotations

# pyright: reportMissingImports=false  # Serena optional dependency
import asyncio
import getpass
import logging
import os
import resource
import sys
import tempfile
import typing as typ
from importlib import import_module
from pathlib import Path

import msgspec as ms
import msgspec.json as msjson

from weaver_schemas.diagnostics import Diagnostic
from weaver_schemas.error import SchemaError
from weaver_schemas.references import Reference, Symbol
from weaver_schemas.reports import OnboardingReport
from weaver_schemas.status import ProjectStatus

from .rpc import Handler, RPCDispatcher
from .serena_tools import SerenaTool, create_serena_tool

if typ.TYPE_CHECKING:  # pragma: no cover - typing only

    class _OnboardingTool(typ.Protocol):
        def apply(self) -> str: ...

    class _DiagnosticsTool(typ.Protocol):
        def list_diagnostics(
            self,
        ) -> typ.Iterable[Diagnostic | typ.Mapping[str, typ.Any]]: ...


logger = logging.getLogger(__name__)


HANDLERS: list[tuple[str, Handler]] = []
_HandlerT = typ.TypeVar("_HandlerT", bound=Handler)


class HandlerRegistrationError(ValueError):
    """Raised when registering the same RPC handler twice."""

    def __init__(self, name: str) -> None:
        super().__init__(f"handler '{name}' already registered")


class OnboardingError(RuntimeError):
    """Raised when onboarding a project fails unexpectedly."""

    def __init__(self, exc: Exception) -> None:
        super().__init__(f"Onboarding failed: {exc}")


class DiagnosticsError(RuntimeError):
    """Raised when listing diagnostics fails."""

    def __init__(self, exc: Exception) -> None:
        super().__init__(f"Diagnostics failed: {exc}")


class DefinitionLookupError(RuntimeError):
    """Raised when looking up a symbol definition fails."""

    def __init__(self, exc: Exception) -> None:
        super().__init__(f"Definition lookup failed: {exc}")


class ReferenceLookupError(RuntimeError):
    """Raised when looking up symbol references fails."""

    def __init__(self, exc: Exception) -> None:
        super().__init__(f"Reference lookup failed: {exc}")


class InvalidPositionError(ValueError):
    """Raised when a line or character index is negative."""

    def __init__(self, line: int, char: int) -> None:
        super().__init__(
            f"line and character must be non-negative (0-indexed, UTF-16 code units); "
            f"got line={line}, char={char}",
        )


def rpc_handler(name: str) -> typ.Callable[[_HandlerT], _HandlerT]:
    """Register ``func`` as an RPC handler with ``name``."""

    def decorator(func: _HandlerT) -> _HandlerT:
        if any(existing == name for existing, _ in HANDLERS):
            raise HandlerRegistrationError(name)
        HANDLERS.append((name, func))
        return func

    return decorator


def default_socket_path() -> Path:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", tempfile.gettempdir())
    user = getpass.getuser()
    return Path(runtime_dir) / f"weaverd-{user}.sock"


async def handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    dispatcher: RPCDispatcher,
) -> None:
    try:
        while data := await reader.readline():
            try:
                results = dispatcher.handle(data.rstrip())
            except Exception as exc:  # pragma: no cover - fallback
                if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt)):
                    raise
                logger.exception("Unhandled RPC error")

                async def _err(error: Exception) -> typ.AsyncIterator[bytes]:
                    # Yield to the event loop before streaming the error so the
                    # response is delivered asynchronously like normal
                    # handlers. Some runtimes expect an await point before the
                    # first ``yield`` in async generators.
                    await asyncio.sleep(0)
                    yield msjson.encode(SchemaError(message=str(error)))

                results = _err(exc)
            async for chunk in results:
                writer.write(chunk + b"\n")
                await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


async def start_server(path: Path, dispatcher: RPCDispatcher) -> asyncio.AbstractServer:
    if path.exists():
        path.unlink()
    return await asyncio.start_unix_server(
        lambda r, w: handle_client(r, w, dispatcher), path=str(path)
    )


def _get_rss_mb() -> float:
    """Return process memory usage in megabytes."""
    try:
        usage = resource.getrusage(resource.RUSAGE_SELF)
    except OSError:  # pragma: no cover - unsupported platform
        return 0.0

    rss = float(usage.ru_maxrss)
    if sys.platform == "darwin":
        return rss / (1024 * 1024)
    return rss / 1024


@rpc_handler("project-status")
def handle_project_status() -> ProjectStatus:
    """Return daemon PID, memory usage, and Serena availability."""

    try:
        import_module("serena")
        ready = True
    except ModuleNotFoundError:
        ready = False

    rss_mb = _get_rss_mb()

    return ProjectStatus(
        pid=os.getpid(),
        rss_mb=rss_mb,
        ready=ready,
        message="ok" if ready else "serena missing",
    )


@rpc_handler("onboard-project")
async def handle_onboard_project() -> OnboardingReport:
    """Run the onboarding tool and return its report."""
    try:
        tool = typ.cast("_OnboardingTool", create_serena_tool(SerenaTool.ONBOARDING))
        details = await asyncio.to_thread(tool.apply)
    except (asyncio.CancelledError, KeyboardInterrupt):  # propagate cancels
        raise
    except Exception as exc:  # pragma: no cover - unexpected failures
        raise OnboardingError(exc) from exc
    return OnboardingReport(details=details)


def _normalize_filters(
    severity: str | None, files: list[str] | None
) -> tuple[str | None, set[str] | None]:
    """Return case- and path-insensitive versions of filters."""

    norm_severity = severity.lower() if severity else None
    norm_files = (
        {os.path.normcase(os.path.normpath(f)).lower() for f in files}
        if files
        else None
    )
    return norm_severity, norm_files


def _normalize_diagnostic_data(diag: Diagnostic) -> tuple[str | None, str | None]:
    """Return normalised severity and file path from ``diag``."""

    # msgspec does not validate fields on construction, so tools may hand back a
    # ``Diagnostic`` whose severity is missing despite the declared Literal type.
    severity = typ.cast("str | None", diag.severity)
    diag_severity = severity.lower() if severity else None
    diag_file = (
        os.path.normcase(os.path.normpath(diag.location.file)).lower()
        if diag.location and diag.location.file
        else None
    )
    return diag_severity, diag_file


def _should_include_diagnostic(
    norm_severity: str | None,
    norm_files: set[str] | None,
    diag_severity: str | None,
    diag_file: str | None,
) -> bool:
    """Return ``True`` if the diagnostic passes the given filters."""

    return not (
        (norm_severity and diag_severity != norm_severity)
        or (norm_files and diag_file not in norm_files)
    )


@rpc_handler("list-diagnostics")
async def handle_list_diagnostics(
    severity: str | None = None,
    files: list[str] | None = None,
) -> typ.AsyncIterator[Diagnostic]:
    """Yield diagnostics, optionally filtered by severity and files."""

    # Prepare filters for case- and path-insensitive comparison
    norm_severity, norm_files = _normalize_filters(severity, files)
    tool = typ.cast("_DiagnosticsTool", create_serena_tool(SerenaTool.LIST_DIAGNOSTICS))
    try:
        data = await asyncio.to_thread(tool.list_diagnostics)
    except (asyncio.CancelledError, KeyboardInterrupt):  # propagate cancels
        raise
    except Exception as exc:
        raise DiagnosticsError(exc) from exc
    for item in data:
        diag = ms.convert(item, Diagnostic)
        diag_severity, diag_file = _normalize_diagnostic_data(diag)
        if _should_include_diagnostic(
            norm_severity, norm_files, diag_severity, diag_file
        ):
            yield diag


@rpc_handler("get-definition")
async def handle_get_definition(
    file: str, line: int, char: int
) -> typ.AsyncIterator[Symbol]:
    """Yield symbol definitions for a 0-indexed UTF-16 line/character."""

    if line < 0 or char < 0:  # basic input validation
        raise InvalidPositionError(line, char)

    tool = typ.cast(
        typ.Any,  # ruff: ignore[runtime-cast-value]
        create_serena_tool(SerenaTool.GET_DEFINITION),
    )
    try:
        data = await asyncio.to_thread(
            tool.get_definition, file=file, line=line, char=char
        )
    except RuntimeError as exc:
        raise DefinitionLookupError(exc) from exc
    for item in data:
        yield ms.convert(item, Symbol)


@rpc_handler("list-references")
async def handle_list_references(
    file: str,
    line: int,
    char: int,
    *,
    include_definition: bool = False,
) -> typ.AsyncIterator[Reference]:
    """Yield references for the symbol at the given position."""

    tool = typ.cast(
        typ.Any,  # ruff: ignore[runtime-cast-value]
        create_serena_tool(SerenaTool.LIST_REFERENCES),
    )
    try:
        data = await asyncio.to_thread(
            tool.list_references,
            file=file,
            line=line,
            char=char,
            include_definition=include_definition,
        )
    except RuntimeError as exc:
        raise ReferenceLookupError(exc) from exc
    for item in data:
        yield ms.convert(item, Reference)


async def main(socket_path: Path | None = None) -> None:
    dispatcher = RPCDispatcher()
    for name, func in HANDLERS:
        dispatcher.register(name)(func)

    path = socket_path or default_socket_path()
    server = await start_server(path, dispatcher)
    async with server:
        await server.serve_forever()
