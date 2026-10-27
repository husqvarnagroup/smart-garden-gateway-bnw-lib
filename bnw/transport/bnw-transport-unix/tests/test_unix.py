# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio

import pytest  # type: ignore
from bnw.tfw.gateway.component.harness.gateway import GenericService, TestingService
from bnw.transport.unix.socket import (
    COMMAND_REQUEST_MESSAGE_MAX_SIZE,
    ConsumerConnection,
)
from bnw.transport.unix.unix_socket_consumer import (
    COMMAND_RESPONSE_MESSAGE_MAX_SIZE,
    EVENT_MESSAGE_MAX_SIZE,
)

from bnw.protocol import (
    ProtocolEnvelope,
    ProtocolMessage,
    ProtocolOperation,
    ProtocolPayload,
)
from bnw.protocol.command import EventBusCommandResponseEnvelope

pytestmark = pytest.mark.asyncio


async def test_consumer_connection_publish():
    service_name = "generic"
    async with GenericService(service_name) as service:
        sut = ConsumerConnection(service_name)
        await sut.connect()
        await asyncio.sleep(0.001)  # give the testing service time to accept the connection

        message = ProtocolMessage(operation=ProtocolOperation.UPDATE)
        await service.publish_protocol_message(message)

        received = await sut.receive_event()
        envelope = ProtocolEnvelope.deserialize(received)
        assert len(envelope.messages) == 1
        assert envelope.messages[0] == message

        await sut.disconnect()


async def test_consumer_connection_publish_oversize():
    service_name = "generic"
    async with GenericService(service_name) as service:

        async def drain_hack():
            # Drain the event writers to not clog the socket for future events, otherwise the test would fail on
            # machines with heavy load, e.g. in the CI.
            for writer in service._connection._event_tasks_writers.values():
                await writer.drain()

        sut = ConsumerConnection(service_name)
        await sut.connect()
        await asyncio.sleep(0.001)  # give the testing service time to accept the connection

        data = "X" * EVENT_MESSAGE_MAX_SIZE
        message = ProtocolMessage(operation=ProtocolOperation.UPDATE, payload=ProtocolPayload({"big_data": data}))
        await service.publish_protocol_message(message)
        await drain_hack()

        with pytest.raises(asyncio.TimeoutError):
            async with asyncio.timeout(0.1):
                await sut.receive_event()

        message = ProtocolMessage(operation=ProtocolOperation.UPDATE, payload=ProtocolPayload({"big_data": "small"}))
        await service.publish_protocol_message(message)

        received = await sut.receive_event()
        envelope = ProtocolEnvelope.deserialize(received)
        assert len(envelope.messages) == 1
        assert message == envelope.messages[0]

        data = "Y" * 5 * EVENT_MESSAGE_MAX_SIZE
        message = ProtocolMessage(operation=ProtocolOperation.UPDATE, payload=ProtocolPayload({"big_data": data}))
        await service.publish_protocol_message(message)
        await drain_hack()

        with pytest.raises(asyncio.TimeoutError):
            async with asyncio.timeout(0.1):
                await sut.receive_event()

        message = ProtocolMessage(operation=ProtocolOperation.UPDATE, payload=ProtocolPayload({"big_data": "tiny"}))
        await service.publish_protocol_message(message)

        received = await sut.receive_event()
        envelope = ProtocolEnvelope.deserialize(received)
        assert len(envelope.messages) == 1
        assert message == envelope.messages[0]

        await sut.disconnect()


async def test_consumer_connection_command():
    service_name = "generic"
    async with TestingService(service_name) as service:
        command = ProtocolMessage(operation=ProtocolOperation.EXECUTE)

        async def command_impl():
            received_operation = await service.request_operation()
            if received_operation == command:
                await service.respond_success()
            else:
                await service.respond_failure()

        sut = ConsumerConnection(service_name)
        await sut.connect()

        testing_command_task = asyncio.create_task(command_impl())
        command_response_bytes = await sut.perform_command(ProtocolEnvelope(messages=[command]).serialize().encode())

        assert command_response_bytes is not None
        command_response_envelope = EventBusCommandResponseEnvelope.deserialize(command_response_bytes)
        assert len(command_response_envelope.messages) == 1
        assert command_response_envelope.messages[0].success is True
        await testing_command_task

        await sut.disconnect()


async def test_consumer_connection_command_timeout():
    service_name = "generic"
    async with TestingService(service_name) as service:

        async def command_impl():
            while True:
                received_operation = await service.request_operation()

                sleep = received_operation.payload.get("sleep")
                if sleep is not None:
                    await asyncio.sleep(sleep)
                    await service.respond_success(payload=ProtocolPayload({"sleep_result": sleep}))
                else:
                    await service.respond_failure()

        sut = ConsumerConnection(service_name, command_response_timeout=0.2)
        await sut.connect()

        testing_command_task = asyncio.create_task(command_impl())

        command = ProtocolMessage(operation=ProtocolOperation.EXECUTE, payload=ProtocolPayload({"sleep": 0.3}))
        command_response_bytes = await sut.perform_command(ProtocolEnvelope(messages=[command]).serialize().encode())
        assert command_response_bytes is None

        await asyncio.sleep(0.3)  # wait for the command_impl to finish sleep

        command = ProtocolMessage(operation=ProtocolOperation.EXECUTE, payload=ProtocolPayload({"sleep": 0.1}))
        command_response_bytes = await sut.perform_command(ProtocolEnvelope(messages=[command]).serialize().encode())

        assert command_response_bytes is not None
        command_response_envelope = EventBusCommandResponseEnvelope.deserialize(command_response_bytes)
        assert len(command_response_envelope.messages) == 1

        message = command_response_envelope.messages[0]
        assert message.success is True
        assert message.payload == {"sleep_result": 0.1}

        testing_command_task.cancel()
        try:
            await testing_command_task
        except asyncio.CancelledError:
            pass

        await sut.disconnect()


