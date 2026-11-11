# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
import collections.abc
import contextlib
import json
import logging
import random
import re
import ssl
import string
from asyncio import Queue
from collections import defaultdict
from tempfile import NamedTemporaryFile
from time import time
from typing import (
    Any,
    AsyncGenerator,
    AsyncIterator,
    Callable,
    Dict,
    List,
    Mapping,
    MutableMapping,
    Optional,
    Protocol,
    Tuple,
    Union,
    cast,
)

from aiohttp import web
from aiohttp.test_utils import TestServer
from amqtt import session  # type: ignore
from amqtt.adapters import ReaderAdapter  # type: ignore
from amqtt.broker import Broker  # type: ignore
from amqtt.contexts import BaseContext
from amqtt.events import BrokerEvents
from amqtt.mqtt import ConnectPacket, PublishPacket  # type: ignore

# Patch amqtt so that it accepts connection from cloud adapter
from amqtt.mqtt.constants import QOS_1
from amqtt.mqtt.packet import MQTTPacket
from amqtt.mqtt.protocol.handler import ProtocolHandler
from amqtt.plugins.base import BaseAuthPlugin, BasePlugin
from amqtt.session import ApplicationMessage  # type: ignore
from bnw.transport.mqtt import MqttConnection, MqttSubscription
from mergedeep import merge

from bnw.activity.model.device import DeviceName
from bnw.activity.model.gateway import GatewayName
from bnw.protocol import ProtocolEnvelope, ProtocolMessage, ProtocolPayload
from bnw.protocol.command import EventBusCommandResponse
from bnw.protocol.message import EventBusProtocolEnvelope
from bnw.protocol.status import EventBusDeviceStatusUpdate

from .. import Component

logger = logging.getLogger("bnw.tfw.component.harness.cloud")

_orig_from_stream = ConnectPacket.from_stream


@classmethod  # type: ignore[misc]
async def from_stream(cls, reader: ReaderAdapter, fixed_header=None, variable_header=None):
    packet = await _orig_from_stream(reader, fixed_header=fixed_header, variable_header=variable_header)

    # Set flag and password if not set to prevent connection rejections
    if packet.username_flag and not packet.password_flag:
        packet.password_flag = True
    if packet.password_flag and packet.password is None:
        packet.password = ""

    return packet


ConnectPacket.from_stream = from_stream


# With a recent upstream aMQTT, publishing to a `$`-prefixed topic (e.g. AWS IoT basic ingest
# `$aws/rules/...`) makes the broker's client message loop break and stop processing any further
# messages from that client.
# `_handle_message_delivery` returns `False` for `$` topics just like it does for real protocol
# violations. `ClientDollarBroadcast` still rebroadcasts the message, but every later publish
# from the same client is silently dropped.
#
# Patch `Broker._handle_message_delivery` with a custom function so a `$`-prefixed topic no longer
# breaks the loop, while real violations still do.
_orig_handle_message_delivery = Broker._handle_message_delivery


async def _handle_message_delivery(self, client_session, handler, wait_deliver):
    app_message = wait_deliver.result()
    delivered = await _orig_handle_message_delivery(self, client_session, handler, wait_deliver)
    if not delivered and app_message is not None and app_message.topic.startswith("$"):
        return True
    return delivered


Broker._handle_message_delivery = _handle_message_delivery


class GetTelemetryEnvelopeCall(Protocol):
    async def __call__(self, timeout=10.0, envelope_class=ProtocolEnvelope) -> ProtocolEnvelope: ...


class GetTelemetryMessageCall(Protocol):
    async def __call__(self, timeout=10.0, envelope_class=ProtocolEnvelope) -> ProtocolMessage: ...


class _AllowAllAuthPlugin(BaseAuthPlugin):
    """Authentication plugin that allows all connections without marking sessions as anonymous.

    This differs from amqtt's AnonymousAuthPlugin which sets session.is_anonymous = True,
    causing sessions to be discarded on disconnect and preventing session resumption.
    """

    async def authenticate(self, *, session: session.Session) -> bool:
        return True


