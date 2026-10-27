# SPDX-FileCopyrightText: GARDENA GmbH
#
# SPDX-License-Identifier: GPL-3.0-or-later

import os

import pytest


@pytest.fixture
def azure_pipeline_attachments_directory(tmp_path):
    return tmp_path


@pytest.fixture
def azure_pipeline_attachments_add():
    return "TF_BUILD" in os.environ


@pytest.fixture(autouse=True)
def azure_pipeline_add_attachments(azure_pipeline_attachments_directory, azure_pipeline_attachments_add, request):
    if not azure_pipeline_attachments_add:
        yield
        return

    add_pipelines_attachment = None
    try:
        add_pipelines_attachment = request.getfixturevalue("add_pipelines_attachment")
    except LookupError:
        pass

    yield

    if add_pipelines_attachment:
        try:
            for file in azure_pipeline_attachments_directory.iterdir():
                add_pipelines_attachment(file, file.name)
        except BaseException as e:
            print("##vso[task.logissue type=warning;]{0}".format(f"Could not add attachments: {e}"))
