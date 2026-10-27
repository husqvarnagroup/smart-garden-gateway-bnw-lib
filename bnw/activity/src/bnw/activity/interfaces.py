# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

from abc import ABCMeta, abstractmethod
from types import TracebackType
from typing import Any, Generator, List, Mapping, Optional, Tuple, Type, TypeVar, Union

from .model.device import (
    DeviceName,
    DeviceResource,
    DeviceResourcePath,
    DeviceResourceValue,
    DeviceResourceWriteBatch,
)


class InclusionActivities(metaclass=ABCMeta):
    """A MessageInterface is an object that can include/exclude devices"""

    @abstractmethod
    async def include(self, device: DeviceName, **context):
        """Include a device"""

    @abstractmethod
    async def exclude(self, device: DeviceName, **context):
        """Exclude a device"""

    @abstractmethod
    async def get_included_devices(self) -> Optional[List[DeviceName]]:
        """Get included devices"""


class ActivityContext(metaclass=ABCMeta):
    @abstractmethod
    def get_value(self, name, **context):
        pass

    @abstractmethod
    async def await_value(self, name, **context):
        pass

    @abstractmethod
    async def close(self):
        pass


class ResolvingActivityContext(ActivityContext):
    @abstractmethod
    async def resolve(self, name, cache: bool = False, cache_key: str = None, **context):
        pass


class ContextResolver(metaclass=ABCMeta):
    @abstractmethod
    async def start(self):
        pass

    @abstractmethod
    async def stop(self):
        pass

    @abstractmethod
    def is_supported(self, name):
        pass

    @abstractmethod
    def find(self, name, **context):
        pass

    @abstractmethod
    async def wait_for(self, name, **context):
        pass


AST = TypeVar("AST", bound="ActivityStrategy")


class ActivityStrategy(metaclass=ABCMeta):
    @abstractmethod
    def context_resolvers(self) -> Generator[Any, Any, ContextResolver]:
        pass

    @abstractmethod
    def use_context(self, context: ActivityContext):
        pass

    @abstractmethod
    def context_values(self) -> Mapping[str, Any]:
        pass

    @abstractmethod
    async def activate(self) -> None:
        pass

    @abstractmethod
    async def deactivate(self) -> None:
        pass

    async def __aenter__(self: AST) -> AST:
        await self.activate()
        return self

    async def __aexit__(
        self, exc_type: Optional[Type[BaseException]], exc: Optional[BaseException], tb: Optional[TracebackType]
    ) -> None:
        await self.deactivate()


class IncludableDeviceResolver(metaclass=ABCMeta):
    INCLUDABLE_DEVICE_ID = "includable_device_id"

    @abstractmethod
    def find_includable_device_id(self, device: DeviceName) -> Optional[str]:
        pass

    @abstractmethod
    async def wait_for_includable_device_id(self, device: DeviceName) -> str:
        pass


class ResourceOperationActivities(metaclass=ABCMeta):
    @abstractmethod
    async def read(self, device: DeviceName, path: DeviceResourcePath, **context) -> Tuple[List[DeviceResource], Any]:
        """Read from a device"""

    @abstractmethod
    async def write(
        self,
        device: DeviceName,
        path: DeviceResourcePath,
        value: Union[DeviceResourceValue, DeviceResourceWriteBatch],
        **context
    ) -> Tuple[None, Any]:
        """Write to a device"""

    @abstractmethod
    async def execute(
        self, device: DeviceName, path: DeviceResourcePath, arguments: Optional[DeviceResourceValue] = None, **context
    ) -> Tuple[None, Any]:
        """Execute a command on a device"""