async def test_consumer_connection_command_oversize_request():
    service_name = "generic"
    async with TestingService(service_name) as service:

        async def command_impl():
            while True:
                received_operation = await service.request_operation()

                x = received_operation.payload.get("x")
                if x is not None:
                    await service.respond_success(payload=ProtocolPayload({"x_len": len(x)}))
                else:
                    await service.respond_failure()

        sut = ConsumerConnection(service_name, command_response_timeout=0.2)
        await sut.connect()

        testing_command_task = asyncio.create_task(command_impl())

        data = "X" * COMMAND_REQUEST_MESSAGE_MAX_SIZE
        command = ProtocolMessage(operation=ProtocolOperation.EXECUTE, payload=ProtocolPayload({"x": data}))
        command_response_bytes = await sut.perform_command(ProtocolEnvelope(messages=[command]).serialize().encode())
        assert command_response_bytes is None

        command = ProtocolMessage(operation=ProtocolOperation.EXECUTE, payload=ProtocolPayload({"x": "a few bytes"}))
        command_response_bytes = await sut.perform_command(ProtocolEnvelope(messages=[command]).serialize().encode())
        assert command_response_bytes is not None

        testing_command_task.cancel()
        try:
            await testing_command_task
        except asyncio.CancelledError:
            pass

        await sut.disconnect()


async def test_consumer_connection_command_oversize_response():
    service_name = "generic"
    async with TestingService(service_name) as service:

        async def command_impl():
            while True:
                received_operation = await service.request_operation()

                data_size = received_operation.payload.get("big_data")
                if data_size is not None:
                    data = "X" * data_size
                    await service.respond_success(payload=ProtocolPayload({"big_data": data}))
                else:
                    await service.respond_failure()

        sut = ConsumerConnection(service_name)
        await sut.connect()

        testing_command_task = asyncio.create_task(command_impl())

        command = ProtocolMessage(
            operation=ProtocolOperation.EXECUTE,
            payload=ProtocolPayload({"big_data": COMMAND_RESPONSE_MESSAGE_MAX_SIZE}),
        )
        command_response_bytes = await sut.perform_command(ProtocolEnvelope(messages=[command]).serialize().encode())
        assert command_response_bytes is None

        command = ProtocolMessage(operation=ProtocolOperation.EXECUTE, payload=ProtocolPayload({"big_data": 42}))
        command_response_bytes = await sut.perform_command(ProtocolEnvelope(messages=[command]).serialize().encode())
        assert command_response_bytes is not None

        testing_command_task.cancel()
        try:
            await testing_command_task
        except asyncio.CancelledError:
            pass

        await sut.disconnect()


async def test_consumer_connection_subscription():
    service_name = "generic"
    async with TestingService(service_name) as service:
        sut = ConsumerConnection(service_name)
        await sut.connect()
        await asyncio.sleep(0.001)  # give the testing service time to accept the connection

        await service.publish(b"1")

        sub = await sut.subscription()
        await service.publish(b"2")
        await asyncio.sleep(0.001)  # give the consumer connection time to discard the previous events
        await sub.start()

        with pytest.raises(asyncio.TimeoutError):
            async with asyncio.timeout(0.001):
                await sub.get_message()

        await service.publish(b"3")
        assert await sub.get_message() == b"3"

        await sub.cancel()

        new_sub = await sut.subscription()
        await new_sub.start()

        with pytest.raises(asyncio.TimeoutError):
            async with asyncio.timeout(0.001):
                await new_sub.get_message()

        await sut.disconnect()
        await new_sub.cancel()


async def test_consumer_connection_subscription_multiple():
    service_name = "generic"
    async with TestingService(service_name) as service:
        sut = ConsumerConnection(service_name)

        await sut.connect()

        sub = await sut.subscription()

        await service.publish(b"1")
        await asyncio.sleep(0.001)
        await sub.start()

        message1_fut = asyncio.ensure_future(sub.get_message())
        await service.publish(b"2")
        message1 = await message1_fut
        assert message1 == b"2"

        await service.publish(b"3")
        assert await sub.get_message() == b"3"

        await sub.cancel()
        await service.publish(b"4")

        with pytest.raises(asyncio.exceptions.TimeoutError):
            await asyncio.wait_for(sub.get_message(), 0.001)

        sub1 = await sut.subscription()
        sub2 = await sut.subscription()

        await sub1.start()
        await sub2.start()

        await service.publish(b"5")

        assert await sub1.get_message() == b"5"
        assert await sub2.get_message() == b"5"

        await sub1.cancel()
        await service.publish(b"6")

        assert await sub2.get_message() == b"6"

        await sut.disconnect()
