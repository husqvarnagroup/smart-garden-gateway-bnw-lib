# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
import logging
from typing import Awaitable, Callable, Optional

from . import MESSAGE_SEPERATOR

LOG_DATA_EXCERPT_MAX_SIZE = 100


async def ignore_cancelled_error(awaitable: Awaitable) -> None:
    try:
        await awaitable
    except asyncio.CancelledError:
        pass


def truncate_log_data(data: bytes) -> bytes:
    ellipsis_ = b"..."
    if len(data) > LOG_DATA_EXCERPT_MAX_SIZE:
        return data[: LOG_DATA_EXCERPT_MAX_SIZE - len(ellipsis_)] + ellipsis_
    return data


async def read_loop(
    reader: asyncio.StreamReader,
    handler: Callable[[bytes], Awaitable],
    *,
    before_read_handler: Optional[Callable[[], Awaitable]] = None,
    logger: logging.Logger,
    log_socket_name: str = "",
) -> None:
    truncated = False
    while True:
        if before_read_handler is not None:
            await before_read_handler()
        try:
            data = await reader.readuntil(MESSAGE_SEPERATOR)
        except asyncio.LimitOverrunError as e:
            partial_data = await reader.read(e.consumed)
            logger.error(
                f"Partially received too long message from {log_socket_name} socket:"
                f" {truncate_log_data(partial_data)!r}"
            )
            truncated = True
            continue
        except asyncio.IncompleteReadError as e:
            if len(e.partial) == 0 and not truncated:
                logger.debug(f"Peer disconnected from {log_socket_name} socket")
            else:
                logger.error(
                    f"Received truncated data on {log_socket_name} socket"
                    f" just before peer closed connection: {truncate_log_data(e.partial)!r}"
                )
            break
        data = data[:-1]
        if truncated:
            logger.error(f"End of too long message received from {log_socket_name} socket: {truncate_log_data(data)!r}")
            truncated = False
            continue
        await handler(data)
