# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import enum
import random
import struct
from datetime import datetime
from typing import Dict, List, Mapping, NamedTuple, Optional, Tuple, Union, cast

from bnw.protocol import (
    ProtocolPayload,
    ProtocolPayloadValue,
    ProtocolPayloadValueConversion,
    ProtocolPayloadValueJson,
    ProtocolPayloadValueType,
)

from .wire import Serializable


class Sgtin96:

    SG_COMPANY_PREFIX = 4078500
    HQV_COMPANY_PREFIX = 7392930
    TESTING_COMPANY_PREFIX = 0000000  # Used to issue Restricted Ciruculation Numbers within a company

    class _PTR(NamedTuple):
        p: int
        m: int
        l: int
        n: int

    _PARTITION_TABLE = [
        _PTR(p=0, m=40, l=12, n=4),
        _PTR(p=1, m=37, l=11, n=7),
        _PTR(p=2, m=34, l=10, n=10),
        _PTR(p=3, m=30, l=9, n=14),
        _PTR(p=4, m=27, l=8, n=17),
        _PTR(p=5, m=24, l=7, n=20),
        _PTR(p=6, m=20, l=6, n=24),
    ]

    _SGTIN_96_STRUCT = struct.Struct("8s 3s 47s 38s")

    @classmethod
    def _decode_gtin(cls, gtin_binary: str):
        partition = int(str(int(gtin_binary[:3], 2)))
        for ptr in cls._PARTITION_TABLE:
            if ptr.p == partition:
                break
        else:
            raise ValueError("Length of Company Prefix is invalid")

        rv = cls._decode_partition_table(
            gtin_binary,
            ptr.m,
            ptr.l,
            ptr.n,
            # Total of 13 chars
            13 - ptr.l,
        )
        return (
            rv[0],  # Company prefix
            rv[1][0],  # Indicator digit
            rv[1][1:],  # Item ref
        )

    @classmethod
    def decode(cls, sgtin: str) -> Tuple[int, int, int]:
        sgtin_binary = cls._hex_2_bin(sgtin, 96)
        if len(sgtin_binary) != 96:
            raise ValueError(f"Not a valid SGTIN {sgtin}")

        header, filter_value, gtin, serial = cls._SGTIN_96_STRUCT.unpack(sgtin_binary)
        company_prefix, indicator, item_ref = cls._decode_gtin(gtin)
        return int(company_prefix), int(item_ref), int(cls._decode_integer(serial))

    @classmethod
    def encode(
        cls, company_prefix: int, item_ref: int, serial: int, filter_value: int = 1, company_prefix_digits=7
    ) -> str:
        binary = cls._encode_integer(0x30, 8)

        # Filter (3 bits)
        binary += cls._encode_integer(filter_value, 3)

        # GTIN = Partition + Company Prefix + Item Ref (47 bits)
        binary += cls._encode_gtin(
            company_prefix=company_prefix, item_ref_and_indicator=item_ref, company_prefix_digits=company_prefix_digits
        )

        # Serial
        binary += cls._encode_integer(serial, 38)

        assert len(binary) == 96

        return cls._bin_2_hex(binary)

    @classmethod
    def _encode_gtin(cls, company_prefix: int, company_prefix_digits: int, item_ref_and_indicator: int):
        for ptr in cls._PARTITION_TABLE:
            if ptr.l == company_prefix_digits:  # noqa: E741
                break
        else:
            raise ValueError("Length of Company Prefix is invalid")

        return cls._encode_partition_table(ptr.p, company_prefix, ptr.m, item_ref_and_indicator, ptr.n, 47)

    @classmethod
    def _decode_partition_table(
        cls, bin_value: str, var1_bits: int, var1_digits: int, var2_bits: int, var2_digits: int
    ) -> Tuple[str, str]:
        return (
            cls._decode_integer(bin_value[3 : 3 + var1_bits]).zfill(var1_digits),
            cls._decode_integer(bin_value[3 + var1_bits : 3 + var1_bits + var2_bits]).zfill(var2_digits),
        )

    @classmethod
    def _encode_partition_table(cls, partition, var1, var1_bits, var2, var2_bits, bits):
        return "".join(
            [
                cls._encode_integer(partition, 3),
                cls._encode_integer(var1, var1_bits),
                cls._encode_integer(var2, var2_bits),
            ]
        )

    @classmethod
    def _decode_integer(cls, value: str) -> str:
        return str(int(value, 2))

    @classmethod
    def _encode_integer(cls, value, bits):
        fmt_str = "0{bits}b".format(bits=bits)
        rv = format(int(value), fmt_str)
        if len(rv) > bits:
            raise ValueError("Cannot fit integer '{}' into {} bits".format(value, bits))
        return rv

    @classmethod
    def _hex_2_bin(cls, hex_val, bits):
        return "".join(["{:04b}".format(int(hex_char, 16)) for hex_char in hex_val])[:bits].encode()

    @classmethod
    def _bin_2_hex(cls, binary: str):
        byte = 4
        return "".join(["{:X}".format(int(binary[i : i + byte], 2)) for i in range(0, len(binary), byte)])


