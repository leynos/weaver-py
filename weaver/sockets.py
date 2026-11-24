from __future__ import annotations

import os  # ruff: ignore[typing-only-standard-library-import] -- required at runtime for type evaluation

import anyio


async def can_connect(path: os.PathLike[str] | str, timeout: float = 1.0) -> bool:
    """Return True if a UNIX socket exists and accepts a connection."""
    try:
        with anyio.fail_after(timeout):
            stream = await anyio.connect_unix(path)
    except (
        FileNotFoundError,
        ConnectionRefusedError,
        PermissionError,
        TimeoutError,
        OSError,
    ):
        return False
    else:
        await stream.aclose()
        return True
