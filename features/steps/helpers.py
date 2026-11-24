"""Shared helpers for BDD step implementations."""

from __future__ import annotations

import typing as typ
from typing import TYPE_CHECKING  # ruff: ignore[banned-import-from]

from weaverd.serena_tools import SerenaAgentNotFoundError, SerenaTool

if TYPE_CHECKING:
    from features.types import Context
    from weaverd.rpc import RPCDispatcher

__all__: tuple[str, ...] = (
    "raise_serena_agent_not_found",
    "register_production_handlers",
)


def register_production_handlers(context: Context) -> Context:
    """Register production RPC handlers on the test dispatcher.

    Parameters
    ----------
    context : Context
        Test context that provides a "register" hook accepting a callable
        of shape (dispatcher: RPCDispatcher) -> None.

    Returns
    -------
    Context
        The same context, to enable fluent usage in step setup.
    """

    def setup(dispatcher: RPCDispatcher) -> None:
        # Import lazily to avoid import-time side effects in tests.
        from weaverd import server

        for name, handler in server.HANDLERS:
            dispatcher.register(name)(handler)

    context["register"](setup)
    return context


def raise_serena_agent_not_found(_: SerenaTool) -> typ.NoReturn:
    """Raise :class:`SerenaAgentNotFoundError` for missing serena-agent.

    Centralizing this stub avoids repetition across step definitions and makes
    updates to the error behaviour straightforward.
    """

    raise SerenaAgentNotFoundError()
