# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
import os

import pytest  # type: ignore
import pytest_cases
from bnw.tfw.fixtures.manufacturing import *  # noqa
from bnw.tfw.gateway.fixtures.cases.components import parametrize_with_lwm2mserver
from bnw.tfw.gateway.fixtures.setups.python_gateway import PythonGatewayTestSetup
from bnw.transport.unix.socket import ConsumerConnection

from bnw.activity import ActivityStrategy
from bnw.activity.model.device import (
    DeviceResourcePath,
    DeviceResourceValue,
    DeviceResourceWriteBatch,
)
from bnw.activity.operations import (
    MqttResourceOperationStrategy,
    ResourceOperationError,
    ResourceOperationProcess,
    UnixResourceOperationStrategy,
)

pytestmark = pytest.mark.asyncio
skip_if_testsetup_unavailable = pytest.mark.skipif(
    not PythonGatewayTestSetup.is_available(), reason="Python Gateway Test Setup not available"
)


@pytest.fixture
def lwm2m_port(python_gateway_test_setup):
    return python_gateway_test_setup.lwm2m_port


@pytest.fixture
def cloud_tenant_override():
    return "hickory"


@pytest.fixture
def lwm2mserver(python_gateway_test_setup):
    return python_gateway_test_setup.lwm2mserver


@pytest.fixture
def lemonbeat_network_key() -> bytes:
    return os.urandom(16)


class CasesMultipleServiceUnixConnection:
    @classmethod
    def ids(cls, case_fun):
        return "transport:unix>%s" % pytest_cases.get_case_id(case_fun).replace("_connection", "")

    @parametrize_with_lwm2mserver
    def case_lwm2mserver_connection(self, lwm2mserver):
        return lwm2mserver.eventbus_connection()


class CasesResourceOperationsStrategy:
    def case_mqtt(self, python_gateway_test_setup, cloud_awsclient_mqtt_connection):
        return MqttResourceOperationStrategy(
            mqtt_connection=cloud_awsclient_mqtt_connection,
            gateway=python_gateway_test_setup.gateway_name,
            mqtt_application=python_gateway_test_setup.mqtt_application,
        )

    @pytest_cases.parametrize_with_cases(
        "service_connection", cases=CasesMultipleServiceUnixConnection, ids=CasesMultipleServiceUnixConnection.ids
    )
    def case_unix(self, service_connection: ConsumerConnection):
        return UnixResourceOperationStrategy(service_connection)


parametrize_with_operation_strategy = pytest_cases.parametrize_with_cases(
    "operation_strategy", cases=CasesResourceOperationsStrategy, ids=lambda f: f"strategy:{pytest_cases.get_case_id(f)}"
)


class CasesRead:
    serial_number_value = "a_serial_number"
    fixture = {"2": serial_number_value}

    def case_single_resource_read_object(self):
        return (
            CasesRead.fixture,
            DeviceResourcePath("device"),
            [(("device", 0, "serial_number"), CasesRead.serial_number_value)],
        )

    def case_single_resource_read_instance(self):
        return (
            CasesRead.fixture,
            DeviceResourcePath("device", 0),
            [(("device", 0, "serial_number"), CasesRead.serial_number_value)],
        )

    def case_single_resource_read_resource(self):
        return (
            CasesRead.fixture,
            DeviceResourcePath("device", 0, "serial_number"),
            [(("device", 0, "serial_number"), CasesRead.serial_number_value)],
        )

    def case_multiple_resource_read_instance(self):
        return (
            {"2": "serial", "3": "version"},
            DeviceResourcePath("device", 0),
            [(("device", 0, "serial_number"), "serial"), (("device", 0, "firmware_version"), "version")],
        )


@skip_if_testsetup_unavailable
@parametrize_with_operation_strategy
@pytest_cases.parametrize_with_cases("client_data, read_path, expected_result_data", cases=CasesRead)
async def test_read_operation(
    python_gateway_test_setup: PythonGatewayTestSetup,
    operation_strategy: ActivityStrategy,
    client_data,
    read_path,
    expected_result_data,
):

    device_name = python_gateway_test_setup.device_name
    device = python_gateway_test_setup.device
    async with ResourceOperationProcess(operation_strategy) as process:  # type: ignore[abstract]

        async with device.with_device_object(client_data):
            resources, _ = await asyncio.wait_for(process.read(device_name, read_path), timeout=5.0)
            assert len(resources) == len(expected_result_data)

            for i in range(len(expected_result_data)):
                resource = resources[i]
                expected_path, expected_value = expected_result_data[i]
                assert resource.path.to_tuple() == expected_path
                assert resource.value.raw == expected_value


