# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import pytest
from itsdangerous import URLSafeSerializer

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.services import storage_service as storage_module
from iatoolkit.services.storage_service import StorageService


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setenv("IATOOLKIT_SECRET_KEY", "k" * 64)
    monkeypatch.delenv("IAT_DOWNLOAD_TOKEN_MAX_AGE_DAYS", raising=False)
    # The token methods only read the environment: no storage backend needed.
    return StorageService.__new__(StorageService)


def _at(monkeypatch, seconds):
    monkeypatch.setattr("itsdangerous.timed.time.time", lambda: seconds)


def test_a_token_resolves_to_its_file(service):
    token = service.create_download_token("acme", "acme/downloads/x.pdf", filename="report.pdf")

    payload = service.resolve_download_token(token)

    assert payload["company"] == "acme"
    assert payload["storage_key"] == "acme/downloads/x.pdf"
    assert payload["filename"] == "report.pdf"


def test_a_token_expires_after_the_default_30_days(service, monkeypatch):
    _at(monkeypatch, 1_000_000)
    token = service.create_download_token("acme", "acme/downloads/x.pdf")

    _at(monkeypatch, 1_000_000 + 29 * 86400)
    assert service.resolve_download_token(token)["company"] == "acme"

    _at(monkeypatch, 1_000_000 + 31 * 86400)
    with pytest.raises(IAToolkitException, match="Expired download token"):
        service.resolve_download_token(token)


def test_the_lifetime_is_configurable(service, monkeypatch):
    monkeypatch.setenv("IAT_DOWNLOAD_TOKEN_MAX_AGE_DAYS", "1")
    _at(monkeypatch, 1_000_000)
    token = service.create_download_token("acme", "acme/downloads/x.pdf")

    _at(monkeypatch, 1_000_000 + 2 * 86400)
    with pytest.raises(IAToolkitException, match="Expired"):
        service.resolve_download_token(token)


def test_an_unusable_lifetime_falls_back_to_the_default(service, monkeypatch):
    for value in ("abc", "0", "-3"):
        monkeypatch.setenv("IAT_DOWNLOAD_TOKEN_MAX_AGE_DAYS", value)
        assert service._download_token_max_age_seconds() == 30 * 86400


def test_an_old_token_without_expiry_is_refused(service):
    """v1 links never expired; they are not accepted any more."""
    old = URLSafeSerializer("k" * 64, salt="iatoolkit-download-token-v1").dumps(
        {"v": 1, "company": "acme", "storage_key": "acme/downloads/x.pdf"})

    with pytest.raises(IAToolkitException, match="Invalid download token"):
        service.resolve_download_token(old)


def test_a_token_signed_with_another_key_is_refused(service, monkeypatch):
    token = service.create_download_token("acme", "acme/downloads/x.pdf")
    monkeypatch.setenv("IATOOLKIT_SECRET_KEY", "z" * 64)

    with pytest.raises(IAToolkitException, match="Invalid download token"):
        service.resolve_download_token(token)
    assert storage_module.DOWNLOAD_TOKEN_SALT.endswith("v2")
