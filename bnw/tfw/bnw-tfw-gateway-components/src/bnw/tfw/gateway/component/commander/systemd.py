# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
from pathlib import Path
from typing import List, Mapping, Optional

from bnw.tfw.component.commander import ProcessCommander

from ..harness.systemd import SystemdDaemon


class SystemdUnitNotifyCommander(ProcessCommander):
    def __init__(
        self,
        executable,
        arguments: List[str] = None,
        working_directory: str = None,
        env: Mapping[str, str] = None,
        watchdog_interval: float = None,
        shell_output_file: Optional[Path] = None,
    ):
        self._systemd_daemon = SystemdDaemon(watchdog_interval=watchdog_interval)
        if env is not None:
            env = dict(env)
            env.update(self._systemd_daemon.environ())
        else:
            env = self._systemd_daemon.environ()

        super().__init__(
            executable,
            arguments=arguments,
            working_directory=working_directory,
            env=env,
        )

    async def start(self) -> None:
        await self._systemd_daemon.start()
        return await super().start()

    async def stop(self, **kwargs) -> None:  # type: ignore[override]
        await super().stop(**kwargs)
        await self._systemd_daemon.stop()

    async def ready(self, timeout=10) -> bool:
        """Signal service readyness

        Waits until systemd monitored service notifies "ready".
        Returns false if service failed imediately after start.
        """
        if not await super().ready():
            return False

        await asyncio.wait_for(self._systemd_daemon.notify_ready(), timeout=timeout)
        return True

    def is_alive(self) -> Optional[bool]:
        return self._systemd_daemon.is_service_alive()
