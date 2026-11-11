# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import copy
import functools
from typing import Any, Dict, List, Optional, Union

from bnw.protocol import (
    ProtocolEntity,
    ProtocolEnvelope,
    ProtocolMessage,
    ProtocolMetadata,
    ProtocolOperation,
    ProtocolPayload,
)


class EventBusProtocolMessage(ProtocolMessage):
    def __init__(
        self,
        operation: ProtocolOperation = None,
        entity: ProtocolEntity = None,
        payload: Optional[ProtocolPayload] = None,
        metadata: Optional[ProtocolMetadata] = None,
    ):
        super().__init__(operation=operation, entity=entity, payload=payload, metadata=metadata)

    @classmethod
    def _decode(cls, message: Dict, base_class: type = None):
        return super()._decode(message, base_class=base_class or cls)

    def canonical_path_segments(self) -> Optional[List[str]]:
        if self.entity is None or "path" not in self.entity:
            return None

        path = self.entity["path"]
        path = path.strip()

        if len(path) > 0 and path[0] == "/":
            path = path[1:]

        if len(path) == 0:
            return []

        return path.split("/")

    def canonical_payload(self) -> Optional[Dict[str, Dict[str, Dict[str, Dict]]]]:
        """
        Converts payload into its canonical form where the whole hierarchy is present in the dictionary structure
        """
        if self.payload is None:
            return None

        path_parts = self.canonical_path_segments()
        if path_parts is None:
            return None

        urn: Optional[str] = None
        root: Dict[str, Any] = {}
        leaf = functools.reduce(lambda d, el: d.update({el: {}}) or d[el], path_parts, root)
        payload_copy = copy.deepcopy(self.payload)

        if "_urn" in payload_copy:
            urn = payload_copy.get("_urn")
            del payload_copy["_urn"]

        leaf.update(payload_copy)

        if urn is not None and len(path_parts) > 0:
            root[path_parts[0]]["_urn"] = urn

        return root


class EventBusProtocolEnvelope(ProtocolEnvelope):
    @classmethod
    def decode(cls, envelope: Union[List[Dict], Dict], base_class: type = None):
        return super().decode(envelope, base_class=base_class if base_class else cls)

    @classmethod
    def _decode_message(cls, message: Dict) -> EventBusProtocolMessage:
        return EventBusProtocolMessage.decode(message)
