# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

from __future__ import annotations

from dataclasses import dataclass
import logging
import os

from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
from requests_oauthlib import OAuth2Session


@dataclass(frozen=True)
class GoogleIdentity:
    subject: str
    email: str
    email_verified: bool
    given_name: str | None = None
    family_name: str | None = None
    full_name: str | None = None
    picture: str | None = None
    locale: str | None = None


class GoogleAuthError(Exception):
    def __init__(self, reason_code: str, message_key: str):
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.message_key = message_key


class GoogleAuthClient:
    AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    SCOPES = ["openid", "email", "profile"]

    def __init__(self):
        self.client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
        self.client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
        self.enabled = str(os.getenv("GOOGLE_OAUTH_ENABLED", "false")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        flask_env = str(os.getenv("FLASK_ENV", "") or "").strip().lower()

        if flask_env == "dev" or str(os.getenv("GOOGLE_OAUTH_ALLOW_INSECURE_TRANSPORT", "false")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

        # Google may expand profile/email scopes to their fully-qualified equivalents
        # in the token response. oauthlib treats that as an error unless relaxed.
        os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

    def is_enabled(self) -> bool:
        return self.enabled and bool(self.client_id) and bool(self.client_secret)

    def build_authorization_url(self, redirect_uri: str, state: str, nonce: str) -> str:
        if not self.is_enabled():
            raise GoogleAuthError("GOOGLE_NOT_ENABLED", "errors.auth.google_login_not_available")

        oauth = OAuth2Session(
            client_id=self.client_id,
            scope=self.SCOPES,
            redirect_uri=redirect_uri,
        )
        authorization_url, _ = oauth.authorization_url(
            self.AUTHORIZATION_URL,
            state=state,
            nonce=nonce,
            prompt="select_account",
        )
        return authorization_url

    def exchange_code_for_identity(
        self,
        *,
        code: str,
        state: str,
        nonce: str,
        redirect_uri: str,
    ) -> GoogleIdentity:
        if not self.is_enabled():
            raise GoogleAuthError("GOOGLE_NOT_ENABLED", "errors.auth.google_login_not_available")

        if not code:
            raise GoogleAuthError("GOOGLE_CODE_MISSING", "errors.auth.google_login_failed")

        oauth = OAuth2Session(
            client_id=self.client_id,
            state=state,
            scope=self.SCOPES,
            redirect_uri=redirect_uri,
        )

        try:
            token_response = oauth.fetch_token(
                token_url=self.TOKEN_URL,
                code=code,
                client_secret=self.client_secret,
                include_client_id=True,
            )
        except Exception as exc:
            logging.exception("Google token exchange failed for redirect_uri=%s", redirect_uri)
            raise GoogleAuthError("GOOGLE_TOKEN_EXCHANGE_FAILED", "errors.auth.google_login_failed") from exc

        raw_id_token = token_response.get("id_token")
        if not raw_id_token:
            raise GoogleAuthError("GOOGLE_ID_TOKEN_MISSING", "errors.auth.google_login_failed")

        try:
            token_info = id_token.verify_oauth2_token(
                raw_id_token,
                GoogleRequest(),
                self.client_id,
            )
        except Exception as exc:
            logging.exception("Google id_token verification failed")
            raise GoogleAuthError("GOOGLE_ID_TOKEN_INVALID", "errors.auth.google_login_failed") from exc

        token_nonce = token_info.get("nonce")
        if nonce and token_nonce != nonce:
            logging.warning(
                "Google nonce mismatch. expected=%s received=%s",
                nonce,
                token_nonce,
            )
            raise GoogleAuthError("GOOGLE_NONCE_MISMATCH", "errors.auth.google_login_failed")

        subject = str(token_info.get("sub") or "").strip()
        email = str(token_info.get("email") or "").strip().lower()
        if not subject or not email:
            raise GoogleAuthError("GOOGLE_IDENTITY_INCOMPLETE", "errors.auth.google_login_failed")

        return GoogleIdentity(
            subject=subject,
            email=email,
            email_verified=bool(token_info.get("email_verified")),
            given_name=token_info.get("given_name"),
            family_name=token_info.get("family_name"),
            full_name=token_info.get("name"),
            picture=token_info.get("picture"),
            locale=token_info.get("locale"),
        )
