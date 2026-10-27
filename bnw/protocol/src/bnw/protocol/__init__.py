# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import base64
import copy
import json
from datetime import datetime, timezone
from enum import Enum
from typing import (
    Any,
    Dict,
    List,
    Mapping,
    MutableMapping,
    NamedTuple,
    Optional,
    Union,
    cast,
)

ProtocolPayloadValuePySingle = Union[str, int, float, bool, bytes, datetime]
ProtocolPayloadValuePyMultiple = List[ProtocolPayloadValuePySingle]
ProtocolPayloadValuePy = Union[ProtocolPayloadValuePySingle, ProtocolPayloadValuePyMultiple]

ProtocolPayloadValueJsonSingle = Union[str, int, float, bool]
ProtocolPayloadValueJsonMultiple = List[ProtocolPayloadValueJsonSingle]
ProtocolPayloadValueJson = Union[ProtocolPayloadValueJsonSingle, ProtocolPayloadValueJsonMultiple]


class ProtocolOperation(Enum):
    EXECUTE = "execute"
    WRITE = "write"
    READ = "read"

    UPDATE = "update"
    OVERWRITE = "overwrite"
    DELETE = "delete"


class ProtocolPayloadValuePrefix(Enum):
    VALUE = "v"
    ARRAY = "a"


class ProtocolPayloadValueType(Enum):
    STRING = "s"
    INTEGER = "i"
    FLOAT = "f"
    BOOLEAN = "b"
    OPAQUE = "o"
    TIME = "t"
    LINK = "l"

    def key(self, prefix: ProtocolPayloadValuePrefix) -> str:
        return prefix.value + self.value

    @property
    def value_key(self) -> str:
        return self.key(ProtocolPayloadValuePrefix.VALUE)

    @property
    def array_key(self) -> str:
        return self.key(ProtocolPayloadValuePrefix.ARRAY)

    @classmethod
    def from_key(cls, key: str):
        if len(key) != 2 or key[0] not in (e.value for e in ProtocolPayloadValuePrefix):
            raise ValueError("No value or array key")

        return ProtocolPayloadValueType(key[1])

    """
        NOTE: will return LINK as STRING (no link detection implemented)
    """

    @classmethod
    def from_value(cls, value: ProtocolPayloadValuePySingle) -> "ProtocolPayloadValueType":
        if isinstance(value, bool):  # ordering matters, bool is subclass of int
            return ProtocolPayloadValueType.BOOLEAN
        if isinstance(value, int):
            return ProtocolPayloadValueType.INTEGER
        if isinstance(value, float):
            return ProtocolPayloadValueType.FLOAT
        if isinstance(value, bytes):
            return ProtocolPayloadValueType.OPAQUE
        if isinstance(value, datetime):
            return ProtocolPayloadValueType.TIME
        if isinstance(value, str):
            return ProtocolPayloadValueType.STRING

        raise ValueError("Could not detect value type from type %s" % type(value))


class ProtocolPayloadValueKeys(Enum):
    TIMESTAMP = "ts"

    @classmethod
    def all(cls) -> List[str]:
        if hasattr(cls, "_all"):
            return getattr(cls, "_all")

        all = [e.value for e in cls]
        all.extend(cls.values())

        setattr(cls, "_all", all)
        return all

    @classmethod
    def values(cls) -> List[str]:
        if hasattr(cls, "_values"):
            return getattr(cls, "_values")

        values = []
        for p in ProtocolPayloadValuePrefix:
            for v in ProtocolPayloadValueType:
                values.append(v.key(p))

        setattr(cls, "_values", values)
        return values


class ProtocolPayloadValue(NamedTuple):
    name: Optional[str]
    type: ProtocolPayloadValueType
    value: ProtocolPayloadValueJson
    timestamp: Optional[int]

    def is_multiple(self):
        return isinstance(self.value, List)

    @classmethod
    def from_dict(cls, dict: Dict[str, Any], name: str = None) -> "ProtocolPayloadValue":
        from warnings import warn

        warn("This method is deprecated - use from_json_dict", DeprecationWarning)
        return cls.from_json_dict(dict, name)

    @classmethod
    def from_json_dict(cls, dict: Mapping[str, ProtocolPayloadValueJson], name: str = None) -> "ProtocolPayloadValue":
        key = next((k for k in dict.keys() if k in ProtocolPayloadValueKeys.values()), None)
        if key is None:
            raise ValueError("No payload key present")

        timestamp = dict.get(ProtocolPayloadValueKeys.TIMESTAMP.value, None)
        if timestamp is not None and not isinstance(timestamp, int):
            raise ValueError("Timestamp not an int")

        return ProtocolPayloadValue(
            name=name,
            type=ProtocolPayloadValueType.from_key(key),
            value=dict[key],
            timestamp=timestamp,
        )

    def to_json_dict(self) -> Mapping[str, ProtocolPayloadValueJson]:
        if self.is_multiple():
            key = self.type.array_key
        else:
            key = self.type.value_key

        d: MutableMapping[str, ProtocolPayloadValueJson] = {key: self.value}
        if self.timestamp is not None:
            d[ProtocolPayloadValueKeys.TIMESTAMP.value] = self.timestamp

        return d

    def as_boolean(self) -> bool:
        if self.type != ProtocolPayloadValueType.BOOLEAN:
            raise ValueError("Not a boolean")

        return cast(bool, self.value)


