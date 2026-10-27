# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
import contextlib
import datetime
import functools
import logging
from typing import (
    Any,
    AsyncIterator,
    Callable,
    ClassVar,
    Dict,
    Optional,
    Protocol,
    Tuple,
)

from awscrt import auth, io, mqtt  # type: ignore
from awsiot import mqtt_connection_builder  # type: ignore
from botocore.credentials import RefreshableCredentials

from . import MqttConnection, MqttSubscription

logger = logging.getLogger("bnw.transport.mqtt.awsiot")


class AwsMqttClientConnectionBase(MqttConnection):
    _MQTT_CONNECTION_BUILDER_DEFAULT_ARGS: ClassVar[Dict[str, Any]] = dict(clean_session=False, keep_alive_secs=6)
    _connection: mqtt.Connection
    _loop: asyncio.AbstractEventLoop
    _connected: bool

    def __init__(
        self, connection_factory: Callable[[io.ClientBootstrap], mqtt.Connection], loop: asyncio.BaseEventLoop = None
    ):
        event_loop_group = io.EventLoopGroup(1)
        host_resolver = io.DefaultHostResolver(event_loop_group)
        client_bootstrap = io.ClientBootstrap(event_loop_group, host_resolver)

        self._connection = connection_factory(client_bootstrap)
        self._loop = loop if loop else asyncio.get_event_loop()
        self._connected = False

    @classmethod
    def _build_default_kwargs(cls, endpoint: str, client_id: str):
        kwargs: Dict[str, Any] = {}
        if ":" in endpoint:
            host, port = endpoint.split(":", 2)
            kwargs["port"] = int(port)
        else:
            host = endpoint

        kwargs["endpoint"] = host
        kwargs["client_id"] = client_id
        kwargs.update(AwsMqttClientConnectionBase._MQTT_CONNECTION_BUILDER_DEFAULT_ARGS)

        return kwargs

    async def connect(self):
        await asyncio.wrap_future(self._connection.connect())
        self._connected = True

    async def disconnect(self):
        await asyncio.wrap_future(self._connection.disconnect())
        self._connected = False

    async def publish(self, topic: str, payload: Optional[bytes] = None, qos=mqtt.QoS.AT_LEAST_ONCE) -> None:
        assert self._connected
        future, packed_id = self._connection.publish(topic, payload if payload is not None else b"", qos)
        await asyncio.wrap_future(future)

    @contextlib.asynccontextmanager
    async def subscription(self, topic: str) -> AsyncIterator[MqttSubscription]:  # type: ignore[override]
        assert self._connected

        subscription = AwsMqttClientSubscription(self._connection, topic)
        await subscription.start()
        try:
            yield subscription
        finally:
            await subscription.cancel()


class AwsMqttClientSubscription(MqttSubscription):
    def __init__(self, connection, topic, qos=1):
        self.topic = topic
        self.qos = qos
        self._subscribe = functools.partial(
            connection.subscribe, topic=self.topic, qos=mqtt.QoS.AT_LEAST_ONCE, callback=self._callback_wrapper
        )
        self._unsubscribe = functools.partial(connection.unsubscribe, topic=topic)
        self._messages = asyncio.Queue()
        self._subscribed = False
        self._loop = asyncio.get_event_loop()

    async def start(self) -> None:
        logger.debug("Subscribing to %s...", self.topic)
        sub_future, _ = self._subscribe()
        res = await asyncio.wrap_future(sub_future)
        assert self.topic == res["topic"], "subscribed topic does not match expected topic"
        self._subscribed = True
        logger.debug("Subscribed to %s", self.topic)

    async def cancel(self) -> None:
        if self._subscribed:
            logger.debug("Canceling subscription to %s...", self.topic)
            unsub_future, _ = self._unsubscribe()
            try:
                await asyncio.wait_for(asyncio.wrap_future(unsub_future), 2.0)
            except asyncio.exceptions.TimeoutError:
                logger.warning(
                    "Timeout while unsubscribing from %s. Ignoring and assume unsubscribed", self.topic, exc_info=True
                )
            except asyncio.exceptions.CancelledError:
                logger.debug(
                    "Cancelled while unsubscribing from %s. Ignoring and assume unsubscribed", self.topic, exc_info=True
                )
            self._subscribed = False
            logger.debug("Subscription to %s canceled", self.topic)

    async def get_message(self) -> Tuple[str, bytes]:
        return await self._messages.get()

    async def _on_message(self, topic: str, payload: bytes):
        await self._messages.put((topic, payload))

    def _callback_wrapper(self, topic: str, payload: bytes):
        asyncio.run_coroutine_threadsafe(self._on_message(topic, payload), self._loop)


