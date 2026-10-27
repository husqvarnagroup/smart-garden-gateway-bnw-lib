# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
import os

import pytest  # type: ignore
from aiocoap import Code, numbers
from bnw.tfw.component.harness.manufacturing import (
    ManufacturingDeviceCertificateAuthority,
)
from bnw.tfw.device.component.harness._lwm2m.encdec import SenmlCborDecoder
from bnw.tfw.device.component.harness._lwm2m.model import ClientModel
from bnw.tfw.device.component.harness.lwm2m import Client
from bnw.tfw.gateway.component.commander import lwm2mserver

from bnw.activity.transport.unix import UnixOperationConnection
from bnw.protocol import ProtocolOperation, ProtocolPayload
from bnw.protocol.command import EventBusCommandRequest, EventBusCommandResponseEnvelope
from bnw.protocol.entity import EventBusServiceEntity
from bnw.protocol.message import EventBusProtocolMessage

pytestmark = pytest.mark.asyncio


@pytest.fixture
def free_port(find_free_port):
    return find_free_port()


@pytest.fixture
def manufacturing_ca():
    return ManufacturingDeviceCertificateAuthority()


@pytest.fixture
def manufacturing_ca_certificate_bytes(manufacturing_ca):
    return manufacturing_ca.ca_certificate_pem()


@pytest.fixture
def device_ipr_id():
    return "a599c2f6-533e-43d2-b1b1-6d355927cab2"


@pytest.fixture
def device_sgtin():
    return "3018f169003fffc000000002"


@pytest.fixture
def device_key_material(manufacturing_ca, device_ipr_id, device_sgtin):
    return manufacturing_ca.generate_device_certificate(device_ipr_id, device_sgtin)


@pytest.fixture
def device_certificate(device_key_material):
    return device_key_material[1]


@pytest.fixture
def lemonbeat_network_key() -> bytes:
    return os.urandom(16)


@pytest.mark.skipif(not lwm2mserver.Server.is_available(), reason="lwm2mserver not available")
async def test_connection_to_lwm2mserver(
    free_port,
    eventbus_location,
    device_sgtin,
    manufacturing_ca_certificate_bytes: str,
    device_certificate: bytes,
    lemonbeat_network_key: bytes,
    tmp_path,
):
    async with lwm2mserver.ServerPython(
        "lo",
        verbose=2,
        debug=True,
        port=free_port,
        eventbus_location=eventbus_location,
        device_ca_bytes=manufacturing_ca_certificate_bytes.encode(),
        lemonbeat_key=lemonbeat_network_key,
        state_storage_directory=tmp_path,
    ) as server:
        device_urn = f"urn:dev:sg:{device_sgtin}"
        await server.ready()
        await asyncio.sleep(0.1)  # sleep to wait for eventbus to be ready

        async with Client(
            device_urn, port=free_port, certificate=device_certificate
        ) as client, server.eventbus_connection() as eventbus:
            await client.send_bootstrap_with_certificate()
            await asyncio.sleep(0.1)

            allow_inclusion = EventBusCommandRequest(
                ProtocolOperation.EXECUTE,
                EventBusServiceEntity("lwm2mserver", "bootstrap-requests/allow"),
                ProtocolPayload.from_py_dict({"device": device_sgtin}),
            )
            response = await eventbus.perform_command(allow_inclusion.serialize().encode())
            assert response
            allow_inclusion_response = EventBusCommandResponseEnvelope.deserialize(response).messages[0]
            assert allow_inclusion_response.success

            bootstrap_requests = await asyncio.wait_for(client.perform_bootstrap(), 10.0)

            assert (
                next((r for r in bootstrap_requests if r.code == Code.DELETE and r.opt.uri_path == ("0",)), None)
                is not None
            ), "DELETE security missing"
            assert (
                next((r for r in bootstrap_requests if r.code == Code.DELETE and r.opt.uri_path == ("1",)), None)
                is not None
            ), "DELETE server missing"

            write_security = next(
                (r for r in bootstrap_requests if r.code == Code.PUT and r.opt.uri_path == ("0", "1")), None
            )
            assert write_security is not None, "PUT security missing"

            write_server = next(
                (r for r in bootstrap_requests if r.code == Code.PUT and r.opt.uri_path == ("1", "1")), None
            )
            assert write_server, "PUT server missing"

            assert write_security.opt.content_format == numbers.media_types_rev["application/senml+cbor"]
            assert write_server.opt.content_format == numbers.media_types_rev["application/senml+cbor"]

            model = ClientModel()
            security_data = SenmlCborDecoder.decode(model, write_security.opt.uri_path, write_security.payload)
            server_data = SenmlCborDecoder.decode(model, write_server.opt.uri_path, write_server.payload)
            assert security_data is not None
            assert server_data is not None

            client_registration_id = await client.send_registration_request()

            assert client_registration_id.isnumeric()

            async with UnixOperationConnection(eventbus) as unix_op_con:  # type: ignore[abstract]

                def device_filter(m: EventBusProtocolMessage):
                    p = m.canonical_payload()
                    return "device" in p if p is not None else False

                async with unix_op_con.message_subscription(device_filter) as sub:  # type: ignore[arg-type]
                    await client.send_device_object({"2": str(device_sgtin)})
                    message = await sub.get_message()
                    payload = message.canonical_payload()
                    assert payload
                    assert payload["device"]["0"]["serial_number"]["vs"] == str(device_sgtin)
        assert server.is_alive()


@pytest.mark.skipif(not lwm2mserver.Server.is_available(), reason="lwm2mserver not available")
async def test_lwm2mserver_additional_args(
    free_port,
    eventbus_location,
    device_sgtin,
    manufacturing_ca_certificate_bytes: str,
    device_certificate: bytes,
    lemonbeat_network_key: bytes,
    tmp_path,
):
    server = lwm2mserver.ServerPython(
        "lo",
        debug=True,
        port=free_port,
        eventbus_location=eventbus_location,
        device_ca_bytes=manufacturing_ca_certificate_bytes.encode(),
        lemonbeat_key=lemonbeat_network_key,
        state_storage_directory=tmp_path,
    )

    assert "state_storage_directory" in server.additional_kwargs
    async with server:
        pass
