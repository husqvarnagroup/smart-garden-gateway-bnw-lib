# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re

import pytest
from bnw.tfw.component.commander import PexpectCommander

pytestmark = pytest.mark.asyncio


async def test_pexepct_commander_no_arguments():
    class TestCommander(PexpectCommander):
        def __init__(self):
            super().__init__("echo")

    commander = TestCommander()
    await commander.start()
    await commander.stop()


async def test_pexepct_commander_await_output():
    class TestCommander(PexpectCommander):
        def __init__(self):
            super().__init__("echo", ["hello", "world"])

    async with TestCommander() as commander:
        is_match, match_or_exception = await commander.await_output(["HELLO", "wor(ld)"])
        assert is_match == 1
        assert isinstance(match_or_exception, re.Match)
        assert match_or_exception.group(1) == b"ld"


async def test_pexepct_commander_await_output_once():
    class TestCommander(PexpectCommander):
        def __init__(self):
            super().__init__("echo", ["hello", "world"])

    async with TestCommander() as commander:
        is_match, match_or_exception = await commander.await_output_once("wor(ld)")
        assert is_match
        assert isinstance(match_or_exception, re.Match)
        assert match_or_exception.group(1) == b"ld"

        is_match_2, match_or_exception_2 = await commander.await_output_once("wor(ld)")
        assert is_match_2 == is_match
        assert match_or_exception_2 == match_or_exception


async def test_pexepct_commander_shell_output(tmp_path):
    output_file = tmp_path / "stdout.txt"

    class TestCommander(PexpectCommander):
        def __init__(self):
            super().__init__("echo", ["-n", "hello", "world"], shell_output_file=output_file)

    async with TestCommander() as commander:
        is_match, _ = await commander.await_output_once("hello world")

    assert output_file.read_text() == "hello world"
