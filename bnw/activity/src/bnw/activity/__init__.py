# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
from functools import wraps
from types import TracebackType
from typing import Any, Generator, Mapping, Optional, Type, TypeVar

from bnw.protocol import ProtocolMetadata, ProtocolPayload, ProtocolPayloadValueType

from .context import BaseResolvingContext
from .interfaces import (
    ActivityContext,
    ActivityStrategy,
    ContextResolver,
    ResolvingActivityContext,
)


class ActivityError(Exception):
    def __init__(
        self,
        message: str = None,
        payload: Optional[ProtocolPayload] = None,
        metadata: Optional[ProtocolMetadata] = None,
    ):
        if message is None and payload is not None:
            message = payload.get(ProtocolPayloadValueType.STRING.value_key, None)

            if message and metadata is not None:
                error_source = metadata.get("error_source", None)
                if error_source is not None:
                    message += f" (error source: {error_source})"

        super().__init__(message if message else "Generic Activity Error")

        self.payload = payload
        self.metadata = metadata


BP = TypeVar("BP", bound="BusinessProcess")


class BusinessProcess:
    _base_context: BaseResolvingContext
    _strategy: Optional[ActivityStrategy]
    _use_strategy_task: Optional[asyncio.Task]

    def __init__(self, strategy: Optional[ActivityStrategy] = None, **context):
        self._base_context = BaseResolvingContext(**context)
        self._strategy = None
        if strategy is not None:
            self._use_strategy_task = asyncio.create_task(self.use_strategy(strategy))
        else:
            self._use_strategy_task = None

    async def use_strategy(self, strategy: ActivityStrategy):
        if self._strategy is not None:
            await self._strategy.deactivate()

        self._strategy = strategy
        if isinstance(strategy, ActivityStrategy):
            await strategy.activate()
            for resolver in strategy.context_resolvers():
                await self.use_resolver(resolver)

            strategy.use_context(self._base_context)
            self._base_context.update(**strategy.context_values())

    async def use_resolver(self, resolver: ContextResolver):
        await self._base_context.use_resolver(resolver)

    async def close(self):
        await self._base_context.close()
        if self._strategy:
            await self._strategy.deactivate()

    async def __aenter__(self: BP) -> BP:
        if self._use_strategy_task is not None:
            await self._use_strategy_task

        return self

    async def __aexit__(
        self, exc_type: Optional[Type[BaseException]], exc: Optional[BaseException], tb: Optional[TracebackType]
    ):
        await self.close()


def use_strategy(
    clazz,
    strategy_attr_name="_strategy",
    augment_dynamic_context=False,
    context_attr_name="_base_context",
):
    @wraps(clazz)
    def wrapper(*args, **kwds):
        def create_delegator(method):
            async def delegator(self, *args, **kwargs):
                obj = getattr(self, strategy_attr_name)
                if obj is None:
                    raise RuntimeError("Strategy not set")
                m = getattr(obj, method)

                if augment_dynamic_context:
                    context = getattr(self, context_attr_name)
                    kwargs = context.augment(**kwargs)

                return await m(*args, **kwargs)

            return delegator

        for m in clazz.__abstractmethods__:
            setattr(clazz, m, create_delegator(m))

        clazz.__abstractmethods__ = frozenset()
        return clazz(*args, **kwds)

    return wrapper


class BaseActivityStrategy(ActivityStrategy):
    _context: Optional[ActivityContext]

    def __init__(self, context: Optional[ActivityContext] = None):
        if context is not None:
            self.use_context(context)

    def use_context(self, context: ActivityContext):
        self._context = context

    def context_resolvers(self) -> Generator[Any, Any, ContextResolver]:  # type: ignore[return]
        yield from ()

    def context_values(self) -> Mapping[str, Any]:
        return {}

    async def resolve_in_context(self, name, **kwargs):
        value = None
        if self._context:
            if isinstance(self._context, ResolvingActivityContext):
                value = await self._context.resolve(name, **kwargs)
            else:
                value = self._context.get_value(name, **kwargs)
                if value is None:
                    value = await self._context.await_value(name, **kwargs)

        return value

    async def activate(self) -> None:
        pass

    async def deactivate(self) -> None:
        pass
