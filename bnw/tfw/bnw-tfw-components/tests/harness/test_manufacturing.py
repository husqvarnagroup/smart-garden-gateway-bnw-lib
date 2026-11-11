# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest  # type: ignore
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1
from cryptography.x509.oid import NameOID

try:
    from bnw.tfw.gateway.component.commander import lwm2mserver as lwm2mserver_harness

    lwm2mserver_harness_unavailable = False
except ImportError:
    lwm2mserver_harness_unavailable = True
from bnw.tfw.component.harness.manufacturing import (
    ManufacturingDeviceCertificateAuthority,
)


def test_device_certificate_authority_init():
    sut = ManufacturingDeviceCertificateAuthority()

    assert sut.public_key().key_size == 256
    assert sut.public_key().curve.name == SECP256R1().name

    assert sut.ca_certificate_pem()

    cert = x509.load_pem_x509_certificate(sut.ca_certificate_pem().encode(), default_backend())
    assert cert.issuer == cert.subject
    assert cert.public_key().public_numbers() == sut.public_key().public_numbers()


def test_ca_device_cert():
    sut = ManufacturingDeviceCertificateAuthority()
    device_private_key, device_certificate = sut.generate_device_certificate(
        "279a220c-f210-4058-8650-1d0768662ffc", "3018f169003fffc000000002"
    )

    cert = x509.load_der_x509_certificate(device_certificate, default_backend())
    assert cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value == "279a220c-f210-4058-8650-1d0768662ffc"

    try:
        sut.public_key().verify(cert.signature, cert.tbs_certificate_bytes, ec.ECDSA(cert.signature_hash_algorithm))
    except InvalidSignature:
        raise AssertionError("Signature not valid")


@pytest.mark.skipif(
    lwm2mserver_harness_unavailable or not lwm2mserver_harness.ServerPython.is_available(),
    reason="lwm2mserver not available or does not support secure inclusion",
)
def test_ca_cert_with_lwm2m():
    from lwm2mserver.crypto import DeviceCertificate, DeviceCertificateAuthority

    sut = ManufacturingDeviceCertificateAuthority()

    ca = DeviceCertificateAuthority(sut.ca_certificate_pem().encode())
    device_private_key, device_certificate = sut.generate_device_certificate(
        "279a220c-f210-4058-8650-1d0768662ffc", "3018f169003fffc000000002"
    )
    certificate = DeviceCertificate(device_certificate, ca)

    assert certificate.valid() is True
