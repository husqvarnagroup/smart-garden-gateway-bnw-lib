# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

from bnw.protocol import ProtocolEntity


class EventBusDeviceEntity(ProtocolEntity):
    def __init__(self, device: str, path: str):
        super().__init__(device=device, path=path)


class EventBusServiceEntity(ProtocolEntity):
    def __init__(self, service: str, path: str):
        super().__init__(service=service, path=path)


class CloudDeviceEntity(EventBusDeviceEntity):
    def __init__(self, gateway: str, device: str, path: str):
        super().__init__(device=device, path=path)
        self["gateway"] = gateway


class CloudServiceEntity(EventBusServiceEntity):
    def __init__(self, gateway: str, service: str, path: str):
        super().__init__(service=service, path=path)
        self["gateway"] = gateway
