# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio

import pytest

from bnw.activity import BaseResolvingContext, ContextResolver

pytestmark = pytest.mark.asyncio


class TestResolver(ContextResolver):
    async def start(self):
        pass

    async def stop(self):
        pass

    def is_supported(self, name):
        return True

    def find(self, name, **context):
        pass

    async def wait_for(self, name, **context):
        pass


async def test_base_resolving_context_waits_for_all_resolvers():
    sut = BaseResolvingContext()

    # GIVEN: one fast resolver that fails and one slow that succeeds

    class QuickResolver1(TestResolver):
        async def wait_for(self, name, **context):
            await asyncio.sleep(0.1)
            return None

    class SlowResolver1(TestResolver):
        async def wait_for(self, name, **context):
            await asyncio.sleep(0.2)
            return "value"

    await sut.use_resolver(QuickResolver1())
    await sut.use_resolver(SlowResolver1())

    # WHEN resolving
    value = await sut.resolve("name")

    # THEN value is found
    assert value == "value"


async def test_base_resolving_context_waits_no_resolver_results():
    sut = BaseResolvingContext()

    # GIVEN: multiple resolver not returning a value

    class EmptyResolver(TestResolver):
        pass

    await sut.use_resolver(EmptyResolver())
    await sut.use_resolver(EmptyResolver())
    await sut.use_resolver(EmptyResolver())

    # WHEN: resolving
    value = await sut.resolve("name")

    # THEN: no result
    assert value is None


async def test_base_resolving_context_cancels_after_first_find():
    sut = BaseResolvingContext()

    # GIVEN: one quick resolver and another slow one

    class QuickResolver(TestResolver):
        async def wait_for(self, name, **context):
            await asyncio.sleep(0.1)
            return "value"

    slow_started = asyncio.Event()
    slow_canceled = asyncio.Event()
    slow_finished = asyncio.Event()

    class SlowResolver(TestResolver):
        def __init__(self, started, canceled, stopped):
            self.started = started
            self.canceled = canceled
            self.finished = stopped

        async def wait_for(self, name, **context):
            self.started.set()
            try:
                await asyncio.sleep(0.2)
                self.finished.set()
                return "other value"
            except asyncio.exceptions.CancelledError:
                self.canceled.set()

    await sut.use_resolver(QuickResolver())
    await sut.use_resolver(SlowResolver(slow_started, slow_canceled, slow_finished))

    # WHEN: resolving
    value = await sut.resolve("name")

    # THEN: no result
    assert value == "value"
    assert await slow_started.wait()
    assert slow_canceled.is_set()
    assert not slow_finished.is_set()
