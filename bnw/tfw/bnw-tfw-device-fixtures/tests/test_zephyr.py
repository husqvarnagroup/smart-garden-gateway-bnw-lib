# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest


@pytest.mark.asyncio
async def test_zeth_interface(zeth_interface):
    assert zeth_interface
