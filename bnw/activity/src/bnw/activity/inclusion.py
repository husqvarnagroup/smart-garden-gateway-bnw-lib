# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import logging
from typing import Any, Generator, List, Optional, cast

from bnw.transport.mqtt import MqttConnection
from bnw.transport.unix.socket import ConsumerConnection as UnixConsumerConnection

from bnw.protocol import ProtocolOperation, ProtocolPayload
from bnw.protocol.entity import EventBusDeviceEntity, EventBusServiceEntity

from . import ActivityError, BusinessProcess, use_strategy
from .interfaces import (
    ActivityContext,
    ContextResolver,
    IncludableDeviceResolver,
    InclusionActivities,
)
from .model.device import DeviceName
from .model.gateway import GatewayName
from .model.mqtt import MqttCommandRequest, MqttDeviceTopic, MqttOperation
from .model.unix import UnixCommandRequest
from .transport.mqtt import MqttActivityStrategy, MqttContextResolver
from .transport.unix import UnixActivityStrategy, UnixContextResolver

logger = logging.getLogger("bnw.activity.inclusion")


class InclusionCommandError(ActivityError):
    pass


@use_strategy
class InclusionProcess(BusinessProcess, InclusionActivities):
    pass


class MqttInclusionStrategy(MqttActivityStrategy, InclusionActivities):
    def __init__(
        self,
        mqtt_connection: MqttConnection,
        gateway: GatewayName,
        mqtt_application: str = "sg",
        context: Optional[ActivityContext] = None,
    ):
        super().__init__(
            mqtt_connection=mqtt_connection, gateway=gateway, mqtt_application=mqtt_application, context=context
        )
        self._context_resolver = MqttContextResolver(self._mqtt, gateway, mqtt_application)

    def context_resolvers(self) -> Generator[Any, Any, ContextResolver]:  # type: ignore[return]
        yield self._context_resolver

    async def _get_includable_device_id(self, device: DeviceName, includable_device_id: Optional[str]) -> str:
        if includable_device_id is not None:
            return includable_device_id

        includable_device_id = await self.resolve_in_context(
            IncludableDeviceResolver.INCLUDABLE_DEVICE_ID, device_name=device
        )
        if includable_device_id is not None:
            return includable_device_id

        includable_device_id = self._context_resolver.find_includable_device_id(device_name=device)
        if includable_device_id is not None:
            return includable_device_id

        return await self._context_resolver.wait_for_includable_device_id(device_name=device)

    async def include(self, device: DeviceName, includable_device_id: Optional[str] = None, **additional_context):
        includable_device_id = await self._get_includable_device_id(device, includable_device_id)
        gateway_device = self._gateway.device_name()
        topic = MqttDeviceTopic(
            application=self._mqtt_application,
            operation=MqttOperation.EXECUTE,  # type: ignore[call-arg]
            gateway=self._gateway,
            device=gateway_device,
            path=f"includable_device/{includable_device_id}/include",
        )
        payload = MqttCommandRequest(response_topic=topic.response_topic())

        result = await self._mqtt.perform_operation(topic, payload)
        if not result.success:
            raise InclusionCommandError(payload=cast(ProtocolPayload, result.payload), metadata=result.metadata)

    async def exclude(self, device: DeviceName, **additional_context):
        topic = MqttDeviceTopic(
            application=self._mqtt_application,
            operation=MqttOperation.EXECUTE,  # type: ignore[call-arg]
            gateway=self._gateway,
            device=device,
            path="device/0/factory_reset",
        )
        payload = MqttCommandRequest(response_topic=topic.response_topic())

        result = await self._mqtt.perform_operation(topic, payload)
        if not result.success:
            raise InclusionCommandError(payload=cast(ProtocolPayload, result.payload), metadata=result.metadata)
        logger.debug("Exclusion successful. Metadata: %s", result.metadata)

    async def get_included_devices(self) -> Optional[List[DeviceName]]:
        raise NotImplementedError


class UnixInclusionStrategy(UnixActivityStrategy, InclusionActivities):
    def __init__(self, unix_connection: UnixConsumerConnection, context: Optional[ActivityContext] = None):
        super().__init__(unix_connection=unix_connection, context=context)
        self._context_resolver = UnixContextResolver(unix_connection=self._unix)

    def context_resolvers(self) -> Generator[Any, Any, ContextResolver]:  # type: ignore[return]
        yield self._context_resolver

    async def _get_includable_device_id(self, device: DeviceName, includable_device_id: Optional[str]) -> str:
        if includable_device_id is not None:
            return includable_device_id

        includable_device_id = await self.resolve_in_context(
            IncludableDeviceResolver.INCLUDABLE_DEVICE_ID, device_name=device
        )
        if includable_device_id is not None:
            return includable_device_id

        includable_device_id = self._context_resolver.find_includable_device_id(
            device_name=device  # type: ignore[arg-type]
        )
        if includable_device_id is not None:
            return includable_device_id

        return await self._context_resolver.wait_for_includable_device_id(device_name=device)  # type: ignore[arg-type]

    async def include(self, device: DeviceName, includable_device_id: Optional[str] = None, **additional_context):
        includable_device_id = await self._get_includable_device_id(device, includable_device_id)
        op = UnixCommandRequest(
            operation=ProtocolOperation.EXECUTE,
            entity=EventBusServiceEntity(self._unix.service_name, f"includable_device/{includable_device_id}/include"),
        )
        result = await self._unix.perform_operation(op)
        if not result.success:
            raise InclusionCommandError(payload=result.payload, metadata=result.metadata)

    async def exclude(self, device: DeviceName, **additional_context):
        op = UnixCommandRequest(
            operation=ProtocolOperation.EXECUTE, entity=EventBusDeviceEntity(str(device), "device/0/factory_reset")
        )
        result = await self._unix.perform_operation(op)
        if not result.success:
            raise InclusionCommandError(payload=result.payload, metadata=result.metadata)

    async def get_included_devices(self) -> Optional[List[DeviceName]]:
        op = UnixCommandRequest(
            operation=ProtocolOperation.READ, entity=EventBusServiceEntity(str(self._service), "devices")
        )
        result = await self._unix.perform_operation(op)
        if not result.success:
            raise InclusionCommandError(payload=result.payload, metadata=result.metadata)
        assert result.payload is not None
        return [DeviceName.from_string(identifier) for identifier in result.payload.keys()]
