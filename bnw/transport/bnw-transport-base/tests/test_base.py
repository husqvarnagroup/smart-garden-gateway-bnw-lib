# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

from bnw.transport.base import Transport


def test_base():
    class SampleTransport(Transport):
        async def connect(self) -> None:
            pass

        async def disconnect(self) -> None:
            pass

    assert SampleTransport()
