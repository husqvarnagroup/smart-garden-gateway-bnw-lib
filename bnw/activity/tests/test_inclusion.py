# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import pytest_asyncio
import pytest_cases
from bnw.tfw.component.harness.cloud import AwsIotCloud
from bnw.tfw.component.harness.network import PacketCapture
from bnw.tfw.device.component.harness.lwm2m import Client as Lwm2mclient
from bnw.tfw.fixtures.cases.cloud import CasesCloudMqttConnection
from bnw.tfw.fixtures.manufacturing import *  # noqa
from bnw.tfw.gateway.component.commander.lwm2mserver import Server as Lwm2mserver
from bnw.tfw.gateway.component.harness.socket import Capture as UnixCapture
from bnw.tfw.gateway.fixtures.cases.components import (
    parametrize_with_cloudadapter,
    parametrize_with_lwm2mserver,
)
from bnw.tfw.pytest import configure_loggers, wait_for
from bnw.transport.mqtt import MqttConnection
from bnw.transport.unix.socket import ConsumerConnection

from bnw.activity.inclusion import (
    InclusionProcess,
    MqttInclusionStrategy,
    UnixInclusionStrategy,
)
from bnw.activity.interfaces import ActivityStrategy, InclusionActivities
from bnw.activity.model.device import DeviceName
from bnw.activity.model.gateway import GatewayName
from bnw.protocol import ProtocolEnvelope, ProtocolOperation

pytestmark = pytest.mark.asyncio

USE_TEST_STATIC_DATA = False
USE_STANDARD_PORTS = False
USE_STATIC_KEYLOG_FILE = False
CAPTURE_TRAFFIC = False

if CAPTURE_TRAFFIC and "TF_BUILD" in os.environ:
    PacketCapture.use_sudo()

configure_loggers(lwm2mserver=logging.DEBUG, cloudadapter=logging.DEBUG)


@pytest.fixture
def cloud_endpoint_port(find_free_port):
    return 8883 if USE_STANDARD_PORTS else find_free_port()


@pytest.fixture
def cloud_tenant_override():
    return "hickory"


@pytest.fixture
def mqtt_application_override():
    return "hickory"


@pytest_asyncio.fixture(autouse=CAPTURE_TRAFFIC)
async def write_test_name(tmp_path, request):
    with open(tmp_path / "test-name.txt", "w") as f:
        f.write(request.node.name)


@pytest_asyncio.fixture(autouse=CAPTURE_TRAFFIC)
async def capture_network_mqtt(cloud, cloud_endpoint_port, tmp_path):
    if USE_STATIC_KEYLOG_FILE:
        cloud.enable_tls_keylog(Path(__file__).parent.parent / "tls-keylog.txt")
    else:
        cloud.enable_tls_keylog(tmp_path / "tls-keylog.txt")

    if PacketCapture.is_available():
        async with PacketCapture.port("lo", cloud_endpoint_port, tmp_path / f"mqtt-{cloud_endpoint_port}.pcap"):
            await asyncio.sleep(0.1)
            yield True
    else:
        yield False


@pytest_asyncio.fixture(autouse=CAPTURE_TRAFFIC)
async def capture_network_coap(lwm2m_port, tmp_path):
    if PacketCapture.is_available():
        try:
            async with PacketCapture.port("lo", lwm2m_port, tmp_path / f"coap-{lwm2m_port}.pcap"):
                yield True
        except RuntimeError:
            logging.info("Package capture failed", exc_info=True)
            yield False
    else:
        yield False


@pytest.fixture
def gateway_name():
    return GatewayName("38e3a22c-d229-41fe-b568-211bca402560") if USE_TEST_STATIC_DATA else GatewayName.random()


@pytest.fixture
def device_name(device_sgtin):
    return DeviceName(device_sgtin)


@pytest.fixture
def lwm2m_port(find_free_port):
    return 5683 if USE_STANDARD_PORTS else find_free_port()


@pytest.fixture
def device_ipr_id():
    return "ae38b5c4-718f-4500-b57f-5d889505c6b2" if USE_STANDARD_PORTS else str(uuid.uuid4())


@pytest.fixture
def device_sgtin():
    return "3018f169003fffc000000002" if USE_STANDARD_PORTS else DeviceName.random().sgtin


@pytest.fixture
def lwm2mclient_name(device_name):
    return "urn:dev:sg:" + str(device_name)


@pytest.fixture
def device_key_material(manufacturing_device_certificate_authority, device_ipr_id, device_sgtin):
    (
        device_private_key,
        device_certificate,
    ) = manufacturing_device_certificate_authority.generate_device_certificate(device_ipr_id, device_sgtin)
    return device_private_key, device_certificate


@pytest.fixture
def device_certificate(device_key_material):
    return device_key_material[1]


@pytest.fixture
def lemonbeat_network_key() -> bytes:
    return os.urandom(16)


@pytest_asyncio.fixture
async def device(lwm2m_port, lwm2mclient_name, device_certificate):
    async with Lwm2mclient(lwm2mclient_name, port=lwm2m_port, certificate=device_certificate) as client:
        yield client


class CasesServiceUnixConnection:
    @classmethod
    def ids(cls, case_fun):
        return "transport:unix>%s" % pytest_cases.get_case_id(case_fun).replace("_connection", "")

    # TODO pa: Using lwm2mserver cases here, and then parameterize the actual test as well, leads to some
    #          some duplicate cases (it looks like lwm2mserver case here and on test are treated as separate and
    #          cartesian product is built). Might be solved by using pytest-cases union. For now just create
    #          consumer connection ourself (as it won't differ for different lw2mserver cases
    #
    # @pytest_cases.parametrize_with_cases("lwm2mserver", cases=CasesLwm2mserver, idstyle="compact",
    #                                      ids=CasesLwm2mserver.ids)
    # def case_lwm2mserver_connection(self, lwm2mserver):
    #     return lwm2mserver.evenbus_connection()

    def case_lwm2mserver_connection(self, eventbus_location):
        return ConsumerConnection(Lwm2mserver.EVENTBUS_SERVICE_NAME, eventbus_location)


