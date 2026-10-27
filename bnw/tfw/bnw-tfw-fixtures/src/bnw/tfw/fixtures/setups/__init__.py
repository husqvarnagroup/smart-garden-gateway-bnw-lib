# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Contains common testing setups (collection of components and harness) that are shared between test scenarios
"""

import inspect
from abc import ABCMeta, abstractmethod
from functools import wraps
from typing import List, Type

import pytest
from bnw.tfw.component import Component


class BaseTestSetup(metaclass=ABCMeta):
    @abstractmethod
    async def assert_ready(self) -> bool:
        pass

    @staticmethod
    def install(module_name: str) -> None:
        pass

    @classmethod
    def dependencies(cls) -> List[Type[Component]]:
        return []

    @classmethod
    def unavailable_reason(cls) -> str:
        return ", ".join(
            f"{c.__name__} unavailable"
            for c in cls.dependencies()
            if callable(getattr(c, "is_available", None)) and not c.is_available()  # type: ignore[attr-defined]
        )

    @classmethod
    def is_available(cls):
        return all(c.is_available() for c in cls.dependencies() if callable(getattr(c, "is_available", None)))

    @classmethod
    def skip_if_unavailable(cls, func):
        should_skip = not cls.is_available()
        reason = cls.unavailable_reason() if should_skip else ""
        if inspect.iscoroutinefunction(func):

            @pytest.mark.skipif(should_skip, reason=reason)
            @wraps(func)
            async def decorator(*args, **kwargs):
                return func(*args, **kwargs)

        else:

            @pytest.mark.skipif(should_skip, reason=reason)
            @wraps(func)
            def decorator(*args, **kwargs):
                return func(*args, **kwargs)

        return decorator
