# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import absolute_import

import asyncio
import inspect
import logging
import os
import tempfile
import warnings
from typing import Mapping, Optional

from bnw.tfw.component import commander

from .systemd import SystemdUnitNotifyCommander

logger = logging.getLogger("bnw.component.commander.lwm2mserver")


class Cloudadapter(SystemdUnitNotifyCommander):
    EXECUTABLE = "cloudadapter"

    _tempdir: Optional[tempfile.TemporaryDirectory]

    def __init__(
        self,
        gatewayid: str,
        cloud: str = None,
        eventbus_location: str = None,
        debug: bool = False,
        verbose: int = 0,
        working_directory: str = None,
        env: Mapping[str, str] = None,
        cloud_tenant: str = None,
    ):
        args = []

        args.append(f"--gatewayid={gatewayid}")

        if cloud_tenant is not None:
            args.append(f"--tenant={cloud_tenant}")

        if cloud is not None:
            args.append(f"--cloud={cloud}")

        if eventbus_location is not None:
            args.append(f"--path={eventbus_location}")

        if debug:
            args.append("-d")

        if verbose:
            args.append("-" + "v" * verbose)

        super().__init__(self.EXECUTABLE, arguments=args, working_directory=working_directory, env=env)

        self._tempdir = None
        self._gatewayid = gatewayid

    async def stop(self, **kwargs) -> None:  # type: ignore[override]
        try:
            return await super().stop(**kwargs)
        finally:
            if self._tempdir:
                self._tempdir.cleanup()

    def with_credentials(self, public: bytes, private: bytes, ca: bytes, temporary_directory=None) -> "Cloudadapter":
        if temporary_directory is None:
            self._tempdir = tempfile.TemporaryDirectory()
            temporary_directory = str(self._tempdir.name)

        self.change_working_directory(temporary_directory)

        credentials_directory = f"{temporary_directory}/credentials"
        if not os.path.exists(credentials_directory):
            os.mkdir(credentials_directory)

        with open(f"{credentials_directory}/{self._gatewayid}.cert.pem", "wb") as f:
            f.write(public)

        with open(f"{credentials_directory}/{self._gatewayid}.private.pem", "wb") as f:
            f.write(private)

        with open(f"{credentials_directory}/aws-root-ca.crt", "wb") as f:
            f.write(ca)

        return self

    @classmethod
    def is_available(cls):
        return commander.is_available(cls.EXECUTABLE)


class CloudadapterNative(Cloudadapter):
    EXECUTABLE = "cloudadapter_native"

    def __init__(self, *args, **kwargs):
        warnings.warn(
            "CloudadapterNative is being deprecated, use Cloudadapter instead. "
            "Newer component versions will always run component as python interpreted process.",
            DeprecationWarning,
        )
        super().__init__(*args, **kwargs)


class CloudadapterPython(Cloudadapter):
    def __init__(
        self,
        gatewayid: str,
        cloud: str = None,
        eventbus_location: str = None,
        debug: bool = False,
        cloud_tenant: str = None,
        **kwargs,
    ):

        try:
            import cloudadapter
        except ImportError as e:
            raise RuntimeError("Cloudadapter python module not available") from e
        self._gatewayid = gatewayid
        self._cloud = cloud
        self._cloud_tenant = cloud_tenant
        self._eventbus_location = eventbus_location
        self._debug = debug

        self._private: Optional[bytes] = None
        self._public: Optional[bytes] = None
        self._ca: Optional[bytes] = None
        self._gateway: Optional[cloudadapter.Gateway] = None
        self._activate_task: Optional[asyncio.Task] = None

        self._cloudadpater_kwargs = {}
        sig = inspect.signature(cloudadapter.Gateway.__init__)
        params = [p.name for p in sig.parameters.values() if p.kind == p.POSITIONAL_OR_KEYWORD]
        for kwarg in list(kwargs.keys()):
            if kwarg in params:
                self._cloudadpater_kwargs[kwarg] = kwargs.pop(kwarg)

        if len(kwargs) > 0:
            logger.info("Used unsupported arguments %s, they will be ignored", kwargs)

    async def start(self) -> None:
        import cloudadapter

        credentials = cloudadapter.Credentials(self._public, self._private, self._ca)

        self._gateway = cloudadapter.Gateway(
            self._gatewayid,
            self._eventbus_location,
            self._cloud,
            credentials,
            cloud_tenant=self._cloud_tenant,
            debug=self._debug,
            **self._cloudadpater_kwargs,
        )
        self._activate_task = asyncio.create_task(self._gateway.activate())

    async def ready(self, timeout=10) -> bool:
        if self._activate_task is None:
            return False

        await asyncio.wait_for(self._activate_task, timeout=timeout)
        return True

    async def stop(self, timeout=30.0) -> None:  # type: ignore[override]
        if self._gateway is not None:
            try:
                await asyncio.wait_for(self._gateway.deactivate(), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning("Failed stopping cloudadapter within timeout")
            self._gateway = None
            self._activate_task = None

    def with_credentials(
        self, public: bytes, private: bytes, ca: bytes, temporary_directory=None
    ) -> "CloudadapterPython":
        self._public = public
        self._private = private
        self._ca = ca
        return self

    @property
    def additional_kwargs(self):
        return dict(self._cloudadpater_kwargs)

    @classmethod
    def is_available(cls):
        try:
            import cloudadapter  # noqa: F401

            return True
        except ImportError:
            return False
