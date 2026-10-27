# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

from enum import Enum


class StrEnum(str, Enum):
    def __str__(self) -> str:
        return self.value
