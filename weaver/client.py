from __future__ import annotations

import asyncio
import asyncio.subprocess as aio_subprocess
import contextlib
import logging
import os
import sys
import typing as typ
from pathlib import Path  # ruff: ignore[typing-only-standard-library-import]

import anyio
import msgspec as ms
import msgspec.json as msjson
import typer

from weaverd.server import default_socket_path

from .errors import is_dependency_error
from .sockets import can_connect

logger = logging.getLogger(__name__)

# Daemon startup policy
STARTUP_RETRIES = 50
STARTUP_SLEEP_SECS = 0.1
STARTUP_TIMEOUT_SECS: float = STARTUP_RETRIES * STARTUP_SLEEP_SECS

JSONValue: typ.TypeAlias = (
    bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"] | None
)
JSONObject: typ.TypeAlias = dict[str, JSONValue]


class RPCRequest(ms.Struct):
    """An RPC request with method and parameters."""

    method: str
    params: JSONObject | None = None


class DaemonStartError(TimeoutError):
    """Raised when ``weaverd`` fails to become ready."""

    def __init__(self, path: Path, timeout_secs: float) -> None:
        self.path = path
        self.timeout_secs = timeout_secs
        super().__init__(
            f"weaverd failed to start at {path} within {timeout_secs:.1f}s"
        )


def discover_socket() -> Path:
    """Return the daemon socket path."""
    return default_socket_path()


async def spawn_daemon(
    socket_path: Path, *, debug: bool | None = None
) -> aio_subprocess.Process:
    """Spawn ``weaverd`` detached from the controlling terminal."""
    debug_env = os.environ.get("WEAVER_DEBUG", "0")
    debug = bool(int(debug_env)) if debug is None else debug
    return await aio_subprocess.create_subprocess_exec(
        sys.executable,
        "-m",
        "weaverd",
        "--socket-path",
        str(socket_path),
        stdin=aio_subprocess.DEVNULL,
        stdout=None if debug else aio_subprocess.DEVNULL,
        stderr=None if debug else aio_subprocess.DEVNULL,
        start_new_session=True,
    )


async def ensure_daemon_running(socket_path: Path) -> None:
    """Start ``weaverd`` if the socket is unavailable."""
    if await can_connect(socket_path):
        return
    await spawn_daemon(socket_path)
    try:
        with anyio.fail_after(STARTUP_TIMEOUT_SECS):
            for _ in range(STARTUP_RETRIES):
                if await can_connect(socket_path):
                    return
                await anyio.sleep(STARTUP_SLEEP_SECS)
    except TimeoutError as exc:
        raise DaemonStartError(socket_path, STARTUP_TIMEOUT_SECS) from exc
    raise DaemonStartError(socket_path, STARTUP_TIMEOUT_SECS)


def _process_response_line(data: bytes, stdout: typ.TextIO) -> bool:
    """Write ``data`` to ``stdout`` and detect dependency errors.

    Returns:
        bool: ``True`` if a dependency error was detected, ``False`` otherwise.
    """

    text = data.decode(
        encoding=getattr(stdout, "encoding", "utf-8") or "utf-8",
        errors="replace",
    )
    stdout.write(text)
    stdout.flush()

    try:
        record = msjson.decode(data.rstrip())
    except ms.DecodeError as exc:
        logger.warning("Failed to decode response line: %r: %s", data, exc)
        return False
    return bool(isinstance(record, dict) and is_dependency_error(record))


async def _stream_response(reader: asyncio.StreamReader, stdout: typ.TextIO) -> bool:
    """Stream lines from ``reader`` to ``stdout`` and flag dependency errors."""
    error = False
    async for line in reader:
        error |= _process_response_line(line, stdout)
    return error


def _resolve_socket_path(socket_path: Path | None) -> Path:
    """Return ``socket_path`` or discover a fallback."""
    return socket_path or discover_socket()


async def _establish_rpc_connection(
    path: Path,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Ensure the daemon is running and open a Unix socket connection.

    Raises:
        DaemonStartError: If the daemon fails to start.
        OSError: If the Unix socket cannot be opened.
    """
    await ensure_daemon_running(path)
    return await asyncio.open_unix_connection(str(path))


async def _execute_rpc_request(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    request: RPCRequest,
    stdout: typ.TextIO,
) -> bool:
    """Send an RPC request and stream the response."""
    try:
        writer.write(
            msjson.encode({"method": request.method, "params": request.params or {}})
            + b"\n"
        )
        await writer.drain()
        with contextlib.suppress(
            AttributeError, NotImplementedError
        ):  # pragma: no cover - transport-specific
            writer.write_eof()
        return await _stream_response(reader, stdout)
    finally:
        writer.close()
        await writer.wait_closed()


async def rpc_call(
    method: str,
    params: JSONObject | None = None,
    socket_path: Path | None = None,
    stdout: typ.TextIO | None = None,
) -> None:
    """Send an RPC request and stream the response to ``stdout``."""
    path = _resolve_socket_path(socket_path)
    stdout = typ.cast(typ.TextIO, sys.stdout if stdout is None else stdout)  # ruff: ignore[runtime-cast-value]
    try:
        reader, writer = await _establish_rpc_connection(path)
    except DaemonStartError as exc:
        print(f"Error: Could not ensure daemon is running: {exc}", file=sys.stderr)
        raise typer.Exit(1) from exc
    except OSError as exc:
        print(f"Error: Failed to connect to daemon at {path}: {exc}", file=sys.stderr)
        raise typer.Exit(1) from exc
    request = RPCRequest(method=method, params=params)
    error = await _execute_rpc_request(reader, writer, request, stdout)
    if error:
        raise typer.Exit(1)
    return
