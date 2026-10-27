# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import os

import pytest
import pytest_cases
from bnw.tfw.pytest.test_setup import define_test_setup
from pytest_cases import parametrize_with_cases

pytestmark = pytest.mark.asyncio


def sample_test_setup(setup):
    @setup.private
    async def private_fixture_async_gen():
        yield "private_fixture_async_gen"

    @setup.private
    def private_fixture_gen():
        yield "private_fixture_gen"

    @setup.private
    async def private_fixture_async():
        return "private_fixture_async"

    @setup.private
    def private_fixture():
        return "private_fixture"

    @setup.public
    async def sample_test_setup(private_fixture, private_fixture_gen, private_fixture_async, private_fixture_async_gen):
        assert private_fixture == "private_fixture"
        assert private_fixture_async == "private_fixture_async"
        assert private_fixture_gen == "private_fixture_gen"
        assert private_fixture_async_gen == "private_fixture_async_gen"
        return "sample_test_setup"


define_test_setup(sample_test_setup).install(__name__)


@pytest_cases.fixture
async def local_fixture_async_gen():
    yield "local_fixture_async_gen"


@pytest_cases.fixture
def local_fixture_gen():
    yield "local_fixture_gen"


@pytest_cases.fixture
async def local_fixture_async():
    return "local_fixture_async"


@pytest_cases.fixture
def local_fixture():
    return "local_fixture"


@pytest_cases.fixture
def local_request(request):
    return "local_request"


@pytest_cases.fixture
def local(local_fixture, local_fixture_async, local_fixture_gen, local_fixture_async_gen):
    assert local_fixture == "local_fixture"
    assert local_fixture_async == "local_fixture_async"
    assert local_fixture_gen == "local_fixture_gen"
    assert local_fixture_async_gen == "local_fixture_async_gen"

    return local_fixture


@pytest_cases.fixture
async def unused_fixture_dependency():
    yield "unused_fixture_dependency"


@pytest_cases.fixture
async def unused_fixture(unused_fixture_dependency):
    assert False, "Should never be called"


@pytest_cases.fixture
def fixture_none():
    return "none"


def setups_none(fixture_none):
    assert fixture_none == "none"
    return "ok"


def setups_sample(sample_test_setup):
    assert sample_test_setup == "sample_test_setup"
    return "ok"


@pytest.mark.skip(reason="a skipped setup to test that unused fixture is never attempted")
def setups_unused(unused_fixture):
    return "nok"


@pytest.mark.skipif(condition="TF_BUILD" in os.environ, reason="not working on azure devops")
@parametrize_with_cases("setups", cases=".", prefix="setups_")
async def test_different_cases(setups):
    assert setups == "ok"
