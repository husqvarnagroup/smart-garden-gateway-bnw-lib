# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
from typing import cast

import pytest
from bnw.tfw.component import Component, CompoundComponent, ThreadingComponent

pytestmark = pytest.mark.asyncio


class Component1(Component):
    def __init__(self, expected_loop):
        self.did_start = False
        self.did_stop = False
        self.is_ready = False
        self.loop = expected_loop

    async def start(self) -> None:
        assert self.loop == asyncio.get_running_loop()
        self.did_start = True

    async def stop(self) -> None:
        assert self.loop == asyncio.get_running_loop()
        self.did_stop = True

    async def ready(self) -> bool:
        assert self.loop == asyncio.get_running_loop()
        self.is_ready = True
        return True


async def test_threading_component_runs_underlying_component():
    asyncio.get_running_loop().set_debug(True)
    loop = asyncio.new_event_loop()
    loop.set_debug(True)

    comp1 = Component1(expected_loop=loop)
    sut = ThreadingComponent(comp1, thread_name="Component", loop=loop)

    async with sut:
        assert comp1.did_start
        await sut.ready()
        assert comp1.is_ready
    assert comp1.did_stop


async def test_threading_component_init_sync_gen():
    asyncio.get_running_loop().set_debug(True)
    loop = asyncio.new_event_loop()
    loop.set_debug(True)

    comp1 = Component1(expected_loop=loop)
    sut = ThreadingComponent(thread_name="Component", loop=loop)

    factory_called = False
    factory_closed = False

    def factory():
        assert asyncio.get_event_loop() == loop
        nonlocal factory_called, factory_closed
        factory_called = True
        yield cast(Component, comp1)
        factory_closed = True

    await sut.init(factory)
    assert factory_called
    assert sut.component == comp1

    async with sut:
        assert comp1.did_start
        await sut.ready()
        assert comp1.is_ready
    assert comp1.did_stop
    assert factory_closed


async def test_threading_component_init_async_gen():
    asyncio.get_running_loop().set_debug(True)
    loop = asyncio.new_event_loop()
    loop.set_debug(True)

    comp1 = Component1(expected_loop=loop)
    sut = ThreadingComponent(thread_name="Component", loop=loop)

    factory_called = False
    factory_closed = False

    async def factory():
        assert asyncio.get_event_loop() == loop
        nonlocal factory_called, factory_closed
        factory_called = True
        yield comp1
        factory_closed = True

    await sut.init(factory)
    assert factory_called
    assert sut.component == comp1

    async with sut:
        assert comp1.did_start
        await sut.ready()
        assert comp1.is_ready
    assert comp1.did_stop
    assert factory_closed


async def test_threading_component_init_async_gen_raise_on_second_yield():
    asyncio.get_running_loop().set_debug(True)
    loop = asyncio.new_event_loop()
    loop.set_debug(True)

    comp1 = Component1(expected_loop=loop)
    sut = ThreadingComponent(thread_name="Component", loop=loop)

    async def factory():
        yield comp1
        yield "should not yield a second time"

    await sut.init(factory)
    await sut.start()
    with pytest.raises(ValueError):
        await sut.stop()


async def test_threading_component_init_sync_func():
    asyncio.get_running_loop().set_debug(True)
    loop = asyncio.new_event_loop()
    loop.set_debug(True)

    comp1 = Component1(expected_loop=loop)
    sut = ThreadingComponent(thread_name="Component", loop=loop)

    factory_called = False

    def factory():
        assert asyncio.get_event_loop() == loop
        nonlocal factory_called
        factory_called = True
        return comp1

    await sut.init(factory)
    assert factory_called
    assert sut.component == comp1

    async with sut:
        assert comp1.did_start
        await sut.ready()
        assert comp1.is_ready
    assert comp1.did_stop


async def test_threading_component_init_sync_gen_raise_on_second_yield():
    asyncio.get_running_loop().set_debug(True)
    loop = asyncio.new_event_loop()
    loop.set_debug(True)

    comp1 = Component1(expected_loop=loop)
    sut = ThreadingComponent(thread_name="Component", loop=loop)

    def factory():
        yield comp1
        yield "should not yield a second time"

    await sut.init(factory)
    await sut.start()
    with pytest.raises(ValueError):
        await sut.stop()


async def test_threading_component_init_async_func():
    asyncio.get_running_loop().set_debug(True)
    loop = asyncio.new_event_loop()
    loop.set_debug(True)

    comp1 = Component1(expected_loop=loop)
    sut = ThreadingComponent(thread_name="Component", loop=loop)

    factory_called = False

    async def factory():
        assert asyncio.get_event_loop() == loop
        nonlocal factory_called
        factory_called = True
        return comp1

    await sut.init(factory)
    assert factory_called
    assert sut.component == comp1

    async with sut:
        assert comp1.did_start
        await sut.ready()
        assert comp1.is_ready
    assert comp1.did_stop


async def test_threading_component_init_value():
    asyncio.get_running_loop().set_debug(True)
    loop = asyncio.new_event_loop()
    loop.set_debug(True)

    comp1 = Component1(expected_loop=loop)
    sut = ThreadingComponent(thread_name="Component", loop=loop)

    await sut.init(comp1)
    assert sut.component == comp1

    async with sut:
        assert comp1.did_start
        await sut.ready()
        assert comp1.is_ready
    assert comp1.did_stop


async def test_threading_component_stops_thread_on_delete():
    asyncio.get_running_loop().set_debug(True)
    loop = asyncio.new_event_loop()
    loop.set_debug(True)

    comp1 = Component1(expected_loop=loop)
    sut = ThreadingComponent(thread_name="Component", loop=loop)

    await sut.init(comp1)
    assert sut.component == comp1

    await sut.start()

    sut.__del__()

    assert sut._thread is None


async def test_threading_component_proxy():
    asyncio.get_running_loop().set_debug(True)
    loop = asyncio.new_event_loop()
    loop.set_debug(True)

    class Component2(Component):
        def __init__(self) -> None:
            super().__init__()
            self.value = "value"

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def ready(self) -> bool:
            return True

        async def async_method(self) -> bool:
            assert asyncio.get_event_loop() == loop
            return True

        def sync_method(self) -> bool:
            assert asyncio.get_event_loop() == loop
            return True

        @property
        def property(self) -> str:
            assert asyncio.get_event_loop() == loop
            return "property"

    sut = ThreadingComponent(component=Component2(), thread_name="Component", loop=loop)

    assert sut.sync_method() is True
    assert await sut.async_method() is True
    assert sut.property == "property"
    assert sut.value == "value"

    async with sut:
        await sut.ready()


async def test_compound_component():
    comp1 = Component1(asyncio.get_event_loop())
    comp2 = Component1(asyncio.get_event_loop())

    sut = CompoundComponent(comp1, comp2)

    async with sut:
        assert comp1.did_start
        assert comp2.did_start
        await sut.ready()
        assert comp1.is_ready
        assert comp2.is_ready
    assert comp1.did_stop
    assert comp2.did_stop


async def test_compound_component_must_have_at_least_once_component():
    with pytest.raises(ValueError):
        CompoundComponent()


async def test_compound_component_list():
    comp1 = Component1(asyncio.get_event_loop())
    comp2 = Component1(asyncio.get_event_loop())

    sut = CompoundComponent([comp1, comp2])

    async with sut:
        assert comp1.did_start
        assert comp2.did_start
        await sut.ready()
        assert comp1.is_ready
        assert comp2.is_ready
    assert comp1.did_stop
    assert comp2.did_stop
