# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

# flake8: noqa: E721
from datetime import datetime, timezone

import pytest  # type: ignore
from pytest_cases import parametrize_with_cases

from bnw.protocol import (
    ProtocolEntity,
    ProtocolEnvelope,
    ProtocolMessage,
    ProtocolMetadata,
    ProtocolOperation,
    ProtocolPayload,
    ProtocolPayloadValue,
    ProtocolPayloadValueConversion,
    ProtocolPayloadValueType,
)
from bnw.protocol.command import (
    EventBusCommandRequest,
    EventBusCommandRequestEnvelope,
    EventBusCommandResponse,
    EventBusCommandResponseEnvelope,
    EventBusDeviceCommandRequest,
    EventBusDeviceExecuteRequest,
    EventBusDeviceOperationMessage,
    EventBusDeviceReadRequest,
    EventBusDeviceWriteRequest,
)
from bnw.protocol.entity import EventBusDeviceEntity
from bnw.protocol.message import EventBusProtocolEnvelope, EventBusProtocolMessage
from bnw.protocol.status import (
    EventBusDeviceStatusDelete,
    EventBusDeviceStatusMessage,
    EventBusDeviceStatusOverwrite,
    EventBusDeviceStatusUpdate,
    EventBusStatusMessage,
)


def test_canonical_path():
    m = EventBusDeviceOperationMessage(ProtocolOperation.UPDATE, "", "", None)
    assert [] == m.canonical_path_segments()

    m = EventBusDeviceOperationMessage(ProtocolOperation.UPDATE, "", " ", None)
    assert [] == m.canonical_path_segments()

    m = EventBusDeviceOperationMessage(ProtocolOperation.UPDATE, "", "/", None)
    assert [] == m.canonical_path_segments()

    m = EventBusDeviceOperationMessage(ProtocolOperation.UPDATE, "", "device/0", None)
    assert ["device", "0"] == m.canonical_path_segments()

    m = EventBusDeviceOperationMessage(ProtocolOperation.UPDATE, "", "/device/0", None)
    assert ["device", "0"] == m.canonical_path_segments()

    m = EventBusDeviceOperationMessage(ProtocolOperation.UPDATE, "", " /device/0   ", None)
    assert ["device", "0"] == m.canonical_path_segments()


def test_canonical_payload():
    m1 = EventBusDeviceOperationMessage(
        ProtocolOperation.UPDATE,
        "device_id",
        "",
        ProtocolPayload({"device": {"0": {"serial_number": {"vs": "serial"}}}}),
    )

    m2 = EventBusDeviceOperationMessage(
        ProtocolOperation.UPDATE, "device_id", "device", ProtocolPayload({"0": {"serial_number": {"vs": "serial"}}})
    )

    m3 = EventBusDeviceOperationMessage(
        ProtocolOperation.UPDATE, "device_id", "device/0", ProtocolPayload({"serial_number": {"vs": "serial"}})
    )

    m4 = EventBusDeviceOperationMessage(
        ProtocolOperation.UPDATE, "device_id", "device/0/serial_number", ProtocolPayload({"vs": "serial"})
    )

    canonical_form = {"device": {"0": {"serial_number": {"vs": "serial"}}}}

    assert canonical_form == m1.canonical_payload()
    assert canonical_form == m2.canonical_payload()
    assert canonical_form == m3.canonical_payload()
    assert canonical_form == m4.canonical_payload()


def test_canonical_payload_handles_urn():
    m1 = EventBusDeviceOperationMessage(
        ProtocolOperation.UPDATE,
        "device_id",
        "",
        ProtocolPayload({"device": {"_urn": "urn:oma:lwm2m:oma:3:1.1", "0": {"serial_number": {"vs": "serial"}}}}),
    )

    m2 = EventBusDeviceOperationMessage(
        ProtocolOperation.UPDATE,
        "device_id",
        "device",
        ProtocolPayload({"_urn": "urn:oma:lwm2m:oma:3:1.1", "0": {"serial_number": {"vs": "serial"}}}),
    )

    m3 = EventBusDeviceOperationMessage(
        ProtocolOperation.UPDATE,
        "device_id",
        "device/0",
        ProtocolPayload({"_urn": "urn:oma:lwm2m:oma:3:1.1", "serial_number": {"vs": "serial"}}),
    )

    m4 = EventBusDeviceOperationMessage(
        ProtocolOperation.UPDATE,
        "device_id",
        "device/0/serial_number",
        ProtocolPayload({"_urn": "urn:oma:lwm2m:oma:3:1.1", "vs": "serial"}),
    )

    canonical_form = {"device": {"_urn": "urn:oma:lwm2m:oma:3:1.1", "0": {"serial_number": {"vs": "serial"}}}}

    assert canonical_form == m1.canonical_payload()
    assert canonical_form == m2.canonical_payload()
    assert canonical_form == m3.canonical_payload()
    assert canonical_form == m4.canonical_payload()


