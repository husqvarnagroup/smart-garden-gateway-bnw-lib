# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
import datetime
import logging
import socket
import tempfile
from asyncio import BaseTransport, DatagramProtocol
from typing import Mapping, Optional

from bnw.tfw.component import Component

logger = logging.getLogger("bnw.tfw.gateway.component.harness.systemd")


class SystemdDaemon(Component, DatagramProtocol):
    def __init__(self, notify_socket_path: Optional[str] = None, watchdog_interval: Optional[float] = None) -> None:
        super().__init__()

        if notify_socket_path is None:
            with tempfile.NamedTemporaryFile(prefix="notify_", suffix=".sock") as file:
                notify_socket_path = file.name

        self._notify_socket_path = notify_socket_path
        self._notify_socket_transport: Optional[BaseTransport] = None
        self._notify_ready = asyncio.Event()
        self._logger = logger.getChild(self.__class__.__name__)
        self._watchdog_last_keep_alive: Optional[datetime.datetime] = None
        self._watchdog_interval = watchdog_interval

    async def start(self) -> None:
        self._notify_socket_transport, _ = await asyncio.get_event_loop().create_datagram_endpoint(
            lambda: self, local_addr=self._notify_socket_path, family=socket.AF_UNIX  # type: ignore[arg-type]
        )
        self._logger.debug("Notify socket listening on %s", self.notify_socket)

    async def stop(self) -> None:
        if self._notify_socket_transport:
            self._notify_socket_transport.close()
            self._notify_socket_transport = None

    @property
    def notify_socket(self) -> str:
        return self._notify_socket_path

    async def ready(self) -> bool:
        return self._notify_socket_transport is not None

    def is_service_alive(self) -> Optional[bool]:
        if self._watchdog_interval is not None:
            if self._watchdog_last_keep_alive is None:
                return False
            return (datetime.datetime.now() - self._watchdog_last_keep_alive).total_seconds() <= self._watchdog_interval
        else:
            return None

    def datagram_received(self, data, addr):
        message = data.decode("latin1").strip()

        if message == "READY=1":
            self._notify_ready.set()

        if message == "WATCHDOG=1":
            self._watchdog_last_keep_alive = datetime.datetime.now()

    def error_received(self, exc):
        logger.warning("Notify socket transport error: %s", exc)

    async def notify_ready(self):
        return await self._notify_ready.wait()

    def environ(self) -> Mapping[str, str]:
        d = {"NOTIFY_SOCKET": self.notify_socket}
        if self._watchdog_interval is not None:
            d["WATCHDOG_USEC"] = str(int(self._watchdog_interval * 1e6))

        return d
