# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import datetime

import pytest

from bnw.activity.model.device import (
    DeviceModel,
    DeviceName,
    DeviceResource,
    DeviceResourcePath,
    Sgtin96,
)
from bnw.protocol import ProtocolPayload


def test_device_model():
    assert DeviceModel.from_sgtin("301400000000004000000033") == DeviceModel.GENERIC


def test_device_name():
    name = DeviceName.from_string("301400000000004000000033")
    assert name.model == DeviceModel.GENERIC
    assert name.model_number == 1
    assert name.serial == 51

    name2 = DeviceName(None, model=DeviceModel.GENERIC, serial=51)
    assert name.__dict__ == name2.__dict__

    name3 = DeviceName.from_string("3018f169003fffc000000002")
    assert name3.sgtin == "3018f169003fffc000000002"
    assert name3.serial == 2
    with pytest.raises(ValueError):
        assert name3.model


def test_sgtin_encode():
    assert (
        Sgtin96.encode(company_prefix=4078500, item_ref=21869, serial=219, filter_value=1) == "3034F8EE90155B40000000DB"
    )
    assert Sgtin96.encode(company_prefix=0, item_ref=1, serial=51, filter_value=0) == "301400000000004000000033"
    assert (
        Sgtin96.encode(company_prefix=Sgtin96.SG_COMPANY_PREFIX, item_ref=18869, serial=149543)
        == "3034F8EE90126D4000024827"
    )


def test_device_resources_from_payload():
    now = datetime.datetime.now(datetime.timezone.utc)
    now = now.replace(microsecond=0)

    data = {"string": "string", "bool": True, "int": 10, "float": 42.1, "time": now, "opaque": b"opaque"}
    payload = ProtocolPayload.from_py_dict(data)

    def assert_resource(resources):
        for resource in resources:
            assert resource.path.resource_name in data
            assert resource.path.object_name == "object"
            assert resource.path.object_instance_id == 1
            assert resource.value.name == resource.path.resource_name
            assert resource.value.raw == data[resource.value.name]

    assert_resource(DeviceResource.from_payload(DeviceResourcePath("object", 1), payload))
    assert_resource(DeviceResource.from_payload(DeviceResourcePath("object"), ProtocolPayload({"1": payload})))
    assert_resource(DeviceResource.from_payload(DeviceResourcePath(), ProtocolPayload({"object": {"1": payload}})))


def test_device_single_resource_instance():
    payload = ProtocolPayload(vs="value")
    resource = DeviceResource.from_payload(DeviceResourcePath("object", 1, "resource"), payload)[0]

    assert resource.path.resource_name == "resource"
    assert resource.path.object_name == "object"
    assert resource.path.object_instance_id == 1
    assert resource.value.name == resource.path.resource_name
    assert resource.value.raw == "value"


def test_device_single_multiple_resource_instance():
    payload = ProtocolPayload(vi=0)
    resource = DeviceResource.from_payload(DeviceResourcePath("object", 1, "multiple_resource", 10), payload)[0]

    assert resource.path.resource_name == "multiple_resource"
    assert resource.path.resource_instance_id == 10
    assert resource.path.object_name == "object"
    assert resource.path.object_instance_id == 1
    assert resource.value.name == "multiple_resource[10]"
    assert resource.value.raw == 0
