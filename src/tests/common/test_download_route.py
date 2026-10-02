# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.common.routes import register_views


@pytest.fixture
def client_and_storage():
    app = Flask(__name__)
    app.testing = True
    register_views(app)
    storage = MagicMock()
    storage.resolve_download_token.return_value = {
        "company": "acme",
        "storage_key": "companies/acme/generated_downloads/u1/report.xlsx",
        "filename": "report.xlsx",
    }
    storage.generate_presigned_url.side_effect = NotImplementedError()
    toolkit = MagicMock()
    toolkit.get_injector.return_value.get.return_value = storage
    with patch("iatoolkit.core.current_iatoolkit", return_value=toolkit):
        yield app.test_client(), storage


def test_download_streams_the_file_when_no_presigned_url(client_and_storage):
    client, storage = client_and_storage
    storage.get_document_content.return_value = b"xlsx-bytes"

    response = client.get("/download/token")

    assert response.status_code == 200
    assert response.data == b"xlsx-bytes"


def test_download_of_an_expired_file_is_404(client_and_storage):
    client, storage = client_and_storage
    storage.get_document_content.side_effect = IAToolkitException(
        IAToolkitException.ErrorType.FILE_IO_ERROR, "NoSuchKey",
    )

    response = client.get("/download/token")

    assert response.status_code == 404
    assert b"expired" in response.data
