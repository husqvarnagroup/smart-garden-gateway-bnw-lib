# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from time import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union, cast

import aiocoap
from aiocoap import (
    Code,
    Context,
    Message,
    error,
    interfaces,
    messagemanager,
    numbers,
    resource,
)
from aiocoap.interfaces import Request

from . import CoapConnection

logger = logging.getLogger("bnw.transport.coap.lwm2m")

client_logger = logger.getChild("client")


class ClientConnectionException(Exception):
    pass


class ClientConnectionResponseException(ClientConnectionException):
    response: aiocoap.Message

    def __init__(self, message: str, response: aiocoap.Message):
        super().__init__(message)
        self.response = response


class _CallbackSite(resource.Site):
    def __init__(self):
        super(_CallbackSite, self).__init__()
        self._request_messages = asyncio.Queue()
        self._unhandled_request_lock = asyncio.Lock()
        self._unhandled_request_queue = asyncio.Queue(maxsize=1)
        self._unhandled_request_response_queue = asyncio.Queue(maxsize=1)

    async def render(self, request: aiocoap.Message):
        await self._request_messages.put(request)
        try:
            return await super(_CallbackSite, self).render(request)
        except error.NotFound:
            original_request = request.copy()
            async with self._unhandled_request_lock:
                client_logger.debug(
                    "%s: Received unhandled request: %s",
                    original_request.mid,
                    request.mid,
                )
                await self._unhandled_request_queue.put(original_request)
                client_logger.debug(
                    "%s: Enqueued unhandled request: %s",
                    original_request.mid,
                    request.mid,
                )
                start = time()
                while time() < start + 10.0 or True:
                    client_logger.debug("%s: Waiting for response", original_request.mid)
                    (
                        unhandled_request,
                        response,
                    ) = await self._unhandled_request_response_queue.get()
                    if response is None:
                        client_logger.warning("Unhandled request response was none")
                        break

                    client_logger.debug(
                        "%s: Response received for request: %s: %s",
                        original_request.mid,
                        unhandled_request.mid,
                        response,
                    )
                    if unhandled_request == original_request:
                        client_logger.debug("%s: matching", original_request.mid)
                        return response
                    else:
                        client_logger.debug("%s: not matching", original_request.mid)
                        await asyncio.sleep(0.01)
                        await self._unhandled_request_response_queue.put((unhandled_request, response))

                raise error.NotFound()

    async def add_response(self, unhandled_request: Message, response: Message):
        await self._unhandled_request_response_queue.put((unhandled_request, response))

    async def new_unhandled_request(self) -> Message:
        return await self._unhandled_request_queue.get()

    def get_received_requests(self) -> List[Message]:
        requests = []
        while not self._request_messages.empty():
            requests.append(self._request_messages.get_nowait())

        return requests


class AioCoapConnection(CoapConnection):
    _context: Optional[Context]

    def __init__(self, bind=None, host: str = None, port: int = None):
        self._server_site = _CallbackSite()
        self._request_handler_lock = asyncio.Lock()
        self._context = None
        self._context_kwargs: Dict[str, Any] = {}

        self._host = host
        self._port = port

        if bind is not None:
            self._context_kwargs.update(bind=bind)

    async def connect(self):
        # restrict to udp6 only
        os.environ["AIOCOAP_SERVER_TRANSPORT"] = "udp6"

        # increase timeout so that handler have more time
        numbers.constants.EMPTY_ACK_DELAY = 10.0
        messagemanager.EMPTY_ACK_DELAY = 10.0

        self._context = await Context.create_server_context(self._server_site, **self._context_kwargs)

    async def disconnect(self):
        if self._context:
            try:
                await self._context.shutdown()
            finally:
                self._context = None

    async def ready(self) -> bool:
        return self._context is not None

    async def send(
        self,
        message: Message,
        destination: Optional[str] = None,
        remote: Optional[interfaces.RequestInterface] = None,
        await_response: bool = True,
    ) -> Union[Optional[Message], asyncio.Future]:
        if message.remote is None:
            if remote is not None:
                message.remote = remote
            else:
                message.unresolved_remote = self._get_remote(destination)

        if message.remote is None:
            raise ValueError("Must provide destination or remote")

        assert self._context is not None

        request: Request = self._context.request(message)
        if await_response:
            return await request.response
        else:
            return request.response

    def get_received_requests(self) -> List[Message]:
        return self._server_site.get_received_requests()

    def _get_remote(self, custom_remote: Optional[str] = None):
        if custom_remote:
            return custom_remote

        if self._host is None:
            raise ValueError("Must provide custom remote or set host on connection")

        remote = self._host

        if self._port is not None:
            remote += f":{self._port}"

        return remote

    @asynccontextmanager
    async def request_handler(self, request_handler: Callable[[Message], Awaitable[Message]]):
        async with self._request_handler_lock:
            stop = asyncio.Event()

            async def handler():
                while not stop.is_set():
                    try:
                        request = await self._server_site.new_unhandled_request()
                        if request:
                            response = await request_handler(request)
                            await self._server_site.add_response(request, response)
                    except asyncio.CancelledError:
                        pass

            handler_task = asyncio.create_task(handler())

            try:
                yield self
            finally:
                stop.set()
                handler_task.cancel()
                try:
                    await handler_task
                except asyncio.CancelledError:
                    pass

    @asynccontextmanager
    async def with_resources(self, *resources):
        for path, res in resources:
            self._server_site.add_resource(path, res)

        try:
            yield self
        finally:
            for path, _ in resources:
                self._server_site.remove_resource(path)

    def add_resource(self, path, resource):
        self._server_site.add_resource(path, resource)

    def remove_resource(self, path):
        self._server_site.remove_resource(path)


