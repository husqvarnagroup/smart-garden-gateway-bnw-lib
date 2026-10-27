# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import random
import string
from collections import namedtuple
from typing import Dict, List, NamedTuple, Optional, Union

from bnw.protocol import (
    ProtocolEntity,
    ProtocolMessage,
    ProtocolMetadata,
    ProtocolOperation,
    ProtocolPayload,
)

from . import StrEnum
from .gateway import GatewayName
from .wire import Deserializable, Serializable


class MqttOperation(StrEnum):
    GET = "get"
    GET_RESULT = "get-res"
    SET = "set"
    SET_RESULT = "set-res"
    EXECUTE = "exc"
    EXECUTE_RESULT = "exc-res"
    STATUS = "sta"

    COMMAND = "cmd"
    COMMAND_RESULT = "cmd-res"
    DATA = "dat"

    def response_operation(self) -> "MqttOperation":
        if self == MqttOperation.GET:
            return MqttOperation.GET_RESULT

        if self == MqttOperation.SET:
            return MqttOperation.SET_RESULT

        if self == MqttOperation.EXECUTE:
            return MqttOperation.EXECUTE_RESULT

        if self == MqttOperation.COMMAND:
            return MqttOperation.COMMAND_RESULT

        raise ValueError(f"Response operation for {self} not defined")


APPLICATION = "sg"


class MqttTopic(NamedTuple):

    application: str
    operation: MqttOperation
    gateway: GatewayName
    subtopic: str

    def __str__(self):
        return "/".join([str(self.application), str(self.operation), str(self.gateway), str(self.subtopic)])

    def response_topic(self):
        return self._replace(operation=self.operation.response_operation())


_MqttDeviceTopic = namedtuple("_MqttDeviceTopic", MqttTopic._fields[0:-1] + ("device", "path"))  # type: ignore[misc]


class MqttDeviceTopic(_MqttDeviceTopic, MqttTopic):  # type: ignore[misc]
    def __str__(self):
        s = MqttTopic.__str__(self)
        path_segment = f"{self.path}"
        if path_segment:
            s += "/"
            s += path_segment

        return s


_MqttServiceTopic = namedtuple("_MqttServiceTopic", MqttTopic._fields[0:-1] + ("service", "path"))  # type: ignore[misc]


class MqttServiceTopic(_MqttServiceTopic, MqttTopic):  # type: ignore[misc]
    def __str__(self):
        s = MqttTopic.__str__(self)
        path_segment = f"{self.path}"
        if path_segment:
            s += "/"
            s += path_segment

        return s


class MqttMessage(Serializable, Deserializable):
    payload: Optional[Union[ProtocolPayload, ProtocolMessage, List[ProtocolMessage]]]
    metadata: Optional[ProtocolMetadata]

    def __init__(
        self,
        payload: Optional[Union[ProtocolPayload, ProtocolMessage, List[ProtocolMessage]]] = None,
        metadata: Optional[ProtocolMetadata] = None,
    ) -> None:
        super().__init__()
        self.payload = payload
        self.metadata = metadata

    def encode(self) -> Dict:
        d: Dict[str, Union[List[Dict], Dict]] = {}

        if self.payload is not None:
            if isinstance(self.payload, list):
                d["payload"] = [p.encode() for p in self.payload]
            else:
                d["payload"] = self.payload.encode()

        if self.metadata is not None:
            d["metadata"] = self.metadata.encode()

        return d

    @classmethod
    def _decode(cls, message: Dict, base_class: type = None):
        m = base_class() if base_class else cls()
        if "payload" in message:
            if isinstance(message["payload"], list):
                m.payload = [ProtocolPayload(p) for p in message["payload"]]
            else:
                m.payload = ProtocolPayload(message["payload"])

        if "metadata" in message:
            m.metadata = ProtocolMetadata(message["metadata"])

        return m


class MqttSessionMessage(MqttMessage):
    session_id: str

    def __init__(
        self,
        session_id: Optional[str] = None,
        payload: Optional[Union[ProtocolPayload, ProtocolMessage, List[ProtocolMessage]]] = None,
        metadata: Optional[ProtocolMetadata] = None,
    ) -> None:
        super().__init__(payload=payload, metadata=metadata)

        self.session_id = (
            "".join(random.choices(string.ascii_lowercase + string.digits, k=20)) if session_id is None else session_id
        )

    def encode(self) -> Dict:
        encoded = super().encode()

        if self.session_id is not None:
            encoded["session-id"] = self.session_id

        return encoded

    @classmethod
    def _decode(cls, message: Dict, base_class: type = None):
        m = super()._decode(message, base_class=base_class if base_class else cls)

        if "session-id" in message:
            m.session_id = message["session-id"]

        return m


class MqttCommandRequest(MqttSessionMessage):
    res_topic: Optional[str]

    def __init__(
        self,
        session_id: Optional[str] = None,
        payload: Optional[Union[ProtocolPayload, ProtocolMessage, List[ProtocolMessage]]] = None,
        metadata: Optional[ProtocolMetadata] = None,
        response_topic: Optional[Union[str, MqttTopic]] = None,
    ) -> None:
        super().__init__(session_id=session_id, payload=payload, metadata=metadata)

        if response_topic is not None:
            if isinstance(response_topic, MqttTopic):
                self.res_topic = str(response_topic)
            else:
                self.res_topic = response_topic
        else:
            self.res_topic = None

    def encode(self) -> Dict:
        encoded = super().encode()

        if self.res_topic is not None:
            encoded["res-topic"] = self.res_topic

        return encoded

    @classmethod
    def _decode(cls, message: Dict, base_class: type = None):
        m = super()._decode(message, base_class=base_class if base_class else cls)

        if "res-topic" in message:
            m.res_topic = message["res-topic"]

        return m


class MqttCommandResponse(MqttSessionMessage):
    def __init__(
        self,
        success: Optional[bool] = None,
        session_id: Optional[str] = None,
        payload: Optional[ProtocolPayload] = None,
        metadata: Optional[ProtocolMetadata] = None,
    ) -> None:
        super().__init__(session_id=session_id, payload=payload, metadata=metadata)
        self.success = success

    def encode(self) -> Dict:
        encoded = super().encode()
        if self.success is not None:
            encoded["success"] = self.success

        return encoded

    @classmethod
    def _decode(cls, message: Dict, base_class: type = None):
        m = super()._decode(message, base_class=base_class if base_class else cls)
        m.success = message.get("success", None)
        return m


class MqttTelemetry(MqttMessage):
    operation: Optional[ProtocolOperation]
    entity: Optional[ProtocolEntity]

    def __init__(
        self,
        operation: Optional[ProtocolOperation] = None,
        entity: Optional[ProtocolEntity] = None,
        payload: Optional[ProtocolPayload] = None,
        metadata: Optional[ProtocolMetadata] = None,
    ) -> None:
        super().__init__(payload=payload, metadata=metadata)
        self.operation = operation
        self.entity = entity

    def encode(self) -> Dict:
        encoded = super().encode()

        if self.operation is not None:
            encoded["op"] = self.operation.value

        if self.entity is not None:
            encoded["entity"] = self.entity.encode()

        return encoded

    @classmethod
    def _decode(cls, message: Dict, base_class: type = None):
        m = super()._decode(message, base_class=base_class if base_class else cls)

        if "op" in message:
            m.operation = ProtocolOperation(message["op"])

        if "entity" in message:
            m.entity = ProtocolEntity(message["entity"])

        return m
