# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

from typing import Dict

from bnw.protocol import ProtocolOperation, ProtocolPayload
from bnw.protocol.entity import EventBusDeviceEntity
from bnw.protocol.message import EventBusProtocolMessage


class EventBusStatusMessage(EventBusProtocolMessage):
    @classmethod
    def _decode(cls, message: Dict, base_class: type = None):
        m = super()._decode(message, EventBusStatusMessage)

        r = cls._decode_factory(m)
        r.metadata = m.metadata
        return r

    @classmethod
    def _decode_factory(cls, m: "EventBusStatusMessage"):
        return EventBusStatusMessage(
            operation=m.operation,
            entity=m.entity,
            payload=m.payload,
            metadata=m.metadata,
        )


class EventBusDeviceStatusMessage(EventBusStatusMessage):
    @classmethod
    def _decode_factory(cls, m: "EventBusStatusMessage"):
        assert m.entity
        device = m.entity.get("device", None)
        path = m.entity.get("path", None)

        assert isinstance(device, str)
        assert isinstance(path, str)

        return cls._decode_factory_status(m, device=device, path=path)

    @classmethod
    def _decode_factory_status(cls, m: EventBusStatusMessage, device: str, path: str):
        return EventBusDeviceStatusMessage(
            operation=m.operation,
            entity=EventBusDeviceEntity(device, path),
            payload=m.payload,
            metadata=m.metadata,
        )


class EventBusDeviceStatusUpdate(EventBusDeviceStatusMessage):
    def __init__(self, device: str, path: str, payload: ProtocolPayload):
        super().__init__(ProtocolOperation.UPDATE, EventBusDeviceEntity(device, path), payload)

    @classmethod
    def _decode_factory_status(cls, m: EventBusStatusMessage, device: str, path: str):
        return EventBusDeviceStatusUpdate(device, path, m.payload or ProtocolPayload())


class EventBusDeviceStatusOverwrite(EventBusDeviceStatusMessage):
    def __init__(self, device: str, path: str, payload: ProtocolPayload):
        super().__init__(ProtocolOperation.OVERWRITE, EventBusDeviceEntity(device, path), payload)

    @classmethod
    def _decode_factory_status(cls, m: EventBusStatusMessage, device: str, path: str):
        return EventBusDeviceStatusOverwrite(device, path, m.payload or ProtocolPayload())


class EventBusDeviceStatusDelete(EventBusDeviceStatusMessage):
    def __init__(self, device: str, path: str):
        super().__init__(ProtocolOperation.DELETE, EventBusDeviceEntity(device, path), None)

    @classmethod
    def _decode_factory_status(cls, m: EventBusStatusMessage, device: str, path: str):
        return EventBusDeviceStatusDelete(device, path)