class AwsMqttClientMqttConnection(AwsMqttClientConnectionBase):
    def __init__(self, endpoint: str, client_id: str, ca: bytes, cert: bytes, key: bytes, loop=None) -> None:
        default_kwargs = AwsMqttClientConnectionBase._build_default_kwargs(endpoint, client_id)

        def connection_factory(client_bootstrap: io.ClientBootstrap) -> mqtt.Connection:
            return mqtt_connection_builder.mtls_from_bytes(
                client_bootstrap=client_bootstrap,
                cert_bytes=cert,
                pri_key_bytes=key,
                ca_bytes=ca,
                **default_kwargs,
            )

        super(AwsMqttClientMqttConnection, self).__init__(connection_factory, loop=loop)


class AwsCredentialsProviderFactory(Protocol):
    def __call__(
        self, client_bootstrap: io.ClientBootstrap, profile_name: str, region: str
    ) -> auth.AwsCredentialsProvider:
        pass


class AwsMqttClientMqttWssConnection(AwsMqttClientConnectionBase):
    def __init__(
        self,
        endpoint: str,
        client_id: str,
        profile_name="sg-lab",
        signing_region="eu-west-1",
        credentials_provider_factory: Optional[AwsCredentialsProviderFactory] = None,
        loop=None,
    ):

        default_kwargs = AwsMqttClientConnectionBase._build_default_kwargs(endpoint, client_id)

        def connection_factory(client_bootstrap: io.ClientBootstrap) -> mqtt.Connection:
            if credentials_provider_factory is not None and callable(credentials_provider_factory):
                credentials_provider = credentials_provider_factory(client_bootstrap, profile_name, signing_region)
            else:
                credentials_provider = self._default_credentials_provider_factory(
                    client_bootstrap, profile_name, signing_region
                )

            return mqtt_connection_builder.websockets_with_default_aws_signing(
                client_bootstrap=client_bootstrap,
                region=signing_region,
                credentials_provider=credentials_provider,
                **default_kwargs,
            )

        super(AwsMqttClientMqttWssConnection, self).__init__(connection_factory, loop=loop)

    @classmethod
    def _default_credentials_provider_factory(
        cls, client_bootstrap: io.ClientBootstrap, profile_name: str, region: str
    ):
        profile_provider = auth.AwsCredentialsProvider.new_profile(client_bootstrap, profile_name=profile_name)
        # awscrt currently does not support SSO (https://github.com/awslabs/aws-crt-python/issues/335),
        # so we use boto3 based provider as fallback:
        fallback_provider = cls._boto3_credentials_provider_factory(profile_name, region)

        # keep default profile_provider in chain in case awscrt supports SSO in the future
        return auth.AwsCredentialsProvider.new_chain([profile_provider, fallback_provider])

    @classmethod
    def _boto3_credentials_provider_factory(cls, profile_name: str, region: str):
        # We don't initialize session already here so that we don't need to import boto3 when
        # credential provider would never be used
        session = None

        def boto3_get_credentials():
            try:
                import boto3
            except ImportError:
                logger.error("Need boto3 dependency for fetching AWS credentials, requests will fail.")
                # awscrt does not properly handle exceptions, so we return invalid credentials,
                # otherwise awscrt hangs indefinitely
                return auth.AwsCredentials("MISSING BOTO3 DEPENDENCY", "INVALID", "INVALID", expiration=None)

            nonlocal session
            session = session or boto3.Session(profile_name=profile_name, region_name=region)

            credentials = session.get_credentials()

            if isinstance(credentials, RefreshableCredentials):
                # ensure credentials are fetched / refreshed, so that expiry time is known
                frozen_credentials = credentials.get_frozen_credentials()

                expiration = None
                if hasattr(credentials, "_expiry_time"):
                    expiration = getattr(credentials, "_expiry_time")

                if expiration is None:
                    # Fallback to short expiration time as we don't know when credentials will expire
                    expiration = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=5)

                return auth.AwsCredentials(
                    frozen_credentials.access_key,
                    frozen_credentials.secret_key,
                    frozen_credentials.token,
                    expiration=expiration,
                )
            else:
                return auth.AwsCredentials(
                    credentials.access_key, credentials.secret_key, credentials.token, expiration=None
                )

        return auth.AwsCredentialsProvider.new_delegate(boto3_get_credentials)
