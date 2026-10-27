# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
import binascii
import logging
from contextlib import asynccontextmanager
from typing import Awaitable, Callable, Dict, List, Optional, Tuple, cast

import aiocoap
from aiocoap import Code, Message, interfaces, numbers, resource
from bnw.tfw.component import Component
from bnw.transport.coap.lwm2m import ClientConnection, ServerConnection

from ..harness._lwm2m.encdec import (
    OpaqueDecoder,
    SenmlCborDecoder,
    SenmlCborEncoder,
    TlvDecoder,
)
from ..harness._lwm2m.model import ClientModel

logger = logging.getLogger("bnw.tfw.component.harness.lwm2m")


class RecordingResource(resource.Resource):
    def __init__(self):
        super().__init__()
        self._request_messages = asyncio.Queue()

    async def render(self, request):
        await self._request_messages.put(request)
        return await super().render(request)

    def get_received_requests(self):
        requests = []
        while not self._request_messages.empty():
            requests.append(self._request_messages.get_nowait())

        return requests


class AcceptGetCertificateResource(RecordingResource):
    def __init__(self, certificate: Optional[bytes] = None):
        super().__init__()
        self._certificate = certificate

    async def render_get(self, request):
        if self._certificate is None:
            return Message(code=Code.BAD_REQUEST)
        return _generate_bootstrap_read_certificate_response(self._certificate)


class AcceptPutResource(RecordingResource):
    async def render_put(self, request):
        return aiocoap.Message(code=Code.CHANGED)


class AcceptDeleteResource(RecordingResource):
    async def render_delete(self, request):
        return aiocoap.Message(code=Code.DELETED)


class BootstrapFinishResource(RecordingResource):
    PATH = ("bs",)

    def __init__(self, event: Optional[asyncio.Event] = None):
        super().__init__()
        self._event = event

    async def render_post(self, request):
        if self._event:
            asyncio.get_event_loop().call_soon(self._event.set)

        return aiocoap.Message(code=Code.CHANGED)


def _generate_bootstrap_read_certificate_response(certificate: bytes, path=("0", "0")):
    model = ClientModel(data={path[0]: {path[1]: {"3": binascii.hexlify(certificate).decode()}}})
    model.definition["0"]["resourcedefs"]["3"]["operations"] = "R"
    return SenmlCborEncoder.encode_object_instance(model, path[0], path[1])


