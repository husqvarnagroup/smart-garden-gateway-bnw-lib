# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
from contextlib import asynccontextmanager
from time import time
from typing import Any, Awaitable, Callable, Optional

from bnw.tfw.component import Component
from bnw.transport.unix import DEFAULT_SOCKET_LOCATION
from bnw.transport.unix.socket import ProducerConnection

from bnw.protocol import (
    ProtocolEnvelope,
    ProtocolMessage,
    ProtocolMetadata,
    ProtocolPayload,
)
from bnw.protocol.command import (
    EventBusCommandRequest,
    EventBusCommandRequestEnvelope,
    EventBusCommandResponse,
    EventBusResponseEnvelope,
    EventBusResponseMessage,
)


class GenericService(Component):
    def __init__(self, name, *, location=DEFAULT_SOCKET_LOCATION, producer_connection_class=ProducerConnection):
        self.name = name
        self._connection = producer_connection_class(name, location)

    async def start(self) -> None:
        await self._connection.connect()

    async def stop(self) -> None:
        await self._connection.disconnect()

    async def ready(self) -> bool:
        return self._connection is not None

    async def publish(self, message: bytes):
        await self._connection.send_event(message)

    async def publish_protocol_message(self, message: ProtocolMessage) -> None:
        await self._connection.send_event(ProtocolEnvelope(messages=[message]).serialize().encode())

    async def respond_success(self, **kwargs: Optional[Any]) -> None:
        if "metadata" not in kwargs:
            kwargs["metadata"] = ProtocolMetadata(source=self.name)

        await self.respond_operation(EventBusResponseMessage(True, **kwargs))

    async def respond_failure(self, **kwargs: Optional[Any]) -> None:
        if "metadata" not in kwargs:
            kwargs["metadata"] = ProtocolMetadata(error_source=self.name)
        await self.respond_operation(EventBusResponseMessage(False, **kwargs))

    async def respond_operation(self, message: EventBusResponseMessage) -> None:
        await self.respond_operation_envelope(EventBusResponseEnvelope([message]))

    async def respond_operation_envelope(self, envelope: EventBusResponseEnvelope) -> None:
        await self._connection._respond_command(envelope.serialize().encode())


class RequestHandingService(GenericService):
    def __init__(self, name, *, location=DEFAULT_SOCKET_LOCATION):
        super().__init__(name, location=location)
        self.location = location
        self._request_handler_lock = asyncio.Lock()

    @asynccontextmanager
    async def request_handler(
        self, request_handler: Callable[[EventBusCommandRequest], Awaitable[EventBusCommandResponse]]
    ):
        async with self._request_handler_lock:
            stop = asyncio.Event()

            async def handler_runner():
                async def handle_eventbus_command(cmd: bytes) -> bytes:
                    try:
                        e = EventBusCommandRequestEnvelope.deserialize(cmd)
                        responses = []
                        for m in e.messages:
                            r = await request_handler(m)
                            responses.append(r)

                        return EventBusCommandRequestEnvelope(messages=responses).serialize().encode()

                    except Exception as e:
                        return (
                            EventBusCommandRequestEnvelope(
                                messages=[EventBusCommandResponse(success=False, payload=ProtocolPayload(vs=str(e)))]
                            )
                            .serialize()
                            .encode()
                        )

                while not stop.is_set():
                    try:
                        await self._connection.handle_next_command(handle_eventbus_command)
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        pass

            handler_task = asyncio.create_task(handler_runner())

            try:
                yield self
            finally:
                stop.set()
                handler_task.cancel()
                await handler_task


class TestingService(GenericService):
    __test__ = False  # prevent detection as test class

    async def request_operation(self, timeout: float = 10.0) -> EventBusCommandRequest:
        return (await self.request_operation_envelope(timeout)).messages[0]

    async def request_operation_envelope(self, timeout: float = 10.0) -> EventBusCommandRequestEnvelope:
        start = time()
        while time() < start + timeout:
            try:
                b = await self._connection._receive_command()
                return EventBusCommandRequestEnvelope.deserialize(b)
            except asyncio.TimeoutError:
                pass

        raise TimeoutError
