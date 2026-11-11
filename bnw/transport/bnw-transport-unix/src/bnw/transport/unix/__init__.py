# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

from bnw.transport.base import Transport

DEFAULT_SOCKET_LOCATION = "/tmp"

COMMAND_REQUEST_QUEUE_SIZE = 5
COMMAND_REQUEST_MESSAGE_MAX_SIZE = 16 * 1024 * 1024
COMMAND_RESPONSE_MESSAGE_MAX_SIZE = 16 * 1024 * 1024

EVENT_MESSAGE_MAX_SIZE = 16 * 1024 * 1024

MESSAGE_SEPERATOR = b"\n"


class UnixConnection(Transport):
    pass