class DeviceModel(enum.IntEnum):

    GENERIC = 1
    GATEWAY_HC = 21869
    GATEWAY_LC = 46350
    WATER_CONTROL = 18869
    SENSOR = 18845
    SENSOR_2 = 19040
    MOWER_CBT2 = 6146
    MOWER_CBTG = 29694
    MOWER_CBTL = 53988
    EPP = 22538
    IC24 = 31653
    IC24_ECO = 469
    POWER = 35279

    @classmethod
    def from_sgtin(cls, sgtin: str) -> "DeviceModel":
        _, item_ref, _ = Sgtin96.decode(sgtin)
        return cls.from_model_number(item_ref)

    @classmethod
    def from_model_number(cls, number: int) -> "DeviceModel":
        e = next((e for e in cls if e.value == number), None)
        if e is None:
            raise ValueError(f"No such device model with number {number}")
        else:
            return e

    def model_name(self) -> DeviceModelName:
        return DeviceModelName.from_device_model(self)


class DeviceModelName(str):
    _NAME_MAP = {
        1: "Generic",
        18869: "Water Control",
        18845: "Sensor",
        6146: "Robotics Lawnmower",
        22538: "Automatic Home and Garden Pump",
        31653: "Irrigation Control",
        469: "Irrigation Control",
        35279: "Power Adapter",
        19040: "Sensor",
        29694: "Robotics Lawnmower",
        53988: "Robotics Lawnmower",
        21869: "Gateway",
        46350: "Gateway",
    }

    @classmethod
    def from_device_model(cls, device_model: DeviceModel) -> DeviceModelName:
        name = cls._NAME_MAP.get(device_model.value, None)
        if name is None:
            raise ValueError(f"No model name for {device_model} defined")

        return DeviceModelName(name)


class DeviceName:
    sgtin: Optional[str]

    def __init__(
        self,
        sgtin: Optional[str] = None,
        model: Optional[DeviceModel] = None,
        serial: Optional[int] = None,
        company_prefix: Optional[int] = None,
    ):

        if sgtin is None:
            if model is None or serial is None:
                raise ValueError("Must provide model and serial if not providing SGTIN")

            company_prefix = company_prefix or Sgtin96.TESTING_COMPANY_PREFIX
            filter_value = 0 if company_prefix == Sgtin96.TESTING_COMPANY_PREFIX else 1
            self.sgtin = Sgtin96.encode(
                company_prefix=company_prefix or Sgtin96.TESTING_COMPANY_PREFIX,
                item_ref=model.value,
                serial=serial,
                filter_value=filter_value,
            )
        else:
            # ensure it is valid sgtin
            Sgtin96.decode(sgtin)
            self.sgtin = sgtin

    def __str__(self):
        return self.sgtin

    @classmethod
    def from_string(cls, string):
        return DeviceName(string)

    @property
    def model_number(self) -> int:
        return self.model.value

    @property
    def model(self) -> DeviceModel:
        assert self.sgtin
        return DeviceModel.from_sgtin(self.sgtin)

    @property
    def serial(self) -> int:
        assert self.sgtin

        company_prefix, item_ref, serial_number = Sgtin96.decode(self.sgtin)
        return serial_number

    @classmethod
    def random(cls) -> "DeviceName":
        return DeviceName(None, model=DeviceModel.GENERIC, serial=random.randint(1, 1000))


class DeviceResourcePath(NamedTuple):
    object_name: Optional[str] = None
    object_instance_id: Optional[int] = None
    resource_name: Optional[str] = None
    resource_instance_id: Optional[int] = None

    def __len__(self):
        return len(self.to_tuple())

    def to_tuple(self) -> Tuple[Union[int, str], ...]:
        return tuple(i for i in self if i is not None)

    @classmethod
    def from_string(cls, string: str):
        parts = string.split("/")
        if parts[0] == "":
            parts.pop(0)

        object_name: Optional[str] = None
        instance_id: Optional[int] = None
        resource_name: Optional[str] = None
        resource_instance_id: Optional[int] = None

        if len(parts) > 0:
            object_name = parts[0]

        if len(parts) > 1:
            instance_id = int(parts[1])

        if len(parts) > 2:
            resource_name = parts[2]

        if len(parts) > 3:
            resource_instance_id = int(parts[3])

        return DeviceResourcePath(
            object_name=object_name,
            object_instance_id=instance_id,
            resource_name=resource_name,
            resource_instance_id=resource_instance_id,
        )

    def to_string(self) -> str:
        parts = list(str(i) for i in self if i is not None)
        return "/".join(parts)

    def __str__(self):
        return self.to_string()


