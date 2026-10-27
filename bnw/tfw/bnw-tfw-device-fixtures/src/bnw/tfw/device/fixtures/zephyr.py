# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import os

import pytest_cases
from bnw.tfw.device.component.harness.zephyr import ZephyrNativePosixNetworkInterface


@pytest_cases.fixture
async def zeth_interface():
    if "TF_BUILD" in os.environ:
        ZephyrNativePosixNetworkInterface.use_sudo()

    interface = ZephyrNativePosixNetworkInterface()

    if interface.exists():
        yield interface
    else:
        # create interface on our own
        async with interface:
            yield interface
