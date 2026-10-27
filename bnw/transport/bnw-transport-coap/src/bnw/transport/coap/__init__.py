# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

from abc import abstractmethod
from typing import Optional

from aiocoap import Message, interfaces
from bnw.transport.base import Transport


class CoapConnection(Transport):
    @abstractmethod
    async def send(
        self, message: Message, destination: Optional[str] = None, remote: Optional[interfaces.RequestInterface] = None
    ) -> Optional[Message]:
        pass
