# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Callable, Dict, Mapping, Optional, Type, Union

from bnw.transport.unix.socket import (
    ConsumerConnection,
    EventsSubscription,
    UnixConnection,
)

from bnw.protocol import ProtocolEntity, ProtocolMetadata, ProtocolPayload
from bnw.protocol.message import EventBusProtocolEnvelope, EventBusProtocolMessage

from .. import BaseActivityStrategy
from ..context import BaseResolver
from ..interfaces import ActivityContext, IncludableDeviceResolver
from ..model.device import DeviceName
from ..model.gateway import ServiceName
from ..model.unix import UnixCommandRequest, UnixCommandResponse
from ..model.wire import Deserializable
from . import delegate_abstract_methods

logger = logging.getLogger("bnw.activity.transport.unix")


class UnixSubscription:
    def __init__(
        self, subscription: EventsSubscription, filter: Callable[[Union[ProtocolEntity, EventBusProtocolMessage]], bool]
    ):
        self._subscription = subscription
        self._filter = filter
        self._matching_message: asyncio.Queue = asyncio.Queue()

    async def get_message(
        self, envelope_clazz: Type[Deserializable] = EventBusProtocolEnvelope  # type: ignore[assignment]
    ) -> EventBusProtocolMessage:

        while self._matching_message.empty():
            data = await self._subscription.get_message()
            envelope = envelope_clazz.deserialize(data)
            for m in envelope.messages:
                if self._filter(m.entity):
                    self._matching_message.put_nowait(m)

        return self._matching_message.get_nowait()

    def has_message(self) -> bool:
        return not self._matching_message.empty()


class UnixMessageSubscription(UnixSubscription):
    async def get_message(
        self, envelope_clazz: Type[Deserializable] = EventBusProtocolEnvelope  # type: ignore[assignment]
    ) -> EventBusProtocolMessage:

        while self._matching_message.empty():
            data = await self._subscription.get_message()
            envelope = envelope_clazz.deserialize(data)
            for m in envelope.messages:
                if self._filter(m):
                    self._matching_message.put_nowait(m)

        return self._matching_message.get_nowait()


@delegate_abstract_methods(to="_connection")
class UnixOperationConnection(UnixConnection):
    service_name: ServiceName

    def __init__(self, connection: ConsumerConnection) -> None:
        super().__init__()
        self._connection = connection
        self.service_name = ServiceName(connection.producer_name)
        self._events: asyncio.Queue = asyncio.Queue()
        self._logger = logger.getChild(self.__class__.__name__)

    async def perform_operation(self, request: UnixCommandRequest) -> UnixCommandResponse:
        response_bytes = await self._connection.perform_command(request.serialize_bytes())
        if response_bytes is not None:
            return UnixCommandResponse.deserialize(response_bytes)
        else:
            return UnixCommandResponse(
                success=False,
                payload=ProtocolPayload(vs="No response received"),
                metadata=ProtocolMetadata(error_source=__name__),
            )

    @asynccontextmanager
    async def subscription(
        self, entity_filter: Callable[[Union[ProtocolEntity, EventBusProtocolMessage]], bool]
    ) -> AsyncGenerator[UnixSubscription, None]:
        sub = await self._connection.subscription()
        try:
            await sub.start()
            yield UnixSubscription(sub, entity_filter)
        finally:
            await sub.cancel()

    @asynccontextmanager
    async def message_subscription(
        self, entity_filter: Callable[[Union[ProtocolEntity, EventBusProtocolMessage]], bool]
    ) -> AsyncGenerator[UnixSubscription, None]:
        sub = await self._connection.subscription()
        try:
            await sub.start()
            yield UnixMessageSubscription(sub, entity_filter)
        finally:
            await sub.cancel()


class UnixContextResolver(BaseResolver, IncludableDeviceResolver):
    def __init__(self, unix_connection: UnixOperationConnection):
        super().__init__(IncludableDeviceResolver.INCLUDABLE_DEVICE_ID)

        self._unix = unix_connection

        self._includable_device_listener_task: Optional[asyncio.Task] = None
        self._includable_device_listener_active: asyncio.Event = asyncio.Event()
        self._includable_device_queue: asyncio.Queue = asyncio.Queue()
        self._includable_devices: Dict[str, str] = {}
        self._logger = logger.getChild(self.__class__.__name__)

    async def start(self):
        self._includable_device_listener_task = asyncio.create_task(self._includable_device_listener())
        await self._includable_device_listener_active.wait()

    async def stop(self):
        if self._includable_device_listener_task is not None:
            self._includable_device_listener_task.cancel()
            await self._includable_device_listener_task

    async def _includable_device_listener(self):
        def includable_device_filter(entity: ProtocolEntity) -> bool:
            return entity.get("service", None) is not None and entity.get("path", "").startswith("includable_device/")

        async with self._unix.subscription(includable_device_filter) as subscription:
            self._includable_device_listener_active.set()
            try:
                while True:
                    try:
                        message = await subscription.get_message()
                        includable_device_id = message.entity["path"].split("/")[-1]
                        device_name = message.payload.protocol_values()["identifier"]
                        self._includable_devices[device_name] = includable_device_id
                        self._logger.debug("New includable device with id %s: %s", includable_device_id, device_name)
                        await self._includable_device_queue.put((device_name, includable_device_id))
                    except Exception:
                        self._logger.warning("Failure during listening for includable device message", exc_info=True)
            except asyncio.exceptions.CancelledError:
                pass  # Ignore
            self._includable_device_listener_active.clear()

    def find_includable_device_id(self, device_name: DeviceName) -> Optional[str]:
        return self._includable_devices.get(str(device_name), None)

    async def wait_for_includable_device_id(self, device_name: DeviceName) -> str:
        while True:
            device_str, includable_device = await self._includable_device_queue.get()
            if device_str == str(device_name):
                return includable_device


class UnixActivityStrategy(BaseActivityStrategy):
    def __init__(self, unix_connection: ConsumerConnection, context: Optional[ActivityContext] = None):
        super().__init__(context=context)
        self._unix = UnixOperationConnection(connection=unix_connection)  # type: ignore[abstract]
        self._service = ServiceName(unix_connection.producer_name)

    def context_values(self) -> Mapping[str, Any]:
        return {f"{UnixOperationConnection.__name__}-{self._unix.service_name}": self._unix}

    async def activate(self) -> None:
        await super().activate()
        await self._unix.connect()

    async def deactivate(self) -> None:
        await self._unix.disconnect()
        await super().deactivate()
