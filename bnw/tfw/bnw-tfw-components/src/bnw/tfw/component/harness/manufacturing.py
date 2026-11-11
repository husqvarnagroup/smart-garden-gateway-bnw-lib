# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import datetime
from typing import Optional, Tuple

from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ec import (
    SECP256R1,
    EllipticCurvePublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)
from cryptography.x509 import DirectoryName
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


class ManufacturingDeviceCertificateAuthority:
    def __init__(self, name: str = "smartsystem testing"):
        self._ec_curve = SECP256R1()
        self._root_key = ec.generate_private_key(curve=self._ec_curve, backend=default_backend())

        common_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
        authority_key_identifier = x509.AuthorityKeyIdentifier.from_issuer_public_key(self._root_key.public_key())

        self._root_cert_serial_number = x509.random_serial_number()
        self._root_cert = (
            x509.CertificateBuilder()
            .subject_name(common_name)
            .issuer_name(common_name)
            .public_key(self._root_key.public_key())
            .serial_number(self._root_cert_serial_number)
            .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
            .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1))
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(self._root_key.public_key()), critical=False)
            .add_extension(
                x509.AuthorityKeyIdentifier(
                    key_identifier=authority_key_identifier.key_identifier,
                    authority_cert_issuer=[DirectoryName(common_name)],
                    authority_cert_serial_number=self._root_cert_serial_number,
                ),
                critical=False,
            )
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=False,
                    content_commitment=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=True,
                    crl_sign=True,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=False,
            )
            .sign(self._root_key, hashes.SHA256(), default_backend())
        )

    def ca_certificate_pem(self) -> str:
        return self._root_cert.public_bytes(serialization.Encoding.PEM).decode()

    def generate_device_certificate(self, ipr_id: str, sgtin: Optional[str] = None) -> Tuple[bytes, bytes]:
        device_key = ec.generate_private_key(curve=self._ec_curve, backend=default_backend())

        new_subject = x509.Name(
            [
                x509.NameAttribute(NameOID.COMMON_NAME, ipr_id),
            ]
        )
        cert_builder = (
            x509.CertificateBuilder()
            .subject_name(new_subject)
            .issuer_name(self._root_cert.issuer)
            .public_key(device_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
            .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=False)
            .add_extension(x509.ExtendedKeyUsage(usages=[ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    content_commitment=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=False,
                    crl_sign=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=False,
            )
        )

        if sgtin:
            cert_builder = cert_builder.add_extension(
                x509.SubjectAlternativeName([x509.UniformResourceIdentifier(f"sgtin:{sgtin}")]), critical=False
            )

        cert = cert_builder.sign(self._root_key, hashes.SHA256(), default_backend())

        cert_der = cert.public_bytes(serialization.Encoding.DER)
        private_key_der = device_key.private_bytes(Encoding.DER, PrivateFormat.PKCS8, NoEncryption())

        return private_key_der, cert_der

    def public_key(self) -> EllipticCurvePublicKey:
        return self._root_key.public_key()
