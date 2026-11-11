# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import uuid
from typing import Optional

from .device import DeviceName


class GatewayName:
    def __init__(self, ipr_id: str, sgtin: str = None):
        self.ipr_id = ipr_id
        self.sgtin = sgtin

    @classmethod
    def random(cls) -> "GatewayName":
        return cls(str(uuid.uuid4()), DeviceName.random().sgtin)

    def device_name(self) -> Optional[DeviceName]:
        return DeviceName(self.sgtin) if self.sgtin else None

    def __str__(self):
        return self.ipr_id


class ServiceName(str):
    pass
