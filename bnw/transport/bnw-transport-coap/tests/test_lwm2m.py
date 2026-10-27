# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio

import aiocoap
import pytest  # type: ignore
from aiocoap import Code, Message
from bnw.tfw.device.component.harness import lwm2m
from bnw.transport.coap.lwm2m import ClientConnection, ServerConnection

pytestmark = pytest.mark.asyncio


@pytest.fixture
def free_port(find_free_port):
    return find_free_port()


async def test_connection_custom_handler(free_port):
    port = free_port

    async with ServerConnection(listen_port=port) as server, ClientConnection("client", server_port=port) as client:

        async def server_request_handler(request: aiocoap.Message) -> aiocoap.Message:
            try:
                assert request.code == Code.GET
                assert request.opt.uri_path == ("server-resource", "1")

                return Message(code=Code.CONTENT)
            except AssertionError as e:
                return Message(code=Code.INTERNAL_SERVER_ERROR, payload=str(e).encode())

        server_received_registration_request_received = asyncio.Event()
        registration_path, registration_resource = lwm2m.Server.accept_registration_resource(
            server_received_registration_request_received
        )
        async with server.request_handler(server_request_handler), server.with_resources(
            (registration_path, registration_resource)
        ):

            registration_response = await client.send_registration_request()
            assert registration_response.opt.location_path == ("rd", "0")
            assert server_received_registration_request_received.is_set(), "server did not receive registration request"

            server_resource_request = Message(code=Code.GET)
            server_resource_request.opt.uri_path = ("server-resource", "1")
            server_resource_response = await client.send(server_resource_request)
            assert server_resource_response.code == Code.CONTENT

            client_resource_request_received = asyncio.Event()

            async def handle_read_client_resource(request: aiocoap.Message) -> aiocoap.Message:
                try:
                    assert request.code == Code.GET
                    assert request.opt.uri_path == ("client-resource", "1")
                    client_resource_request_received.set()
                    return Message(code=Code.CONTENT)
                except AssertionError as e:
                    return Message(code=Code.INTERNAL_SERVER_ERROR, payload=str(e).encode())

            async with client.request_handler(handle_read_client_resource):
                client_resource_request = Message(code=Code.GET)
                client_resource_request.opt.uri_path = ("client-resource", "1")
                client_resource_response = await server.send(
                    client_resource_request, remote=registration_resource.get_remote("0")
                )
                assert client_resource_response.code == Code.CONTENT
                assert client_resource_request_received.is_set()
