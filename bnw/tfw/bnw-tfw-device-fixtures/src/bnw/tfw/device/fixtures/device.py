# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncContextManager, Callable, Optional

import pytest
from bnw.tfw.device.component.harness.lwm2m import Client as Lwm2mclient

from bnw.activity.model.device import DeviceModel

logger = logging.getLogger("tfw.fixtures.device")


@pytest.fixture(scope="session")
def inclusion_runner() -> Callable[[Lwm2mclient, Optional[float]], AsyncContextManager[asyncio.Event]]:
    @asynccontextmanager
    async def runner(device: Lwm2mclient, bootstrap_request_interval=10.0):
        _logger = logger.getChild("InclusionRunner")
        _running = asyncio.Event()

        async def run():
            _logger.info("Starting runner")
            try:
                async with device:
                    _running.set()
                    _logger.info("Started runner")

                    while True:
                        try:
                            _logger.info("Performing bootstrap")
                            await asyncio.wait_for(device.perform_bootstrap(), bootstrap_request_interval)
                            _logger.info("Bootstrap finished")
                            break
                        except asyncio.exceptions.TimeoutError:
                            pass

                    # send registration
                    device_values = {"1": str(DeviceModel.GENERIC.value), "2": device.name, "17": "1-DEVICE"}
                    water_control_values = {"3": 0, "4": 60, "5": False, "6": 0}
                    async with device.with_readonly_data(
                        {"3": {"0": device_values}, "28151": {"0": water_control_values}}
                    ):
                        _logger.info("Performing registration")
                        await device.send_registration_request(
                            objects="</3/0>, </28151/0>",
                        )
                        _logger.info("Registration finished")

                        # keep running
                        while True:
                            try:
                                await asyncio.sleep(60)
                            except asyncio.exceptions.CancelledError:
                                pass
            except Exception:
                _logger.warning("Runner failed", exc_info=True)
            finally:
                _logger.info("Runner stopped")
                _running.clear()

        run_device_task = asyncio.create_task(run(), name="device-runner-" + device.name)
        try:
            yield _running
        finally:
            logging.warning("Task: %s", run_device_task)
            run_device_task.cancel()

    return runner


@pytest.fixture(scope="session")
def including_device_factory(inclusion_runner):
    @asynccontextmanager
    async def factory(name, port, bootstrap_request_interval=10.0):
        device = Lwm2mclient(name, port=port)

        async with inclusion_runner(device, bootstrap_request_interval=bootstrap_request_interval):
            yield device

    return factory