class Cloud(Component):
    endpoint: str
    websocket_endpoint: Optional[str]

    _SERVER_NAME = "default"

    def __init__(
        self,
        ip,
        port,
        cert_public,
        cert_private,
        ca_public,
        ws_port=None,
        loop=None,
        additional_amqtt_plugins: List[str] = [],
    ):
        self.endpoint = f"{ip}:{port}"
        self.ip = ip
        self.port = port
        self._cert_public = cert_public
        self._cert_private = cert_private
        self._ca_public = ca_public
        self._ws_port = ws_port
        self._loop = loop or asyncio.get_event_loop()
        self._additional_amqtt_plugins = additional_amqtt_plugins
        self.__broker: Optional[Broker] = None

        if self._ws_port:
            self.websocket_endpoint = f"{self.ip}:{self._ws_port}"

    @property
    def _broker(self) -> Broker:
        assert self.__broker is not None, "Broker not initialized yet"
        return self.__broker

    @_broker.setter
    def _broker(self, value: Broker):
        self.__broker = value

    def _init_broker(self):
        listeners = {
            Cloud._SERVER_NAME: {
                "type": "tcp",
                "bind": f"0.0.0.0:{self.port}",
                "ssl": True,
                "cafile": self._ca_public,
                "certfile": self._cert_public,
                "keyfile": self._cert_private,
                "max_connections": 10,
            },
        }

        if self._ws_port:
            listeners["wss"] = {"type": "ws", "bind": f"0.0.0.0:{self._ws_port}"}

        config = {
            "listeners": listeners,
            "session_expiry_interval": 60,
            "timeout_disconnect_delay": 60,
            "plugins": {
                "bnw.tfw.component.harness.cloud.ClientDollarBroadcast": {},
                "bnw.tfw.component.harness.cloud._AllowAllAuthPlugin": {},
                "amqtt.plugins.sys.broker.BrokerSysPlugin": {},
                "amqtt.plugins.logging_amqtt.EventLoggerPlugin": {},
                "amqtt.plugins.logging_amqtt.PacketLoggerPlugin": {},
                "bnw.tfw.component.harness.cloud.PacketPlugin": {},
                "bnw.tfw.component.harness.cloud.BrokerEventPlugin": {},
            },
        }

        # All plugins need to be provided as config when the broker is constructed
        for plugin in self._additional_amqtt_plugins:
            config["plugins"][plugin] = {}  # no of the additional plugins have a config

        self._broker = Broker(
            config=config,
            loop=self._loop,
        )

        self._init_plugins()
        self._enable_tls_keylog: Optional[str] = None

    def _init_plugins(self):
        """Get the plugin from the broker so that we can use it in our code. It is expected that
        one (and only one) plungin of a given type is registered.

        Subclasses that need access to a registered plugin need to overwrite this method and call the
        method from the base class (`super()._init_plugins()`)"""
        self._packet_plugin: PacketPlugin = self._get_plugin(PacketPlugin)
        self._broker_event_plugin: BrokerEventPlugin = self._get_plugin(BrokerEventPlugin)

    def _get_plugin(self, clazz: type):

        assert self._broker is not None
        p = [p for p in self._broker.plugins_manager.plugins if isinstance(p, clazz)][0]
        return cast(clazz, p)  # type: ignore

    async def start(self):
        self._init_broker()
        await self._broker.start()

        self._setup_ssl()

        if self._enable_tls_keylog is not None:
            self.enable_tls_keylog(self._enable_tls_keylog)

    def _setup_ssl(self):
        """
        This prevents TLS handshake errors when using AWS IoT client:
        "awscrt.exceptions.AwsCrtError: AWS_IO_TLS_ERROR_NEGOTIATION_FAILURE: TLS (SSL) negotiation failed"

        aMQTT uses the default SSL context: https://docs.python.org/3/library/ssl.html#ssl.create_default_context

        which has the following change for Python 3.13:
        "Changed in version 3.13: The context now uses VERIFY_X509_PARTIAL_CHAIN and VERIFY_X509_STRICT in its default
        verify flags."
        """
        assert Cloud._SERVER_NAME in self._broker._servers
        self._broker._servers[Cloud._SERVER_NAME].instance._ssl_context.verify_flags = (
            ssl.VerifyFlags.VERIFY_X509_TRUSTED_FIRST
        )

    async def stop(self):
        await self._broker.shutdown()

    async def ready(self) -> bool:
        if self._broker.transitions.is_started():
            return True

        await self._broker_event_plugin.broker_post_start.wait()
        return True

    def enable_tls_keylog(self, filename: str):
        if Cloud._SERVER_NAME in self._broker._servers:
            self._broker._servers[Cloud._SERVER_NAME].instance._ssl_context.keylog_filename = filename
        else:
            self._enable_tls_keylog = filename

    def get_sessions(self) -> List[session.Session]:
        return list(self._broker.plugins_manager.context.sessions)

    def get_subscriptions(self) -> Mapping[str, List[Tuple[session.Session, int]]]:
        return self._broker._subscriptions

    def has_subscription(self, topic: str, client_id: Optional[str] = None) -> bool:
        topic_subscriptions = self.get_subscriptions().get(topic, None)
        if topic_subscriptions is None:
            return False

        if client_id is None:
            return True
        else:
            session = next(
                (session for session, qos in topic_subscriptions if session.client_id == client_id),
                None,
            )
            return session is not None

    async def disconnect_client(self, client_id: str) -> bool:
        session = self._broker._sessions.get(client_id)
        if session is None:
            return False

        client_session, protocol_handler = session
        await self._broker._delete_session(client_id)
        await self._broker._stop_handler(protocol_handler)
        client_session.transitions.disconnect()
        await self._broker.plugins_manager.fire_event(
            BrokerEvents.CLIENT_DISCONNECTED,
            client_id=client_session.client_id,
        )
        return True

    def _to_regex(self, topic_filter):
        if topic_filter[-1] == "#":
            pattern = topic_filter[0:-1] + ".*"
        else:
            pattern = topic_filter

        pattern = pattern.replace("+", "[^/]+")

        return re.compile(pattern)

    async def published_message(self, topic_filter: str, timeout=10.0) -> PublishPacket:
        pattern = self._to_regex(topic_filter)
        return await self._packet_plugin.wait_for(
            lambda p: isinstance(p, PublishPacket) and pattern.match(p.topic_name),
            timeout=timeout,
        )

    async def published_telemetry(
        self, gateway, device, path="#", timeout=10.0, mqtt_application="sg"
    ) -> ProtocolMessage:
        """
        @deprecated Use listen_for_telemetry for more fine grained control when to start listening and when
        to get messages
        """
        async with self.listen_for_telemetry_single(
            gateway, device, path, mqtt_application=mqtt_application
        ) as get_message:
            return await get_message(timeout)

    @contextlib.asynccontextmanager
    async def listen_for_telemetry(
        self, gateway, device, path="#", mqtt_application="sg"
    ) -> AsyncGenerator[GetTelemetryEnvelopeCall, None]:
        topic = f"{mqtt_application}/sta/{gateway}/{device}"
        if path is not None:
            topic += f"/{path}"

        async with self.get_connection() as connection:
            async with connection.subscription(topic) as sub:

                async def get_telemetry(timeout=10.0, envelope_class=ProtocolEnvelope) -> ProtocolEnvelope:
                    topic, data = await asyncio.wait_for(sub.get_message(), timeout=timeout)
                    return envelope_class.deserialize(data)

                yield get_telemetry

    @contextlib.asynccontextmanager
    async def listen_for_telemetry_single(
        self, gateway, device, path="#", mqtt_application="sg"
    ) -> AsyncGenerator[GetTelemetryMessageCall, None]:
        async with self.listen_for_telemetry(
            gateway, device, path, mqtt_application=mqtt_application
        ) as get_telemetry_multiple:

            async def get_telemetry_single(timeout=10.0, envelope_class=ProtocolEnvelope) -> ProtocolMessage:
                return (await get_telemetry_multiple(timeout, envelope_class)).messages[0]

            yield get_telemetry_single

    async def publish_read(self, gateway: str, device: str, path: str, mqtt_application: str = "sg"):
        data: MutableMapping[str, Any] = {
            "session-id": "".join(random.choices(string.ascii_lowercase + string.digits, k=10)),
            "res-topic": f"{mqtt_application}/get-res/{gateway}/{device}/{path}",
        }

        await self.publish_message(
            f"{mqtt_application}/get/{gateway}/{device}/{path}",
            json.dumps(data).encode(),
        )

        async def get_response(timeout=10.0):
            packet = await self.published_message(data["res-topic"], timeout=timeout)
            response = json.loads(packet.data)
            assert response["session-id"] == response["session-id"]

            return EventBusCommandResponse.decode(response)

        return get_response

    async def publish_write(
        self,
        gateway: str,
        device: str,
        path: str,
        payload: Dict,
        mqtt_application: str = "sg",
    ):
        data: MutableMapping[str, Any] = {
            "session-id": "".join(random.choices(string.ascii_lowercase + string.digits, k=10)),
            "res-topic": f"{mqtt_application}/set-res/{gateway}/{device}/{path}",
            "payload": payload,
        }

        await self.publish_message(
            f"{mqtt_application}/set/{gateway}/{device}/{path}",
            json.dumps(data).encode(),
        )

        async def get_response(timeout=10.0):
            packet = await self.published_message(data["res-topic"], timeout=timeout)
            response = json.loads(packet.data)
            assert response["session-id"] == response["session-id"]

            return EventBusCommandResponse.decode(response)

        return get_response

    async def publish_command(
        self,
        gateway: str,
        device: str,
        path: str,
        payload: dict = None,
        mqtt_application: str = "sg",
    ):
        data: MutableMapping[str, Any] = {
            "session-id": "".join(random.choices(string.ascii_lowercase + string.digits, k=10)),
            "res-topic": f"{mqtt_application}/exc-res/{gateway}/{device}/{path}",
        }

        if payload is not None:
            data["payload"] = payload

        await self.publish_message(
            f"{mqtt_application}/exc/{gateway}/{device}/{path}",
            json.dumps(data).encode(),
        )

        async def get_response(timeout=10.0):
            packet = await self.published_message(data["res-topic"], timeout=timeout)
            response = json.loads(packet.data)
            assert response["session-id"] == response["session-id"]

            return EventBusCommandResponse.decode(response)

        return get_response

    async def publish_message(self, topic: str, data: bytes):
        assert data is not None
        await self._broker.internal_message_broadcast(topic, data)

    async def publish_telemetry(
        self,
        gateway: Union[str, GatewayName],
        device: Union[str, DeviceName],
        path: str,
        payload: ProtocolPayload,
        mqtt_application: str = "sg",
    ):
        topic = f"{mqtt_application}/sta/{gateway}/{device}"
        if path is not None:
            topic += f"/{path}"

        envelope = EventBusProtocolEnvelope([EventBusDeviceStatusUpdate(str(device), str(path), payload)])
        await self.publish_message(topic, envelope.serialize().encode())

    def is_connected(self, cliend_id: str) -> bool:
        return next(
            (s.transitions.is_connected() for s in self.get_sessions() if s.client_id == cliend_id),
            False,
        )

    def get_connection(self) -> MqttConnection:
        return _CloudProducerConnection(self)