class ProtocolPayloadValueConversion:
    @staticmethod
    def py_to_json(value: ProtocolPayloadValuePy) -> ProtocolPayloadValueJson:
        if isinstance(value, list):
            return [ProtocolPayloadValueConversion._py_to_json_single(v) for v in value]
        else:
            return ProtocolPayloadValueConversion._py_to_json_single(value)

    @staticmethod
    def _py_to_json_single(value: ProtocolPayloadValuePySingle) -> ProtocolPayloadValueJsonSingle:
        if isinstance(value, datetime):
            return int(value.timestamp())

        if isinstance(value, bytes):
            return base64.b64encode(value).decode()

        return value

    @staticmethod
    def value_to_py(value: ProtocolPayloadValue) -> ProtocolPayloadValuePy:
        return ProtocolPayloadValueConversion.json_to_py(value.value, type_hint=value.type)

    @staticmethod
    def json_to_py(
        value: ProtocolPayloadValueJson, type_hint: Optional[ProtocolPayloadValueType] = None
    ) -> ProtocolPayloadValuePy:
        if isinstance(value, list):
            return [ProtocolPayloadValueConversion._json_to_py_single(v, type_hint=type_hint) for v in value]
        else:
            return ProtocolPayloadValueConversion._json_to_py_single(value, type_hint=type_hint)

    @staticmethod
    def _json_to_py_single(
        value: ProtocolPayloadValueJsonSingle, type_hint: Optional[ProtocolPayloadValueType] = None
    ) -> ProtocolPayloadValuePySingle:
        if type_hint == ProtocolPayloadValueType.BOOLEAN:
            if not isinstance(value, bool) and isinstance(value, int):
                return bool(value)
            elif isinstance(value, bool):
                return value
            else:
                raise ValueError("Boolean value not of type bool or int")

        if type_hint == ProtocolPayloadValueType.TIME:
            if not isinstance(value, int):
                raise ValueError("Time value not of type int")

            return datetime.fromtimestamp(value, tz=timezone.utc)

        if type_hint == ProtocolPayloadValueType.OPAQUE:
            if not isinstance(value, str):
                raise ValueError("Opaque value not of type str")

            return base64.b64decode(value, validate=True)

        return value


class ProtocolEntity(dict):
    def encode(self) -> Dict[str, Any]:
        return dict(self)


class ProtocolPayloadValueView(Mapping[str, ProtocolPayloadValueJson]):

    _values: List[ProtocolPayloadValue]

    def __init__(self, *args):
        self._values = list(*args)

    def __getitem__(self, item):
        try:
            return next(v.value for v in self._values if v.name == item)
        except StopIteration:
            raise KeyError(item)

    def __len__(self):
        return len(self._values)

    def __iter__(self):
        return iter(v.name for v in self._values)

    def as_list(self) -> List[ProtocolPayloadValue]:
        return self._values


class ProtocolPayload(dict):
    def __init__(self, *args, **kwargs):
        if args == (None,):
            # Create empty dict when called with ProtocolPayload(None)
            super().__init__((), **kwargs)
        else:
            super().__init__(*args, **kwargs)

    def encode(self) -> Dict[str, Any]:
        return dict(self)

    @classmethod
    def from_dict(cls, dict: Dict[str, Any], timestamp: int = None) -> "ProtocolPayload":
        from warnings import warn

        warn("This method is deprecated - use from_py_dict", DeprecationWarning)
        return cls.from_py_dict(
            dict,
            datetime.fromtimestamp(timestamp, tz=timezone.utc) if timestamp else None,
        )

    @classmethod
    def from_py_dict(cls, dict: Mapping[str, ProtocolPayloadValuePy], timestamp: datetime = None) -> "ProtocolPayload":
        return ProtocolPayload(cls._to_payload_dict(dict, timestamp))

    @classmethod
    def from_payload_value_py(
        cls,
        value: ProtocolPayloadValuePy,
        timestamp: datetime = None,
    ) -> "ProtocolPayload":
        return ProtocolPayload(cls._to_payload(value, timestamp))

    @classmethod
    def _to_payload_dict(
        cls, dict: Mapping[str, ProtocolPayloadValuePy], timestamp: datetime = None
    ) -> Mapping[str, Mapping[str, ProtocolPayloadValueJson]]:
        payload = {}
        for k, v in dict.items():
            payload[k] = cls._to_payload(v, timestamp)

        return payload

    @classmethod
    def _to_payload(
        cls,
        value: ProtocolPayloadValuePy,
        timestamp: datetime = None,
    ) -> Mapping[str, ProtocolPayloadValueJson]:
        if isinstance(value, list):
            t = ProtocolPayloadValueType.from_value(value[0])
            key = t.array_key
        else:
            t = ProtocolPayloadValueType.from_value(value)
            key = t.value_key

        p: Dict[str, ProtocolPayloadValueJson] = {key: ProtocolPayloadValueConversion.py_to_json(value)}
        if timestamp is not None:
            p[ProtocolPayloadValueKeys.TIMESTAMP.value] = ProtocolPayloadValueConversion.py_to_json(timestamp)
        return p

    def protocol_values(self, root: Optional[dict] = None) -> ProtocolPayloadValueView:
        root = root if root is not None else self
        return ProtocolPayloadValueView(
            ProtocolPayloadValue.from_json_dict(d, name) for name, d in root.items() if name != "_urn"
        )

    def to_py_dict(self) -> Mapping[str, ProtocolPayloadValuePy]:
        return {
            k: ProtocolPayloadValueConversion.value_to_py(ProtocolPayloadValue.from_json_dict(v))
            for k, v in self.items()
        }

    def to_py(self) -> Union[None, ProtocolPayloadValuePy, Mapping[str, Union[Mapping, ProtocolPayloadValuePy]]]:
        if len(self) == 0:
            return None

        py = copy.deepcopy(self)
        return self._convert_protocol_value_to_py(py)

    @classmethod
    def _convert_protocol_value_to_py(cls, obj):
        if isinstance(obj, dict):
            is_value = next((k for k in obj.keys() if k in ProtocolPayloadValueKeys.values()), False)
            if is_value:
                return ProtocolPayloadValueConversion.value_to_py(ProtocolPayloadValue.from_json_dict(obj))
            else:
                for k, v in obj.items():
                    obj[k] = cls._convert_protocol_value_to_py(v)
                return obj
        else:
            return obj


