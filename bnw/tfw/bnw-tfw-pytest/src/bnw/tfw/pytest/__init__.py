# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, Coroutine, Optional


async def wait_for(fut: Coroutine, timeout: float = 1.0, description: Optional[str] = None, **kwargs) -> Any:
    async with asyncio_timeout_description(description):
        return await asyncio.wait_for(fut, timeout=timeout, **kwargs)


@asynccontextmanager
async def asyncio_timeout_description(description: Optional[str]):
    try:
        yield
    except asyncio.exceptions.TimeoutError as e:
        raise AssertionError(f"{description} timeout" if description else "timeout") from e


def configure_loggers(
    client=logging.INFO, lwm2mserver=logging.INFO, cloudadapter=logging.INFO, reduce_third_party=True
):
    def change_log_level(name, level):
        logger = logging.getLogger(name)
        logger.setLevel(level)
        for handler in logger.handlers:
            handler.setLevel(level)

    if reduce_third_party:
        # noisy third party components
        change_log_level("asyncio", logging.WARNING)
        change_log_level("transitions", logging.WARNING)
        change_log_level("amqtt", logging.WARNING)
        change_log_level("passlib", logging.INFO)
        change_log_level("urllib3", logging.WARNING)
        change_log_level("websockets", logging.WARNING)
        change_log_level("aws_encryption_sdk", logging.WARNING)
        change_log_level("botocore", logging.WARNING)
        change_log_level("kafka", logging.WARNING)

    # client
    change_log_level("coap-server", client)
    change_log_level("bnw.transport.coap.lwm2m", client)
    change_log_level("bnw.tfw.component.harness._lwm2m", client)

    # lwm2mserver
    change_log_level("bnw.component.commander.log.lwm2mserver", lwm2mserver)
    change_log_level("bnw.component.commander.log.lwm2mserver_native", lwm2mserver)
    change_log_level("lwm2mserver", lwm2mserver)
    change_log_level("wakaama", lwm2mserver)

    # cloudadapter
    change_log_level("bnw.component.commander.log.cloudadapter", cloudadapter)
    change_log_level("bnw.component.commander.log.cloudadapter_native", cloudadapter)
    change_log_level("cloudadapter", cloudadapter)
