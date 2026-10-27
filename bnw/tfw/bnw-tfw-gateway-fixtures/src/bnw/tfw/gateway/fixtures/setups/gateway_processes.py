# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
import os
import uuid
from dataclasses import dataclass
from typing import List, Protocol, Tuple, Type

from bnw.tfw.component import Component
from bnw.tfw.component.harness.cloud import AwsIotCloud, Cloud
from bnw.tfw.component.harness.manufacturing import (
    ManufacturingDeviceCertificateAuthority,
)
from bnw.tfw.device.component.harness.lwm2m import Client as Lwm2mclient
from bnw.tfw.fixtures.setups import BaseTestSetup
from bnw.tfw.pytest import wait_for
from bnw.tfw.pytest.test_setup import define_test_setup

from bnw.activity.inclusion import InclusionProcess, UnixInclusionStrategy
from bnw.activity.model.device import DeviceName
from bnw.activity.model.gateway import GatewayName

from ...component.commander.cloudadapter import Cloudadapter
from ...component.commander.lwm2mserver import Server as Lwm2mserver


class DeviceFactory(Protocol):
    def __call__(
        self, device_name: DeviceName = None, device_ipr_id: str = None, device_certificate: bytes = None
    ) -> Tuple[Lwm2mclient, DeviceName, str, bytes]: ...


@dataclass
class GatewayProcessesTestSetup(BaseTestSetup):
    gateway_name: GatewayName
    device_name: DeviceName

    cloud: Cloud
    cloudadapter: Cloudadapter
    lwm2mserver: Lwm2mserver
    device: Lwm2mclient

    lwm2m_port: int
    mqtt_port: int
    eventbus_location: str
    cloud_tenant: str
    mqtt_application: str

    manufacturing_ca: ManufacturingDeviceCertificateAuthority
    device_factory: DeviceFactory

    async def assert_ready(self):
        readiness = await asyncio.gather(
            self.cloud.ready(), self.cloudadapter.ready(), self.lwm2mserver.ready(), self.device.ready()
        )
        assert all(r is True for r in readiness), "process gateway not fully ready"

        assert self.cloud.is_connected(str(self.gateway_name)), "cloudadapter not connected to cloud"
        return True

    @classmethod
    def dependencies(cls) -> List[Type[Component]]:
        return [Cloudadapter, Lwm2mserver]

    @staticmethod
    def install(module_name: str) -> None:
        pass

    async def include(self, device_name: DeviceName, device: Lwm2mclient):
        if not await device.ready():
            raise ValueError("Lwm2mclient must be started")

        async with (
            InclusionProcess() as process,  # type: ignore[abstract]
            self.lwm2mserver.eventbus_connection() as unix_connection,
        ):
            await process.use_strategy(UnixInclusionStrategy(unix_connection=unix_connection))
            include_task = asyncio.ensure_future(process.include(device_name))
            perform_bootstrap_task = asyncio.ensure_future(device.perform_bootstrap())
            done, pending = await asyncio.wait([include_task, perform_bootstrap_task])
            assert len(pending) == 0, "inclusion not completed"

            # wait for observations
            devices_values = {"2": str(device_name)}
            async with device.with_device_object(devices_values):
                await device.send_registration_request()
                async with self.cloud.listen_for_telemetry_single(
                    self.gateway_name, device_name, path="device/#", mqtt_application=self.mqtt_application
                ) as get_telemetry:
                    await device.send_device_object(devices_values)
                    telemetry = await get_telemetry()
                    assert telemetry


