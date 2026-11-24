from __future__ import annotations

import collections.abc as cabc
import inspect
import typing as typ
from functools import cached_property

import msgspec as ms
import msgspec.json as msjson

from weaver_schemas.error import SchemaError

if typ.TYPE_CHECKING:
    from weaver.client import JSONObject
else:  # pragma: no cover - runtime compatibility
    JSONObject = dict[str, object]

HandlerSync = typ.Callable[..., object]
HandlerAsync = typ.Callable[..., typ.Awaitable[object]]
Handler = HandlerSync | HandlerAsync

Predicate = typ.Callable[[object], bool]
ResultProcessor = typ.Callable[[object], typ.AsyncIterator[bytes]]


class RPCRequest(ms.Struct, frozen=True):
    """JSON-RPC style request."""

    method: str
    params: JSONObject | None = None


class RPCDispatcher:
    """Simple RPC dispatcher mapping method names to handlers."""

    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    def register(self, name: str) -> typ.Callable[[Handler], Handler]:
        def decorator(func: Handler) -> Handler:
            self._handlers[name] = func
            return func

        return decorator

    @staticmethod
    def _encode_error(message: str) -> bytes:
        return msjson.encode(SchemaError(message=message))

    def _decode_request(self, data: bytes) -> tuple[RPCRequest | None, bytes | None]:
        try:
            return msjson.decode(data, type=RPCRequest), None
        except ms.DecodeError as exc:
            return None, self._encode_error(f"invalid request: {exc}")

    async def _execute_handler(
        self, handler: Handler | None, request: RPCRequest
    ) -> tuple[object | None, bytes | None]:
        if handler is None:
            return None, self._encode_error(f"unknown method: {request.method}")
        try:
            result = handler(**(request.params or {}))
            if inspect.isawaitable(result):
                result = await typ.cast(typ.Awaitable[object], result)  # ruff: ignore[runtime-cast-value]
        except Exception as exc:  # ruff: ignore[blind-except] - ensure structured errors
            return None, self._encode_error(str(exc))
        return result, None

    async def _process_bytes_result(
        self, result: bytes | bytearray
    ) -> typ.AsyncIterator[bytes]:
        yield result if isinstance(result, bytes) else bytes(result)

    async def _process_async_iterable_result(
        self, result: typ.AsyncIterable[object]
    ) -> typ.AsyncIterator[bytes]:
        try:
            async for item in result:
                yield msjson.encode(item)
        except Exception as exc:  # ruff: ignore[blind-except] - ensure structured errors
            yield self._encode_error(str(exc))

    async def _process_sync_iterable_result(
        self, result: typ.Iterable[object]
    ) -> typ.AsyncIterator[bytes]:
        try:
            for item in result:
                yield msjson.encode(item)
        except Exception as exc:  # ruff: ignore[blind-except] - ensure structured errors
            yield self._encode_error(str(exc))

    async def _process_single_result(self, result: object) -> typ.AsyncIterator[bytes]:
        yield msjson.encode(result)

    @staticmethod
    def _is_bytes_result(result: object) -> bool:
        return isinstance(result, (bytes, bytearray))

    @staticmethod
    def _is_async_iterable_result(result: object) -> bool:
        return isinstance(result, cabc.AsyncIterable)

    @staticmethod
    def _is_sync_iterable_result(result: object) -> bool:
        return isinstance(result, cabc.Iterable) and not isinstance(
            result, (str, bytes, bytearray, cabc.Mapping)
        )

    @cached_property
    def _processor_chain(self) -> tuple[tuple[Predicate, ResultProcessor], ...]:
        return (
            (
                self._is_bytes_result,
                typ.cast("ResultProcessor", self._process_bytes_result),
            ),
            (
                self._is_async_iterable_result,
                typ.cast("ResultProcessor", self._process_async_iterable_result),
            ),
            (
                self._is_sync_iterable_result,
                typ.cast("ResultProcessor", self._process_sync_iterable_result),
            ),
        )

    async def _process_result(self, result: object) -> typ.AsyncIterator[bytes]:
        for predicate, processor in self._processor_chain:
            if predicate(result):
                async for chunk in processor(result):
                    yield chunk
                return

        async for chunk in self._process_single_result(result):
            yield chunk

    async def handle(self, data: bytes) -> typ.AsyncIterator[bytes]:
        request, err = self._decode_request(data)
        if err is not None:
            yield err
            return

        result, err = await self._execute_handler(
            self._handlers.get(request.method), request
        )
        if err is not None:
            yield err
            return

        async for chunk in self._process_result(result):
            yield chunk
