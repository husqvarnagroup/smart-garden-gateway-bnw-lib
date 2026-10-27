# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
import contextlib
import json
import logging
import shutil
from pathlib import Path

import msgpack
from bnw.transport.unix import MESSAGE_SEPERATOR


class Capture:
    @classmethod
    def is_available(cls) -> bool:
        return shutil.which("socat") is not None

    @classmethod
    @contextlib.asynccontextmanager
    async def subscribe(cls, path: str, output_file: Path):
        """
        socat - UNIX-CONNECT:/tmp/lwm2mserver-event.ipc
        """
        args = ["socat", "-", f"UNIX-CONNECT:{path}"]

        with open(str(output_file) + "-stdout", "wb") as file_stdout, open(str(output_file), "wb") as file_messages:
            process = await asyncio.create_subprocess_exec(
                *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            if process.returncode is not None:
                raise ValueError(f"socat stopped with exit code {process.returncode}")
            write_task = asyncio.create_task(cls._write_capture_files(process, file_stdout, file_messages))

            try:
                yield
            finally:
                try:
                    process.terminate()
                    await process.wait()
                    await write_task
                except (Exception, asyncio.exceptions.CancelledError):
                    pass

    @classmethod
    async def _write_capture_files(cls, process, file_stdout, file_messages):
        buffer_size = 1024
        unpacker = msgpack.Unpacker(max_buffer_size=buffer_size * 8)

        while True:
            try:
                chunk = await process.stdout.read(buffer_size)
                if not chunk:
                    break
                file_stdout.write(chunk)
                unpacker.feed(chunk)

                for o in unpacker:
                    if not isinstance(o, bytes):
                        continue

                    try:
                        # validate if it is json
                        json.loads(o)

                        # write a new line
                        file_messages.write(o)
                        file_messages.write(MESSAGE_SEPERATOR)
                    except Exception:
                        logging.debug("Invalid JSON msg received: %s", o, exc_info=True)
            except Exception:
                logging.error("Failure", exc_info=True)
                break
