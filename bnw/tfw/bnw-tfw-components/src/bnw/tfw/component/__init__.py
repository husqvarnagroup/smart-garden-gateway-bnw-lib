# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio.exceptions
import inspect
import logging
import threading
from abc import ABCMeta, abstractmethod
from functools import wraps
from types import TracebackType
from typing import (
    Any,
    AsyncGenerator,
    AsyncIterator,
    Awaitable,
    Callable,
    Generator,
    Iterator,
    MutableMapping,
    Optional,
    Tuple,
    Type,
    TypeVar,
    Union,
    cast,
)

logger = logging.getLogger("tfw.component")

T = TypeVar("T", bound="Component")


class Component(metaclass=ABCMeta):
    @abstractmethod
    async def start(self) -> None:
        pass

    @abstractmethod
    async def stop(self) -> None:
        pass

    @abstractmethod
    async def ready(self) -> bool:
        pass

    async def __aenter__(self: T) -> T:
        await self.start()
        return self

    async def __aexit__(
        self, exc_type: Optional[Type[BaseException]], exc: Optional[BaseException], tb: Optional[TracebackType]
    ) -> None:
        try:
            await self.stop()
        except asyncio.exceptions.CancelledError:
            # cancelled errors could be thrown during stop, not treating them as exception
            pass


class ThreadLoggerAppender(logging.LoggerAdapter):
    def process(self, msg: Any, kwargs: MutableMapping[str, Any]) -> Tuple[Any, MutableMapping[str, Any]]:
        return "[%s] %s" % (threading.current_thread().name, msg), kwargs


