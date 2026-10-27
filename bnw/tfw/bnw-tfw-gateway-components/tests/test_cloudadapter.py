# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio

import pytest  # type: ignore
from bnw.tfw.component.harness.cloud import AwsIotCloud
from bnw.tfw.gateway.component.commander import cloudadapter
from bnw.tfw.gateway.component.commander.cloudadapter import (
    Cloudadapter,
    CloudadapterPython,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
def free_port(find_free_port):
    return find_free_port()


@pytest.mark.skipif(not cloudadapter.Cloudadapter.is_available(), reason="cloudadapter not available")
async def test_cloudadapter_cloud_connection(
    short_tmpdir,
    eventbus_location,
    cloud: AwsIotCloud,
    cloud_ca_public_key,
    cloud_client_private_key,
    cloud_client_public_key_chain,
):

    gateway_name = "testgateway"

    async with Cloudadapter(
        gateway_name,
        cloud=cloud.endpoint,
        verbose=2,
        eventbus_location=eventbus_location,
        working_directory=short_tmpdir,
    ).with_credentials(cloud_client_public_key_chain, cloud_client_private_key, cloud_ca_public_key):
        await asyncio.wait_for(cloud.published_message("#"), timeout=10.0)
        sessions = cloud.get_sessions()
        assert sessions and len(sessions) == 1
        session = sessions[0]

        assert session.client_id == gateway_name
        assert session.transitions.state == "connected"


@pytest.mark.skipif(not cloudadapter.Cloudadapter.is_available(), reason="cloudadapter not available")
async def test_cloudadapter_python_additional_args(
    short_tmpdir,
    tmp_path,
    eventbus_location,
):

    gateway_name = "testgateway"

    adapter = CloudadapterPython(
        gateway_name,
        cloud="test",
        verbose=2,
        eventbus_location=eventbus_location,
        working_directory=short_tmpdir,
        state_storage_directory=tmp_path,
    )
    assert adapter

    assert "state_storage_directory" in adapter.additional_kwargs
