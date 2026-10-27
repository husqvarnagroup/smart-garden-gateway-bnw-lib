# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

from typing import Dict, List, Optional, Union

from bnw.protocol import ProtocolEnvelope, ProtocolOperation, ProtocolPayload
from bnw.protocol.entity import EventBusDeviceEntity
from bnw.protocol.message import EventBusProtocolMessage


class EventBusCommandRequest(EventBusProtocolMessage):
    pass


class EventBusCommandResponse(EventBusProtocolMessage):
    success: Optional[bool]

    def __init__(self, success: bool = None, **kwargs):
        super().__init__(**kwargs)
        self.success = success

    def encode(self) -> Dict:
        encoded = super().encode()
        if self.success is not None:
            encoded["success"] = self.success

        return encoded

    @classmethod
    def _decode(cls, message: Dict, base_class: type = None):
        m = super()._decode(message, base_class=base_class if base_class else cls)
        m.success = message["success"]
        return m


class EventBusDeviceCommandRequest(EventBusCommandRequest):
    def __init__(
        self,
        operation: ProtocolOperation,
        device: str,
        path: str,
        payload: Optional[ProtocolPayload] = None,
    ):
        super().__init__(
            operation=operation,
            entity=EventBusDeviceEntity(device=device, path=path),
            payload=payload,
        )

    @classmethod
    def _decode(cls, message: Dict, base_class: type = None):
        m = super()._decode(message, EventBusCommandRequest)

        r = cls._decode_factory(m)
        r.metadata = m.metadata
        return r

    @classmethod
    def _decode_factory(cls, m: "EventBusCommandRequest"):
        assert m.entity
        device = m.entity.get("device", None)
        path = m.entity.get("path", None)

        assert isinstance(device, str)
        assert isinstance(path, str)

        return cls._decode_factory_command(m, device, path)

    @classmethod
    def _decode_factory_command(cls, m: EventBusCommandRequest, device: str, path: str):
        assert m.operation is not None
        return EventBusDeviceCommandRequest(m.operation, device, path, payload=m.payload)


class EventBusDeviceExecuteRequest(EventBusDeviceCommandRequest):
    def __init__(self, device: str, path: str, payload: Optional[ProtocolPayload]):
        super().__init__(ProtocolOperation.EXECUTE, device, path, payload)

    @classmethod
    def _decode_factory_command(cls, m: EventBusCommandRequest, device: str, path: str):
        return EventBusDeviceExecuteRequest(device, path, m.payload)


class EventBusDeviceWriteRequest(EventBusDeviceCommandRequest):
    def __init__(self, device: str, path: str, payload: ProtocolPayload):
        super().__init__(ProtocolOperation.WRITE, device, path, payload)

    @classmethod
    def _decode_factory_command(cls, m: EventBusCommandRequest, device: str, path: str):
        return EventBusDeviceWriteRequest(device, path, m.payload or ProtocolPayload())


class EventBusDeviceReadRequest(EventBusDeviceCommandRequest):
    def __init__(self, device: str, path: str):
        super().__init__(ProtocolOperation.READ, device, path, None)

    @classmethod
    def _decode_factory_command(cls, m: EventBusCommandRequest, device: str, path: str):
        return EventBusDeviceReadRequest(device, path)


class EventBusCommandRequestEnvelope(ProtocolEnvelope):
    @classmethod
    def decode(cls, envelope: Union[List[Dict], Dict], base_class: type = None):
        return super().decode(envelope, base_class=base_class if base_class else cls)

    @classmethod
    def _decode_message(cls, message: Dict) -> EventBusCommandRequest:
        return EventBusCommandRequest.decode(message)


class EventBusCommandResponseEnvelope(ProtocolEnvelope):
    @classmethod
    def decode(cls, envelope: Union[List[Dict], Dict], base_class: type = None):
        return super().decode(envelope, base_class=base_class if base_class else cls)

    @classmethod
    def _decode_message(cls, message: Dict) -> EventBusCommandResponse:
        return EventBusCommandResponse.decode(message)


# Backwards Compatibility
EventBusOperationMessage = EventBusCommandRequest
EventBusResponseMessage = EventBusCommandResponse
EventBusDeviceOperationMessage = EventBusDeviceCommandRequest
EventBusExecuteMessage = EventBusDeviceExecuteRequest
EventBusWriteMessage = EventBusDeviceWriteRequest
EventBusReadMessage = EventBusDeviceReadRequest
EventBusOperationEnvelope = EventBusCommandRequestEnvelope
EventBusResponseEnvelope = EventBusCommandResponseEnvelope
