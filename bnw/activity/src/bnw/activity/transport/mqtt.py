# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, Mapping, Optional, Tuple, Type, Union, cast

from bnw.transport.mqtt import MqttConnection, MqttSubscription

from .. import BaseActivityStrategy
from ..context import BaseResolver
from ..interfaces import ActivityContext, IncludableDeviceResolver
from ..model.device import DeviceName
from ..model.gateway import GatewayName
from ..model.mqtt import (
    MqttCommandRequest,
    MqttCommandResponse,
    MqttDeviceTopic,
    MqttMessage,
    MqttOperation,
    MqttTelemetry,
    MqttTopic,
)
from ..model.wire import Deserializable
from . import delegate_abstract_methods


@delegate_abstract_methods(to="_subscription")
class MqttOperationSubscription(MqttSubscription):
    def __init__(self, subscription: MqttSubscription):
        self._subscription = subscription

    async def get_message(  # type: ignore[override]
        self, clazz: Type[Deserializable] = MqttMessage
    ) -> Tuple[str, MqttMessage]:
        topic, data = await self._subscription.get_message()
        return topic, clazz.deserialize(data)


@delegate_abstract_methods(to="_connection")
class MqttOperationConnection(MqttConnection):
    def __init__(self, connection: MqttConnection) -> None:
        super().__init__()
        self._connection = connection

    async def perform_operation(self, topic: MqttTopic, payload: MqttCommandRequest) -> MqttCommandResponse:
        if payload.res_topic is None:
            payload.res_topic = str(topic.response_topic())

        async with self.subscription(payload.res_topic) as subscription:
            await self.publish(str(topic), payload.serialize_bytes())

            while True:
                topic_str, response = await subscription.get_message(clazz=MqttCommandResponse)
                response = cast(MqttCommandResponse, response)
                if response.session_id == payload.session_id:
                    break

            return response

    @asynccontextmanager
    async def subscription(  # type: ignore[override]
        self, topic: Union[MqttTopic, str]
    ) -> AsyncIterator[MqttOperationSubscription]:
        async with self._connection.subscription(str(topic)) as sub:  # type: ignore[attr-defined]
            yield MqttOperationSubscription(sub)


class MqttContextResolver(BaseResolver, IncludableDeviceResolver):
    def __init__(self, mqtt_connection: MqttOperationConnection, gateway: GatewayName, mqtt_application: str = "sg"):
        super().__init__(IncludableDeviceResolver.INCLUDABLE_DEVICE_ID)

        self._mqtt = mqtt_connection
        self._mqtt_application = mqtt_application
        self._gateway = gateway

        self._includable_device_listener_task: Optional[asyncio.Task] = None
        self._includable_device_listener_active: asyncio.Event = asyncio.Event()
        self._includable_device_queue: asyncio.Queue = asyncio.Queue()
        self._includable_devices: Dict[str, str] = {}

    async def start(self):
        self._includable_device_listener_task = asyncio.create_task(self._includable_device_listener())
        await self._includable_device_listener_active.wait()

    async def stop(self):
        if self._includable_device_listener_task is not None:
            try:
                self._includable_device_listener_task.cancel()
                await self._includable_device_listener_task
            except asyncio.exceptions.CancelledError:
                logging.debug(
                    "Received cancelled error when stopping includable device task. Ignoring it", exc_info=True
                )

    async def _includable_device_listener(self):
        async with self._mqtt.subscription(
            MqttDeviceTopic(
                application=self._mqtt_application,
                operation=MqttOperation.STATUS,
                gateway=self._gateway,
                device="+" if self._gateway.sgtin is None else self._gateway.device_name(),
                path="includable_device/+",
            )
        ) as subscription:
            self._includable_device_listener_active.set()
            try:
                while True:
                    try:
                        topic, telemetry = await subscription.get_message(MqttTelemetry)
                        values = telemetry.payload.protocol_values()
                        topic_parts = topic.split("/")
                        if self._gateway.sgtin is None:
                            self._gateway.sgtin = topic_parts[3]

                        device_name = values["identifier"]
                        includable_device_id = topic_parts[-1]
                        self._includable_devices[device_name] = includable_device_id
                        await self._includable_device_queue.put((device_name, includable_device_id))
                    except Exception:
                        logging.warning("Failure during listening for includable device message", exc_info=True)
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


class MqttActivityStrategy(BaseActivityStrategy):
    _gateway: GatewayName

    def __init__(
        self,
        mqtt_connection: MqttConnection,
        gateway: GatewayName,
        mqtt_application: str = "sg",
        context: Optional[ActivityContext] = None,
    ):
        super().__init__(context=context)
        self._mqtt = MqttOperationConnection(connection=mqtt_connection)  # type: ignore[abstract]
        self._mqtt_application = mqtt_application
        self._gateway = gateway

    def context_values(self) -> Mapping[str, Any]:
        c: Dict[str, Any] = {MqttOperationConnection.__name__: self._mqtt}
        if self._gateway is not None:
            c["gateway_name"] = self._gateway

        return c

    async def activate(self) -> None:
        await super().activate()
        await self._mqtt.connect()

    async def deactivate(self) -> None:
        await self._mqtt.disconnect()
        await super().deactivate()
