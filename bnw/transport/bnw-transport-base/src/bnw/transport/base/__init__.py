# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

from abc import ABCMeta, abstractmethod
from types import TracebackType
from typing import Optional, Type, TypeVar

T = TypeVar("T", bound="Transport")


class Transport(metaclass=ABCMeta):
    @abstractmethod
    async def connect(self) -> None:
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        pass

    async def __aenter__(self: T) -> T:
        await self.connect()
        return self

    async def __aexit__(
        self, exc_type: Optional[Type[BaseException]], exc: Optional[BaseException], tb: Optional[TracebackType]
    ) -> None:
        await self.disconnect()