class CasesWrite:
    def case_failure(self):
        return (
            ("1",),
            DeviceResourcePath("device", 0, "timezone"),
            DeviceResourceValue.from_raw_value("Europe/Zurich"),
            ResourceOperationError,
        )

    def case_single(self):
        return (
            ("3",),
            DeviceResourcePath("device", 0, "timezone"),
            DeviceResourceValue.from_raw_value("Europe/Zurich"),
            {"3": {"0": {"15": "Europe/Zurich"}}},
        )

    def case_batch(self):
        return (
            ("3",),
            DeviceResourcePath("device", 0),
            DeviceResourceWriteBatch(
                DeviceResourceValue.from_raw_value("Europe/Zurich", name="timezone"),
                DeviceResourceValue.from_raw_value("+0200", name="utc_offset"),
            ),
            {"3": {"0": {"14": "+0200", "15": "Europe/Zurich"}}},
        )


@skip_if_testsetup_unavailable
@parametrize_with_operation_strategy
@pytest_cases.parametrize_with_cases(
    "accept_write_path, write_path, write_value, expected_written_data", cases=CasesWrite
)
async def test_write_operation(
    python_gateway_test_setup: PythonGatewayTestSetup,
    operation_strategy: ActivityStrategy,
    accept_write_path,
    write_path,
    write_value,
    expected_written_data,
):

    device_name = python_gateway_test_setup.device_name
    device = python_gateway_test_setup.device
    async with ResourceOperationProcess(operation_strategy) as process:  # type: ignore[abstract]

        async with device.accept_write(accept_write_path) as write_events:
            if type(expected_written_data) is type and issubclass(expected_written_data, Exception):
                with pytest.raises(expected_written_data):
                    await asyncio.wait_for(process.write(device_name, write_path, write_value), timeout=5.0)
            else:
                await asyncio.wait_for(process.write(device_name, write_path, write_value), timeout=5.0)
                written_content, write_request = await write_events.get()
                assert written_content == expected_written_data


class CasesExecute:
    def case_without_arguments(self):
        return ("3", "0", "5"), DeviceResourcePath("device", 0, "factory_reset"), None, ""

    def case_with_arguments(self):
        return (
            ("3", "0", "5"),
            DeviceResourcePath("device", 0, "factory_reset"),
            DeviceResourceValue.from_raw_value(["arg1", "arg"]),
            "arg1, arg",
        )

    def case_invalid_argument_value(self):
        return (
            ("3", "0", "5"),
            DeviceResourcePath("device", 0, "factory_reset"),
            DeviceResourceValue.from_raw_value("string"),
            ResourceOperationError,
        )


@skip_if_testsetup_unavailable
@parametrize_with_operation_strategy
@pytest_cases.parametrize_with_cases(
    "accept_execute_path, execute_path, execute_arguments, expected_received_arguments", cases=CasesExecute
)
async def test_execute_operation(
    python_gateway_test_setup: PythonGatewayTestSetup,
    operation_strategy: ActivityStrategy,
    accept_execute_path,
    execute_path,
    execute_arguments,
    expected_received_arguments,
):

    device_name = python_gateway_test_setup.device_name
    device = python_gateway_test_setup.device
    async with ResourceOperationProcess(operation_strategy) as process:  # type: ignore[abstract]

        async with device.accept_execute(accept_execute_path) as execute_events:

            if type(expected_received_arguments) is type and issubclass(expected_received_arguments, Exception):
                with pytest.raises(expected_received_arguments):
                    await asyncio.wait_for(
                        process.execute(device_name, execute_path, arguments=execute_arguments), timeout=5.0
                    )
            else:
                await asyncio.wait_for(
                    process.execute(device_name, execute_path, arguments=execute_arguments), timeout=5.0
                )
                arguments, execute_request = await asyncio.wait_for(execute_events.get(), timeout=2)
                assert arguments == expected_received_arguments