class _CloudProducerConnectionSubscription(MqttSubscription, ProtocolHandler):
    def __init__(self, cloud, topic):
        super().__init__(cloud._broker.plugins_manager)
        self._cloud = cloud
        self.topic = str(topic)
        self._session = session.Session()
        self._session.client_id = "".join(random.choices(string.ascii_lowercase, k=20))
        self._messages = asyncio.Queue()

    async def start(self):
        self._session.transitions.connect()
        self._cloud._broker._sessions[self._session.client_id] = (self._session, self)
        await self._cloud._broker.add_subscription((self.topic, QOS_1), self._session)

    async def cancel(self):
        self._session.transitions.disconnect()
        deleted = self._cloud._broker._del_subscription(self.topic, self._session)
        assert deleted == 1

    async def get_message(self) -> Tuple[str, bytes]:
        return await self._messages.get()

    async def mqtt_publish(self, topic, data, qos, retain, ack_timeout=None):
        await self._messages.put((topic, data))


class _CloudProducerConnection(MqttConnection):
    @contextlib.asynccontextmanager
    async def subscription(self, topic: str) -> AsyncIterator[MqttSubscription]:  # type: ignore[override]
        subscription = _CloudProducerConnectionSubscription(self._cloud, topic)
        async with subscription:
            yield subscription

    def __init__(self, cloud: Cloud):
        self._cloud = cloud

    async def publish(self, topic: str, payload: Optional[bytes] = None, qos: int = 1) -> None:
        await self._cloud.publish_message(topic, payload if payload is not None else b"")

    async def connect(self) -> None:
        await self._cloud.ready()

    async def disconnect(self) -> None:
        pass


