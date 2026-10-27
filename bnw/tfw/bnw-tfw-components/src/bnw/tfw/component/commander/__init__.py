# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Package for modules that command / control other components
"""

import asyncio
import logging
import os
import shutil
import sys
import warnings
from pathlib import Path
from typing import Dict, List, Mapping, Match, Optional, Tuple, Union, cast

import pexpect as pexpect

from .. import Component

logger = logging.getLogger("bnw.component.commander")


class _LoggerFile:
    def __init__(self, executable):
        self._logger = logger.getChild(f"log.{Path(executable).name}")

    def write(self, s):
        self._logger.debug(self._try_decode(s))

    def flush(self):
        pass

    def _try_decode(self, s: bytes) -> str:
        try:
            string = s.decode()
        except UnicodeDecodeError:
            self._logger.info("Decoding error, falling back to ignore errors", exc_info=True)
            string = s.decode(errors="ignore")

        return string.replace("\r\r\n", "\n")


def is_available(binary: str) -> bool:
    return get_executable(binary) is not None


def get_executable(binary: str):
    python_executable_path = str(Path(sys.executable).parent)
    path = os.environ.get("PATH", None)
    if path is not None:
        path = python_executable_path + os.pathsep + path
    else:
        path = python_executable_path

    return shutil.which(binary, path=path)


class PexpectCommander(Component):
    _executable: str
    _arguments: List[str]
    _read_task: Optional[asyncio.Task]
    _instance: Optional[pexpect.spawn]
    _await_output_history: Dict[str, Tuple[bool, Union[Match, Exception]]]
    _shell_output_file: Optional[Path]

    def __init__(
        self,
        executable,
        arguments: List[str] = None,
        working_directory: str = None,
        env: Mapping[str, str] = None,
        shell_output_file: Optional[Path] = None,
    ):
        self._executable = get_executable(executable)
        if self._executable is None:
            raise ValueError(f"Executable '{executable}' not found")
        self._arguments = arguments or []
        self._working_directory = working_directory
        if env is None:
            self._environment = {}
        else:
            self._environment = cast(Dict[str, str], env)
        self._read_task = None
        self._instance = None
        self._await_output_history = {}
        self._shell_output_file = shell_output_file

        if shell_output_file and get_executable("tee") is None:
            raise ValueError("tee binary is required for shell output")

        warnings.warn("use ProcessCommander", DeprecationWarning)

    async def start(self) -> None:
        if self._shell_output_file:
            exectutable = "sh"
            args = [
                "-c",
                " ".join([self._executable] + self._arguments + ["2>&1", "|", "tee", str(self._shell_output_file)]),
            ]
        else:
            exectutable = self._executable
            args = self._arguments

        # Check environment value types to prevent unexpected behaviour with pexpect.
        # See https://github.com/pexpect/pexpect/issues/512
        for key, val in self._environment.items():
            if not isinstance(val, str):
                raise TypeError(f"Environment variable {key} must be of type str, but is {val}")

        self._instance = pexpect.spawn(
            exectutable,
            args=args,
            logfile=_LoggerFile(self._executable),
            cwd=self._working_directory,
            env=self._environment,
        )

    async def ready(self) -> bool:
        return self._instance is not None

    async def stop(self, timeout=30.0) -> None:
        if self._instance:
            self._instance.terminate()
            try:
                self._instance.expect(pexpect.exceptions.EOF, timeout=timeout)
            except pexpect.TIMEOUT:
                logger.warning("Failed to stop %s within timeout, killing it", self._instance)
                self._instance.terminate(force=True)

            self._instance = None

    def change_working_directory(self, working_directory: str) -> None:
        self._working_directory = working_directory

    async def await_output(self, pattern, timeout=-1) -> Tuple[int, Union[Match, Exception]]:
        assert self._instance is not None
        result = await self._instance.expect(pattern, timeout=timeout, async_=True)
        match = self._instance.match
        return result, match

    async def await_output_once(self, pattern: str, timeout=-1) -> Tuple[bool, Union[Match, Exception]]:
        """
        Awaits that a output was found once. It records previous outputs for the pattern, and will return the previous
        result making this method safe to be called multiple times without the underlying executable having to produce
        the output once again to complete.
        """
        assert isinstance(pattern, str), "Only supporting string pattern"

        recorded_result = self._await_output_history.get(pattern, None)
        if recorded_result is not None:
            return recorded_result

        result, match = await self.await_output(pattern, timeout=timeout)
        self._await_output_history[pattern] = result == 0, match
        return result == 0, match


class ProcessCommander(Component):
    """Start a long running process in the background."""

    _executable: str
    _arguments: List[str]
    _stdout_task: Optional[asyncio.Task]
    _process: Optional[asyncio.subprocess.Process]

    def __init__(
        self,
        executable,
        arguments: List[str] = None,
        working_directory: str = None,
        env: Mapping[str, str] = None,
    ):
        self._executable = get_executable(executable)
        if self._executable is None:
            raise ValueError(f"Executable '{executable}' not found")
        self._arguments = arguments or []
        self._working_directory = working_directory
        if env is None:
            self._environment = {}
        else:
            self._environment = cast(Dict[str, str], env)
        self._process = None
        self._stdout_task = None

    async def start(self) -> None:
        logger.debug("starting program %s with args: %s", self._executable, " ".join(self._arguments))
        self._process = await asyncio.create_subprocess_exec(
            self._executable,
            *self._arguments,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=self._working_directory,
            env=self._environment,
        )

        # Start a background task to asynchronously read stdout and stderr
        self._stdout_task = asyncio.create_task(self._stdout_handler(), name="stdout_task")

    async def ready(self) -> bool:
        return isinstance(self._process, asyncio.subprocess.Process)

    async def stop(self) -> None:
        if not isinstance(self._stdout_task, asyncio.Task):
            raise RuntimeError

        await self._stop()
        self._stdout_task.cancel()

    async def _stop(self, timeout=10.0) -> None:
        if not isinstance(self._process, asyncio.subprocess.Process):
            raise RuntimeError

        if self._process.returncode is not None:
            # Process already terminated
            logger.debug(
                "process %s with pid %s already terminated, returncode %s",
                self._executable,
                self._process.pid,
                self._process.returncode,
            )
            return

        self._process.terminate()
        logger.debug("SIGTERM sent to process %s with pid %s", self._executable, self._process.pid)

        try:
            await asyncio.wait_for(self._process.wait(), timeout=timeout)
        except asyncio.exceptions.TimeoutError:
            logger.debug("Processed did not terminate within %s seconds", timeout)

        if self._process.returncode is None:
            # Indicates that the process is still running, so kill it.
            self._process.kill()
            logger.debug("SIGKILL sent to process %s with pid %s", self._executable, self._process.pid)

    async def _stdout_handler(self):
        logger.debug("start stdout report task")
        while True:
            if self._process.returncode is not None:
                logger.debug("stdout handler: Process (%s) not running", self._process.pid)
                stdout, stderr = await self._process.communicate()
                logger.debug("%s", stdout.decode())
                return

            # An obvious solution here would be to use the communicate() coroutine to wait for output on stdout and
            # stderr. However communicate() relys on read() which blocks until EOF which is not desireabale for a long
            # running service.
            stdout = await self._process.stdout.readline()
            if stdout == b"":
                await asyncio.sleep(0.5)
                continue
            logger.info("lwm2mserver: %s", "\n".join(stdout.decode().split("\n")[:-1]))

    def change_working_directory(self, working_directory: str) -> None:
        self._working_directory = working_directory

    async def await_output(self, pattern, timeout=-1) -> Tuple[int, Union[Match, Exception]]:
        raise NotImplementedError

    async def await_output_once(self, pattern: str, timeout=-1) -> Tuple[bool, Union[Match, Exception]]:
        raise NotImplementedError
