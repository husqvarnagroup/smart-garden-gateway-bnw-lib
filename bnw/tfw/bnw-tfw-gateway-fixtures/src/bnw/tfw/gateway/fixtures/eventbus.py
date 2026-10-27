# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import tempfile

import py
import pytest


@pytest.fixture()
def short_tmpdir():
    with tempfile.TemporaryDirectory() as tdir:
        yield py.path.local(tdir)


@pytest.fixture
def eventbus_location(short_tmpdir):
    # regular pytest tmpdir can be too long nng (causing invalid address error)
    return f"{short_tmpdir}"