class Client(Component):
    _rd_resource: Optional[str]

    def __init__(
        self,
        name: str,
        host: str = "127.0.0.1",
        port=numbers.COAP_PORT,
        bootstrap="[ff02::1]",
        certificate: Optional[bytes] = None,
    ):
        super(Client, self).__init__()
        self._connection = ClientConnection(name, server_host=host, server_port=port)
        self._bootstrap_host = bootstrap
        if port != numbers.COAP_PORT:
            self._bootstrap_host += f":{port}"
        self._certificate_bytes = certificate
        self._logger = logger.getChild(self.__class__.__name__)

    @property
    def name(self) -> str:
        return self._connection.name

    @property
    def port(self) -> Optional[int]:
        return self._connection._port

    async def start(self) -> None:
        await self._connection.connect()

    async def stop(self) -> None:
        await self._connection.disconnect()

    async def ready(self) -> bool:
        return await self._connection.ready()

    async def perform_bootstrap(
        self,
        bootstrap_request_interval: float = 3.0,
        bootstrap_process_timeout: float = 8.0,
    ) -> List[Message]:
        """
        :param bootstrap_request_interval: how much time (seconds) should pass at least in between bootstrap requests
            if they are not acknowledged
        :param bootstrap_process_timeout: how much time (seconds) should be waited for the process to finish until we
            try again with new a new bootstrap request
        :return: a list of messages received during the bootstrap process
        """
        return await self._perform_bootstrap_with_handler(bootstrap_request_interval, bootstrap_process_timeout)

    def _read_certificate_response(self, request: Message) -> Message:
        if self._certificate_bytes is None:
            return Message(code=Code.BAD_REQUEST)

        return _generate_bootstrap_read_certificate_response(self._certificate_bytes, request.opt.uri_path)

    async def _perform_bootstrap_with_handler(
        self, bootstrap_request_interval: float, boostrap_process_timeout: float
    ) -> List[Message]:
        bootstrap_requests = []
        bootstrap_finish = asyncio.Event()

        async def bootstrap_request_handler(request: Message) -> Optional[Message]:
            bootstrap_requests.append(request)

            if request.code == Code.GET and request.opt.uri_path == ("0", "0"):
                return self._read_certificate_response(request)

            if request.code == Code.PUT:
                return Message(code=Code.CHANGED)

            if request.code == Code.DELETE:
                return Message(code=Code.DELETED)

            if request.code == Code.POST and request.opt.uri_path == ("bs",):
                asyncio.get_event_loop().call_soon(bootstrap_finish.set)
                return Message(code=Code.CHANGED)

            self._logger.warning("Unhandled request could not be answered: %s (options: %s)", request, request.opt)
            return None

        async with self._connection.request_handler(bootstrap_request_handler):
            while True:
                try:
                    await asyncio.wait_for(
                        self.send_bootstrap_request(destination=self._bootstrap_host, await_response=True),
                        timeout=bootstrap_request_interval,
                    )
                except asyncio.TimeoutError:
                    if bootstrap_finish.is_set():
                        self._logger.debug("Bootstrap request did timeout, but bootstrap process finished")
                        # previous bootstrap request was probably responded
                        break
                    else:
                        self._logger.debug("Bootstrap request did timeout, retrying once again")
                        continue

                # we have at least received one bootstrap request response, so device is allowed and bootstrap should
                # be in progress
                if not bootstrap_finish.is_set():
                    self._logger.debug("Bootstrap request acknowledged, waiting for bootstrap process to finish")
                    try:
                        await asyncio.wait_for(bootstrap_finish.wait(), timeout=boostrap_process_timeout)
                        break
                    except asyncio.TimeoutError:
                        # for some reason the bootstrap did not finish fully, let's retry
                        self._logger.debug("Bootstrap process did not finish within timeout, retrying the bootstrap")
                        continue
                else:
                    self._logger.debug("Bootstrap request acknowledged, process already did finish in the meantime")
                    break
            self._logger.debug("Bootstrap finished")

        return bootstrap_requests

    async def _perform_bootstrap_with_resource(self) -> List[Message]:
        """
        Less flexible but robuster bootstrap implementation that can deal with concurrent requests
        :return: Received Bootstrap Messages
        """
        accept_get_certificate = AcceptGetCertificateResource(self._certificate_bytes)
        accept_put = AcceptPutResource()
        accept_delete = AcceptDeleteResource()
        bootstrap_finish = asyncio.Event()
        accept_bootstrap_finish = BootstrapFinishResource(bootstrap_finish)
        async with self._connection.with_resources(
            (("0", "0"), accept_get_certificate),
            (("0",), accept_delete),
            (("1",), accept_delete),
            (("0", "1"), accept_put),
            (("1", "1"), accept_put),
            (accept_bootstrap_finish.PATH, accept_bootstrap_finish),
        ):
            await self.send_bootstrap_request(destination=self._bootstrap_host, await_response=False)
            await bootstrap_finish.wait()

        return self._connection.get_received_requests()

    async def send_bootstrap_request(
        self, client_name: Optional[str] = None, destination: Optional[str] = None, await_response: bool = True
    ) -> Message:
        return await self._connection.send_bootstrap_request(
            client_name=client_name,
            destination=destination if destination is not None else self._bootstrap_host,
            await_response=await_response,
        )

    async def send_bootstrap_request_until_response(self, time_between_requests: float = 10.0) -> Message:
        """
        NOTE: sending an additional bootstrap request will reset bootstrap process on the lwm2mserver, so use with care.
        Make sure you leave enough time between requests to allow bootstrap to complete
        """
        while True:
            try:
                await asyncio.wait_for(self.send_bootstrap_request(), timeout=time_between_requests)
                break  # got response, stopping
            except asyncio.TimeoutError:
                pass  # no response yet, sending another
            except asyncio.CancelledError:
                break  # should stop

    async def send_bootstrap_with_certificate(
        self, client_name: Optional[str] = None, destination: Optional[str] = None
    ):
        assert self._certificate_bytes, "certificate must be set"

        certificate_read = asyncio.Event()

        async def bootstrap_request_handler(request: Message) -> Optional[Message]:
            if request.code == Code.GET and request.opt.uri_path == ("0", "0"):
                asyncio.get_event_loop().call_soon(certificate_read.set)
                return self._read_certificate_response(request)

            self._logger.warning("Unhandled request could not be answered: %s (options: %s)", request, request.opt)
            return None

        async with self._connection.request_handler(bootstrap_request_handler):
            await self.send_bootstrap_request(client_name, destination, await_response=False)
            await certificate_read.wait()

    async def send_registration_request(self, **kwargs) -> str:
        response = await self._connection.send_registration_request(**kwargs)
        self._rd_resource = response.opt.location_path[1]
        return cast(str, self._rd_resource)

    async def send_deregistration_request(self, client_id=None) -> bool:
        request = Message(code=Code.DELETE)
        request.opt.uri_path = ("rd", client_id or self._rd_resource)

        result = cast(Message, await self._connection.send(request))

        return result.code == Code.DELETED

    async def send_device_object(self, device_values):
        await self.send_data(("3", "0"), {"3": {"0": device_values}})

    async def send_data(self, path: Tuple[str, ...], data: Dict, **kwargs):
        model = ClientModel(data=data)

        path_len = len(path)
        if path_len == 1:
            msg = SenmlCborEncoder.encode_object(model, path[0])
        elif path_len == 2:
            msg = SenmlCborEncoder.encode_object_instance(model, path[0], path[1])
        elif path_len == 3:
            msg = SenmlCborEncoder.encode_resource(model, path[0], path[1], path[2])
        else:
            raise ValueError(f"Path length {path_len} not supported ")

        await self._connection.send_data(msg.payload, content_format=msg.opt.content_format, **kwargs)

    @asynccontextmanager
    async def with_readonly_data(self, data):
        model = ClientModel(data=data)

        async def read_data_handler(request: Message) -> Optional[Message]:

            if request.code != Code.GET:
                self._logger.warning("Unhandled request could not be answered: %s (options: %s)", request, request.opt)
                return None

            path_len = len(request.opt.uri_path)
            if path_len == 1:
                response = SenmlCborEncoder.encode_object(model, request.opt.uri_path[0])
            elif path_len == 2:
                response = SenmlCborEncoder.encode_object_instance(
                    model, request.opt.uri_path[0], request.opt.uri_path[1]
                )
            elif path_len == 3:
                response = SenmlCborEncoder.encode_resource(
                    model, request.opt.uri_path[0], request.opt.uri_path[1], request.opt.uri_path[2]
                )
            else:
                raise ValueError("Not supporting reading resource instance")

            if request.opt.observe is not None:
                response.opt.observe = request.opt.observe

            return response

        async with self._connection.request_handler(read_data_handler):
            yield self

    @asynccontextmanager
    async def with_device_object(self, device_values):
        async with self.with_readonly_data({"3": {"0": device_values}}):
            yield self

    @asynccontextmanager
    async def accept_write(self, uri_path: Tuple[str, ...], partial: bool = True):
        """

        :param uri_path: accepted path
        :return: asyncio.Queue with (decoded tlv, request) for valid requests
        """
        events: asyncio.Queue = asyncio.Queue()
        model = ClientModel(data={})

        async def write_handler(request: Message) -> Optional[Message]:
            if request.code != (Code.POST if partial else Code.PUT):
                return Message(code=Code.METHOD_NOT_ALLOWED)

            request_uri_path = tuple(request.opt.uri_path)
            if len(request_uri_path) < len(uri_path):
                return Message(code=Code.FORBIDDEN)

            if request_uri_path[0 : len(uri_path)] != uri_path:
                return Message(code=Code.FORBIDDEN)

            try:
                if request.opt.content_format == numbers.media_types_rev["application/octet-stream"]:
                    decoded = OpaqueDecoder.decode(model, request.opt.uri_path, request.payload)
                elif request.opt.content_format == numbers.media_types_rev["application/vnd.oma.lwm2m+tlv"]:
                    decoded = TlvDecoder.decode(model, request.opt.uri_path, request.payload)
                elif request.opt.content_format == numbers.media_types_rev["application/senml+cbor"]:
                    decoded = SenmlCborDecoder.decode(model, request.opt.uri_path, request.payload)
                else:
                    self._logger.info("Unsupported content format %d, assuming TLV", request.opt.content_format)
                    decoded = TlvDecoder.decode(model, request.opt.uri_path, request.payload)
            except Exception:
                self._logger.warning("Failed decoding payload of %s", request, exc_info=True)
                return Message(code=Code.INTERNAL_SERVER_ERROR)

            await events.put((decoded, request))
            return Message(code=Code.CHANGED)

        async with self._connection.request_handler(write_handler):
            yield events

    @asynccontextmanager
    async def accept_execute(self, uri_path: Tuple[str, ...]):
        """

        :param uri_path: accepted path
        :return: asyncio.Queue with (arguments, request) for valid requests
        """
        events: asyncio.Queue = asyncio.Queue()

        async def execute_handler(request: Message) -> Optional[Message]:
            if request.code != Code.POST:
                return Message(code=Code.METHOD_NOT_ALLOWED)

            request_uri_path = tuple(request.opt.uri_path)
            if len(request_uri_path) < len(uri_path):
                return Message(code=Code.FORBIDDEN)

            if request_uri_path[0 : len(uri_path)] != uri_path:
                return Message(code=Code.FORBIDDEN)

            arguments = request.payload

            await events.put((arguments.decode(), request))
            return Message(code=Code.CHANGED)

        async with self._connection.request_handler(execute_handler):
            yield events

    @asynccontextmanager
    async def with_request_handler(self, handler: Callable[[Message], Awaitable[Message]]):
        """

        :param handler:
        :return: asyncio.Queue with each received request
        """
        events: asyncio.Queue = asyncio.Queue()

        async def request_handler(request: Message) -> Optional[Message]:
            await events.put(request)
            return await handler(request)

        async with self._connection.request_handler(request_handler):
            yield events


