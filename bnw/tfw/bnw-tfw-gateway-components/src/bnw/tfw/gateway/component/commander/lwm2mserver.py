# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import absolute_import

import asyncio
import inspect
import json
import logging
import os
import tempfile
import warnings
from collections import ChainMap
from pathlib import Path
from typing import IO, Mapping, Optional

from bnw.tfw.component import commander
from bnw.transport.unix.socket import ConsumerConnection

from .systemd import SystemdUnitNotifyCommander

logger = logging.getLogger("bnw.component.commander.lwm2mserver")


class Server(SystemdUnitNotifyCommander):
    EVENTBUS_SERVICE_NAME = "lwm2mserver"
    EXECUTABLE = "lwm2mserver"

    _key_file: Optional[IO[str]]
    _eventbus_location: Optional[str]
    _ca_cert_file: Optional[IO[bytes]]

    def __init__(
        self,
        interface: str,
        eventbus_location=None,
        server_uri=None,
        port=None,
        debug=False,
        verbose=0,
        lemonbeat_key: Optional[bytes] = None,
        lemonbeat_key_file: Optional[str] = None,
        lemonbeat_dongle_connection: Optional[bool] = None,
        device_ca_file: Optional[str] = None,
        device_ca_bytes: Optional[bytes] = None,
        allow_all: Optional[bool] = None,
        working_directory: str = None,
        lemonbeatd_runtime_directory: str = None,
        env: Mapping[str, str] = None,
        watchdog_interval: float = 1.0,
        shell_output_file: Optional[Path] = None,
    ):
        args = []
        if port is not None:
            args.append(f"-p {port}")

        if debug:
            args.append("-d")

        if verbose:
            args.append("-" + "v" * verbose)

        if lemonbeat_key is None:
            lemonbeat_key = b""

        if lemonbeat_key_file is None:
            self._key_file = tempfile.NamedTemporaryFile(mode="w")
            content = {"network_key": lemonbeat_key.hex()}
            json.dump(content, self._key_file)
            self._key_file.flush()
            lemonbeat_key_file = self._key_file.name
        else:
            self._key_file = None

        args.append("--lb-key-file")
        args.append(lemonbeat_key_file)

        if lemonbeat_dongle_connection:
            args.append("--lemonbeat-dongle-connection")

        if allow_all:
            args.append("--allow-all")

        args.append("--no-load-state")

        if device_ca_bytes and device_ca_file is None:
            self._ca_cert_file = tempfile.NamedTemporaryFile(mode="wb")
            self._ca_cert_file.write(device_ca_bytes)
            self._ca_cert_file.flush()
            device_ca_file = self._ca_cert_file.name
        else:
            self._ca_cert_file = None

        if device_ca_file:
            args.append("--device-ca-file")
            args.append(device_ca_file)

        if lemonbeatd_runtime_directory:
            args.append("--lemonbeatd-runtime-directory")
            args.append(lemonbeatd_runtime_directory)

        args.append(interface)

        self._eventbus_location = eventbus_location
        if eventbus_location is not None:
            args.append(eventbus_location)

        if server_uri:
            args.append("--server-uri")
            args.append(server_uri)

        super().__init__(
            self.EXECUTABLE,
            arguments=args,
            working_directory=working_directory,
            env=env,
            watchdog_interval=watchdog_interval,
            shell_output_file=shell_output_file,
        )

    async def stop(self, **kwargs) -> None:  # type: ignore[override]
        try:
            return await super().stop(**kwargs)
        finally:
            if self._key_file:
                self._key_file.close()
            if self._ca_cert_file:
                self._ca_cert_file.close()

    def evenbus_connection(self) -> ConsumerConnection:
        import warnings

        warnings.warn("use eventbus_connection()", DeprecationWarning)

        return self.eventbus_connection()

    def eventbus_connection(self) -> ConsumerConnection:
        return ConsumerConnection(self.EVENTBUS_SERVICE_NAME, self._eventbus_location, command_response_timeout=20.0)

    @classmethod
    def is_available(cls):
        return commander.is_available(cls.EXECUTABLE)


