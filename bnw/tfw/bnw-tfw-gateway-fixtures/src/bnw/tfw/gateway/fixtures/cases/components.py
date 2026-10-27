# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import os

import pytest
import pytest_cases
from bnw.tfw.component.harness.cloud import AwsIotCloud
from bnw.tfw.gateway.component.commander.cloudadapter import (
    Cloudadapter,
    CloudadapterPython,
)
from bnw.tfw.gateway.component.commander.lwm2mserver import Server as Lwm2mserver
from bnw.tfw.gateway.component.commander.lwm2mserver import (
    ServerPython as Lwm2mserverPython,
)


class CasesCloudadapter:
    @staticmethod
    def lookup_cloud_tenant(request):
        try:
            return request.getfixturevalue("cloud_tenant_override")
        except LookupError:
            pass

        try:
            return request.getfixturevalue("cloud_tenant")
        except LookupError:
            pass

        return None

    @classmethod
    def ids(cls, case_fun):
        return "cloudadapter(%s)" % pytest_cases.get_case_id(case_fun)

    @pytest.mark.skipif(not CloudadapterPython.is_available(), reason="cloudadapter package not available")
    @pytest_cases.case(tags=["commander", "python"])
    def case_python(
        self,
        monkeypatch,
        gateway_name,
        eventbus_location,
        cloud: AwsIotCloud,
        cloud_ca_public_key,
        cloud_client_private_key,
        cloud_client_public_key_chain,
        request,
    ):
        monkeypatch.setenv("CLOUDADAPTER_GDS_SGTIN", str(gateway_name.device_name()))
        monkeypatch.setenv("CLOUDADAPTER_GDS_SYSTEMCTL_CMD", "true")
        return CloudadapterPython(
            str(gateway_name),
            cloud=cloud.endpoint,
            verbose=3,
            debug=True,
            eventbus_location=eventbus_location,
            cloud_tenant=self.lookup_cloud_tenant(request),
        ).with_credentials(cloud_client_public_key_chain, cloud_client_private_key, cloud_ca_public_key)

    @pytest_cases.case(tags=["commander", "binary"])
    @pytest.mark.skipif(not Cloudadapter.is_available(), reason=f"{Cloudadapter.EXECUTABLE} not available")
    def case_binary(
        self,
        gateway_name,
        eventbus_location,
        cloud: AwsIotCloud,
        cloud_ca_public_key,
        cloud_client_private_key,
        cloud_client_public_key_chain,
        request,
    ):
        return Cloudadapter(
            str(gateway_name),
            cloud=cloud.endpoint,
            verbose=1,
            debug=True,
            eventbus_location=eventbus_location,
            env={"CLOUDADAPTER_GDS_SGTIN": str(gateway_name.device_name()), "CLOUDADAPTER_GDS_SYSTEMCTL_CMD": "true"},
            cloud_tenant=self.lookup_cloud_tenant(request),
        ).with_credentials(cloud_client_public_key_chain, cloud_client_private_key, cloud_ca_public_key)


def parametrize_with_cloudadapter(f=None, **kwargs):
    decorator = pytest_cases.parametrize_with_cases(
        "cloudadapter", cases=CasesCloudadapter, ids=CasesCloudadapter.ids, **kwargs
    )
    return decorator if f is None else decorator(f)


class CasesLwm2mserver:
    @classmethod
    def ids(cls, case_fun):
        return "lwm2mserver(%s)" % pytest_cases.get_case_id(case_fun)

    @pytest.mark.skipif(not Lwm2mserverPython.is_available(), reason="lwm2mserver package not available")
    @pytest_cases.case(tags=["commander", "python"])
    def case_python(
        self, eventbus_location, lwm2m_port, manufacturing_device_ca_certificate_bytes, lemonbeat_network_key
    ):
        return Lwm2mserverPython(
            "lo",
            verbose=2,
            debug=True,
            port=lwm2m_port,
            eventbus_location=eventbus_location,
            device_ca_bytes=manufacturing_device_ca_certificate_bytes,
            lemonbeat_key=lemonbeat_network_key,
        )

    @pytest.mark.skipif(not Lwm2mserver.is_available(), reason=f"{Lwm2mserver.EXECUTABLE} not available")
    @pytest_cases.case(tags=["commander", "binary"])
    def case_binary(
        self, eventbus_location, lwm2m_port, manufacturing_device_ca_certificate_bytes, lemonbeat_network_key
    ):
        return Lwm2mserver(
            "lo",
            verbose=2,
            debug=True,
            port=lwm2m_port,
            eventbus_location=eventbus_location,
            device_ca_bytes=manufacturing_device_ca_certificate_bytes,
            lemonbeat_key=lemonbeat_network_key,
        )

    @pytest.fixture
    def lemonbeat_network_key(self):
        return os.urandom(16)


def parametrize_with_lwm2mserver(f=None, **kwargs):
    decorator = pytest_cases.parametrize_with_cases(
        "lwm2mserver", cases=CasesLwm2mserver, ids=CasesLwm2mserver.ids, **kwargs
    )
    return decorator if f is None else decorator(f)
