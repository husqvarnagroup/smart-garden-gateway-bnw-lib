# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
import json
import logging
import warnings
from typing import Any, Awaitable, Callable, Optional

from . import (
    COMMAND_REQUEST_MESSAGE_MAX_SIZE,
    COMMAND_REQUEST_QUEUE_SIZE,
    DEFAULT_SOCKET_LOCATION,
    MESSAGE_SEPERATOR,
    UnixConnection,
)
from ._utils import ignore_cancelled_error, read_loop, truncate_log_data
from .unix_socket_consumer import CommandConnection, EventConnection

logger = logging.getLogger("bnw.transport.unix.socket")


def socket_event_path(producer_name: str, socket_location: str) -> str:
    return f"{socket_location}/{producer_name}-event.ipc"


def socket_command_path(producer_name: str, socket_location: str) -> str:
    return f"{socket_location}/{producer_name}-command.ipc"


class ProducerConnection(UnixConnection):
    """A connection for a producer (e.g. lwm2mserver) that can send events and handle commands."""

    def __init__(self, producer_name: str, socket_location: str = DEFAULT_SOCKET_LOCATION):
        super().__init__()
        self.producer_name = producer_name
        self.event_path = socket_event_path(producer_name, socket_location)
        self.command_path = socket_command_path(producer_name, socket_location)
        self._logger = logger.getChild(self.__class__.__name__)
        self._event_server: Optional[asyncio.Server] = None
        self._command_server: Optional[asyncio.Server] = None
        self._event_tasks_writers: dict[asyncio.Task[None], asyncio.StreamWriter] = {}
        self._command_tasks: set[asyncio.Task[None]] = set()
        self._command_request_queue: asyncio.Queue[tuple[bytes, asyncio.StreamWriter]] = asyncio.Queue(
            maxsize=COMMAND_REQUEST_QUEUE_SIZE
        )
        self._hacky_response_writer: Optional[asyncio.StreamWriter] = None

    async def connect(self) -> None:
        self._event_server = await asyncio.start_unix_server(self._handle_new_event_connection, self.event_path)
        self._command_server = await asyncio.start_unix_server(
            self._handle_new_command_connection, self.command_path, limit=COMMAND_REQUEST_MESSAGE_MAX_SIZE
        )

    async def disconnect(self) -> None:
        awaitables: list[Awaitable] = []

        def do_close(server: Optional[asyncio.Server], tasks: dict[asyncio.Task, Any] | set[asyncio.Task]) -> None:
            if server is not None:
                server.close()
                awaitables.append(server.wait_closed())

            for task in tasks:
                task.cancel()
                awaitables.append(task)
            tasks.clear()

        do_close(self._event_server, self._event_tasks_writers)
        self._event_server = None
        do_close(self._command_server, self._command_tasks)
        self._command_server = None

        await asyncio.gather(*awaitables)

    async def _handle_new_event_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._logger.debug("Client connected on event socket")
        task = asyncio.create_task(self._handle_event_connection(reader, writer))
        self._event_tasks_writers[task] = writer
        task.add_done_callback(lambda t: self._event_tasks_writers.pop(t, None))

    async def _handle_event_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            warned = False
            while True:
                data = await reader.read(1024)
                if len(data) == 0:
                    self._logger.debug("Client disconnected from event socket")
                    break
                if not warned:
                    warned = True
                    self._logger.warning(f"Received unexpected data on event socket: {truncate_log_data(data)!r}")
        except asyncio.CancelledError:
            self._logger.debug("Connection task for event socket cancelled")
        except Exception as e:
            self._logger.error("Error handling event connection", exc_info=e)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except asyncio.CancelledError:
                pass
            except Exception as e:
                self._logger.error("Error while closing event connection", exc_info=e)

    async def _handle_new_command_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._logger.debug("Client connected on command socket")
        task = asyncio.create_task(self._handle_command_connection(reader, writer))
        self._command_tasks.add(task)
        task.add_done_callback(self._command_tasks.discard)

    async def _handle_command_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        async def handler(data: bytes) -> None:
            await self._command_request_queue.put((data, writer))

        try:
            # Only read data when the write buffer for responses is empty, so a connection cannot stall other
            # connections that easily, thus drain before read.
            await read_loop(
                reader, handler, before_read_handler=writer.drain, logger=self._logger, log_socket_name="command"
            )
        except asyncio.CancelledError:
            self._logger.debug("Connection task for command socket cancelled")
        except Exception as e:
            self._logger.error("Error handling command connection", exc_info=e)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except asyncio.CancelledError:
                pass
            except Exception as e:
                self._logger.error("Error while closing command connection", exc_info=e)

    async def send_event(self, message: bytes) -> None:
        if MESSAGE_SEPERATOR in message:
            raise ValueError("Event message must not contain newline")
        message += MESSAGE_SEPERATOR
        for task, writer in self._event_tasks_writers.items():
            try:
                size = writer.transport.get_write_buffer_size()
                _, high_water = writer.transport.get_write_buffer_limits()
                self._logger.debug(
                    f"Sending {len(message)} bytes to event socket. Write buffer size: {size}, limit: {high_water}"
                )
                if size > high_water:
                    # waiting for drain would block now
                    self._logger.error(f"Dropping event message to prevent blocking: {truncate_log_data(message)!r}")
                else:
                    await writer.drain()
                    writer.write(message)
            except Exception as e:
                self._logger.error("Error writing to event socket", exc_info=e)
                self._event_tasks_writers.pop(task, None)
                task.cancel()

    async def handle_next_command(self, handler: Callable[[bytes], Awaitable[bytes]]) -> None:
        data, writer = await self._command_request_queue.get()

        response = b""
        try:
            response = await handler(data)
            if MESSAGE_SEPERATOR in response:
                raise ValueError("Response message must not contain newline")
        except Exception as e:
            self._logger.error(f"Error while handling command: {truncate_log_data(data)!r}", exc_info=e)
            error_message = [
                {
                    "payload": {"vs": f"Internal error while handling command: {e!r}"},
                    "metadata": {"error_source": self.producer_name},
                    "success": False,
                }
            ]
            response = json.dumps(error_message, indent=None, separators=(",", ":")).encode()
        finally:
            response += MESSAGE_SEPERATOR
            writer.write(response)
            # NOTE: drain will be waited for before reading the next request

    async def _receive_command(self) -> Optional[bytes]:
        warnings.warn(
            "The hacky `_receive_command()` is deprecated. Use `handle_next_command()` instead.", DeprecationWarning
        )
        if self._hacky_response_writer is not None:
            raise RuntimeError("A hacky command is already pending.")
        data, self._hacky_response_writer = await self._command_request_queue.get()
        return data

    async def _respond_command(self, message: bytes) -> None:
        warnings.warn(
            "The hacky `_respond_command()` is deprecated. Use `handle_next_command()` instead.", DeprecationWarning
        )
        if self._hacky_response_writer is None:
            raise RuntimeError("No hacky command is pending.")

        if MESSAGE_SEPERATOR in message:
            raise ValueError("Response message must not contain newline")
        message += MESSAGE_SEPERATOR
        self._hacky_response_writer.write(message)
        self._hacky_response_writer = None


