# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest
from bnw.tfw.gateway.fixtures.setups.gateway_processes import GatewayProcessesTestSetup
from bnw.tfw.pytest import wait_for

GatewayProcessesTestSetup.install(__name__)


@GatewayProcessesTestSetup.skip_if_unavailable
@pytest.mark.asyncio
async def test_gateway_processes_test_setup_is_ready(gateway_processes_test_setup: GatewayProcessesTestSetup):
    assert wait_for(
        gateway_processes_test_setup.assert_ready(), timeout=60, description="Gateway Processes Test Setup not ready"
    )


@GatewayProcessesTestSetup.skip_if_unavailable
@pytest.mark.asyncio
async def test_gateway_processes_test_device_factory_and_inclusion(
    gateway_processes_test_setup: GatewayProcessesTestSetup,
):
    device, device_name, _, _ = gateway_processes_test_setup.device_factory()
    async with gateway_processes_test_setup.cloud.listen_for_telemetry_single(
        gateway_processes_test_setup.gateway_name,
        device_name,
        path="#",
        mqtt_application=gateway_processes_test_setup.mqtt_application,
    ) as get_telemetry:
        await wait_for(gateway_processes_test_setup.include(device_name, device), timeout=10, description="Inclusion")
        assert await get_telemetry()
