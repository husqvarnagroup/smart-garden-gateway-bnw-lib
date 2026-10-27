# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
import ssl
import sys

import aiohttp
import boto3
import paho.mqtt.client as mqtt
import pytest
import pytest_asyncio
from bnw.tfw.fixtures.cloud import *  # noqa
from bnw.tfw.fixtures.cloud import AwsIotCloud
from bnw.tfw.pytest import wait_for

from bnw.activity.model.device import DeviceName
from bnw.activity.model.gateway import GatewayName
from bnw.protocol import ProtocolEnvelope, ProtocolMessage, ProtocolPayload
from bnw.protocol.message import EventBusProtocolEnvelope, EventBusProtocolMessage

pytestmark = pytest.mark.asyncio


def is_python_3_12():
    return sys.version_info.major == 3 and sys.version_info.minor == 12


@pytest.fixture
def rest_port(find_free_port):
    return find_free_port()


@pytest.fixture
def mqtt_port(find_free_port):
    return find_free_port()


@pytest.fixture
def ws_port(find_free_port):
    return find_free_port()


@pytest_asyncio.fixture
async def sut(cloud_factory, mqtt_port, ws_port, rest_port):
    with cloud_factory("127.0.0.1", mqtt_port, ws_port=ws_port, rest_port=rest_port) as sut:
        assert isinstance(sut, AwsIotCloud)
        yield sut


@pytest.mark.skipif(is_python_3_12(), reason="Test hangs on CI pipeline when running with Python 3.12")
async def test_cloud_rest_api_has_endpoint(sut, rest_port):
    assert sut.rest_endpoint == f"127.0.0.1:{rest_port}"


async def test_cloud_rest_api_get_thing(sut, rest_port):
    async with sut:
        gateway_name = GatewayName.random()
        device_name = DeviceName.random()
        sut.add_gateway(str(gateway_name))
        sut.add_device(str(gateway_name), str(device_name))

        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://{sut.rest_endpoint}/things/{gateway_name}") as resp:
                assert resp.ok

                thing_json = await resp.json()
                assert thing_json["thingId"] == str(gateway_name)
                assert thing_json["thingName"] == str(gateway_name)
                assert thing_json["thingTypeName"] == "gateway"


async def test_cloud_rest_api_get_unknown_thing(sut, rest_port):
    async with sut:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://{sut.rest_endpoint}/things/non-existing") as resp:
                assert not resp.ok
                assert resp.status == 404


async def test_cloud_rest_api_get_thing_shadow(sut, rest_port):
    assert sut.rest_endpoint == f"127.0.0.1:{rest_port}"

    async with sut:
        gateway_name = GatewayName.random()
        device_name = DeviceName.random()
        sut.add_gateway(str(gateway_name))
        sut.add_device(str(gateway_name), str(device_name))

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://{sut.rest_endpoint}/things/{gateway_name}/shadow", params={"name": str(device_name)}
            ) as resp:
                assert resp.ok
                shadow_json = await resp.json()
                assert shadow_json["version"] == 1
                assert shadow_json["state"] == {}
                assert shadow_json["metadata"] == {}
                assert "timestamp" in shadow_json


async def test_cloud_rest_api_get_unknown_thing_shadow(sut, rest_port):
    assert sut.rest_endpoint == f"127.0.0.1:{rest_port}"

    async with sut:
        gateway_name = GatewayName.random()
        sut.add_gateway(str(gateway_name))

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://{sut.rest_endpoint}/things/{gateway_name}/shadow", params={"name": "non-existing"}
            ) as resp:
                assert not resp.ok
                assert resp.status == 404


