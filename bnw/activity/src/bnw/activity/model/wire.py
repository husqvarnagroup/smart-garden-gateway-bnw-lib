# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import json
from abc import ABCMeta, abstractmethod
from typing import Dict, Mapping, Union

from bnw.protocol import ProtocolPayloadValueJson


class Deserializable(metaclass=ABCMeta):
    @classmethod
    def decode(cls, data: Dict):
        return cls._decode(data)

    @classmethod
    @abstractmethod
    def _decode(cls, data: Dict, base_class: type = None):
        pass

    @classmethod
    def deserialize(cls, s: Union[str, bytes]):
        return cls.decode(json.loads(s))


class Serializable(metaclass=ABCMeta):
    @abstractmethod
    def encode(self) -> Mapping[str, Union[Mapping, ProtocolPayloadValueJson]]:
        pass

    def serialize(self) -> str:
        return json.dumps(self.encode(), separators=(",", ":"))

    def serialize_bytes(self):
        return self.serialize().encode()
