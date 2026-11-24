import asyncio
import collections.abc as cabc
import contextlib
import functools
import multiprocessing as mp
import os
from pathlib import Path

import anyio
import pytest

from features.types import Context
from weaver import client
from weaverd.rpc import RPCDispatcher
from weaverd.server import start_server

HandlerFunc = cabc.Callable[[RPCDispatcher], None]


async def _wait_for_socket(path: Path, timeout: float = 5.0) -> None:
    """Poll ``path`` until a daemon accepts a connection or timeout."""
    deadline = anyio.current_time() + timeout
    while anyio.current_time() < deadline:
        try:
            _, writer = await asyncio.open_unix_connection(str(path))
        except OSError:
            await anyio.sleep(0.05)
        else:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            return
    raise DaemonNotReadyError(path, timeout)


class DaemonNotReadyError(TimeoutError):
    """Raised when the test daemon fails to accept connections."""

    def __init__(self, path: Path, timeout: float | None = None) -> None:
        suffix = f" (after {timeout:.2f}s)" if timeout is not None else ""
        super().__init__(f"Daemon socket not ready: {path}{suffix}")


async def _serve_daemon(path: Path, handler_func: HandlerFunc) -> None:
    """Run a minimal daemon for tests."""
    dispatcher = RPCDispatcher()
    handler_func(dispatcher)
    server = await start_server(path, dispatcher)
    async with server:
        await server.serve_forever()


def spawn_daemon(
    path: Path, handler_func: HandlerFunc, *, debug: bool | None = None
) -> mp.Process:
    """Start the test daemon in a background process."""
    del debug

    def _run() -> None:
        loop: asyncio.AbstractEventLoop | None = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(_serve_daemon(path, handler_func))
        except Exception:  # ruff: ignore[blind-except, try-except-pass] - best effort for tests
            pass
        finally:
            if loop is not None:
                loop.close()

    proc = mp.Process(target=_run)
    proc.start()
    return proc


async def async_spawn_daemon(
    path: Path,
    *,
    handler: dict[str, HandlerFunc],
    processes: list[mp.Process],
    debug: bool | None = None,
) -> mp.Process:
    proc = spawn_daemon(path, handler["func"], debug=debug)
    processes.append(proc)
    await _wait_for_socket(path)
    return proc


def _cleanup_process(proc: mp.Process) -> None:
    """Cleanup a single process with graceful fallback."""
    if not (proc and proc.is_alive()):
        return
    proc.terminate()
    try:  # ruff: ignore[suppressible-exception]
        proc.join(timeout=5)
    except Exception:  # ruff: ignore[blind-except, try-except-pass] - cleanup best effort
        pass
    if not proc.is_alive():
        return
    try:
        proc.kill()
        proc.join(timeout=1)
    except Exception:  # ruff: ignore[blind-except, try-except-pass] - cleanup best effort
        pass


def _cleanup_processes(processes: list[mp.Process]) -> None:
    """Terminate test processes best effort."""
    for proc in processes:
        _cleanup_process(proc)


@pytest.fixture
def runtime_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> cabc.Generator[Context, None, None]:
    os.environ["XDG_RUNTIME_DIR"] = str(tmp_path)
    sock = client.discover_socket()
    processes: list[mp.Process] = []
    handler: dict[str, HandlerFunc] = {"func": lambda dispatcher: None}

    monkeypatch.setattr(
        client,
        "spawn_daemon",
        functools.partial(async_spawn_daemon, handler=handler, processes=processes),
    )

    ctx: Context = {"sock": sock, "processes": processes}

    def register(fn: HandlerFunc) -> Context:
        handler["func"] = fn
        return ctx

    ctx["register"] = register
    yield ctx

    _cleanup_processes(processes)