class ServerNative(Server):
    EXECUTABLE = "lwm2mserver_native"

    def __init__(self, *args, **kwargs):
        warnings.warn(
            "(Lwm2m)ServerNative is being deprecated, use (Lwm2m)Server instead. "
            "Newer component versions will always run component as python interpreted process.",
            DeprecationWarning,
        )
        super().__init__(*args, **kwargs)


class ServerPython(Server):
    def __init__(
        self,
        interface: str,
        eventbus_location=None,
        server_uri=None,
        port=None,
        debug=False,
        lemonbeat_key: Optional[bytes] = None,
        lemonbeat_key_file: Optional[str] = None,
        lemonbeat_dongle_connection: Optional[bool] = None,
        device_ca_file: Optional[str] = None,
        device_ca_bytes: Optional[bytes] = None,
        allow_all: bool = False,
        **kwargs,
    ):

        try:
            from lwm2mserver.lemonbeat import LemonbeatNetworkConfiguration
            from lwm2mserver.lwm2mserver import Server
        except ImportError as e:
            raise RuntimeError("Lwm2mserver python module not available") from e

        if lemonbeat_key is None:
            lemonbeat_key = b""

        if lemonbeat_key_file is None:
            self._key_file = tempfile.NamedTemporaryFile(mode="w")
            content = {"network_key": lemonbeat_key.hex()}
            json.dump(content, self._key_file)
            self._key_file.flush()
            lemonbeat_key_file = self._key_file.name
        else:
            self._key_file = None

        if not os.path.isfile(lemonbeat_key_file):
            raise RuntimeError("Lemonbeat key file not found")

        lemonbeat_configuration = LemonbeatNetworkConfiguration(lemonbeat_key_file)

        if device_ca_file and device_ca_bytes is None:
            device_ca_bytes = Path(device_ca_file).read_bytes()

        server_kwargs = {}

        if device_ca_bytes:
            from lwm2mserver.crypto import DeviceCertificateAuthority

            server_kwargs["device_certificate_authorities"] = [DeviceCertificateAuthority(device_ca_bytes)]

        self._additional_server_kwargs = {}
        sig = inspect.signature(Server.__init__)
        params = [p.name for p in sig.parameters.values() if p.kind == p.POSITIONAL_OR_KEYWORD]
        for kwarg in list(kwargs.keys()):
            if kwarg in params:
                self._additional_server_kwargs[kwarg] = kwargs.pop(kwarg)

        self._eventbus_location = eventbus_location
        self._server_factory = lambda: Server(
            interface=interface,
            eventbus_location=eventbus_location,
            url=server_uri,
            port=port,
            lemonbeat_configuration=lemonbeat_configuration,
            lemonbeat_dongle_connection=lemonbeat_dongle_connection,
            load_state=False,
            allow_all=allow_all,
            debug=debug,
            **ChainMap(server_kwargs, self._additional_server_kwargs),
        )
        self._server: Optional[Server] = None
        self._activate_task: Optional[asyncio.Task] = None

        if len(kwargs) > 0:
            logger.info("Used unsupported arguments %s, they will be ignored", kwargs)

    async def start(self) -> None:
        self._server = self._server_factory()
        self._activate_task = asyncio.create_task(self._server.activate())

    async def ready(self, timeout=10) -> bool:
        if self._activate_task is None:
            return False

        await asyncio.wait_for(self._activate_task, timeout=timeout)
        return True

    async def stop(self, timeout=30.0) -> None:  # type: ignore[override]
        if self._server is not None:
            try:
                await asyncio.wait_for(self._server.deactivate(), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning("Failed stopping lwm2mserver within timeout")

            self._server = None
            self._activate_task = None

        if self._key_file:
            self._key_file.close()

    @classmethod
    def is_available(cls):
        try:
            import lwm2mserver  # noqa: F401

            return True
        except ImportError:
            return False

    def is_alive(self) -> Optional[bool]:
        is_running_method = getattr(self._server, "is_running", None)
        if callable(is_running_method):
            return is_running_method()
        else:
            return None

    @property
    def additional_kwargs(self):
        return dict(self._additional_server_kwargs)
