import json
from unittest.mock import MagicMock, patch

import pytest

from iatoolkit.infra.connectors.file_connector_factory import FileConnectorFactory


def test_create_gdrive_connector_with_service_account_secret_ref():
    secret_provider = MagicMock()
    secret_provider.get_secret.return_value = json.dumps(
        {
            "type": "service_account",
            "client_email": "svc@example.iam.gserviceaccount.com",
            "private_key": "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )

    with patch("iatoolkit.infra.connectors.file_connector_factory.GoogleDriveConnector") as connector_cls:
        FileConnectorFactory.create(
            {
                "type": "gdrive",
                "folder_id": "folder-123",
                "service_account_secret_ref": "GDRIVE_SA_JSON",
            },
            company_short_name="acme",
            secret_provider=secret_provider,
        )

    secret_provider.get_secret.assert_called_once_with("acme", "GDRIVE_SA_JSON", default=None)
    connector_cls.assert_called_once()
    kwargs = connector_cls.call_args.kwargs
    assert kwargs["folder_id"] == "folder-123"
    assert kwargs["service_account_path"] == "service_account.json"
    assert kwargs["service_account_info"]["client_email"] == "svc@example.iam.gserviceaccount.com"


def test_create_gcs_connector_with_service_account_secret_ref():
    secret_provider = MagicMock()
    secret_provider.get_secret.return_value = json.dumps(
        {
            "type": "service_account",
            "client_email": "svc@example.iam.gserviceaccount.com",
            "private_key": "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )

    with patch("iatoolkit.infra.connectors.file_connector_factory.GoogleCloudStorageConnector") as connector_cls:
        FileConnectorFactory.create(
            {
                "type": "gcs",
                "bucket": "bucket-123",
                "service_account_secret_ref": "GCS_SA_JSON",
            },
            company_short_name="acme",
            secret_provider=secret_provider,
        )

    secret_provider.get_secret.assert_called_once_with("acme", "GCS_SA_JSON", default=None)
    connector_cls.assert_called_once()
    kwargs = connector_cls.call_args.kwargs
    assert kwargs["bucket_name"] == "bucket-123"
    assert kwargs["service_account_path"] == "service_account.json"
    assert kwargs["service_account_info"]["client_email"] == "svc@example.iam.gserviceaccount.com"


def test_create_connector_with_invalid_service_account_secret_json_raises():
    secret_provider = MagicMock()
    secret_provider.get_secret.return_value = "{not-json"

    with pytest.raises(ValueError, match="valid JSON service account payload"):
        FileConnectorFactory.create(
            {
                "type": "gdrive",
                "folder_id": "folder-123",
                "service_account_secret_ref": "BROKEN_JSON",
            },
            company_short_name="acme",
            secret_provider=secret_provider,
        )
