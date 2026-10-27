# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

from abc import ABCMeta, abstractmethod
from contextlib import asynccontextmanager
from types import TracebackType
from typing import AsyncIterator, Optional, Tuple, Type, TypeVar, Union

from bnw.transport.base import Transport

from bnw.activity.model.mqtt import MqttTopic

S = TypeVar("S", bound="MqttSubscription")


class MqttSubscription(metaclass=ABCMeta):
    async def start(self) -> None:
        pass

    async def cancel(self) -> None:
        pass

    @abstractmethod
    async def get_message(self) -> Tuple[str, bytes]:
        pass

    async def __aenter__(self: S) -> S:
        await self.start()
        return self

    async def __aexit__(
        self, exc_type: Optional[Type[BaseException]], exc: Optional[BaseException], tb: Optional[TracebackType]
    ) -> None:
        await self.cancel()


class MqttConnection(Transport):
    @abstractmethod
    async def publish(self, topic: str, payload: Optional[bytes] = None, qos: int = 1) -> None:
        pass

    @abstractmethod
    @asynccontextmanager
    def subscription(self, topic: Union[MqttTopic, str]) -> AsyncIterator[MqttSubscription]:
        pass
