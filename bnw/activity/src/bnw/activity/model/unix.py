# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

from typing import Dict, List, Union, cast

from bnw.protocol import ProtocolMessage
from bnw.protocol.command import (
    EventBusCommandRequest,
    EventBusCommandRequestEnvelope,
    EventBusCommandResponse,
    EventBusCommandResponseEnvelope,
)

from .wire import Deserializable, Serializable


class UnixMessage(ProtocolMessage, Serializable, Deserializable):
    pass


class UnixCommandRequest(UnixMessage, EventBusCommandRequest, EventBusCommandRequestEnvelope):
    def __init__(self, *args, **kwargs):
        if (len(args) > 0 and isinstance(args[0], list)) or "messages" in kwargs:
            if "messages" in kwargs:
                messages = cast(list, kwargs["messages"])
            else:
                messages = cast(list, args[0])

            if len(messages) == 1:
                message = messages[0]
                UnixCommandRequest.__init__(
                    self,
                    operation=message.operation,
                    entity=message.entity,
                    payload=message.payload,
                    metadata=message.metadata,
                )
                self.messages = [self]
            else:
                raise ValueError("Currently only envelope with size=1 supported")
        else:
            EventBusCommandRequest.__init__(self, **kwargs)

    def encode(self) -> List:  # type: ignore[override]
        return [super().encode()]

    @classmethod
    def decode(cls, envelope: Union[List[Dict], Dict], base_class: type = None):
        return EventBusCommandRequestEnvelope.decode(envelope, base_class=base_class if base_class else cls)

    @classmethod
    def _decode_message(cls, message: Dict) -> "UnixCommandResponse":  # type: ignore[override]
        return UnixCommandRequest.decode(message)


class UnixCommandResponse(UnixMessage, EventBusCommandResponse, EventBusCommandResponseEnvelope):  # type: ignore[misc]
    success: bool

    def __init__(self, *args, **kwargs):
        if (len(args) > 0 and isinstance(args[0], list)) or "messages" in kwargs:
            if "messages" in kwargs:
                messages = cast(list, kwargs["messages"])
            else:
                messages = cast(list, args[0])

            if len(messages) == 1:
                message = messages[0]
                EventBusCommandResponse.__init__(
                    self,
                    success=message.success,
                    operation=message.operation,
                    entity=message.entity,
                    payload=message.payload,
                    metadata=message.metadata,
                )
                self.messages = [self]
            else:
                raise ValueError("Currently only envelope with size=1 supported")
        else:
            EventBusCommandResponse.__init__(self, **kwargs)

    def encode(self) -> List:  # type: ignore[override]
        return [super().encode()]

    @classmethod
    def decode(cls, envelope: Union[List[Dict], Dict], base_class: type = None):
        return EventBusCommandResponseEnvelope.decode(envelope, base_class=base_class if base_class else cls)

    @classmethod
    def _decode_message(cls, message: Dict) -> "UnixCommandResponse":
        return UnixCommandResponse.decode(message)
