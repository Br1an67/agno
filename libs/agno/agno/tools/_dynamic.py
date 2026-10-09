"""Bind dynamic registration to the tool call that requested it."""

from collections.abc import AsyncIterator as AsyncIteratorABC
from collections.abc import Iterator as IteratorABC
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Iterator, Optional

if TYPE_CHECKING:
    from agno.tools.function import Function


@dataclass
class _ToolCallContext:
    function: "Function"
    active: bool = True


_current_tool_call: ContextVar[Optional[_ToolCallContext]] = ContextVar("agno_current_tool_call", default=None)


@contextmanager
def tool_call_context(function: "Function") -> Iterator[None]:
    context = _ToolCallContext(function)
    token = _current_tool_call.set(context)
    try:
        yield
    finally:
        # A child task inherits the value, so resetting this task's ContextVar
        # alone would still leave that child able to change a finished call.
        context.active = False
        _current_tool_call.reset(token)


def get_dynamic_tool_adder(agent: Any) -> Optional[Callable[[Any], None]]:
    context = _current_tool_call.get()
    if context is None or context.function._agent is not agent:
        return None
    if not context.active:
        raise RuntimeError("Cannot add a tool from a finished tool call.")
    return context.function._dynamic_tool_adder


def bind_tool_result(result: Any, function: "Function") -> Any:
    # Generator bodies execute later, sometimes in another task. Renew the
    # binding for each advance and reset it before yielding to the consumer.
    if isinstance(result, IteratorABC):
        return _iterate_tool_result(result, function)
    if isinstance(result, AsyncIteratorABC):
        return _aiterate_tool_result(result, function)
    return result


def _iterate_tool_result(iterator: Any, function: "Function") -> Iterator[Any]:
    try:
        while True:
            try:
                with tool_call_context(function):
                    value = next(iterator)
            except StopIteration:
                return
            yield value
    finally:
        close = getattr(iterator, "close", None)
        if close is not None:
            with tool_call_context(function):
                close()


async def _aiterate_tool_result(iterator: Any, function: "Function"):
    try:
        while True:
            try:
                with tool_call_context(function):
                    value = await iterator.__anext__()
            except StopAsyncIteration:
                return
            yield value
    finally:
        aclose = getattr(iterator, "aclose", None)
        if aclose is not None:
            with tool_call_context(function):
                await aclose()
