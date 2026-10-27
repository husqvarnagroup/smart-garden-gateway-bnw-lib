# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

from dataclasses import dataclass
from typing import List, Type

from bnw.tfw.component import Component
from bnw.tfw.fixtures.setups import BaseTestSetup


class UnavailableComponent(Component):
    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def ready(self) -> bool:
        return False

    @classmethod
    def is_available(cls):
        return False


class AvailableComponent(Component):
    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def ready(self) -> bool:
        return True

    @classmethod
    def is_available(cls):
        return True


@dataclass  # type: ignore[misc]
class UnavailableSampleTestSetup(BaseTestSetup):
    value: str

    component: UnavailableComponent

    @classmethod
    def dependencies(cls) -> List[Type[Component]]:
        return [UnavailableComponent]


@dataclass  # type: ignore[misc]
class AvailableSampleTestSetup(BaseTestSetup):
    value: str

    component: UnavailableComponent

    @classmethod
    def dependencies(cls) -> List[Type[Component]]:
        return [AvailableComponent]


@dataclass  # type: ignore[misc]
class MixedSampleTestSetup(BaseTestSetup):
    @classmethod
    def dependencies(cls) -> List[Type[Component]]:
        return [AvailableComponent, UnavailableComponent]


@UnavailableSampleTestSetup.skip_if_unavailable
def test_sample_setup():
    assert False, "Should have been skipped"


def test_sample_setup_unavailable():
    assert UnavailableSampleTestSetup.is_available() is False


def test_sample_setup_unavailable_reason():
    assert UnavailableSampleTestSetup.unavailable_reason() == "UnavailableComponent unavailable"


def test_available():
    assert AvailableSampleTestSetup.is_available() is True
    assert AvailableSampleTestSetup.unavailable_reason() == ""


def test_mixed():
    assert MixedSampleTestSetup.is_available() is False
    assert MixedSampleTestSetup.unavailable_reason() == "UnavailableComponent unavailable"