class AwsIotCloud(Cloud):
    rest_endpoint: Optional[str]
    _rest_api_server: Optional[TestServer]
    _thing_attributes: Dict[str, Dict[str, str]]

    def __init__(self, *args, rest_port=None, **kwargs):
        super().__init__(
            additional_amqtt_plugins=["bnw.tfw.component.harness.cloud.AwsShadowPlugin"],
            *args,
            **kwargs,
        )

        if rest_port:
            self.rest_endpoint = f"{args[0]}:{rest_port}"
            self._rest_api_server = TestServer(
                self._rest_api_application(),
                host="0.0.0.0",
                port=rest_port,
                loop=self._loop,
            )
        else:
            self._rest_api_server = None

        self._thing_attributes = defaultdict(dict)

    def _init_plugins(self):
        super()._init_plugins()
        self._aws_shadow_plugin = self._get_plugin(AwsShadowPlugin)

    @classmethod
    @contextlib.contextmanager
    def factory(
        cls,
        ip: str,
        port: int,
        private_key: bytes,
        public_key: bytes,
        ca_cert: bytes,
        ws_port: int = None,
        rest_port: int = None,
        loop: asyncio.BaseEventLoop = None,
    ):
        with NamedTemporaryFile() as private, NamedTemporaryFile() as public, NamedTemporaryFile() as ca:
            private.write(private_key)
            public.write(public_key)
            ca.write(ca_cert)

            private.flush()
            public.flush()
            ca.flush()

            yield AwsIotCloud(
                ip,
                port,
                public.name,
                private.name,
                ca.name,
                ws_port=ws_port,
                rest_port=rest_port,
                loop=loop,
            )

    async def start(self):
        await super().start()
        if self._rest_api_server:
            await self._rest_api_server.start_server()

    async def stop(self):
        if self._rest_api_server:
            await self._rest_api_server.close()

        await super().stop()

    def _rest_api_application(self) -> web.Application:
        routes = web.RouteTableDef()

        # https://docs.aws.amazon.com/iot/latest/apireference/API_iotdata_GetThingShadow.html
        @routes.get("/things/{thingName}/shadow")
        async def get_shadow(request):
            thing_name = request.match_info["thingName"]
            shadow_name = request.query["name"]

            if not self._aws_shadow_plugin.has_thing(thing_name) or not self._aws_shadow_plugin.has_shadow(
                thing_name, shadow_name
            ):
                return web.json_response(
                    {},
                    status=404,
                    headers={"x-amzn-ErrorType": "ResourceNotFoundException"},
                )

            data = self._aws_shadow_plugin.get_state_document(thing_name, shadow_name)
            return web.json_response(data)

        # https://docs.aws.amazon.com/iot/latest/apireference/API_DescribeThing.html
        @routes.get("/things/{thingName}")
        async def describe_thing(request):
            thing_name = request.match_info["thingName"]

            if not self._aws_shadow_plugin.has_thing(thing_name):
                return web.json_response(
                    {},
                    status=404,
                    headers={"x-amzn-ErrorType": "ResourceNotFoundException"},
                )

            return web.json_response(
                {
                    "attributes": self._thing_attributes[thing_name],
                    "thingArn": "arn",
                    "thingId": thing_name,
                    "thingName": thing_name,
                    "thingTypeName": "gateway",
                    "version": 1,
                }
            )

        # https://docs.aws.amazon.com/iot/latest/apireference/API_UpdateThing.html
        @routes.patch("/things/{thingName}")
        async def update_thing(request):
            thing_name = request.match_info["thingName"]

            if not self._aws_shadow_plugin.has_thing(thing_name):
                return web.json_response(
                    {},
                    status=404,
                    headers={"x-amzn-ErrorType": "ResourceNotFoundException"},
                )

            data = await request.json()

            if "attributePayload" in data:
                merge = data["attributePayload"].get("merge", False)
                if merge:
                    self._thing_attributes[thing_name].update(data["attributePayload"]["attributes"])
                else:
                    self._thing_attributes[thing_name] = data["attributePayload"]["attributes"]

            return web.json_response({})

        # https://docs.aws.amazon.com/iot/latest/apireference/API_iotdata_ListNamedShadowsForThing.html
        @routes.get("/api/things/shadow/ListNamedShadowsForThing/{thingName}")
        async def list_named_shadows_for_thing(request):
            thing_name = request.match_info["thingName"]

            if not self._aws_shadow_plugin.has_thing(thing_name):
                return web.json_response(
                    {},
                    status=404,
                    headers={"x-amzn-ErrorType": "ResourceNotFoundException"},
                )

            shadows = self._aws_shadow_plugin.list_shadows(thing_name)
            return web.json_response({"nextToken": None, "results": shadows, "timestamp": int(time())})

        app = web.Application()
        app.add_routes(routes)

        return app

    def add_gateway(self, gateway_id):
        self._aws_shadow_plugin.add_thing(gateway_id)

    def add_device(self, gateway_id, device_id):
        self._aws_shadow_plugin.add_shadow(gateway_id, device_id)

    async def await_shadow_update(self, gateway, device):
        return await self.published_message(f"$aws/things/{gateway}/shadow/name/{device}/update")


