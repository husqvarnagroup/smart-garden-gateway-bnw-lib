# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest
from bnw.tfw.component.harness.manufacturing import (
    ManufacturingDeviceCertificateAuthority,
)


@pytest.fixture(scope="session")
def manufacturing_device_certificate_authority() -> ManufacturingDeviceCertificateAuthority:
    return ManufacturingDeviceCertificateAuthority()


@pytest.fixture(scope="session")
def manufacturing_device_ca_certificate_bytes(manufacturing_device_certificate_authority) -> bytes:
    return manufacturing_device_certificate_authority.ca_certificate_pem().encode()
