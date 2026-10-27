# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

from testcode.flatten_test_module_cyclic.sub_c import class3  # type: ignore


class class2(class3):
    pass