class ClientDollarBroadcast(BasePlugin[BaseContext]):
    """Inspired by: https://github.com/ajmirsky/amqtt/blob/main/samples/broker_dollar_topics.py"""

    async def _broadcast_sys_topic(self, topic_basename: str, data: bytes) -> None:
        """Broadcast a system topic."""

    async def on_broker_message_received(self, *, client_id: str, message: ApplicationMessage) -> None:
        """typically, MQTT-4.7.2-1 blocks clients from sending `$` messages, example how to bypass"""
        if message.topic.startswith("$"):
            await self.context.broadcast_message(message.topic, message.data, message.qos)

            # spec doesn't define if we're required to retain `$` topic messages, so this is optional
            if message.publish_packet and message.publish_packet.retain_flag:
                await self.context.retain_message(message.topic, message.data, message.qos)


class BrokerEventPlugin(BasePlugin[BaseContext]):
    def __init__(self, context):
        self.context = context
        self.broker_post_start = asyncio.Event()

    async def on_broker_post_start(self, *args, **kwargs):
        self.broker_post_start.set()


class PacketPlugin(BasePlugin[BaseContext]):
    def __init__(self, context):
        self.context = context
        self._received_packets = Queue()
        self._sent_packets = Queue()

    async def on_mqtt_packet_received(self, *args, **kwargs):
        packet = kwargs.get("packet")
        # session = kwargs.get("session", None)

        self._received_packets.put_nowait(packet)

    async def on_mqtt_packet_sent(self, *args, **kwargs):
        packet = kwargs.get("packet")
        # session = kwargs.get("session", None)

        self._sent_packets.put_nowait(packet)

    async def wait_for(self, packet_filter: Callable[[MQTTPacket], bool], timeout=10.0):
        start = time()
        remaining_timeout = timeout
        while remaining_timeout > 0.0:
            try:
                packet = await asyncio.wait_for(self._received_packets.get(), timeout=remaining_timeout)
                if packet_filter(packet):
                    return packet
            except asyncio.exceptions.TimeoutError:
                pass
            except Exception:
                logging.warning("Exception during packet filtering", exc_info=True)

            elapsed = time() - start
            remaining_timeout = timeout - elapsed

        raise asyncio.exceptions.TimeoutError()


