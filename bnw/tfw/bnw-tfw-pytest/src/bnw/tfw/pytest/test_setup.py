# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import inspect
import logging
import random
import string
from functools import wraps
from typing import Callable, List, NamedTuple

import pytest_cases
from pytest_asyncio.plugin import _make_asyncio_fixture_function


class _TestSetupFixture(NamedTuple):
    public: Callable
    private: Callable


class TestSetup(NamedTuple):
    install: Callable


# Prevent to be detected as test class
setattr(TestSetup, "__test__", False)


def define_test_setup(
    definition, dependencies: List[str] = None, setup_name=None, random_fixture_prefix=True, random_prefix=None
):
    if setup_name is None:
        setup_name = definition.__name__

    all_fixtures = []
    private_fixture_names = []
    public_fixture_names = []
    private_fixture_prefix = f"_{setup_name}_" if setup_name is not None else "_"
    if random_fixture_prefix:
        private_fixture_prefix += (
            "".join(random.choices(string.ascii_letters, k=16)) if random_prefix is None else random_prefix
        )

    private_fixture_prefix += "_"

    def record_fixture(fixture_name, f):
        all_fixtures.append((fixture_name, f))
        return f

    def transform_fixture_function(private, fixture_function, *fixture_args, **fixture_kwargs):
        assert fixture_function is not None
        orig_name_attr = fixture_kwargs.pop("name", None)
        if orig_name_attr is None:
            orig_name_attr = fixture_function.__name__

        if private:
            private_fixture_names.append(orig_name_attr)
            fixture_name = private_fixture_prefix + orig_name_attr
        else:
            public_fixture_names.append(orig_name_attr)
            fixture_name = orig_name_attr

        def process_call_arguments(*function_args, **function_kwargs):
            # convert back prefixed parameter name to actual parameter names before calling actual function
            real_kwargs = {
                k[len(private_fixture_prefix) :] if k.startswith(private_fixture_prefix) else k: v
                for k, v in function_kwargs.items()
            }

            if "request" in real_kwargs:
                request = real_kwargs["request"]
                orig_getfixturevalue = request.getfixturevalue

                if getattr(orig_getfixturevalue, "__private_fixture_extended__", False) is False:

                    def mapping_get_fixture_value(argname):
                        if argname in private_fixture_names:
                            return orig_getfixturevalue(private_fixture_prefix + argname)
                        else:
                            return orig_getfixturevalue(argname)

                    setattr(mapping_get_fixture_value, "__private_fixture_extended__", True)
                    request.getfixturevalue = mapping_get_fixture_value

            return function_args, real_kwargs

        if inspect.isasyncgenfunction(fixture_function):
            _make_asyncio_fixture_function(fixture_function, loop_scope=None)

            @wraps(fixture_function)
            async def fixture_call_wrapper(*function_args, **function_kwargs):
                if not func_needs_request:
                    function_kwargs.pop("request")

                modified_args, modified_kwargs = process_call_arguments(*function_args, **function_kwargs)
                async for value in fixture_function(*modified_args, **modified_kwargs):
                    yield value

        elif inspect.iscoroutinefunction(fixture_function):
            _make_asyncio_fixture_function(fixture_function, loop_scope=None)

            @wraps(fixture_function)
            async def fixture_call_wrapper(*function_args, **function_kwargs):
                if not func_needs_request:
                    function_kwargs.pop("request")

                modified_args, modified_kwargs = process_call_arguments(*function_args, **function_kwargs)
                return await fixture_function(*modified_args, **modified_kwargs)

        elif inspect.isgeneratorfunction(fixture_function):

            @wraps(fixture_function)
            def fixture_call_wrapper(*function_args, **function_kwargs):
                if not func_needs_request:
                    function_kwargs.pop("request")

                modified_args, modified_kwargs = process_call_arguments(*function_args, **function_kwargs)
                yield from fixture_function(*modified_args, **modified_kwargs)

        else:

            @wraps(fixture_function)
            def fixture_call_wrapper(*function_args, **function_kwargs):
                if not func_needs_request:
                    function_kwargs.pop("request")

                modified_args, modified_kwargs = process_call_arguments(*function_args, **function_kwargs)
                return fixture_function(*modified_args, **modified_kwargs)

        fixture_signature = inspect.signature(fixture_function)
        # replace signature of method and replace parameter name with prefixed parameter name
        # so that pytest can find the private fixtures
        renamed_parameters = []
        for p in fixture_signature.parameters.values():
            is_private_fixture = p.name in private_fixture_names

            if not is_private_fixture and p.name[0] == "_":
                logging.info(
                    "Assuming argument %s is a private fixture but fixture not yet defined. "
                    "Reorder fixture definition to get rid of this notice.",
                    p,
                )
                is_private_fixture = True

            if is_private_fixture:
                renamed_parameters.append(
                    inspect.Parameter(
                        private_fixture_prefix + p.name, p.kind, default=p.default, annotation=p.annotation
                    )
                )
            else:
                renamed_parameters.append(p)

        # add request if needed (for pytest_cases)
        func_needs_request = any(p.name == "request" for p in renamed_parameters)
        if not func_needs_request:
            renamed_parameters.append(inspect.Parameter("request", kind=inspect.Parameter.POSITIONAL_OR_KEYWORD))

        # modify the wrapper, not the actual fixture_function
        fixture_call_wrapper.__signature__ = fixture_signature.replace(parameters=renamed_parameters)
        return record_fixture(
            fixture_name,
            pytest_cases.fixture_plus(fixture_call_wrapper, *fixture_args, name=fixture_name, **fixture_kwargs),
        )

    class fixture_marker_wrapper(object):
        """wrapper for fixture decorator that does not immediately provide fixture function argument"""

        def __init__(self, private, *args, **kwargs):
            self.private = private
            self.args = args
            self.kwargs = kwargs

        def __call__(self, function):
            return transform_fixture_function(self.private, function, *self.args, **self.kwargs)

    def private_fixture(func=None, *args, **kwargs):
        if func is not None:
            return transform_fixture_function(True, func, *args, **kwargs)
        else:
            return fixture_marker_wrapper(True, *args, **kwargs)

    def public_fixture(func=None, *fixture_args, **fixture_kwargs):

        if func is not None:
            return transform_fixture_function(False, func, *fixture_args, **fixture_kwargs)
        else:
            return fixture_marker_wrapper(False, *fixture_args, **fixture_kwargs)

    # evaluate definition
    definition(_TestSetupFixture(public=public_fixture, private=private_fixture))

    def install(module_name):
        import sys

        module = sys.modules[module_name]
        for fixture_name, fixture in all_fixtures:
            key = "_test_setup_fixture_" + fixture_name

            existing = module.__dict__.get(key, None)
            if existing is not None and existing != fixture:
                raise ValueError(f"Fixture {fixture_name} has already been defined somewhere else")

            module.__dict__[key] = fixture

        if dependencies:
            if "pytest_plugins" in module.__dict__:
                plugins = module.__dict__["pytest_plugins"]
                if isinstance(plugins, str):
                    module.__dict__["pytest_plugins"] = [plugins]
                elif isinstance(plugins, tuple):
                    module.__dict__["pytest_plugins"] = list(plugins)

                module.__dict__["pytest_plugins"].extend(dependencies)
            else:
                module.__dict__["pytest_plugins"] = dependencies

    return TestSetup(install=install)
