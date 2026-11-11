# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

from testcode.flatten_test_module_cyclic.sub_b import class2  # type: ignore


class class1(class2):
    pass