class AwsShadowPlugin(BasePlugin[BaseContext]):
    _SHADOW_TOPICS_REGEX = re.compile(
        "^\\$aws/things/(?P<thing>[^/]+)/shadow/name/(?P<shadow>[^/]+)/(?P<method>[^/]+)(/(?P<result>[^/]+))?$"
    )

    def __init__(self, context):
        self.context = context

        def nested_dict(n, type):
            if n == 1:
                return defaultdict(type)
            else:
                return defaultdict(lambda: nested_dict(n - 1, type))

        self._shadows = nested_dict(2, dict)

    def has_thing(self, thing_name):
        return thing_name in self._shadows

    def add_thing(self, thing_name):
        return self._shadows[thing_name]

    def has_shadow(self, thing_name, shadow_name):
        return shadow_name in self._shadows[thing_name]

    def add_shadow(self, thing_name, shadow_name):
        return self._shadows[thing_name][shadow_name]

    def get_shadow(self, thing_name, shadow_name):
        return self._shadows[thing_name][shadow_name]

    def list_shadows(self, thing_name):
        return list(self._shadows[thing_name].keys())

    def get_state_document(self, thing_name, shadow_name):
        shadow = self.get_shadow(thing_name, shadow_name)
        document = {
            "state": shadow.get("state", {}),
            "metadata": shadow.get("metadata", {}),
            "timestamp": int(time()),
            "version": shadow.get("version", 1),
        }
        return document

    async def on_mqtt_packet_received(self, *args, **kwargs):
        packet = kwargs.get("packet")

        if not isinstance(packet, PublishPacket):
            return

        match = self._SHADOW_TOPICS_REGEX.match(packet.topic_name)
        if not match:
            return

        groups = match.groupdict()

        def get_shadow():
            return self.get_shadow(groups["thing"], groups["shadow"])

        if groups["method"] == "get":
            data = json.loads(packet.data)
            document = self.get_state_document(groups["thing"], groups["shadow"])
            client_token = data.get("clientToken", None)
            if client_token:
                document["clientToken"] = client_token

            await self.context.broadcast_message(
                packet.topic_name + "/accepted",
                json.dumps(document).encode(),
                packet.qos,
            )

        if groups["method"] == "update":
            data = json.loads(packet.data)

            shadow = get_shadow()

            shadow.update({"state": merge({}, shadow.get("state", {}), data["state"])})
            shadow.update(
                {
                    "metadata": merge(
                        {},
                        shadow.get("metadata", {}),
                        self.compute_timestamp(data["state"]),
                    )
                }
            )
            shadow.update({"version": shadow.get("version", 0) + 1})

            document = self.get_state_document(groups["thing"], groups["shadow"])
            client_token = data.get("clientToken", None)
            if client_token:
                document["clientToken"] = client_token

            await self.context.broadcast_message(
                packet.topic_name + "/accepted",
                json.dumps(document).encode(),
                packet.qos,
            )

        if groups["method"] == "delete":
            data = json.loads(packet.data)

            if groups["shadow"] in self._shadows[groups["thing"]]:
                del self._shadows[groups["thing"]][groups["shadow"]]

            document = {
                "clientToken": data.get("clientToken", None),
            }
            await self.context.broadcast_message(
                packet.topic_name + "/accepted",
                json.dumps(document).encode(),
                packet.qos,
            )

    def compute_timestamp(self, values, now=None):
        now = now or int(time())

        def update(d, timestamp):
            for k, v in d.items():
                if isinstance(v, collections.abc.Mapping):
                    d[k] = update(d.get(k, {}), timestamp)
                else:
                    d[k] = {"timestamp": timestamp}
            return d

        timestamps = merge({}, values)

        return update(timestamps, now)
