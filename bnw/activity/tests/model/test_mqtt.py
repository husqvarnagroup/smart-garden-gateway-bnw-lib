# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

from typing import Dict, List, Mapping, cast

import pytest
from bnw.tfw.component.harness.cloud import AwsIotCloud
from bnw.tfw.gateway.component.harness.gateway import RequestHandingService
from bnw.tfw.gateway.fixtures.cases.components import parametrize_with_cloudadapter

from bnw.activity.model.gateway import GatewayName
from bnw.activity.model.mqtt import MqttCommandRequest, MqttOperation, MqttTopic
from bnw.activity.transport.mqtt import MqttOperationConnection
from bnw.protocol import (
    ProtocolMessage,
    ProtocolMetadata,
    ProtocolOperation,
    ProtocolPayload,
    ProtocolPayloadValuePy,
)
from bnw.protocol.command import EventBusCommandRequest, EventBusCommandResponse
from bnw.protocol.entity import EventBusServiceEntity

pytestmark = pytest.mark.asyncio


@pytest.fixture
def gateway_name():
    return GatewayName.random()


@parametrize_with_cloudadapter(has_tag="python")
async def test_mqtt_protocol_command(cloudadapter, cloud: AwsIotCloud, gateway_name, eventbus_location):
    async def command_impl(request: EventBusCommandRequest) -> EventBusCommandResponse:
        if request.operation == ProtocolOperation.DELETE:
            return EventBusCommandResponse(True)
        else:
            return EventBusCommandResponse(False)

    async with RequestHandingService("lwm2mserver", location=eventbus_location) as service, service.request_handler(
        command_impl
    ):

        async with cloudadapter:
            await cloudadapter.ready()

            async with MqttOperationConnection(cloud.get_connection()) as mqtt_connection:  # type: ignore[abstract]

                topic = MqttTopic(
                    application="sg",
                    operation=MqttOperation.COMMAND,
                    gateway=gateway_name,
                    subtopic="protocol",
                )

                m1 = ProtocolMessage(
                    operation=ProtocolOperation.DELETE,
                    entity=EventBusServiceEntity(service.name, "path/1"),
                )
                m2 = ProtocolMessage(
                    operation=ProtocolOperation.WRITE,
                    entity=EventBusServiceEntity(service.name, "path/1"),
                )

                request = MqttCommandRequest(payload=[m1, m2], response_topic=topic.response_topic())
                result = await mqtt_connection.perform_operation(topic, request)
                assert isinstance(result.payload, list)
                payload = cast(List[Dict], result.payload)

                responses = [EventBusCommandResponse.decode(r) for r in payload]
                assert responses[0].success is True
                assert responses[1].success is False


@parametrize_with_cloudadapter(has_tag="python")
async def test_mqtt_service_command_single(cloudadapter, cloud: AwsIotCloud, gateway_name, eventbus_location):
    payload_data: Mapping[str, ProtocolPayloadValuePy] = dict(string="hello", number=1)

    async def command_impl(request: EventBusCommandRequest) -> EventBusCommandResponse:
        if request.operation == ProtocolOperation.READ:
            return EventBusCommandResponse(
                True,
                payload=ProtocolPayload.from_py_dict(payload_data),
                metadata=ProtocolMetadata(source="lwm2mserver"),
            )
        else:
            return EventBusCommandResponse(False, metadata=ProtocolMetadata(error_source="lwm2mserver"))

    async with RequestHandingService("lwm2mserver", location=eventbus_location) as service, service.request_handler(
        command_impl
    ):
        async with cloudadapter:
            await cloudadapter.ready()

            async with MqttOperationConnection(cloud.get_connection()) as mqtt_connection:  # type: ignore[abstract]

                topic = MqttTopic(
                    application="sg",
                    operation=MqttOperation.COMMAND,
                    gateway=gateway_name,
                    subtopic=service.name,
                )
                message = ProtocolMessage(
                    operation=ProtocolOperation.READ,
                    entity=EventBusServiceEntity(service.name, "path/1"),
                )

                request = MqttCommandRequest(payload=message, response_topic=topic.response_topic())
                response = await mqtt_connection.perform_operation(topic, request)

                assert response.success is True
                assert response.metadata
                assert response.metadata["source"] == service.name
                assert isinstance(response.payload, ProtocolPayload)
                assert dict(response.payload.protocol_values()) == payload_data


@parametrize_with_cloudadapter(has_tag="python")
async def test_mqtt_service_command_multiple(cloudadapter, cloud: AwsIotCloud, gateway_name, eventbus_location):
    payload_data: Mapping[str, ProtocolPayloadValuePy] = dict(string="hello", number=1)

    async def command_impl(request: EventBusCommandRequest) -> EventBusCommandResponse:
        if request.operation == ProtocolOperation.READ:
            return EventBusCommandResponse(True, payload=ProtocolPayload.from_py_dict(payload_data))
        else:
            return EventBusCommandResponse(False)

    async with RequestHandingService("lwm2mserver", location=eventbus_location) as service, service.request_handler(
        command_impl
    ):
        async with cloudadapter:
            await cloudadapter.ready()

            async with MqttOperationConnection(cloud.get_connection()) as mqtt_connection:  # type: ignore[abstract]
                topic = MqttTopic(
                    application="sg",
                    operation=MqttOperation.COMMAND,
                    gateway=gateway_name,
                    subtopic="protocol",
                )

                m1 = ProtocolMessage(
                    operation=ProtocolOperation.READ,
                    entity=EventBusServiceEntity(service.name, "path/1"),
                )
                m2 = ProtocolMessage(
                    operation=ProtocolOperation.READ,
                    entity=EventBusServiceEntity(service.name, "path/1"),
                )
                m3 = ProtocolMessage(
                    operation=ProtocolOperation.DELETE,
                    entity=EventBusServiceEntity(service.name, "path/1"),
                )

                request = MqttCommandRequest(payload=[m1, m2, m3], response_topic=topic.response_topic())
                result = await mqtt_connection.perform_operation(topic, request)
                assert isinstance(result.payload, list)
                assert len(result.payload) == 3
                payload = cast(List[Dict], result.payload)

                responses = [EventBusCommandResponse.decode(r) for r in payload]
                assert responses[0].success is True
                assert responses[1].success is True
                assert responses[2].success is False

                assert responses[0].payload
                assert responses[1].payload
                assert dict(responses[0].payload.protocol_values()) == payload_data
                assert dict(responses[1].payload.protocol_values()) == payload_data
