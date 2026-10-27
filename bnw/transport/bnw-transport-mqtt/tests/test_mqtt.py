# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio

import pytest  # type: ignore
from bnw.tfw.component.harness.cloud import AwsIotCloud
from bnw.transport.mqtt.awsiot import AwsMqttClientMqttConnection

pytestmark = pytest.mark.asyncio


async def test_connection(
    cloud: AwsIotCloud, cloud_ca_public_key, cloud_client_private_key, cloud_client_public_key_chain
):
    sut = AwsMqttClientMqttConnection(
        cloud.endpoint, "test", cloud_ca_public_key, cloud_client_public_key_chain, cloud_client_private_key
    )
    await sut.connect()

    topic = "topic"
    payload = b"payload"
    await sut.publish(topic, payload)
    packet = await cloud.published_message(topic)

    assert packet
    assert packet.topic_name == topic
    assert packet.data == payload

    await sut.disconnect()


async def test_subscription(
    cloud: AwsIotCloud, cloud_ca_public_key, cloud_client_private_key, cloud_client_public_key_chain
):
    client_id = "test"
    subscribe_topic = "subscription"
    publish_data = b"data"

    sut = AwsMqttClientMqttConnection(
        cloud.endpoint, client_id, cloud_ca_public_key, cloud_client_public_key_chain, cloud_client_private_key
    )

    # GIVEN connection and active subscription
    async with sut as connection:
        async with connection.subscription(subscribe_topic) as s:
            assert cloud.has_subscription(subscribe_topic, client_id), "subscription not started"

            # WHEN publishing message
            asyncio.ensure_future(cloud.publish_message(subscribe_topic, publish_data))

            # THEN subscription delivers message
            topic, message = await s.get_message()
            assert topic == subscribe_topic
            assert message == publish_data

        assert cloud.has_subscription(subscribe_topic, client_id) is False, "subscription has not been canceled"
