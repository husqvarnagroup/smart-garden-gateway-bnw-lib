# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest_cases
from bnw.tfw.component.harness.cloud import Cloud
from bnw.transport.mqtt.awsiot import AwsMqttClientMqttConnection


class CasesCloudMqttConnection:
    @classmethod
    def ids(cls, case_fun):
        return "transport:%s>cloud(python)" % pytest_cases.get_case_id(case_fun)

    @pytest_cases.case(tags=["cloud"])
    def case_direct(self, cloud: Cloud):
        """Direct connection to cloud/broker (interaction via python method calls)"""
        return cloud.get_connection()

    @pytest_cases.case(tags=["cloud", "cloud_client"])
    def case_mqtt(
        self, cloud: Cloud, cloud_ca_public_key, cloud_client_private_key, cloud_client_public_key_chain, request
    ):
        """Connection to cloud as regular mqtt client (using aws iot client library)"""
        try:
            cloud_client_name = request.getfixturevalue("cloud_client_name")
        except LookupError:
            cloud_client_name = "test"
        return AwsMqttClientMqttConnection(
            cloud.endpoint,
            cloud_client_name,
            cloud_ca_public_key,
            cloud_client_public_key_chain,
            cloud_client_private_key,
        )