def test_canonical_payload_returns_copy():
    payload = ProtocolPayload({"device": {"0": {"serial_number": {"vs": "serial"}}}})
    m = EventBusDeviceOperationMessage(ProtocolOperation.UPDATE, "device_id", "", payload)

    canonical = m.canonical_payload()
    del canonical["device"]["0"]["serial_number"]

    assert "serial_number" in payload["device"]["0"]


def test_protocol_payload_value_from_dict():
    v = ProtocolPayloadValue.from_json_dict({"vs": "string"})
    assert ProtocolPayloadValueType.STRING == v.type
    assert "string" == v.value
    assert v.timestamp is None

    v = ProtocolPayloadValue.from_json_dict({"as": ["string"]})
    assert ProtocolPayloadValueType.STRING, v.type
    assert ["string"] == v.value
    assert v.is_multiple()

    v = ProtocolPayloadValue.from_json_dict({"ts": 1234, "vi": 1})
    assert ProtocolPayloadValueType.INTEGER == v.type
    assert 1 == v.value
    assert 1234 == v.timestamp

    with pytest.raises(ValueError):
        ProtocolPayloadValue.from_json_dict({"v?": 1})

    with pytest.raises(ValueError):
        ProtocolPayloadValue.from_json_dict({"s": 1})

    with pytest.raises(ValueError):
        ProtocolPayloadValue.from_json_dict({"v": 1})

    with pytest.raises(ValueError):
        ProtocolPayloadValue.from_json_dict({"?s": 1})


def test_protocol_payload_value_from_value():
    vt = ProtocolPayloadValueType.from_value("string")
    assert ProtocolPayloadValueType.STRING == vt

    vt = ProtocolPayloadValueType.from_value(1)
    assert ProtocolPayloadValueType.INTEGER == vt

    vt = ProtocolPayloadValueType.from_value(5.8)
    assert ProtocolPayloadValueType.FLOAT == vt

    vt = ProtocolPayloadValueType.from_value(True)
    assert ProtocolPayloadValueType.BOOLEAN == vt

    vt = ProtocolPayloadValueType.from_value(b"opaque")
    assert ProtocolPayloadValueType.OPAQUE == vt

    vt = ProtocolPayloadValueType.from_value(datetime.now(timezone.utc))
    assert ProtocolPayloadValueType.TIME == vt


def test_protocol_payload_value_to_value():
    assert "string" == ProtocolPayloadValueConversion.py_to_json("string")
    assert 1 == ProtocolPayloadValueConversion.py_to_json(1)
    assert 5.8 == ProtocolPayloadValueConversion.py_to_json(5.8)
    assert ProtocolPayloadValueConversion.py_to_json(True) is True
    assert "b3BhcXVl" == ProtocolPayloadValueConversion.py_to_json(b"opaque")
    assert "b3BhcXVlMg==" == ProtocolPayloadValueConversion.py_to_json(b"opaque2")
    now = datetime.now(timezone.utc)
    assert int(now.timestamp()) == ProtocolPayloadValueConversion.py_to_json(now)


def test_protocol_payload_from_dict():
    now = datetime.now(timezone.utc)

    result = ProtocolPayload.from_py_dict(
        {"string": "string", "bool": True, "int": 10, "float": 42.1, "time": now, "opaque": b"opaque"}
    )

    assert result == {
        "bool": {"vb": True},
        "float": {"vf": 42.1},
        "int": {"vi": 10},
        "opaque": {"vo": "b3BhcXVl"},
        "string": {"vs": "string"},
        "time": {"vt": int(now.timestamp())},
    }

    result = ProtocolPayload.from_py_dict(
        {
            "string": ["string"],
            "bool": [True],
            "int": [10],
            "float": [42.1],
            "time": [now],
            "opaque": [b"opaque", b"opaque2"],
        }
    )

    assert result == {
        "bool": {"ab": [True]},
        "float": {"af": [42.1]},
        "int": {"ai": [10]},
        "opaque": {"ao": ["b3BhcXVl", "b3BhcXVlMg=="]},
        "string": {"as": ["string"]},
        "time": {"at": [int(now.timestamp())]},
    }


def test_protocol_payload_to_py_dict():
    now = datetime.now(timezone.utc)
    now = now.replace(microsecond=0)

    payload = ProtocolPayload(
        {
            "string": {"vs": "string"},
            "bool": {"vb": 1},
            "int": {"vi": 10},
            "float": {"vf": 42.1},
            "time": {"vt": int(now.timestamp())},
            "opaque": {"vo": "b3BhcXVl"},
        }
    )

    assert payload.to_py_dict() == {
        "string": "string",
        "bool": True,
        "int": 10,
        "float": 42.1,
        "time": now,
        "opaque": b"opaque",
    }