class EventsSubscription:
    def __init__(
        self,
        start_callback: Optional[Callable[["EventsSubscription"], Awaitable[None]]],
        cancel_callback: Optional[Callable[["EventsSubscription"], Awaitable[None]]],
    ):
        self._messages: asyncio.Queue[bytes] = asyncio.Queue()
        self._is_started = False
        self._start_callback = start_callback
        self._cancel_callback = cancel_callback

    async def start(self) -> None:
        self._is_started = True
        if self._start_callback is not None:
            await self._start_callback(self)

    async def cancel(self) -> None:
        self._is_started = False
        if self._cancel_callback is not None:
            await self._cancel_callback(self)

    async def get_message(self) -> bytes:
        return await self._messages.get()

    async def _on_event(self, event: bytes) -> None:
        if self._is_started:
            await self._messages.put(event)


class ConsumerConnection(UnixConnection):
    """A connection for a consumer (e.g. cloudadapter, bnwcli) that can receive events and send commands."""

    def __init__(
        self,
        producer_name: str,
        socket_location: Optional[str] = None,
        command_response_timeout: float = 10.0,
    ):
        super().__init__()
        self._logger = logger.getChild(self.__class__.__name__)
        self.producer_name = producer_name
        if socket_location is None:
            socket_location = DEFAULT_SOCKET_LOCATION
        self._socket_location = socket_location

        self._event_queue: Optional[asyncio.Queue[bytes]] = asyncio.Queue(maxsize=1)
        self._subscriptions: Optional[set[EventsSubscription]] = set()
        self._subscriptions_tasks: set[asyncio.Task[None]] = set()

        self._event_connection: Optional[EventConnection] = None
        self._command_response_timeout = command_response_timeout
        self._command_connection: Optional[CommandConnection] = None

    @property
    def command_path(self) -> str:
        return socket_command_path(self.producer_name, self._socket_location)

    @property
    def event_path(self) -> str:
        return socket_event_path(self.producer_name, self._socket_location)

    async def connect(self) -> None:
        self._event_connection = await EventConnection.new(self.event_path, handler=self.event_handler)
        self._command_connection = await CommandConnection.new(
            self.command_path, response_timeout=self._command_response_timeout
        )

    async def disconnect(self) -> None:
        awaitables: list[Awaitable] = []

        for task in self._subscriptions_tasks:
            task.cancel()
            awaitables.append(ignore_cancelled_error(task))

        if self._event_connection is not None:
            awaitables.append(self._event_connection.disconnect())

        if self._command_connection is not None:
            awaitables.append(self._command_connection.disconnect())

        await asyncio.gather(*awaitables)

    async def event_handler(self, data: bytes) -> None:
        if self._event_queue is not None:
            await self._event_queue.put(data)
        else:
            self._forward_event_to_subscriptions(data)

    async def receive_event(self) -> Optional[bytes]:
        if self._event_queue is None:
            raise RuntimeError("Either use the `receive_event()` or the `subscription()` interface, but not both.")
        self._subscriptions = None
        return await self._event_queue.get()

    async def perform_command(self, message: bytes) -> Optional[bytes]:
        if self._command_connection is None:
            raise RuntimeError("Not connected")
        return await self._command_connection.send(message)

    async def _clear_event_queue(self) -> None:
        while True:
            assert self._event_queue is not None
            try:
                self._event_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            # one sleep per await in the _handle_event_connection loop
            await asyncio.sleep(0)
            await asyncio.sleep(0)

    async def subscription(self) -> EventsSubscription:
        if self._subscriptions is None:
            raise RuntimeError("Either use the `receive_event()` or the `subscription()` interface, but not both.")
        if self._event_queue is not None:
            await self._clear_event_queue()
            self._event_queue = None
        return EventsSubscription(self._on_subscription_start, self._on_subscription_cancel)

    async def _on_subscription_start(self, sub: EventsSubscription) -> None:
        assert self._subscriptions is not None
        self._subscriptions.add(sub)

    async def _on_subscription_cancel(self, sub: EventsSubscription) -> None:
        assert self._subscriptions is not None
        try:
            self._subscriptions.remove(sub)
        except KeyError:
            self._logger.debug("Subscription cancelled but not in subscriptions set")

    def _forward_event_to_subscriptions(self, event: bytes) -> None:
        assert self._subscriptions is not None
        for sub in self._subscriptions:
            # keep the tasks referenced, otherwise they might get garbage collected
            task = asyncio.create_task(sub._on_event(event))  # noqa
            self._subscriptions_tasks.add(task)
            task.add_done_callback(self._subscriptions_tasks.discard)
