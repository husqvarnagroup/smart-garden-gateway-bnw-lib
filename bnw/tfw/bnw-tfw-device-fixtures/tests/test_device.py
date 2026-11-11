# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

from typing import Callable

import pytest


@pytest.mark.asyncio
async def test_inclusion_runner(inclusion_runner):
    assert isinstance(inclusion_runner, Callable)


@pytest.mark.asyncio
async def test_including_device_factory(including_device_factory):
    async with including_device_factory("name", 5783) as device:
        assert device
