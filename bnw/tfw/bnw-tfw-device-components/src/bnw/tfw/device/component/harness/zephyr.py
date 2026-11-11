# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
import json
import logging
import subprocess
from typing import List

import netifaces
from bnw.tfw.component import Component


class ZephyrNativePosixNetworkInterface(Component):
    _USE_SUDO = False

    @classmethod
    def use_sudo(cls, value=True):
        cls._USE_SUDO = value

    def __init__(
        self,
        interface_name: str = "zeth",
        hardware_address="00:00:5e:00:53:ff",
        ipv6_address="2001:db8::2",
        ipv6_route="2001:db8::/64",
    ):
        self.interface_name = interface_name
        self.hardware_address = hardware_address
        self.ipv6_address = ipv6_address
        self.ipv6_route = ipv6_route

    async def _execute_commands(self, commands: List[List[str]]):
        for command in commands:
            if self._USE_SUDO:
                if subprocess.run(["sudo", "-n", "true"], stderr=subprocess.DEVNULL).returncode:
                    raise RuntimeError("sudo is locked and would need a password")
                command = ["sudo"] + command
            else:
                command = command

            proc = await asyncio.create_subprocess_exec(
                command[0], *(command[1:]), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()

            if stdout:
                logging.debug("Command '%s' stdout: %s", " ".join(command), stdout.decode())
            if stderr:
                logging.debug("Command '%s' stderr: %s", " ".join(command), stderr.decode())

            if proc.returncode != 0:
                cmd = " ".join(command)
                raise ValueError(f"Command '{cmd}' failed: {stderr.decode()}")

    async def start(self) -> None:
        commands = [
            ["ip", "tuntap", "add", self.interface_name, "mode", "tap"],
            ["ip", "link", "set", "dev", self.interface_name, "up"],
            ["ip", "link", "set", "dev", self.interface_name, "address", self.hardware_address],
            ["ip", "-6", "address", "add", self.ipv6_address, "dev", self.interface_name, "nodad"],
            ["ip", "-6", "route", "add", self.ipv6_route, "dev", self.interface_name],
        ]

        await self._execute_commands(commands)

    async def stop(self) -> None:
        commands = [["ip", "tuntap", "del", self.interface_name, "mode", "tap"]]

        await self._execute_commands(commands)

    async def ready(self) -> bool:
        return self.exists()

    def exists(self):
        return self.interface_name in netifaces.interfaces()

    def check_setup(self):
        """Ensure the already running interface is setup correctly"""
        ip_r_get = json.loads(subprocess.check_output(["ip", "-j", "r", "get", "2001:db8::1"]).decode())
        assert ip_r_get[0]["dev"] == self.interface_name
        ip_a_show_dev = json.loads(subprocess.check_output(["ip", "-j", "a", "show", self.interface_name]).decode())
        assert ip_a_show_dev[0]["address"] == self.hardware_address
        ipv6_addr_found = False
        for addr_info in ip_a_show_dev[0]["addr_info"]:
            if addr_info["family"] == "inet6" and addr_info["local"] == self.ipv6_address:
                ipv6_addr_found = True
                break
        assert ipv6_addr_found