class ThreadingComponent(Component):
    """
    Component that wraps another component and runs it in a seperate thread with its own asyncio loop.
    Calls to the component are forwarded to the underlying componenent and made sure that it happens threadsafe and
    with correct asycnio loop (in case of
    """

    def __init__(self, component: Component = None, thread_name=None, loop=None):
        self.component = component
        self.thread_name = thread_name
        self.running = False
        self._loop = loop or asyncio.new_event_loop()
        self._thread: Optional[threading.Thread] = None
        self._finalizer: Optional[Callable] = None
        self._logger = ThreadLoggerAppender(logger.getChild(self.__class__.__name__), extra={})

    async def init(
        self,
        factory: Union[
            Component,
            Callable[[], Component],
            Callable[[], Awaitable[Component]],
            Callable[[], Generator[Component, Any, None]],
            Callable[[], AsyncGenerator[Component, None]],
        ],
    ):
        """
        Use this init method to create the underlying component if it implicitly accesses the asyncio loop.
        The factory will be executed in the dedicated thread and with the correct loop. If you provide a generator
        it must yield exactly once.
        """
        if inspect.isasyncgenfunction(factory):

            async def _init():
                gen_obj = cast(AsyncIterator[Component], factory())

                async def setup():
                    res = await gen_obj.__anext__()
                    return res

                async def finalizer():
                    try:
                        await gen_obj.__anext__()
                    except StopAsyncIteration:
                        pass
                    else:
                        msg = "Async generator didn't stop."
                        msg += "Yield only once."
                        raise ValueError(msg)

                self._finalizer = finalizer
                self.component = await setup()

        elif inspect.isgeneratorfunction(factory):

            async def _init():
                gen_obj = cast(Iterator[Component], factory())

                async def setup():
                    res = gen_obj.__next__()
                    return res

                async def finalizer():
                    """Yield again, to finalize."""
                    try:
                        gen_obj.__next__()
                    except StopIteration:
                        pass
                    else:
                        msg = "Generator didn't stop."
                        msg += "Yield only once."
                        raise ValueError(msg)

                self._finalizer = finalizer
                self.component = await setup()

        elif inspect.iscoroutinefunction(factory):

            async def _init():
                self.component = await factory()

        elif inspect.isfunction(factory):

            async def _init():
                self.component = factory()

        else:
            self.component = cast(Component, factory)
            return

        await self._start_thread()
        await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(_init(), self._loop))
        self._logger.debug("Init done")

    async def start(self) -> None:
        assert self.component, "component must be provided"
        self._logger.debug("Starting")

        async def _start():
            self._logger.debug("Starting underlying component")
            assert self._loop == asyncio.get_running_loop()
            await self.component.start()
            self._logger.debug("Underlying components started")

        await self._start_thread()

        await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(_start(), self._loop))

    async def stop(self) -> None:
        self._logger.debug("Stopping")

        # Stop underlying component
        async def _stop():
            self._logger.debug("Stopping underlying component")
            assert self._loop == asyncio.get_running_loop()
            await self.component.stop()
            self._logger.debug("Underlying components stopped")

        await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(_stop(), self._loop))

        # Calling finalizer
        if self._finalizer:
            self._logger.debug("Calling finalizer")
            await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(self._finalizer(), self._loop))
            self._logger.debug("Finalizer finished")

        # Stop thread
        await self._stop_thread()

    async def ready(self) -> bool:
        async def _ready():
            assert self._loop == asyncio.get_running_loop()
            return await self.component.ready()

        fut = asyncio.run_coroutine_threadsafe(_ready(), self._loop)
        return await asyncio.wrap_future(fut)

    async def _start_thread(self):
        if self._create_thread():
            await asyncio.get_event_loop().run_in_executor(None, self._thread.start)
            self._logger.debug("Started Thread (async)")

    def _start_thread_blocking(self):
        if self._create_thread():
            self._thread.start()
            self._logger.debug("Started Thread (sync)")

    def _create_thread(self):
        if self._thread:
            return False
        self._logger.debug("Starting Thread")

        def run():
            self._logger.debug("Thread running")
            asyncio.set_event_loop(self._loop)
            try:
                self._loop.run_forever()
            except Exception:
                self._logger.warning("Exception while running loop", exc_info=True)
            self._logger.debug("Thread stopped")

        self._thread = threading.Thread(target=run)
        self._thread.daemon = True
        self._thread.name = self.thread_name
        return True

    def _stop_loop(self):
        self._logger.debug("Stopping loop")
        self._loop.call_soon_threadsafe(self._loop.stop)

    async def _stop_thread(self):
        if self._thread:
            self._stop_loop()
            self._logger.debug("Waiting for thread to finish")
            await asyncio.get_event_loop().run_in_executor(None, self._thread.join)
            self._logger.debug("Stopped")
            self._thread = None

    def _stop_thread_sync(self):
        if self._thread:
            self._stop_loop()
            self._logger.debug("Waiting for thread to finish")
            self._thread.join()
            self._logger.debug("Stopped (sync")
            self._thread = None

    def __del__(self):
        self._stop_thread_sync()

    def __getattr__(self, attr):
        t = type(self.component)
        is_property = isinstance(getattr(t, attr), property) if hasattr(t, attr) else False

        if is_property:

            async def _call():
                return getattr(self.component, attr)

            self._start_thread_blocking()
            return asyncio.run_coroutine_threadsafe(_call(), self._loop).result()
        else:
            component_attr = getattr(self.component, attr)
            if inspect.iscoroutinefunction(component_attr):

                @wraps(component_attr)
                async def wrapper(*function_args, **function_kwargs):
                    async def _call():
                        return await component_attr(*function_args, **function_kwargs)

                    await self._start_thread()
                    return await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(_call(), self._loop))

                return wrapper
            elif inspect.ismethod(component_attr):

                @wraps(component_attr)
                def wrapper(*function_args, **function_kwargs):
                    async def _call():
                        return component_attr(*function_args, **function_kwargs)

                    self._start_thread_blocking()
                    return asyncio.run_coroutine_threadsafe(_call(), self._loop).result()

                return wrapper
            else:
                return component_attr


class CompoundComponent(Component):
    def __init__(self, *components):
        if len(components) == 0:
            raise ValueError("Must provide at least one component")

        if len(components) == 1 and isinstance(components[0], list):
            components = components[0]
        self.components = components

    async def start(self) -> None:
        await asyncio.gather(*[c.start() for c in self.components])

    async def stop(self) -> None:
        await asyncio.gather(*[c.stop() for c in self.components])

    async def ready(self) -> bool:
        readiness = await asyncio.gather(*[c.ready() for c in self.components])
        return all(r is True for r in readiness)
