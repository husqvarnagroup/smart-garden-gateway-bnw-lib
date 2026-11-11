# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

pytest_plugins = [
    "bnw.tfw.fixtures.network",
    "bnw.tfw.gateway.fixtures.eventbus",
    "bnw.tfw.fixtures.cloud",
    "bnw.tfw.gateway.fixtures.setups.python_gateway",
    "bnw.tfw.pytest.plugins.azure_pipeline.add_attachments",
]
