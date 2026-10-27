# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional, TypeVar

from . import (
    COMMAND_RESPONSE_MESSAGE_MAX_SIZE,
    EVENT_MESSAGE_MAX_SIZE,
    MESSAGE_SEPERATOR,
)
from ._utils import ignore_cancelled_error, read_loop, truncate_log_data

logger = logging.getLogger("unix_socket_consumer")


class _Connection:
    # Starting with Python 3.12 we can use a type parameter instead
    _CLS = TypeVar("_CLS", bound="_Connection")

    # 0 is an invalid value for limit, it must be overridden by subclasses
    LIMIT = 0

    def __init__(self, path: str, *, reader_writer: tuple[asyncio.StreamReader, asyncio.StreamWriter]):
        self._logger = logger.getChild(self.__class__.__name__)
        self._path = path
        self._reader, self._writer = reader_writer
        self._shutdown = False

        self._task = asyncio.create_task(self._handle())

    @classmethod
    async def new(cls: type[_CLS], path: str, **kwargs: Any) -> _CLS:
        reader_writer = await cls._connect_socket(path)
        return cls(path, reader_writer=reader_writer, **kwargs)

    @classmethod
    async def _connect_socket(cls, path: str) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        return await asyncio.open_unix_connection(path, limit=cls.LIMIT)

    async def _reconnect_socket(self) -> None:
        self._reader, self._writer = await self._connect_socket(self._path)
        self._logger.debug("Successfully reconnected to socket")

    async def _reconnect(self) -> None:
        if self._shutdown:
            return
        self._writer.close()
        await self._writer.wait_closed()
        await self._reconnect_socket()

    async def disconnect(self) -> None:
        # Give some time for the _shutdown flag to propagate to the _handle() loop
        # This is need, otherwise some tests error during teardown
        await asyncio.sleep(0.1)
        self._shutdown = True
        self._task.cancel()
        await self._task

    async def _handle(self) -> None:
        raise NotImplementedError()


class EventConnection(_Connection):
    LIMIT = EVENT_MESSAGE_MAX_SIZE

    def __init__(
        self,
        path: str,
        *,
        reader_writer: tuple[asyncio.StreamReader, asyncio.StreamWriter],
        handler: Callable[[bytes], Awaitable[None]],
    ):
        self._handler = handler
        super().__init__(path, reader_writer=reader_writer)

    async def _handle(self) -> None:
        try:
            while not self._shutdown:
                await read_loop(self._reader, self._handler, logger=self._logger, log_socket_name="event")
                await self._reconnect()
        except asyncio.CancelledError:
            self._logger.debug("Connection task for event socket cancelled")
        finally:
            self._writer.close()
            await self._writer.wait_closed()


