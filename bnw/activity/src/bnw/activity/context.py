# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
import logging
from abc import ABC
from types import TracebackType
from typing import Any, List, MutableMapping, Optional, Set, Type, TypeVar

from . import interfaces

logger = logging.getLogger("bnw.activity.context")


class BaseResolvingContext(interfaces.ResolvingActivityContext):
    _default_context: MutableMapping[str, Any]
    _resolvers: Set[interfaces.ContextResolver]

    def __init__(self, **context):
        self._default_context = context
        self._resolvers = set()

    async def use_resolver(self, resolver: interfaces.ContextResolver):
        self._resolvers.add(resolver)
        await resolver.start()

    async def close(self):
        await asyncio.gather(*(r.stop() for r in self._resolvers))

    def augment(self, **context):
        augmented_context = dict(self._default_context)
        augmented_context.update(context)
        return augmented_context

    def update(self, **context):
        self._default_context.update(**context)

    def get_value(self, name, **context):
        value = self.augment(**context).get(name, None)
        if value is None:
            for resolver in self.find_supporting_resolvers(name):
                value = resolver.find(name, **context)
                if value is not None:
                    return value

    async def await_value(self, name, **context):
        logger.debug("Awaiting value %s...", name)
        value = self.augment(**context).get(name, None)

        if value is not None:
            logger.debug("Found value in passed context")
            return value

        resolver_awaitables = [resolver.wait_for(name, **context) for resolver in self.find_supporting_resolvers(name)]
        if not resolver_awaitables:
            logger.debug("No supporting resolvers found")
            return None

        logger.debug("Found %d resolvers", len(resolver_awaitables))

        resolver_tasks = [asyncio.create_task(awaitable) for awaitable in resolver_awaitables]

        while resolver_tasks:
            logger.debug("Waiting for %d resolvers...", len(resolver_tasks))
            try:
                finished, unfinished = await asyncio.wait(resolver_tasks, return_when=asyncio.FIRST_COMPLETED)
            except (Exception, asyncio.CancelledError):
                for task in resolver_tasks:
                    task.cancel()
                raise
            for x in finished:
                value = x.result()

                if value is not None:
                    logger.debug("Value found: %s", value)
                    try:
                        # cancel the other tasks, we have a result. We need to wait for the cancellations
                        # to propagate.
                        for task in unfinished:
                            task.cancel()

                        if unfinished:
                            await asyncio.wait(list(unfinished))
                    except asyncio.exceptions.CancelledError:
                        pass

                    return value

            if value is None:
                resolver_tasks = list(unfinished)

        logger.debug("Value %s not found", name)
        return None

    def find_supporting_resolvers(self, name):
        yield from (r for r in self._resolvers if r.is_supported(name))

    async def resolve(self, name: str, cache: bool = False, cache_key: str = None, **context):
        value = self.get_value(name, **context)
        if value is not None:
            return value

        value = await self.await_value(name, **context)
        if value is not None and cache:
            key = cache_key if cache_key is not None else name
            self._default_context.update({key: value})

        return value


BR = TypeVar("BR", bound="BaseResolver")


class BaseResolver(interfaces.ContextResolver, ABC):

    _supported_values: List[str]

    def __init__(self, *values, **kwargs):
        super(BaseResolver, self).__init__(**kwargs)

        self._supported_values = []
        for v in values:
            if not self._check_resolver_implemented(v):
                raise TypeError(f"Resolver methods not implemented for {v} by {self.__class__.__name__}")
            else:
                self._supported_values.append(v)

    def _check_resolver_implemented(self, value_name) -> bool:
        find_available = hasattr(self, f"find_{value_name}") and callable(getattr(self, f"find_{value_name}"))
        wait_for_available = hasattr(self, f"wait_for_{value_name}") and callable(
            getattr(self, f"wait_for_{value_name}")
        )

        return find_available or wait_for_available

    def is_supported(self, value_name):
        return value_name in self._supported_values

    def find(self, name, **context):
        m = getattr(self, f"find_{name}")
        return m(**context)

    async def wait_for(self, name, **context):
        m = getattr(self, f"wait_for_{name}")
        return await m(**context)

    async def __aenter__(self: BR) -> BR:
        await self.start()
        return self

    async def __aexit__(
        self, exc_type: Optional[Type[BaseException]], exc: Optional[BaseException], tb: Optional[TracebackType]
    ) -> None:
        await self.stop()
