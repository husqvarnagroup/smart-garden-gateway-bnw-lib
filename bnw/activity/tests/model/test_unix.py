# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

# flake8: noqa: E721
from pytest_cases import parametrize_with_cases

from bnw.activity.model.unix import UnixCommandRequest, UnixCommandResponse
from bnw.protocol import ProtocolEntity, ProtocolOperation, ProtocolPayload
from bnw.protocol.entity import EventBusDeviceEntity


def test_unix_command_request_serializes_to_array():
    sut = UnixCommandRequest(operation=ProtocolOperation.READ, entity=EventBusDeviceEntity("device", "path"))
    assert isinstance(sut.encode(), list)
    assert sut.serialize()[0] == "["


def test_unix_command_request_behaves_like_an_envelope():
    # GIVEN: request
    req = UnixCommandRequest(operation=ProtocolOperation.READ, entity=EventBusDeviceEntity("device", "path"))
    # WHEN: creating command request as envelope (arg)
    sut = UnixCommandRequest([req])

    # THEN: matches behaviour of envelope
    assert sut.messages == [req]
    assert isinstance(sut.encode(), list)
    assert sut.serialize()[0] == "["
    assert sut == req
    assert sut.encode() == req.encode()

    # WHEN: creating command request as envelope (kwarg)
    sut = UnixCommandRequest(messages=[req])

    # THEN: matches behaviour of envelope
    assert sut.messages == [req]
    assert isinstance(sut.encode(), list)
    assert sut.serialize()[0] == "["
    assert sut == req
    assert sut.encode() == req.encode()


def test_unix_command_response_behaves_like_an_envelope():
    # GIVEN: request
    res = UnixCommandResponse(
        success=True, operation=ProtocolOperation.READ, entity=EventBusDeviceEntity("device", "path")
    )
    # WHEN: creating command response as envelope (arg)
    sut = UnixCommandResponse([res])

    # THEN: matches behaviour of envelope
    assert sut.messages == [res]
    assert isinstance(sut.encode(), list)
    assert sut.serialize()[0] == "["
    assert sut == res
    assert sut.encode() == res.encode()

    # WHEN: creating command request as envelope (kwarg)
    sut = UnixCommandResponse(messages=[res])

    # THEN: matches behaviour of envelope
    assert sut.messages == [res]
    assert isinstance(sut.encode(), list)
    assert sut.serialize()[0] == "["
    assert sut == res
    assert sut.encode() == res.encode()


def serialize_deserialize_case_unix_command_request():
    return UnixCommandRequest(
        operation=ProtocolOperation.READ,
        entity=ProtocolEntity(device="device", path="path"),
        payload=ProtocolPayload.from_py_dict({"value": "string"}),
    )


def serialize_deserialize_case_unix_command_response():
    return UnixCommandResponse(
        success=True,
        operation=ProtocolOperation.READ,
        entity=ProtocolEntity(device="device", path="path"),
        payload=ProtocolPayload.from_py_dict({"value": "string"}),
    )


@parametrize_with_cases("object", cases=".", prefix="serialize_deserialize_case_")
def test_serialize_deserialize_classes(object):
    # WHEN: serializing and deserializing
    result = object.deserialize(object.serialize())

    # THEN: same result as the start
    assert result == object
    assert result.encode() == object.encode()
    assert result.serialize() == object.serialize()
    assert type(result) == type(object)
    assert type(result.entity) == type(object.entity)
