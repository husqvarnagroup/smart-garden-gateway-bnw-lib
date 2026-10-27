# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
import contextlib
import logging
import shutil
from pathlib import Path


class PacketCapture:

    _SUPPORTED_TOOLS = ["dumpcap", "tcpdump"]
    _USE_SUDO = False

    @classmethod
    def use_sudo(cls, value=True):
        cls._USE_SUDO = value

    @classmethod
    def is_available(cls):
        return next((True for t in cls._SUPPORTED_TOOLS if cls._is_tool_available(t)), False)

    @classmethod
    def _is_tool_available(cls, tool):
        return shutil.which(tool) is not None

    @classmethod
    @contextlib.asynccontextmanager
    async def new_session(cls, interface: str, output_file: Path, capture_filter: str = None):
        for t in cls._SUPPORTED_TOOLS:
            if cls._is_tool_available(t) is False:
                continue

            if t == "dumpcap":
                args = ["dumpcap", "-i", interface, "-w", str(output_file)]
                if capture_filter is not None:
                    args.append("-f")
                    args.append(capture_filter)
            elif t == "tcpdump":
                args = ["tcpdump", "-i", interface, "-w", str(output_file)]
                if capture_filter is not None:
                    args.append(capture_filter)
            else:
                assert False, "Unsupported tool"

            try:
                if cls._USE_SUDO:
                    args = ["sudo"] + args
                process = await asyncio.create_subprocess_exec(
                    *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )
                if process.returncode is not None:
                    raise ValueError(f"{t} stopped with exit code {process.returncode}")
            except Exception as e:
                logging.info("Failure starting packet capture: %s", e)
                logging.debug("Failed capture command: '%s'", " ".join(args))
                continue

            try:
                yield
            finally:
                try:
                    process.terminate()
                    await process.wait()
                except (Exception, asyncio.exceptions.CancelledError):
                    pass
            return

        raise Exception("Could not start packet capture")

    @classmethod
    @contextlib.asynccontextmanager
    async def port(cls, interface, port, output_file=None):
        if output_file is None:
            output_file = f"port-{port}.pcap"

        async with cls.new_session(interface=interface, capture_filter=f"port {port}", output_file=output_file):
            yield
