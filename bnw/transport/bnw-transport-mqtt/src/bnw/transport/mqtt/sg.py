# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
import contextlib
import logging
import random
import string
from typing import AsyncIterator, Optional, Union

from awscrt import io, mqtt  # type: ignore
from awsiot import mqtt_connection_builder  # type: ignore

from . import MqttConnection, MqttSubscription
from .awsiot import (
    AwsMqttClientConnectionBase,
    AwsMqttClientMqttConnection,
    AwsMqttClientMqttWssConnection,
)

logger = logging.getLogger("bnw.transport.mqtt.sg")


class SgIotMqttClientConnection(MqttConnection):
    def __init__(
        self,
        aws_connection: Union[AwsMqttClientMqttConnection, AwsMqttClientMqttWssConnection],
        telemetry_inspector_connection: MqttConnection,
    ):

        super().__init__()

        self._aws_connection = aws_connection
        self._telemetry_inspector_connection = telemetry_inspector_connection

    async def connect(self):
        await asyncio.gather(self._aws_connection.connect(), self._telemetry_inspector_connection.connect())

    async def disconnect(self):
        await asyncio.gather(self._aws_connection.disconnect(), self._telemetry_inspector_connection.disconnect())

    async def publish(self, topic: str, payload: Optional[bytes] = None, qos=mqtt.QoS.AT_LEAST_ONCE) -> None:
        return await self._aws_connection.publish(topic, payload=payload, qos=qos)

    @contextlib.asynccontextmanager
    async def subscription(self, topic: str) -> AsyncIterator[MqttSubscription]:  # type: ignore[override]
        topic_parts = topic.split("/")

        # subscription to status channel (telemetry) that is using basic ingest, we need to use telemetry inspector
        if len(topic_parts) > 2 and topic_parts[1] == "sta":
            async with self._telemetry_inspector_connection.subscription(topic) as s:
                yield s
        else:
            async with self._aws_connection.subscription(topic) as s:
                yield s


class SgTelemetryInspectorConnection(AwsMqttClientConnectionBase):
    def __init__(
        self,
        endpoint: str,
        diam_token: str = None,
        diam_username: str = None,
        diam_password: str = None,
        mqtt_client_id: str = None,
        loop=None,
    ) -> None:

        client_id = (
            mqtt_client_id
            if mqtt_client_id
            else "sg-bnw-lib-" + "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
        )
        default_kwargs = AwsMqttClientConnectionBase._build_default_kwargs(endpoint, client_id)
        if "port" not in default_kwargs:
            default_kwargs["port"] = 8883

        default_kwargs["enable_metrics_collection"] = False

        if diam_username and diam_password:
            default_kwargs["username"] = diam_username
            default_kwargs["password"] = diam_password
        elif diam_token:
            default_kwargs["username"] = diam_token
            default_kwargs["password"] = "token"
        else:
            raise ValueError("Must provide diam_token or diam_username and diam_password")

        def connection_factory(client_bootstrap: io.ClientBootstrap) -> mqtt.Connection:
            return mqtt_connection_builder.new_default_builder(**default_kwargs)

        super(SgTelemetryInspectorConnection, self).__init__(connection_factory, loop=loop)