DeviceResourceValueRaw = Union[
    str, int, float, bool, bytes, datetime, List[Union[str, int, float, bool, bytes, datetime]]
]


class DeviceResourceValue(Serializable):

    _protocol_value: ProtocolPayloadValue

    def __init__(self, protocol_value: ProtocolPayloadValue):
        self._protocol_value = protocol_value

    @classmethod
    def from_protocol_value(cls, value: ProtocolPayloadValue):
        return DeviceResourceValue(protocol_value=value)

    @classmethod
    def from_raw_value(
        cls,
        value: DeviceResourceValueRaw,
        name: Optional[str] = None,
        type: Optional[ProtocolPayloadValueType] = None,
        timestamp: Optional[datetime] = None,
    ):
        if type is None:
            if isinstance(value, list):
                type = ProtocolPayloadValueType.from_value(value[0])
            else:
                type = ProtocolPayloadValueType.from_value(value)

        return DeviceResourceValue(
            protocol_value=ProtocolPayloadValue(
                type=type,
                value=ProtocolPayloadValueConversion.py_to_json(value),
                name=name,
                timestamp=cast(int, ProtocolPayloadValueConversion.py_to_json(timestamp)) if timestamp else None,
            )
        )

    @property
    def raw(self) -> DeviceResourceValueRaw:
        return ProtocolPayloadValueConversion.json_to_py(self._protocol_value.value, type_hint=self.type)

    @property
    def type(self) -> ProtocolPayloadValueType:
        return self._protocol_value.type

    @property
    def name(self) -> Optional[str]:
        return self._protocol_value.name

    def encode(self) -> Mapping[str, ProtocolPayloadValueJson]:
        return self._protocol_value.to_json_dict()


class DeviceResourceWriteBatch(Serializable):
    def __init__(self, *values: DeviceResourceValue):
        for v in values:
            if not v.name:
                raise ValueError("Value must have name")

        self._values = values

    def encode(self) -> Dict:
        return {v.name: v.encode() for v in self._values}


class DeviceResource(NamedTuple):
    path: DeviceResourcePath
    value: DeviceResourceValue

    @classmethod
    def from_payload(cls, path: DeviceResourcePath, payload: ProtocolPayload) -> List[DeviceResource]:
        resources: List[DeviceResource]
        path_len = len(path)

        if path_len == 0:
            resources = []
            for object_name, object_instances in payload.items():
                for object_id, object_resources in object_instances.items():
                    if object_id == "_urn":
                        continue
                    resources.extend(
                        DeviceResource(
                            path=DeviceResourcePath(
                                object_name=object_name, object_instance_id=int(object_id), resource_name=value.name
                            ),
                            value=DeviceResourceValue.from_protocol_value(value),
                        )
                        for value in payload.protocol_values(object_resources).as_list()
                    )
            return resources
        elif path_len == 1:
            resources = []
            for object_id, object_resources in payload.items():
                if object_id == "_urn":
                    continue
                resources.extend(
                    DeviceResource(
                        path=DeviceResourcePath(
                            object_name=path.object_name, object_instance_id=int(object_id), resource_name=value.name
                        ),
                        value=DeviceResourceValue.from_protocol_value(value),
                    )
                    for value in payload.protocol_values(object_resources).as_list()
                )
            return resources
        elif path_len == 2:
            return [
                DeviceResource(
                    path=DeviceResourcePath(
                        object_name=path.object_name,
                        object_instance_id=path.object_instance_id,
                        resource_name=value.name,
                    ),
                    value=DeviceResourceValue.from_protocol_value(value),
                )
                for value in payload.protocol_values().as_list()
            ]
        elif path_len == 3:
            v = ProtocolPayloadValue.from_json_dict(payload, path.resource_name)
            return [
                DeviceResource(
                    path=DeviceResourcePath(
                        object_name=path.object_name, object_instance_id=path.object_instance_id, resource_name=v.name
                    ),
                    value=DeviceResourceValue.from_protocol_value(v),
                )
            ]
        elif path_len == 4:

            v = ProtocolPayloadValue.from_json_dict(
                payload, cast(str, path.resource_name) + f"[{path.resource_instance_id}]"
            )
            return [
                DeviceResource(
                    path=DeviceResourcePath(
                        object_name=path.object_name,
                        object_instance_id=path.object_instance_id,
                        resource_name=path.resource_name,
                        resource_instance_id=path.resource_instance_id,
                    ),
                    value=DeviceResourceValue.from_protocol_value(v),
                )
            ]
        else:
            raise ValueError("Unsupported path")