def test_protocol_payload_to_py():
    payload = ProtocolPayload({})
    assert payload.to_py() is None

    payload = ProtocolPayload({"vo": "b3BhcXVl"})
    assert payload.to_py() == b"opaque"

    payload = ProtocolPayload({"opaque": {"vo": "b3BhcXVl", "ts": 100}})
    assert payload.to_py() == {"opaque": b"opaque"}

    payload = ProtocolPayload({"1": {"opaque": {"vo": "b3BhcXVl"}}})
    assert payload.to_py() == {"1": {"opaque": b"opaque"}}

    payload = ProtocolPayload({"object": {"1": {"opaque": {"vo": "b3BhcXVl"}}}})
    assert payload.to_py() == {"object": {"1": {"opaque": b"opaque"}}}


def test_protocol_payload_init_with_none_equal_to_empty_payload():
    payload = ProtocolPayload(None)

    assert payload == ProtocolPayload()


def test_protocol_payload_init_same_as_dict():
    a = ProtocolPayload(one=1, two=2, three=3)
    b = ProtocolPayload({"one": 1, "two": 2, "three": 3})
    c = ProtocolPayload(zip(["one", "two", "three"], [1, 2, 3]))
    d = ProtocolPayload([("two", 2), ("one", 1), ("three", 3)])
    e = ProtocolPayload({"three": 3, "one": 1, "two": 2})
    f = ProtocolPayload({"one": 1, "three": 3}, two=2)

    assert a == b == c == d == e == f


def test_protocol_payload_to_protocol_values():
    now = datetime.now(timezone.utc)
    values = {"string": "string", "bool": True, "int": 10, "float": 42.1, "time": now, "opaque": b"opaque"}
    payload = ProtocolPayload.from_py_dict(values)

    protocol_values = payload.protocol_values()
    assert len(protocol_values), len(values)
    assert iter(protocol_values) is not None
    assert protocol_values.keys() == values.keys()
    assert set(protocol_values.values()) == set(ProtocolPayloadValueConversion.py_to_json(v) for v in values.values())

    for k, v in values.items():
        if isinstance(v, datetime) or isinstance(v, bytes):
            assert ProtocolPayloadValueConversion.py_to_json(v) == protocol_values[k]
        else:
            assert v == protocol_values[k]

    with pytest.raises(KeyError):
        protocol_values["non-existing"]

    assert set(v.name for v in protocol_values.as_list()) == values.keys()
    assert set(v.value for v in protocol_values.as_list()) == set(
        ProtocolPayloadValueConversion.py_to_json(v) for v in values.values()
    )


def test_protocol_metadata_init_with_none_equal_to_empty_payload():
    payload = ProtocolMetadata(None)

    assert payload == ProtocolMetadata()


def test_protocol_metadata_init_same_as_dict():
    a = ProtocolMetadata(one=1, two=2, three=3)
    b = ProtocolMetadata({"one": 1, "two": 2, "three": 3})
    c = ProtocolMetadata(zip(["one", "two", "three"], [1, 2, 3]))
    d = ProtocolMetadata([("two", 2), ("one", 1), ("three", 3)])
    e = ProtocolMetadata({"three": 3, "one": 1, "two": 2})
    f = ProtocolMetadata({"one": 1, "three": 3}, two=2)

    assert a == b == c == d == e == f


def test_protocol_payload_value_to_dict():
    array = ProtocolPayloadValue(type=ProtocolPayloadValueType.STRING, value=["val1", "val2"], timestamp=10, name=None)
    assert array.to_json_dict() == {"as": ["val1", "val2"], "ts": 10}

    array_without_ts = ProtocolPayloadValue(
        type=ProtocolPayloadValueType.STRING, value=["val1", "val2"], timestamp=None, name=None
    )
    assert array_without_ts.to_json_dict() == {"as": ["val1", "val2"]}

    string = ProtocolPayloadValue(type=ProtocolPayloadValueType.STRING, value="string", timestamp=10, name=None)
    assert string.to_json_dict() == {"vs": "string", "ts": 10}

    string_without_ts = ProtocolPayloadValue(
        type=ProtocolPayloadValueType.STRING, value="string", timestamp=None, name=None
    )
    assert string_without_ts.to_json_dict() == {"vs": "string"}


def envelope_protocol():
    return ProtocolEnvelope, ProtocolMessage


