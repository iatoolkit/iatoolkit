# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from unittest.mock import MagicMock, patch

import pytest

from iatoolkit.infra.google_auth_client import GoogleAuthClient, GoogleAuthError


class TestGoogleAuthClient:
    def test_build_authorization_url_requires_enabled_config(self):
        with patch.dict('os.environ', {}, clear=True):
            client = GoogleAuthClient()

        with pytest.raises(GoogleAuthError) as exc:
            client.build_authorization_url(
                redirect_uri='https://app.test/callback',
                state='oauth-state',
                nonce='oauth-nonce',
            )

        assert exc.value.reason_code == 'GOOGLE_NOT_ENABLED'

    @patch('iatoolkit.infra.google_auth_client.OAuth2Session')
    def test_build_authorization_url_success(self, mock_oauth_session):
        mock_oauth = MagicMock()
        mock_oauth.authorization_url.return_value = ('https://accounts.google.com/mock', 'oauth-state')
        mock_oauth_session.return_value = mock_oauth

        with patch.dict('os.environ', {
            'GOOGLE_OAUTH_ENABLED': 'true',
            'GOOGLE_OAUTH_CLIENT_ID': 'client-id',
            'GOOGLE_OAUTH_CLIENT_SECRET': 'client-secret',
        }):
            client = GoogleAuthClient()
            result = client.build_authorization_url(
                redirect_uri='https://app.test/callback',
                state='oauth-state',
                nonce='oauth-nonce',
            )

        assert result == 'https://accounts.google.com/mock'
        mock_oauth.authorization_url.assert_called_once()

    @patch('iatoolkit.infra.google_auth_client.id_token.verify_oauth2_token')
    @patch('iatoolkit.infra.google_auth_client.OAuth2Session')
    def test_exchange_code_for_identity_success(self, mock_oauth_session, mock_verify_token):
        mock_oauth = MagicMock()
        mock_oauth.fetch_token.return_value = {
            'id_token': 'jwt-token',
        }
        mock_oauth_session.return_value = mock_oauth
        mock_verify_token.return_value = {
            'sub': 'sub-123',
            'email': 'user@example.com',
            'email_verified': True,
            'nonce': 'oauth-nonce',
            'given_name': 'Test',
            'family_name': 'User',
            'name': 'Test User',
        }

        with patch.dict('os.environ', {
            'GOOGLE_OAUTH_ENABLED': 'true',
            'GOOGLE_OAUTH_CLIENT_ID': 'client-id',
            'GOOGLE_OAUTH_CLIENT_SECRET': 'client-secret',
        }):
            client = GoogleAuthClient()
            identity = client.exchange_code_for_identity(
                code='auth-code',
                state='oauth-state',
                nonce='oauth-nonce',
                redirect_uri='https://app.test/callback',
            )

        assert identity.subject == 'sub-123'
        assert identity.email == 'user@example.com'
        assert identity.email_verified is True

    @patch('iatoolkit.infra.google_auth_client.id_token.verify_oauth2_token')
    @patch('iatoolkit.infra.google_auth_client.OAuth2Session')
    def test_exchange_code_for_identity_rejects_nonce_mismatch(self, mock_oauth_session, mock_verify_token):
        mock_oauth = MagicMock()
        mock_oauth.fetch_token.return_value = {
            'id_token': 'jwt-token',
        }
        mock_oauth_session.return_value = mock_oauth
        mock_verify_token.return_value = {
            'sub': 'sub-123',
            'email': 'user@example.com',
            'email_verified': True,
            'nonce': 'unexpected-nonce',
        }

        with patch.dict('os.environ', {
            'GOOGLE_OAUTH_ENABLED': 'true',
            'GOOGLE_OAUTH_CLIENT_ID': 'client-id',
            'GOOGLE_OAUTH_CLIENT_SECRET': 'client-secret',
        }):
            client = GoogleAuthClient()
            with pytest.raises(GoogleAuthError) as exc:
                client.exchange_code_for_identity(
                    code='auth-code',
                    state='oauth-state',
                    nonce='oauth-nonce',
                    redirect_uri='https://app.test/callback',
                )

        assert exc.value.reason_code == 'GOOGLE_NONCE_MISMATCH'