def gateway_processes(setup):
    @setup.private
    def gateway_name():
        return GatewayName.random()

    @setup.private
    def device_name_factory():
        return lambda: DeviceName.random()

    @setup.private
    def device_ipr_id():
        return str(uuid.uuid4())

    @setup.private
    def device_sgtin():
        return DeviceName.random().sgtin

    @setup.private
    def device_name(device_sgtin):
        return DeviceName(device_sgtin)

    @setup.private
    def cloud_tenant(request):
        try:
            return request.getfixturevalue("cloud_tenant_override")
        except LookupError:
            return None

    @setup.private
    def mqtt_application(request, cloud_tenant):
        try:
            return request.getfixturevalue("mqtt_application_override")
        except LookupError:
            if cloud_tenant is not None:
                if cloud_tenant == "sg-live":
                    return "sg"
                else:
                    return cloud_tenant
            else:
                return "sg"

    @setup.private
    def lwm2mclient_name_converter():
        def convert(device_name: DeviceName):
            return "urn:dev:sg:" + str(device_name)

        return convert

    @setup.private
    def lwm2mclient_name(device_name, lwm2mclient_name_converter):
        return lwm2mclient_name_converter(device_name)

    @setup.private
    def manufacturing_ca():
        return ManufacturingDeviceCertificateAuthority()

    @setup.private
    def manufacturing_ca_certificate_bytes(manufacturing_ca):
        return manufacturing_ca.ca_certificate_pem().encode()

    @setup.private
    def device_key_material_factory(manufacturing_ca):
        def factory(device_sgtin, device_ipr_id):
            device_private_key, device_certificate = manufacturing_ca.generate_device_certificate(
                device_ipr_id, device_sgtin
            )
            return device_private_key, device_certificate

        return factory

    @setup.private
    def device_key_material(device_ipr_id, device_sgtin, device_key_material_factory):
        return device_key_material_factory(device_sgtin, device_ipr_id)

    @setup.private
    def device_certificate(device_key_material):
        return device_key_material[1]

    @setup.private
    def lemonbeat_network_key() -> bytes:
        return os.urandom(16)

    @setup.private
    def lwm2m_port(find_free_port):
        return find_free_port()

    @setup.private
    async def lwm2mserver(lwm2m_port, eventbus_location, manufacturing_ca_certificate_bytes, lemonbeat_network_key):
        async with Lwm2mserver(
            "lo",
            verbose=1,
            debug=False,
            port=lwm2m_port,
            eventbus_location=eventbus_location,
            device_ca_bytes=manufacturing_ca_certificate_bytes,
            lemonbeat_key=lemonbeat_network_key,
        ) as server:
            yield server

    @setup.private
    async def cloudadapter(
        gateway_name: GatewayName,
        lwm2mserver,
        eventbus_location,
        cloud: AwsIotCloud,
        cloud_ca_public_key,
        cloud_client_private_key,
        cloud_client_public_key_chain,
        cloud_tenant,
    ):
        # wait for dependencies
        cloud_ready, lwm2mserver_ready = await asyncio.gather(cloud.ready(), lwm2mserver.ready())
        assert cloud_ready
        assert lwm2mserver_ready

        async with Cloudadapter(
            str(gateway_name),
            cloud=cloud.endpoint,
            verbose=1,
            eventbus_location=eventbus_location,
            env={"CLOUDADAPTER_GDS_SGTIN": str(gateway_name.device_name()), "CLOUDADAPTER_GDS_SYSTEMCTL_CMD": "true"},
            cloud_tenant=cloud_tenant,
        ).with_credentials(
            cloud_client_public_key_chain, cloud_client_private_key, cloud_ca_public_key
        ) as cloudadapter:
            yield cloudadapter

    @setup.private
    async def device(lwm2m_port, lwm2mclient_name, device_certificate):
        async with Lwm2mclient(lwm2mclient_name, port=lwm2m_port, certificate=device_certificate) as client:
            yield client

    @setup.public
    async def gateway_processes_test_setup(
        gateway_name,
        device_name,
        cloud,
        cloudadapter,
        lwm2mserver,
        device,
        lwm2m_port,
        eventbus_location,
        cloud_tenant,
        mqtt_application,
        lwm2mclient_name_converter,
        device_name_factory,
        device_key_material_factory,
        manufacturing_ca,
    ):
        def device_factory(
            device_name: DeviceName = None, device_ipr_id: str = None, device_certificate: bytes = None
        ) -> Tuple[Lwm2mclient, DeviceName, str, bytes]:
            name = device_name or device_name_factory()
            ipr_id = device_ipr_id or str(uuid.uuid4())
            certificate = device_certificate or device_key_material_factory(name.sgtin, ipr_id)[1]
            return (
                Lwm2mclient(lwm2mclient_name_converter(name), port=lwm2m_port, certificate=certificate),
                name,
                ipr_id,
                certificate,
            )

        setup = GatewayProcessesTestSetup(
            gateway_name=gateway_name,
            device_name=device_name,
            cloud=cloud,
            cloudadapter=cloudadapter,
            lwm2mserver=lwm2mserver,
            device=device,
            lwm2m_port=lwm2m_port,
            mqtt_port=cloud.port,
            eventbus_location=eventbus_location,
            cloud_tenant=cloud_tenant,
            mqtt_application=mqtt_application,
            manufacturing_ca=manufacturing_ca,
            device_factory=device_factory,
        )

        await wait_for(setup.assert_ready(), timeout=60, description="Startup")
        await wait_for(setup.include(device_name, device), timeout=10, description="Inclusion")

        return setup


GatewayProcessesTestSetup.install = define_test_setup(gateway_processes).install  # type: ignore[assignment]
GatewayProcessesTestSetup.install(__name__)
