# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""
Generic OpenID Connect client: sign-in with the identity provider a company
configures (Microsoft Entra ID, Okta, or any other OIDC provider) — BL-031.

It covers the authorization code flow and nothing else:

* discovery from ``<issuer>/.well-known/openid-configuration``, HTTPS only and
  through the shared SSRF guard, since the issuer is typed in by a tenant;
* the authorization URL, always with PKCE S256, a ``state`` and a ``nonce``;
* the code exchange at the token endpoint;
* full validation of the ``id_token`` against the provider's JWKS: signature
  with an asymmetric algorithm only (never ``none`` or HMAC), ``iss``, ``aud``,
  ``azp``, ``exp``, ``iat`` and ``nonce``.

What the identity is then allowed to do (which company, which e-mail domains,
whether a user may be created) is not decided here: the login flow decides it
with the company's Signup Policy. This module only answers "who did the
provider say this is", and refuses to answer when the token does not prove it.

The issuer is an exact, single-tenant issuer. Multi-tenant endpoints such as
Entra's ``/common`` publish a templated issuer (``{tenantid}``) that cannot be
matched exactly and are therefore rejected at discovery.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlencode

import jwt
import requests

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.common.url_safety import assert_public_http_url, fetch_with_safe_redirects

DISCOVERY_PATH = "/.well-known/openid-configuration"
DEFAULT_SCOPES = ("openid", "email", "profile")
ALLOWED_ALGORITHMS = ("RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512")
HTTP_TIMEOUT_SECONDS = 10
METADATA_TTL_SECONDS = 3600
# A token signed with a key we do not know yet triggers one JWKS refresh (the
# provider rotated its keys), but not more often than this: otherwise anyone
# could make the server hit the provider on every request with made-up kids.
JWKS_FORCED_REFRESH_SECONDS = 60
CLOCK_SKEW_SECONDS = 60
MAX_RESPONSE_BYTES = 512 * 1024


@dataclass(frozen=True)
class OidcProviderConfig:
    """One company's identity provider, as its administrator configured it."""
    issuer: str
    client_id: str
    client_secret: str = field(repr=False)
    scopes: tuple[str, ...] = DEFAULT_SCOPES


@dataclass(frozen=True)
class OidcAuthorizationRequest:
    """What the login flow sends the browser to, and what it must keep in the
    session until the provider calls back."""
    url: str
    state: str
    nonce: str
    code_verifier: str


@dataclass(frozen=True)
class OidcIdentity:
    """
    Who the provider says signed in. ``email_verified`` is None when the
    provider does not say: Entra ID never sends the claim, so the caller decides
    (BL-031: accept it only for the company's own domains).
    """
    issuer: str
    subject: str
    email: str | None
    email_verified: bool | None
    given_name: str | None = None
    family_name: str | None = None
    full_name: str | None = None
    claims: dict = field(default_factory=dict, compare=False, repr=False)


class OidcError(Exception):
    """A sign-in that cannot go on. ``reason_code`` is for the logs, never for
    the user, who gets ``message_key``."""

    def __init__(self, reason_code: str, message_key: str = "errors.auth.sso_login_failed"):
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.message_key = message_key


def normalize_issuer(issuer: str) -> str:
    return str(issuer or "").strip().rstrip("/")


def pkce_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _default_fetch_json(url: str) -> dict:
    response = fetch_with_safe_redirects(
        url,
        allowed_schemes=("https",),
        label="Identity provider URL",
        timeout=HTTP_TIMEOUT_SECONDS,
        headers={"Accept": "application/json"},
    )
    return _json_body(response)


def _default_post_form(url: str, data: dict, auth: tuple[str, str]) -> dict:
    assert_public_http_url(url, allowed_schemes=("https",), label="Identity provider token URL")
    response = requests.post(
        url,
        data=data,
        auth=auth,
        timeout=HTTP_TIMEOUT_SECONDS,
        allow_redirects=False,
        headers={"Accept": "application/json"},
    )
    return _json_body(response)


def _json_body(response: requests.Response) -> dict:
    if len(response.content or b"") > MAX_RESPONSE_BYTES:
        raise OidcError("OIDC_RESPONSE_TOO_LARGE")
    try:
        body = response.json()
    except ValueError as exc:
        raise OidcError("OIDC_RESPONSE_NOT_JSON") from exc
    if not isinstance(body, dict):
        raise OidcError("OIDC_RESPONSE_NOT_JSON")
    if response.status_code >= 400:
        # The provider's error code is safe to log; its description may echo input.
        raise OidcError(f"OIDC_HTTP_{response.status_code}_{str(body.get('error') or 'error')[:40]}")
    return body