class AcceptRegistrationResource(RecordingResource):
    PATH = ("rd",)

    def __init__(self, event: Optional[asyncio.Event] = None, registrations: Optional[asyncio.Queue] = None):
        super().__init__()
        self._event = event
        self._registered_clients: Dict[str, interfaces.EndpointAddress] = {}
        self._registrations = registrations
        self._logger = logger.getChild(self.__class__.__name__)

    async def render_post(self, request):
        if request.code == Code.POST and request.opt.uri_path == AcceptRegistrationResource.PATH:
            self._logger.debug("Received non-matching registration request: %s", request)
            return None

        if self._event:
            asyncio.get_event_loop().call_soon(self._event.set)

        if request.opt.content_format != numbers.media_types_rev["application/link-format"]:
            self._logger.debug("Content format %s not as expected, ignoring", request.opt.content_format)

        response = Message(code=Code.CREATED)
        current_client_id = str(len(self._registered_clients))
        response.opt.location_path = AcceptRegistrationResource.PATH + (current_client_id,)

        if self._registrations is not None:
            await self._registrations.put((current_client_id, request.remote))
        self._registered_clients[current_client_id] = request.remote

        return response

    def get_remote(self, client_id: str) -> Optional[interfaces.EndpointAddress]:
        return self._registered_clients.get(client_id, None)


class Server(Component):
    def __init__(self, host: str = "127.0.0.1", port=numbers.COAP_PORT):
        super(Server, self).__init__()
        self._connection = ServerConnection(listen_host=host, listen_port=port)
        self._registration_resource = None

    async def start(self) -> None:
        await self._connection.connect()

    async def stop(self) -> None:
        await self._connection.disconnect()

    async def ready(self) -> bool:
        return await self._connection.ready()

    def accept_registration(self):
        if self._registration_resource is not None:
            return

        path, self._registration_resource = self.__class__.accept_registration_resource()
        self._connection.add_resource(path, self._registration_resource)

    @classmethod
    def accept_registration_resource(
        cls, event: Optional[asyncio.Event] = None
    ) -> Tuple[Tuple, AcceptRegistrationResource]:
        return AcceptRegistrationResource.PATH, AcceptRegistrationResource(event=event)