class ClientConnection(AioCoapConnection):
    def __init__(self, name: str, server_host: str = "127.0.0.1", server_port=numbers.COAP_PORT):
        super().__init__(bind=("::", 0), host=server_host, port=server_port)
        self.name = name

    async def send_bootstrap_request(
        self,
        client_name: Optional[str] = None,
        await_response: bool = True,
        preferred_content_type: Optional[int] = numbers.media_types_rev["application/senml+cbor"],
        **send_kwargs,
    ) -> Union[Message, asyncio.Future]:
        request = Message(code=Code.POST)
        request.opt.uri_path = ("bs",)
        request.opt.uri_query = (f"ep={client_name if client_name is not None else self.name}",)
        if preferred_content_type is not None:
            request.opt.uri_query += (f"pct={preferred_content_type}",)

        response = await self.send(request, await_response=await_response, **send_kwargs)
        if await_response:
            response = cast(Message, response)
            if response is None:
                raise ClientConnectionException("No response from bootstrap request")
            if response.code != Code.CHANGED:
                raise ClientConnectionResponseException(f"Bootstrap request failed with {response.code}", response)

        return response

    async def send_registration_request(
        self,
        lwm2m_version="1.1",
        lifetime: int = 60,
        objects: str = "</3/0>",
        client_name: Optional[str] = None,
        binding: Optional[str] = None,
        content_type: Optional[int] = numbers.media_types_rev["application/senml+cbor"],
        **send_kwargs,
    ) -> Message:
        request = Message(code=Code.POST)
        request.opt.uri_path = ("rd",)

        request.opt.uri_query = (
            f"lwm2m={lwm2m_version}",
            f"ep={client_name if client_name is not None else self.name}",
            f"lt={lifetime}",
        )

        if binding is not None:
            request.opt.uri_query += (f"b={binding}",)

        request.opt.content_format = numbers.media_types_rev["application/link-format"]

        payload_parts = []
        if content_type is not None:
            payload_parts.append(f'</>;rt="oma.lwm2m";ct={content_type}')

        payload_parts.append(objects)

        request.payload = ",".join(payload_parts).encode()

        self._await_response_required(**send_kwargs)
        response = cast(Message, await self.send(request, **send_kwargs))

        if response is None:
            raise ClientConnectionException("No response from registration request")

        # expect ACK
        if response.code != Code.CREATED:
            raise ClientConnectionResponseException(f"Registration failed with {response.code}", response)

        return response

    async def send_data(
        self,
        payload: bytes,
        content_format: Optional[int] = None,
        **send_kwargs,
    ) -> Message:
        request = Message(code=Code.POST)
        request.opt.uri_path = ("dp",)

        if content_format is not None:
            request.opt.content_format = content_format

        request.payload = payload

        self._await_response_required(**send_kwargs)
        response = cast(Message, await self.send(request, **send_kwargs))

        if response is None:
            raise ClientConnectionException("No response from lwm2m send")

        # expect ACK
        if response.code != Code.CHANGED:
            raise ClientConnectionResponseException(f"Lwm2m send failed with {response.code}", response)

        return response

    @classmethod
    def _await_response_required(cls, **send_kwargs):
        if send_kwargs.get("await_response", True) is False:
            raise ValueError("await_response=False not supported")


class ServerConnection(AioCoapConnection):
    def __init__(self, listen_host: str = "127.0.0.1", listen_port=numbers.COAP_PORT):
        super().__init__(bind=(listen_host, listen_port))
