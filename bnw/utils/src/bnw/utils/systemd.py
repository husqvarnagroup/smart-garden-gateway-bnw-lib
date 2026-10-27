# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
import logging
import os
import socket
from datetime import timedelta
from typing import Callable, Optional


class SystemdNotifier:
    _socket: Optional[socket.socket]
    _keep_alive_task: Optional[asyncio.Task]

    def __init__(self, notify_socket: Optional[str] = None):
        self._logger = logging.getLogger("watchdog")
        self._keep_alive_task = None
        try:
            if notify_socket is None:
                notify_socket = os.getenv("NOTIFY_SOCKET")

            if notify_socket:
                self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
                if notify_socket[0] == "@":
                    notify_socket = "\0" + notify_socket[1:]
                self._socket.connect(notify_socket)

            else:
                self._socket = None
        except OSError as e:
            self._logger.warning("OSError: %s", e)
        except Exception as e:
            self._socket = None
            self._logger.exception("Unexpected error: %s", e)

    def is_enabled(self):
        return self._socket is not None

    def _send(self, state: str):
        if self._socket is None:
            return

        try:
            self._socket.sendall(state.encode("latin-1"))
        except Exception as e:
            self._logger.exception("Unexpected error: %s", e)

    def ready(self):
        self._send("READY=1\n")

    def stopping(self):
        self._send("STOPPING=1\n")

    def status(self, msg: str):
        self._send("STATUS=%s\n" % (msg,))

    def alive(self):
        self._send("WATCHDOG=1\n")

    def panic(self, msg: str = None):
        if msg is not None:
            self.status(msg)
        self._send("WATCHDOG=trigger\n")

    def enable_watchdog(self, health_check: Callable[[], bool] = None) -> bool:
        if self._keep_alive_task is not None:
            return False

        watchdog_usec = os.getenv("WATCHDOG_USEC", None)
        if watchdog_usec is None:
            return False

        notify_interval = timedelta(microseconds=int(watchdog_usec) * 0.9 / 2).total_seconds()
        self._logger.debug("Enabling watchdog. Notification interval: %s", notify_interval)

        async def keep_alive():
            while True:
                try:
                    if health_check is not None:
                        if health_check():
                            self.alive()
                    else:
                        self.alive()
                    await asyncio.sleep(notify_interval)
                except asyncio.exceptions.CancelledError:
                    break
                except Exception as e:
                    self._logger.exception("Unexpected error: %s", e)

        self._keep_alive_task = asyncio.get_event_loop().create_task(keep_alive(), name="systemd_watchdog_keep_alive")
        return True

    def disable_watchdog(self) -> bool:
        if self._keep_alive_task:
            try:
                self._keep_alive_task.cancel()
            except Exception as e:
                self._logger.exception("Unexpected error: %s", e)
            finally:
                self._keep_alive_task = None
            return True
        return False