def envelope_eventbus_protocol():
    return EventBusProtocolEnvelope, EventBusProtocolMessage


def envelope_eventbus_command_request():
    return EventBusCommandRequestEnvelope, EventBusCommandRequest


def envelope_eventbus_command_response():
    return EventBusCommandResponseEnvelope, lambda: EventBusCommandResponse(success=True)


@parametrize_with_cases("envelope_class, message_class", cases=".", prefix="envelope_")
def test_serialize_deserialize_envelope(envelope_class, message_class):
    message = message_class()
    envelope = envelope_class([message])
    serialized = envelope.serialize()
    envelope_deserialized = envelope_class.deserialize(serialized)

    assert envelope_deserialized.encode() == envelope.encode()
    assert type(envelope_deserialized) == type(envelope)
    assert type(envelope_deserialized.messages[0]) == type(envelope.messages[0])


def serialize_deserialize_case_protocol():
    return ProtocolMessage(
        operation=ProtocolOperation.WRITE,
        entity=ProtocolEntity(service="service", path="path"),
        payload=ProtocolPayload.from_py_dict({"value": "string"}),
        metadata=ProtocolMetadata(test="metadata"),
    )


def serialize_deserialize_case_protocol_null_payload():
    return ProtocolMessage(
        operation=ProtocolOperation.WRITE,
        entity=ProtocolEntity(service="service", path="path"),
        payload=None,
        metadata=ProtocolMetadata(test="metadata"),
    )


def serialize_deserialize_case_protocol_null_metadata():
    return EventBusProtocolMessage(
        operation=ProtocolOperation.WRITE,
        entity=ProtocolEntity(service="service", path="path"),
        payload=ProtocolPayload.from_py_dict({"value": "string"}),
        metadata=None,
    )


def serialize_deserialize_case_eventbus_protocol():
    return EventBusProtocolMessage(
        operation=ProtocolOperation.WRITE,
        entity=ProtocolEntity(service="service", path="path"),
        payload=ProtocolPayload.from_py_dict({"value": "string"}),
        metadata=ProtocolMetadata(test="metadata"),
    )


def serialize_deserialize_case_eventbus_command_request():
    return EventBusCommandRequest(
        operation=ProtocolOperation.WRITE,
        entity=ProtocolEntity(service="service", path="path"),
        payload=ProtocolPayload.from_py_dict({"value": "string"}),
        metadata=ProtocolMetadata(test="metadata"),
    )


def serialize_deserialize_case_eventbus_device_command_request():
    r = EventBusDeviceCommandRequest(ProtocolOperation.WRITE, "device", "path")
    r.metadata = ProtocolMetadata(test="metadata")
    return r


def serialize_deserialize_case_eventbus_execute_request_with_args():
    return EventBusDeviceExecuteRequest("device", "path", ProtocolPayload({"as": ["arg1"]}))


def serialize_deserialize_case_eventbus_execute_request_no_args():
    return EventBusDeviceExecuteRequest("device", "path", None)


def serialize_deserialize_case_eventbus_write_request():
    return EventBusDeviceWriteRequest("device", "path", ProtocolPayload.from_py_dict({"value": "string"}))


def serialize_deserialize_case_eventbus_read_request():
    return EventBusDeviceReadRequest("device", "path")


def serialize_deserialize_case_eventbus_status_message():
    return EventBusStatusMessage(
        operation=ProtocolOperation.UPDATE,
        entity=ProtocolEntity(device="device", path="path"),
        payload=ProtocolPayload.from_py_dict({"value": "string"}),
        metadata=ProtocolMetadata(test="metadata"),
    )


def serialize_deserialize_case_eventbus_device_status_message():
    return EventBusDeviceStatusMessage(
        operation=ProtocolOperation.UPDATE,
        entity=EventBusDeviceEntity(device="device", path="path"),
        payload=ProtocolPayload.from_py_dict({"value": "string"}),
        metadata=ProtocolMetadata(test="metadata"),
    )


def serialize_deserialize_case_eventbus_status_update():
    return EventBusDeviceStatusUpdate("device", "path", ProtocolPayload.from_py_dict({"value": "string"}))


def serialize_deserialize_case_eventbus_status_overwrite():
    return EventBusDeviceStatusOverwrite("device", "path", ProtocolPayload.from_py_dict({"value": "string"}))


def serialize_deserialize_case_eventbus_status_delete():
    return EventBusDeviceStatusDelete("device", "path")


@parametrize_with_cases("object", cases=".", prefix="serialize_deserialize_case_")
def test_serialize_deserialize_classes(object):
    result = object.deserialize(object.serialize())
    assert result == object
    assert result.encode() == object.encode()
    assert type(result) == type(object)
    assert type(result.entity) == type(object.entity)
