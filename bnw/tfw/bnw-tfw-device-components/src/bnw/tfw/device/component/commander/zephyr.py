# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path
from typing import Optional

from bnw.tfw.component.commander import PexpectCommander

from bnw.activity.model.device import DeviceName


class ZephyrNativePosixCommander(PexpectCommander):
    def __init__(self, executable: str, working_directory: str = None):
        super().__init__(executable, arguments=[], working_directory=working_directory)
        self._device_name: Optional[DeviceName] = None
        self._keep_flash = False

    def with_keep_flash(self):
        self._keep_flash = True
        return self

    async def ready(self) -> bool:
        if not await super().ready():
            return False

        await self.await_output_once("Hello GARDENA! native_posix")
        await self.await_output_once("net_lwm2m_rd_client: .*urn:dev:sg:([0-9A-F]{24})")
        if self._device_name is None:
            assert self._instance
            assert self._instance.match
            self._device_name = DeviceName.from_string(self._instance.match.group(1).decode())

        return True

    @property
    def device_name(self) -> DeviceName:
        assert self._device_name
        return self._device_name

    async def stop(self, **kwargs) -> None:  # type: ignore[override]
        try:
            await super().stop(**kwargs)
        finally:
            if not self._keep_flash:
                flash = Path(Path.cwd()) / "flash.bin"
                if flash.exists():
                    flash.unlink()