async def test_cloud_rest_api_get_thing_boto3_compatibility(sut, rest_port):
    session = boto3.Session(
        region_name="eu-west-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )

    iot_data_client = session.client("iot-data", endpoint_url=f"http://127.0.0.1:{rest_port}")
    iot_client = session.client("iot", endpoint_url=f"http://127.0.0.1:{rest_port}")

    async with sut:
        gateway_name = GatewayName.random()
        device_name = DeviceName.random()
        sut.add_gateway(str(gateway_name))
        sut.add_device(str(gateway_name), str(device_name))

        def describe_thing():
            return iot_client.describe_thing(thingName=str(gateway_name))

        thing = await asyncio.get_running_loop().run_in_executor(None, describe_thing)
        assert thing["thingId"] == str(gateway_name)
        assert thing["thingName"] == str(gateway_name)
        assert thing["thingTypeName"] == "gateway"

        def get_thing_shadow():
            return iot_data_client.get_thing_shadow(thingName=str(gateway_name), shadowName=str(device_name))

        thing_shadow = await asyncio.get_running_loop().run_in_executor(None, get_thing_shadow)
        assert "payload" in thing_shadow

        def list_thing_shadows():
            return iot_data_client.list_named_shadows_for_thing(thingName=str(gateway_name))

        named_shadows = await asyncio.get_running_loop().run_in_executor(None, list_thing_shadows)
        assert "results" in named_shadows
        assert named_shadows["results"] == [str(device_name)]

        def update_thing():
            return iot_client.update_thing(
                thingName=str(gateway_name), attributePayload={"attributes": {"string": "string"}, "merge": True}
            )

        update_thing_response = await asyncio.get_running_loop().run_in_executor(None, update_thing)
        assert update_thing_response


async def test_cloud_mqtt_over_ws(sut, ws_port):
    assert sut.websocket_endpoint == f"127.0.0.1:{ws_port}"

    async with sut:
        is_connected = asyncio.Event()

        def on_connect(mqttc, obj, flags, rc):
            is_connected.set()

        # GIVEN: mqtt over websocket client
        mqttc = mqtt.Client(transport="websockets")
        tls_context = ssl.create_default_context()
        tls_context.check_hostname = False
        tls_context.verify_mode = ssl.VerifyMode.CERT_NONE
        mqttc.tls_set_context(tls_context)
        mqttc.enable_logger()
        mqttc.on_connect = on_connect

        # WHEN: connecting
        mqttc.connect_async("127.0.0.1", ws_port)
        mqttc.loop_start()

        # THEN: connection is successful
        try:
            await wait_for(is_connected.wait(), description="connect")
        finally:
            mqttc.loop_stop()


async def test_cloud_disconnect(sut: AwsIotCloud, mqtt_port):
    async with sut:
        client_id = "client-id"
        is_connected = asyncio.Event()
        is_disconnected = asyncio.Event()

        def on_connect(mqttc, obj, flags, rc):
            is_connected.set()

        def on_disconnect(client, userdata, rc):
            is_disconnected.set()

        # GIVEN: connected mqtt client
        mqttc = mqtt.Client(client_id=client_id)
        tls_context = ssl.create_default_context()
        tls_context.check_hostname = False
        tls_context.verify_mode = ssl.VerifyMode.CERT_NONE
        mqttc.tls_set_context(tls_context)
        mqttc.enable_logger()
        mqttc.on_connect = on_connect
        mqttc.on_disconnect = on_disconnect

        mqttc.connect_async("127.0.0.1", mqtt_port)
        mqttc.loop_start()

        try:
            await wait_for(is_connected.wait(), description="connect")

            # WHEN: cloud disconnects client connection
            assert await sut.disconnect_client(client_id)

            # THEN: client disconnected
            await wait_for(is_disconnected.wait(), description="disconnect")
            assert is_disconnected.is_set()
        finally:
            mqttc.loop_stop()


async def test_cloud_delivers_message_published_after_a_dollar_topic(sut: AwsIotCloud, mqtt_port):
    """A client publishing to a `$`-prefixed topic (e.g. AWS IoT basic ingest `$aws/rules/...`) must
    not stop the broker from delivering that client's later messages."""
    async with sut:
        first_topic = "$test/one"
        second_topic = "$test/two"
        first_received = asyncio.Event()
        second_received = asyncio.Event()

        def on_message(mqttc, userdata, msg):
            if msg.topic == first_topic:
                first_received.set()
            elif msg.topic == second_topic:
                second_received.set()

        subscriber_connected = asyncio.Event()
        subscribed = asyncio.Event()

        def on_subscriber_connect(mqttc, obj, flags, rc):
            subscriber_connected.set()

        def on_subscribe(mqttc, userdata, mid, granted_qos):
            subscribed.set()

        tls_context = ssl.create_default_context()
        tls_context.check_hostname = False
        tls_context.verify_mode = ssl.VerifyMode.CERT_NONE

        subscriber = mqtt.Client(client_id="subscriber")
        subscriber.tls_set_context(tls_context)
        subscriber.enable_logger()
        subscriber.on_connect = on_subscriber_connect
        subscriber.on_subscribe = on_subscribe
        subscriber.on_message = on_message
        subscriber.connect_async("127.0.0.1", mqtt_port)
        subscriber.loop_start()

        publisher_connected = asyncio.Event()

        def on_publisher_connect(mqttc, obj, flags, rc):
            publisher_connected.set()

        publisher = mqtt.Client(client_id="publisher")
        publisher.tls_set_context(tls_context)
        publisher.enable_logger()
        publisher.on_connect = on_publisher_connect
        publisher.connect_async("127.0.0.1", mqtt_port)
        publisher.loop_start()

        try:
            await wait_for(subscriber_connected.wait(), description="subscriber connect")
            subscriber.subscribe([(first_topic, 1), (second_topic, 1)])
            await wait_for(subscribed.wait(), description="subscribe")

            await wait_for(publisher_connected.wait(), description="publisher connect")

            # GIVEN: the publisher sends a message to a `$`-prefixed topic
            publisher.publish(first_topic, b"first")
            await wait_for(first_received.wait(), description="first message")

            # WHEN: the same publisher sends a second message, also to a `$`-prefixed topic
            publisher.publish(second_topic, b"second")

            # THEN: the broker still delivers the second message
            await wait_for(second_received.wait(), description="second message")
        finally:
            publisher.loop_stop()
            subscriber.loop_stop()


async def test_cloud_listen_for_telemetry(sut: AwsIotCloud):
    gateway = GatewayName.random()
    device = DeviceName.random()
    path = "device"

    async with sut:
        # GIVEN: listen for telemetry
        async with sut.listen_for_telemetry(gateway, device) as get_telemetry:

            # WHEN: publishing telemetry
            await sut.publish_telemetry(gateway, device, path, ProtocolPayload.from_py_dict(dict(value="str")))

            # THEN: matching telemetry received
            telemetry = await get_telemetry(timeout=1.0)

            assert isinstance(telemetry, ProtocolEnvelope)
            assert len(telemetry.messages) == 1
            assert telemetry.messages[0].payload == ProtocolPayload.from_py_dict(dict(value="str"))

            # AND: can deserialize into custom envelope
            await sut.publish_telemetry(gateway, device, path, ProtocolPayload.from_py_dict(dict(value="test 2")))
            telemetry = await get_telemetry(envelope_class=EventBusProtocolEnvelope)
            assert isinstance(telemetry, EventBusProtocolEnvelope)


async def test_cloud_listen_for_single_telemetry(sut: AwsIotCloud):
    gateway = GatewayName.random()
    device = DeviceName.random()
    path = "device"

    async with sut:
        # GIVEN: listen for single telemetry
        async with sut.listen_for_telemetry_single(gateway, device) as get_telemetry:
            # WHEN: publishing telemetry
            await sut.publish_telemetry(gateway, device, path, ProtocolPayload.from_py_dict(dict(value="str")))

            # THEN: matching telemetry received
            telemetry = await get_telemetry(timeout=1.0)

            assert isinstance(telemetry, ProtocolMessage)
            assert telemetry.payload == ProtocolPayload.from_py_dict(dict(value="str"))

            # AND: can deserialize into custom envelope
            await sut.publish_telemetry(gateway, device, path, ProtocolPayload.from_py_dict(dict(value="test 2")))
            telemetry = await get_telemetry(envelope_class=EventBusProtocolEnvelope)
            assert isinstance(telemetry, EventBusProtocolMessage)