class CommandConnection(_Connection):
    LIMIT = COMMAND_RESPONSE_MESSAGE_MAX_SIZE

    response_channel_type = asyncio.Queue[Optional[bytes]]
    get_request_task_type = asyncio.Task[tuple[bytes, response_channel_type]]

    def __init__(
        self,
        path: str,
        *,
        reader_writer: tuple[asyncio.StreamReader, asyncio.StreamWriter],
        response_timeout: float,
        request_queue: Optional[asyncio.Queue[tuple[bytes, "CommandConnection.response_channel_type"]]] = None,
    ):
        self._response_timeout = response_timeout

        self._response_channel: Optional[CommandConnection.response_channel_type] = None
        self._read_response_task: Optional[asyncio.Task[bytes]] = None
        self._timeout: Optional[float] = None

        if request_queue is None:
            request_queue = asyncio.Queue()
        self._request_queue = request_queue
        self._get_request_task: Optional[CommandConnection.get_request_task_type] = self._create_get_request_task()

        super().__init__(path, reader_writer=reader_writer)

    def _create_get_request_task(self) -> get_request_task_type:
        return asyncio.create_task(self._request_queue.get())

    async def _handle_response(self, response: Optional[bytes]) -> None:
        assert self._response_channel is not None
        assert self._timeout is not None
        assert self._get_request_task is None
        await self._response_channel.put(response)
        self._response_channel = None
        self._timeout = None
        self._get_request_task = self._create_get_request_task()

    async def _handle_timeout(self) -> None:
        assert self._read_response_task is not None

        self._logger.debug("Command timed out")

        await self._handle_response(None)

        self._read_response_task.cancel()
        await ignore_cancelled_error(self._read_response_task)
        self._read_response_task = None
        # Reconnect on timeout, because the connection is spoiled
        await self._reconnect()

    async def _handle_read_response_task(self) -> None:
        assert self._read_response_task is not None

        response_data = None
        try:
            response_data = (await self._read_response_task).removesuffix(MESSAGE_SEPERATOR)
        except asyncio.LimitOverrunError as e:
            # this read will not block
            partial_data = await self._reader.read(e.consumed)
            self._logger.error(
                "Partially received too long message from command socket:" f" {truncate_log_data(partial_data)!r}"
            )
        except asyncio.IncompleteReadError as e:
            if len(e.partial) == 0:
                self._logger.debug("Peer disconnected from command socket")
            else:
                self._logger.error(
                    f"Received truncated data on command socket just before peer closed connection:"
                    f" {truncate_log_data(e.partial)!r}"
                )
        else:
            if self._response_channel is None:
                self._logger.error(f"Received data without a pending request: {truncate_log_data(response_data)!r}")
        finally:
            if self._response_channel is not None:
                await self._handle_response(response_data)

        self._read_response_task = None
        if response_data is None:
            await self._reconnect()

    async def _handle_get_request_task(self) -> None:
        assert self._get_request_task is not None

        assert self._response_channel is None
        message, self._response_channel = self._get_request_task.result()
        self._get_request_task = None
        self._timeout = self._response_timeout

        self._writer.write(message)

    async def _handle(self) -> None:
        try:
            while True:
                if self._read_response_task is None:
                    self._read_response_task = asyncio.create_task(self._reader.readuntil(MESSAGE_SEPERATOR))

                tasks = [t for t in [self._read_response_task, self._get_request_task] if t is not None]
                done, _ = await asyncio.wait(tasks, timeout=self._timeout, return_when=asyncio.FIRST_COMPLETED)

                if len(done) == 0:
                    await self._handle_timeout()
                    continue

                if self._read_response_task in done:
                    await self._handle_read_response_task()

                if self._get_request_task is not None and self._get_request_task in done:
                    await self._handle_get_request_task()

        except asyncio.CancelledError:
            self._logger.debug("Connection task for command socket cancelled")
        finally:
            awaitables = []

            self._writer.close()
            awaitables.append(self._writer.wait_closed())

            if self._read_response_task is not None:
                self._read_response_task.cancel()
                awaitables.append(ignore_cancelled_error(self._read_response_task))

            if self._get_request_task is not None:
                self._get_request_task.cancel()
                awaitables.append(ignore_cancelled_error(self._get_request_task))

            await asyncio.gather(*awaitables)

    async def send(self, message: bytes) -> Optional[bytes]:
        # NOTE: send will wait without the timout being running if there are other requests in the queue that have to be
        #       handled first. The timeout starts when the request has been sent.
        if MESSAGE_SEPERATOR in message:
            raise ValueError("Command message must not contain newline")
        message += MESSAGE_SEPERATOR
        self._logger.debug(f"Sending command: {truncate_log_data(message)!r}")
        response_channel: CommandConnection.response_channel_type = asyncio.Queue(maxsize=1)
        await self._request_queue.put((message, response_channel))
        response = await response_channel.get()
        if response is not None:
            self._logger.debug(f"Received response: {truncate_log_data(response)!r}")
        return response


class CommandConnectionPool:
    def __init__(self, connections: list[CommandConnection]):
        self.connections = connections

    @classmethod
    async def new(cls, path: str, *, response_timeout: float, num_connections: int) -> "CommandConnectionPool":
        request_queue: asyncio.Queue[tuple[bytes, "CommandConnection.response_channel_type"]] = asyncio.Queue()
        connections = [
            await CommandConnection.new(path, response_timeout=response_timeout, request_queue=request_queue)
            for _ in range(num_connections)
        ]
        return cls(connections)

    async def disconnect(self) -> None:
        for connection in self.connections:
            await connection.disconnect()

    async def send(self, message: bytes) -> Optional[bytes]:
        # Just using the send method of any connection, it will be put to the shared request queue.
        return await self.connections[0].send(message)
