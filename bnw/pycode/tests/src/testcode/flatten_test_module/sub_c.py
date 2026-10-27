# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import collections
from asyncio import Queue

import testcode.flatten_test_module.sub_b  # noqa
from testcode.flatten_test_module import base
from testcode.flatten_test_module.sub_a import class1
from testcode.flatten_test_module.sub_b import class2


class class31(base):
    pass


class class32(class2):
    pass


class class33(class1):
    pass


class class34(collections.Counter):
    pass


class class35(Queue):
    pass
