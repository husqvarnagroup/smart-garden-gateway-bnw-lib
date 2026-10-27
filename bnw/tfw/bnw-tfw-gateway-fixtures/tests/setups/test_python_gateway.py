# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest
from bnw.tfw.gateway.fixtures.setups.python_gateway import PythonGatewayTestSetup
from bnw.tfw.pytest import wait_for

PythonGatewayTestSetup.install(__name__)


@PythonGatewayTestSetup.skip_if_unavailable
@pytest.mark.asyncio
async def test_python_gateway_test_setup_is_ready(python_gateway_test_setup: PythonGatewayTestSetup):
    assert wait_for(
        python_gateway_test_setup.assert_ready(), timeout=60, description="Python Gateway Test Setup not ready"
    )


@PythonGatewayTestSetup.skip_if_unavailable
@pytest.mark.asyncio
async def test_gateway_processes_test_device_factory_and_inclusion(python_gateway_test_setup: PythonGatewayTestSetup):
    device, device_name, _, _ = python_gateway_test_setup.device_factory()
    async with python_gateway_test_setup.cloud.listen_for_telemetry_single(
        python_gateway_test_setup.gateway_name,
        device_name,
        path="#",
        mqtt_application=python_gateway_test_setup.mqtt_application,
    ) as get_telemetry:
        await wait_for(python_gateway_test_setup.include(device_name, device), timeout=10, description="Inclusion")
        assert await get_telemetry()
