# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

from testcode.flatten_test_module_cyclic.sub_a import class1  # type: ignore


class class3(class1):
    pass