class ProtocolMetadata(dict):
    def __init__(self, *args, **kwargs):
        if args == (None,):
            # Create empty dict when called with ProtocolMetadata(None)
            super().__init__((), **kwargs)
        else:
            super().__init__(*args, **kwargs)

    def encode(self) -> Dict[str, Any]:
        return dict(self)


class ProtocolMessage:
    def __init__(
        self,
        operation: ProtocolOperation = None,
        entity: ProtocolEntity = None,
        payload: ProtocolPayload = None,
        metadata: ProtocolMetadata = None,
    ):
        if entity is not None:
            assert isinstance(entity, ProtocolEntity)
        if payload is not None:
            assert isinstance(payload, ProtocolPayload)
        if metadata is not None:
            assert isinstance(metadata, ProtocolMetadata)

        self.operation = operation
        self.entity = entity
        self.payload = payload
        self.metadata = metadata

    def encode(self) -> Dict[str, Any]:
        r: Dict[str, Any] = {}

        if self.operation is not None:
            r["op"] = self.operation.value

        if self.entity is not None:
            r["entity"] = self.entity.encode()

        if self.payload is not None:
            r["payload"] = self.payload.encode()

        if self.metadata is not None:
            r["metadata"] = self.metadata.encode()

        return r

    @classmethod
    def decode(cls, message: Dict[str, Any]):
        return cls._decode(message)

    @classmethod
    def _decode(cls, message: Dict[str, Any], base_class: type = None):
        m = base_class() if base_class else cls()
        if "op" in message:
            m.operation = ProtocolOperation(message["op"])

        if "entity" in message:
            m.entity = ProtocolEntity(message["entity"])

        if "payload" in message:
            m.payload = ProtocolPayload(message["payload"])

        if "metadata" in message:
            m.metadata = ProtocolMetadata(message["metadata"])

        return m

    def serialize(self) -> str:
        return json.dumps(self.encode(), separators=(",", ":"))

    @classmethod
    def deserialize(cls, s: Union[str, bytes]):
        return cls.decode(json.loads(s))

    def __repr__(self):
        return "<{} op={}, entity={}, payload={}, metadata={}>".format(
            self.__class__.__name__, self.operation, self.entity, self.payload, self.metadata
        )

    def __eq__(self, other):
        if isinstance(other, self.__class__) or False:
            return (
                self.operation == other.operation
                and self.entity == other.entity
                and self.payload == other.payload
                and self.metadata == other.metadata
            )

        return super().__eq__(other)


class ProtocolEnvelope:
    messages: List

    def __init__(self, messages: List):
        self.messages = messages

    @classmethod
    def deserialize(cls, s: Union[str, bytes]):
        return cls.decode(json.loads(s))

    @classmethod
    def decode(cls, envelope: Union[List[Dict[str, Any]], Dict[str, Any]], base_class: type = None):
        if isinstance(envelope, dict):
            messages = [cls._decode_message(envelope)]
        else:
            messages = [cls._decode_message(message) for message in envelope]

        return base_class(messages) if base_class else cls(messages)

    @classmethod
    def _decode_message(cls, message: Dict[str, Any]) -> Any:
        return ProtocolMessage.decode(message)

    def serialize(self) -> str:
        return json.dumps(self.encode(), separators=(",", ":"))

    def encode(self) -> list:
        return [m.encode() for m in self.messages]

    def __iter__(self):
        return iter(self.messages)
