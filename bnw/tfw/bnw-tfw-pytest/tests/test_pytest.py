# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio

import pytest
from bnw.tfw.pytest.test_setup import define_test_setup


def setup_definition_1(setup):
    @setup.private  # one time without ()
    def _private1():
        return "private1"

    @setup.private()  # one time with ()
    def _private2(_other_name):  # not yet defined private fixture (must use _ so that it is treated as private fixture)
        assert _other_name == "other_name"
        return "private2"

    @setup.private(name="_other_name")
    def _custom_name():
        return "other_name"

    @setup.private(name="_other_name_dependency")
    def _custom_name_with_dependency(_other_name):
        assert _other_name == "other_name"
        return "other_name_dependency"

    @setup.private(ids=[12])
    def _decorator_without_func(request):
        _decorator_without_func_dependency = request.getfixturevalue("_decorator_without_func_dependency")
        assert (
            _decorator_without_func_dependency == "decorator_without_func_dependency"
        ), "request.getfixturevalue not supporting private fixture"
        return "decorator_without_func"

    @setup.private(ids=[12])
    def _decorator_without_func_dependency(_private1):
        assert _private1 == "private1"
        return "decorator_without_func_dependency"

    @setup.public
    def public1(_private1, _private2):
        assert _private1 == "private1"
        assert _private2 == "private2"

        return "public1"

    @setup.public()
    def public2(_private1, public3):
        assert _private1 == "private1"
        assert public3 == "public3"
        return "public2"

    @setup.public(name="public3")
    def custom_public(_private1, _private2):
        return "public3"

    @setup.public
    def setup_fixture(
        _private1,
        _private2,
        _other_name,
        _other_name_dependency,
        _decorator_without_func,
        _decorator_without_func_dependency,
        request,
    ):
        # access via argument
        assert _private1 == "private1"
        assert _private2 == "private2"
        assert _other_name == "other_name"

        # dynamic access
        private1_dynamic = request.getfixturevalue("_private1")
        private2_dynamic = request.getfixturevalue("_private2")
        other_name_dynamic = request.getfixturevalue("_other_name")

        assert _private1 == private1_dynamic
        assert _private2 == private2_dynamic
        assert _other_name == other_name_dynamic
        return "setup_fixture"


define_test_setup(setup_definition_1, setup_name="test", random_prefix="rand1").install(__name__)


def test_testsetup_setup_fixture_working(setup_fixture):
    assert setup_fixture == "setup_fixture"


def test_testsetup_private_fixtures_not_available(request):
    with pytest.raises(LookupError):
        request.getfixturevalue("private1")

    assert "private1" not in request.fixturenames
    assert "private2" not in request.fixturenames
    assert "other_name" not in request.fixturenames
    assert "custom_name" not in request.fixturenames


def test_testsetup_different_public_fixtures_work(public1, public2, public3):
    assert public1 == "public1"
    assert public2 == "public2"
    assert public3 == "public3"


# define a setup a second time
def setup_definition_2(setup):
    @setup.private
    def _private1():
        return "_second_private1"

    @setup.public
    def setup_fixture_second(_private1):
        assert _private1 == "_second_private1", "received private fixture from another test setup"
        return "setup_fixture_second"


define_test_setup(setup_definition_2, setup_name="test", random_prefix="rand2").install(__name__)


def test_testsetup_define_setup_a_second_time_works(setup_fixture_second):
    assert setup_fixture_second == "setup_fixture_second"


def non_prefixed(setup):
    @setup.private
    def _private1():
        return "_non_prefixed_private1"

    @setup.public
    def non_prefixed():
        return "non_prefixed"


non_prefixed_setup = define_test_setup(non_prefixed, random_fixture_prefix=False).install(__name__)
non_prefixed_setup_2 = define_test_setup(non_prefixed, random_fixture_prefix=False)

module_name = __name__


def test_testsetup_install_a_second_time_fails(non_prefixed):
    assert non_prefixed == "non_prefixed"

    with pytest.raises(ValueError):
        non_prefixed_setup_2.install(module_name)


def pubic_conflict(setup):
    @setup.public
    def public1(_private1, _private2):
        pass


public_conflict_setup = define_test_setup(pubic_conflict)


def test_testsetup_install_with_same_public_fixture_fails():
    with pytest.raises(ValueError):
        public_conflict_setup.install(module_name)


def async_setup(setup):
    @setup.private
    @pytest.mark.asyncio
    async def _async_func():
        await asyncio.sleep(0.01)
        return "async_func"

    @setup.private
    @pytest.mark.asyncio
    async def _async_gen():
        yield "async_gen"

    @setup.private
    @pytest.mark.asyncio
    async def _async_private_dependency(_async_func, _async_gen):
        assert _async_func == "async_func"
        assert _async_gen == "async_gen"
        return "async_private_dependency"

    @setup.public
    @pytest.mark.asyncio
    async def async_setup(_async_func, _async_gen, _async_private_dependency):
        assert _async_func == "async_func"
        assert _async_gen == "async_gen"
        assert _async_private_dependency == "async_private_dependency"

        return "async_setup"


define_test_setup(async_setup).install(__name__)


def test_testsetup_async_works(async_setup):
    assert async_setup == "async_setup"
