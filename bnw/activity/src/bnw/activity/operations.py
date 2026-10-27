# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

from typing import List, Mapping, Optional, Tuple, Union, cast

from bnw.protocol import (
    ProtocolOperation,
    ProtocolPayload,
    ProtocolPayloadValue,
    ProtocolPayloadValueType,
)
from bnw.protocol.entity import EventBusDeviceEntity

from . import ActivityError, BusinessProcess, use_strategy
from .interfaces import ResourceOperationActivities
from .model.device import (
    DeviceName,
    DeviceResource,
    DeviceResourcePath,
    DeviceResourceValue,
    DeviceResourceWriteBatch,
)
from .model.mqtt import (
    MqttCommandRequest,
    MqttCommandResponse,
    MqttDeviceTopic,
    MqttOperation,
)
from .model.unix import UnixCommandRequest, UnixCommandResponse
from .transport.mqtt import MqttActivityStrategy
from .transport.unix import UnixActivityStrategy


class ResourceOperationError(ActivityError):
    pass


@use_strategy
class ResourceOperationProcess(BusinessProcess, ResourceOperationActivities):
    pass


class BaseResourceOperationStrategy(ResourceOperationActivities):
    def _validate_execute_arguments(self, arguments: Optional[DeviceResourceValue]) -> Optional[Mapping]:
        if arguments is not None:
            try:
                encoded = arguments.encode()
                value = ProtocolPayloadValue.from_json_dict(encoded)
                if value.type != ProtocolPayloadValueType.STRING:
                    raise ValueError("Only string value type supported")
                if not value.is_multiple():
                    raise ValueError("Only array value type supported")
            except ValueError as e:
                raise ResourceOperationError(f"Invalid argument: {e}") from e
            return encoded
        else:
            return None


class MqttResourceOperationStrategy(MqttActivityStrategy, BaseResourceOperationStrategy):
    async def read(
        self, device: DeviceName, path: DeviceResourcePath, mqtt_application: str = "sg", **context
    ) -> Tuple[List[DeviceResource], MqttCommandResponse]:
        topic = MqttDeviceTopic(
            application=self._mqtt_application,  # type: ignore[call-arg]
            operation=MqttOperation.GET,
            gateway=self._gateway,
            device=device,
            path=path.to_string(),
        )
        payload = MqttCommandRequest(response_topic=topic.response_topic())

        operation_result = await self._mqtt.perform_operation(topic, payload)
        if not operation_result.success:
            raise ResourceOperationError(
                payload=cast(ProtocolPayload, operation_result.payload), metadata=operation_result.metadata
            )

        if operation_result.payload is None:
            raise ResourceOperationError("Response had no payload")

        return (
            DeviceResource.from_payload(path=path, payload=cast(ProtocolPayload, operation_result.payload)),
            operation_result,
        )

    async def write(
        self,
        device: DeviceName,
        path: DeviceResourcePath,
        value: Union[DeviceResourceValue, DeviceResourceWriteBatch],
        **context,
    ) -> Tuple[None, MqttCommandResponse]:
        topic = MqttDeviceTopic(
            application=self._mqtt_application,
            operation=MqttOperation.SET,  # type: ignore[call-arg]
            gateway=self._gateway,
            device=device,
            path=path.to_string(),
        )
        payload = MqttCommandRequest(response_topic=topic.response_topic(), payload=ProtocolPayload(value.encode()))

        result = await self._mqtt.perform_operation(topic, payload)
        if not result.success:
            raise ResourceOperationError(payload=cast(ProtocolPayload, result.payload), metadata=result.metadata)

        return None, result

    async def execute(
        self, device: DeviceName, path: DeviceResourcePath, arguments: Optional[DeviceResourceValue] = None, **context
    ) -> Tuple[None, MqttCommandResponse]:
        topic = MqttDeviceTopic(
            application=self._mqtt_application,
            operation=MqttOperation.EXECUTE,  # type: ignore[call-arg]
            gateway=self._gateway,
            device=device,
            path=path.to_string(),
        )
        payload = MqttCommandRequest(response_topic=topic.response_topic())

        valid_args = self._validate_execute_arguments(arguments)
        if valid_args is not None:
            payload.payload = ProtocolPayload(valid_args)

        result = await self._mqtt.perform_operation(topic, payload)
        if not result.success:
            raise ResourceOperationError(payload=cast(ProtocolPayload, result.payload), metadata=result.metadata)

        return None, result


class UnixResourceOperationStrategy(UnixActivityStrategy, BaseResourceOperationStrategy):
    async def read(
        self, device: DeviceName, path: DeviceResourcePath, **context
    ) -> Tuple[List[DeviceResource], UnixCommandResponse]:
        op = UnixCommandRequest(
            operation=ProtocolOperation.READ,
            entity=EventBusDeviceEntity(str(device), path.to_string()),
        )

        operation_result = await self._unix.perform_operation(op)
        if not operation_result.success:
            raise ResourceOperationError(payload=operation_result.payload, metadata=operation_result.metadata)

        if operation_result.payload is None:
            raise ResourceOperationError("Response had no payload")

        return DeviceResource.from_payload(path=path, payload=operation_result.payload), operation_result

    async def write(
        self,
        device: DeviceName,
        path: DeviceResourcePath,
        value: Union[DeviceResourceValue, DeviceResourceWriteBatch],
        **context,
    ) -> Tuple[None, UnixCommandResponse]:
        op = UnixCommandRequest(
            operation=ProtocolOperation.WRITE,
            entity=EventBusDeviceEntity(str(device), path.to_string()),
            payload=ProtocolPayload(value.encode()),
        )

        result = await self._unix.perform_operation(op)
        if not result.success:
            raise ResourceOperationError(payload=result.payload, metadata=result.metadata)

        return None, result

    async def execute(
        self, device: DeviceName, path: DeviceResourcePath, arguments: Optional[DeviceResourceValue] = None, **context
    ) -> Tuple[None, UnixCommandResponse]:

        op = UnixCommandRequest(
            operation=ProtocolOperation.EXECUTE, entity=EventBusDeviceEntity(str(device), path.to_string())
        )

        valid_args = self._validate_execute_arguments(arguments)
        if valid_args is not None:
            op.payload = ProtocolPayload(valid_args)

        result = await self._unix.perform_operation(op)
        if not result.success:
            raise ResourceOperationError(payload=result.payload, metadata=result.metadata)

        return None, result
