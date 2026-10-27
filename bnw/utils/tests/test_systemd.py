# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio

import pytest
from bnw.tfw.gateway.component.harness.systemd import SystemdDaemon
from bnw.tfw.pytest import wait_for

from bnw.utils.systemd import SystemdNotifier


@pytest.mark.asyncio
async def test_systemd():
    # GIVEN:
    systemd = SystemdDaemon()
    await systemd.start()

    sut = SystemdNotifier(notify_socket=systemd.notify_socket)

    # WHEN: ready notified
    sut.ready()

    # THEN: ready notification received
    await wait_for(systemd.notify_ready(), timeout=1, description="Notify ready received")


@pytest.mark.asyncio
async def test_systemd_watchdog():
    # GIVEN: systemd with watchdog
    systemd = SystemdDaemon(watchdog_interval=0.1)
    await systemd.start()

    sut = SystemdNotifier(notify_socket=systemd.notify_socket)

    # WHEN: sut sends alive
    sut.alive()
    await asyncio.sleep(0.01)

    # THEN:
    assert systemd.is_service_alive(), "should be alive after 10ms"

    await asyncio.sleep(0.04)
    assert systemd.is_service_alive(), "should be alive after 50ms"

    await asyncio.sleep(0.06)
    assert not systemd.is_service_alive(), "should be not alive after 110ms"

    sut.alive()
    await asyncio.sleep(0.01)
    assert systemd.is_service_alive(), "should be alive again"


def test_systemd_watchdog_errors(caplog, tmp_path):
    """Check logging for watchdog notifier"""

    # No socket provided, should do nothing
    notifier = SystemdNotifier()
    notifier.alive()
    assert len(caplog.records) == 0, "There should be no log entries here"

    # Non existing socket provided
    notifier = SystemdNotifier(str(tmp_path / "test_systemd_notifier.sock"))
    assert "OSError: [Errno 2] No such file or directory" in caplog.records[-1].getMessage()
    notifier.alive()
    assert "Unexpected error: [Errno 107] Transport endpoint is not connected" in caplog.records[-1].getMessage()