class OidcClient:
    """
    Stateless toward the user (the caller keeps state, nonce and verifier in the
    session); caches provider metadata and keys in-process for an hour.
    """

    def __init__(
        self,
        fetch_json: Callable[[str], dict] | None = None,
        post_form: Callable[[str, dict, tuple[str, str]], dict] | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self._fetch_json = fetch_json or _default_fetch_json
        self._post_form = post_form or _default_post_form
        self._clock = clock
        self._lock = threading.Lock()
        self._metadata: dict[str, tuple[float, dict]] = {}
        self._jwks: dict[str, tuple[float, jwt.PyJWKSet]] = {}

    # ------------------------------------------------------------------ discovery

    def discover(self, issuer: str) -> dict:
        issuer = normalize_issuer(issuer)
        if not issuer.startswith("https://"):
            raise OidcError("OIDC_ISSUER_NOT_HTTPS", "errors.auth.sso_not_available")

        now = self._clock()
        with self._lock:
            cached = self._metadata.get(issuer)
            if cached and now - cached[0] < METADATA_TTL_SECONDS:
                return cached[1]

        try:
            metadata = self._fetch_json(issuer + DISCOVERY_PATH)
        except OidcError:
            raise
        except IAToolkitException as exc:
            raise OidcError("OIDC_DISCOVERY_URL_REJECTED", "errors.auth.sso_not_available") from exc
        except Exception as exc:
            logging.warning("OIDC discovery failed. issuer=%s error=%s", issuer, type(exc).__name__)
            raise OidcError("OIDC_DISCOVERY_FAILED", "errors.auth.sso_not_available") from exc

        # The document must describe this very issuer: a mismatch means a
        # templated multi-tenant issuer or a provider serving someone else's.
        if normalize_issuer(metadata.get("issuer")) != issuer:
            raise OidcError("OIDC_DISCOVERY_ISSUER_MISMATCH", "errors.auth.sso_not_available")
        for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            if not str(metadata.get(key) or "").startswith("https://"):
                raise OidcError("OIDC_DISCOVERY_INCOMPLETE", "errors.auth.sso_not_available")

        with self._lock:
            self._metadata[issuer] = (now, metadata)
        return metadata

    def probe(self, issuer: str) -> dict:
        """
        What an administrator's «Probar conexión» checks before anyone signs in:
        the issuer publishes valid metadata and at least one signing key. It cannot
        check the client secret; only a real sign-in does.
        """
        metadata = self.discover(issuer)
        key_set = self._key_set(metadata["jwks_uri"], force=False)
        signing_keys = [k for k in key_set.keys if (k.public_key_use or "sig") == "sig"]
        if not signing_keys:
            raise OidcError("OIDC_NO_SIGNING_KEYS", "errors.auth.sso_not_available")
        return {
            "issuer": metadata["issuer"],
            "authorization_endpoint": metadata["authorization_endpoint"],
            "token_endpoint": metadata["token_endpoint"],
            "signing_keys": len(signing_keys),
            "pkce_s256_advertised": "S256" in (metadata.get("code_challenge_methods_supported") or []),
        }

    # -------------------------------------------------------------- authorization

    def build_authorization_request(self, config: OidcProviderConfig, redirect_uri: str,
                                    *, login_hint: str | None = None) -> OidcAuthorizationRequest:
        metadata = self.discover(config.issuer)
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)

        params = {
            "response_type": "code",
            "client_id": config.client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(config.scopes),
            "state": state,
            "nonce": nonce,
            "code_challenge": pkce_challenge(code_verifier),
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
        if login_hint:
            params["login_hint"] = login_hint

        endpoint = metadata["authorization_endpoint"]
        separator = "&" if "?" in endpoint else "?"
        return OidcAuthorizationRequest(
            url=f"{endpoint}{separator}{urlencode(params)}",
            state=state,
            nonce=nonce,
            code_verifier=code_verifier,
        )

    # ------------------------------------------------------------- code exchange

    def exchange_code(self, config: OidcProviderConfig, *, code: str, redirect_uri: str,
                      code_verifier: str, nonce: str) -> OidcIdentity:
        if not code:
            raise OidcError("OIDC_CODE_MISSING")
        if not code_verifier or not nonce:
            raise OidcError("OIDC_SESSION_STATE_MISSING")

        metadata = self.discover(config.issuer)
        try:
            # client_secret_basic: the method every provider must support (RFC 6749 2.3.1),
            # and Okta's default for web apps.
            token_response = self._post_form(
                metadata["token_endpoint"],
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "code_verifier": code_verifier,
                },
                (config.client_id, config.client_secret),
            )
        except OidcError as exc:
            logging.warning("OIDC token exchange failed. issuer=%s reason=%s", config.issuer, exc.reason_code)
            raise
        except Exception as exc:
            logging.warning("OIDC token exchange failed. issuer=%s error=%s", config.issuer, type(exc).__name__)
            raise OidcError("OIDC_TOKEN_EXCHANGE_FAILED") from exc

        raw_id_token = token_response.get("id_token")
        if not raw_id_token:
            raise OidcError("OIDC_ID_TOKEN_MISSING")

        claims = self.validate_id_token(config, raw_id_token, nonce=nonce)
        return self._identity_from_claims(config, claims)

    # ------------------------------------------------------------ id_token checks

    def validate_id_token(self, config: OidcProviderConfig, raw_id_token: str, *, nonce: str) -> dict:
        issuer = normalize_issuer(config.issuer)
        metadata = self.discover(issuer)

        try:
            header = jwt.get_unverified_header(raw_id_token)
        except jwt.PyJWTError as exc:
            raise OidcError("OIDC_ID_TOKEN_MALFORMED") from exc

        algorithm = header.get("alg")
        if algorithm not in ALLOWED_ALGORITHMS:
            raise OidcError("OIDC_ID_TOKEN_ALGORITHM_REJECTED")

        signing_key = self._signing_key(metadata["jwks_uri"], header.get("kid"))

        try:
            claims = jwt.decode(
                raw_id_token,
                key=signing_key,
                algorithms=[algorithm],
                audience=config.client_id,
                issuer=metadata["issuer"],
                leeway=CLOCK_SKEW_SECONDS,
                options={"require": ["iss", "sub", "aud", "exp", "iat"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise OidcError("OIDC_ID_TOKEN_EXPIRED") from exc
        except jwt.InvalidAudienceError as exc:
            raise OidcError("OIDC_ID_TOKEN_AUDIENCE_MISMATCH") from exc
        except jwt.InvalidIssuerError as exc:
            raise OidcError("OIDC_ID_TOKEN_ISSUER_MISMATCH") from exc
        except jwt.InvalidSignatureError as exc:
            raise OidcError("OIDC_ID_TOKEN_SIGNATURE_INVALID") from exc
        except jwt.PyJWTError as exc:
            raise OidcError("OIDC_ID_TOKEN_INVALID") from exc

        # With more than one audience, the token must name us as the party it was issued to.
        audiences = claims["aud"] if isinstance(claims["aud"], list) else [claims["aud"]]
        if len(audiences) > 1 and claims.get("azp") != config.client_id:
            raise OidcError("OIDC_ID_TOKEN_AZP_MISMATCH")

        token_nonce = str(claims.get("nonce") or "")
        if not token_nonce or not hmac.compare_digest(token_nonce, nonce):
            raise OidcError("OIDC_NONCE_MISMATCH")

        if not str(claims.get("sub") or "").strip():
            raise OidcError("OIDC_IDENTITY_INCOMPLETE")
        return claims

    def _signing_key(self, jwks_uri: str, kid: str | None):
        key = self._find_key(self._key_set(jwks_uri, force=False), kid)
        if key is None:
            # Unknown kid: the provider may have rotated its keys since we cached them.
            key = self._find_key(self._key_set(jwks_uri, force=True), kid)
        if key is None:
            raise OidcError("OIDC_SIGNING_KEY_NOT_FOUND")
        return key

    @staticmethod
    def _find_key(key_set: jwt.PyJWKSet | None, kid: str | None):
        if key_set is None:
            return None
        candidates = [k for k in key_set.keys if kid is None or k.key_id == kid]
        # Without a kid, only an unambiguous single key is acceptable.
        if kid is None and len(candidates) != 1:
            return None
        for candidate in candidates:
            # Keys published for encryption are not signing keys. The key type
            # must also fit the algorithm; jwt.decode enforces that afterwards.
            if (candidate.public_key_use or "sig") != "sig":
                continue
            return candidate.key
        return None

    def _key_set(self, jwks_uri: str, *, force: bool) -> jwt.PyJWKSet | None:
        now = self._clock()
        with self._lock:
            cached = self._jwks.get(jwks_uri)
        if cached:
            age = now - cached[0]
            if not force and age < METADATA_TTL_SECONDS:
                return cached[1]
            if force and age < JWKS_FORCED_REFRESH_SECONDS:
                return cached[1]

        try:
            key_set = jwt.PyJWKSet.from_dict(self._fetch_json(jwks_uri))
        except Exception as exc:
            logging.warning("OIDC JWKS fetch failed. jwks_uri=%s error=%s", jwks_uri, type(exc).__name__)
            if cached:
                return cached[1]
            raise OidcError("OIDC_JWKS_UNAVAILABLE", "errors.auth.sso_not_available") from exc

        with self._lock:
            self._jwks[jwks_uri] = (now, key_set)
        return key_set

    # ----------------------------------------------------------------- identity

    @staticmethod
    def _identity_from_claims(config: OidcProviderConfig, claims: dict) -> OidcIdentity:
        email = str(claims.get("email") or "").strip().lower() or None
        verified = claims.get("email_verified")
        if isinstance(verified, str):
            verified = verified.strip().lower() == "true"
        elif verified is not None:
            verified = bool(verified)

        return OidcIdentity(
            issuer=normalize_issuer(claims.get("iss") or config.issuer),
            subject=str(claims["sub"]).strip(),
            email=email,
            email_verified=verified,
            given_name=claims.get("given_name"),
            family_name=claims.get("family_name"),
            full_name=claims.get("name"),
            claims=claims,
        )