class CasesInclusionStrategy:
    @pytest_cases.parametrize_with_cases(
        "mqtt_connection",
        cases=CasesCloudMqttConnection,
        idstyle="compact",
        ids=CasesCloudMqttConnection.ids,
    )
    def case_mqtt(
        self,
        mqtt_connection: MqttConnection,
        gateway_name: GatewayName,
        mqtt_application_override: str,
    ):
        return MqttInclusionStrategy(mqtt_connection, gateway_name, mqtt_application=mqtt_application_override)

    @pytest_cases.parametrize_with_cases(
        "service_connection",
        cases=CasesServiceUnixConnection,
        idstyle="compact",
        ids=CasesServiceUnixConnection.ids,
    )
    def case_unix(self, service_connection: ConsumerConnection):
        return UnixInclusionStrategy(service_connection)


parametrize_with_inclusion_strategy = pytest_cases.parametrize_with_cases(
    "inclusion_strategy",
    cases=CasesInclusionStrategy,
    ids=lambda f: f"strategy:{pytest_cases.get_case_id(f)}",
)


@asynccontextmanager
async def startup(cloud, cloudadapter, lwm2mserver, tmp_path):
    assert await cloud.ready()
    async with lwm2mserver:
        assert await lwm2mserver.ready()

        if CAPTURE_TRAFFIC and UnixCapture.is_available():
            async with UnixCapture.subscribe(
                lwm2mserver.eventbus_connection().event_path,
                tmp_path / "unix-lwm2mserver-events.txt",
            ):
                async with cloudadapter:
                    assert await cloudadapter.ready()
                    yield
        else:
            async with cloudadapter:
                assert await cloudadapter.ready()
                yield


@parametrize_with_inclusion_strategy
@parametrize_with_cloudadapter
@parametrize_with_lwm2mserver
async def test_integration_setups(
    inclusion_strategy: InclusionActivities,
    cloudadapter,
    lwm2mserver,
    gateway_name: GatewayName,
    cloud: AwsIotCloud,
    device: Lwm2mclient,
    tmp_path,
    mqtt_application_override,
):
    # GIVEN: integration test setup
    async with startup(cloud, cloudadapter, lwm2mserver, tmp_path):
        assert cloud.is_connected(str(gateway_name))
        async with cloud.get_connection() as connection:
            gw_device_name = "+" if gateway_name.sgtin is None else gateway_name.device_name()
            topic = f"{mqtt_application_override}/sta/{gateway_name}/{gw_device_name}/includable_device/+"
            async with connection.subscription(topic) as sub:
                # WHEN: device is started
                await device.send_bootstrap_with_certificate()

                # THEN: includabe device is published
                await wait_for(sub.get_message(), timeout=5)


@parametrize_with_inclusion_strategy
@parametrize_with_cloudadapter
@parametrize_with_lwm2mserver
async def test_inclusion(
    inclusion_strategy: ActivityStrategy,
    cloudadapter,
    lwm2mserver,
    gateway_name: GatewayName,
    device_name: DeviceName,
    cloud: AwsIotCloud,
    device: Lwm2mclient,
    tmp_path,
    mqtt_application_override,
):

    async with startup(cloud, cloudadapter, lwm2mserver, tmp_path):
        assert cloud.is_connected(str(gateway_name))

        async with InclusionProcess(inclusion_strategy) as process:  # type: ignore[abstract,attr-defined]
            async with cloud.get_connection() as connection:
                gw_device_name = "+" if gateway_name.sgtin is None else gateway_name.device_name()
                topic = f"{mqtt_application_override}/sta/{gateway_name}/{gw_device_name}/includable_device/+"
                async with connection.subscription(topic) as sub:
                    await device.send_bootstrap_with_certificate()
                    await wait_for(sub.get_message(), timeout=5, description="Includable Device")

            # WHEN
            await wait_for(process.include(device_name), timeout=5, description="Inclusion")

            # THEN
            await wait_for(device.perform_bootstrap(), timeout=1, description="Perform bootstrap")

            devices_values = {"2": str(device_name)}
            async with device.with_device_object(devices_values):
                await wait_for(
                    device.send_registration_request(),
                    1,
                    description="Send registration request",
                )
                async with lwm2mserver.eventbus_connection() as conn, cloud.listen_for_telemetry_single(
                    gateway_name,
                    device_name,
                    path="device/#",
                    mqtt_application=mqtt_application_override,
                ) as get_cloud_telemetry:
                    await device.send_device_object(devices_values)

                    async def read_eventbus():
                        return await wait_for(conn.receive_event(), description="Read eventbus", timeout=1)

                    max_events = 10
                    while max_events > 0:
                        event = ProtocolEnvelope.deserialize(await read_eventbus()).messages[0]
                        max_events -= 1

                        if "service" in event.entity:
                            continue

                        if event.operation != ProtocolOperation.UPDATE:
                            continue

                        assert "device" in event.entity
                        assert event.entity["device"] == str(device_name)

                        if not event.entity["path"].startswith("device"):
                            continue
                        else:
                            break

                    assert event.operation == ProtocolOperation.UPDATE
                    assert event.entity["path"] == "device/0"

                    message = await get_cloud_telemetry()
                    assert message.payload is not None
                    assert message.entity is not None
                    assert message.entity["path"] == "device/0"
                    values = message.payload.protocol_values(message.payload)
                    assert values["serial_number"] == str(device_name)
