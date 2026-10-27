# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest  # type: ignore

from bnw.pycode import native


def test_flattening_module():
    import testcode.flatten_test_module

    code = native.flatten_module(testcode, testcode.flatten_test_module)
    assert code

    ns = native.execute_source(code)
    assert "class1" in ns
    assert "class2" in ns
    assert "class31" in ns
    assert "class32" in ns
    assert "class33" in ns
    assert "class34" in ns
    assert "class35" in ns


def test_flattening_module_cyclic():
    try:
        import testcode.flatten_test_module_cyclic
    except ImportError:
        pass
    with pytest.raises(ImportError):
        native.flatten_module(testcode, testcode.flatten_test_module_cyclic)


@pytest.mark.skip(
    reason="Due to code modification & import from classes under other module, it can break other tests."
    "E.g. isinstance checks will fail"
)
def test_generate_protocol_py():
    code = native.generate_protocol_py()
    assert code


@pytest.mark.skip(
    reason="Due to code modification & import from classes under other module, it can break other tests."
    "E.g. isinstance checks will fail"
)
def test_generate_protocol_pyi():
    code = native.generate_protocol_pyi()
    assert code


@pytest.mark.skip(
    reason="Due to code modification & import from classes under other module, it can break other tests."
    "E.g. isinstance checks will fail"
)
def test_generate_utils_py():
    code = native.generate_utils_py()
    assert code
