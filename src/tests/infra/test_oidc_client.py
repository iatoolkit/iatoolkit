# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import base64
import json
import time
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from jwt.algorithms import ECAlgorithm, RSAAlgorithm

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.infra.oidc_client import (
    JWKS_FORCED_REFRESH_SECONDS,
    METADATA_TTL_SECONDS,
    OidcClient,
    OidcError,
    OidcProviderConfig,
    pkce_challenge,
)

ISSUER = "https://login.example-idp.com/tenant-1/v2.0"
JWKS_URI = "https://login.example-idp.com/tenant-1/keys"
TOKEN_URI = "https://login.example-idp.com/tenant-1/token"
CONFIG = OidcProviderConfig(issuer=ISSUER, client_id="client-1", client_secret="secret-1")
NONCE = "nonce-123"


def _rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk(private_key, kid, alg="RS256"):
    algorithm = RSAAlgorithm if isinstance(private_key, rsa.RSAPrivateKey) else ECAlgorithm
    data = json.loads(algorithm.to_jwk(private_key.public_key()))
    data.update({"kid": kid, "use": "sig", "alg": alg})
    return data


class FakeIdp:
    """Discovery, JWKS and token endpoints answered in memory."""

    def __init__(self):
        self.key = _rsa_key()
        self.keys = [_jwk(self.key, "kid-1")]
        self.metadata = {
            "issuer": ISSUER,
            "authorization_endpoint": "https://login.example-idp.com/tenant-1/authorize",
            "token_endpoint": TOKEN_URI,
            "jwks_uri": JWKS_URI,
        }
        self.token_response = {}
        self.fetches = []
        self.posts = []
        self.now = time.time()

    def fetch_json(self, url):
        self.fetches.append(url)
        if url == ISSUER + "/.well-known/openid-configuration":
            return dict(self.metadata)
        if url == JWKS_URI:
            return {"keys": list(self.keys)}
        raise AssertionError(f"unexpected fetch {url}")

    def post_form(self, url, data, auth):
        self.posts.append((url, data, auth))
        return dict(self.token_response)

    def client(self):
        return OidcClient(fetch_json=self.fetch_json, post_form=self.post_form, clock=lambda: self.now)

    def id_token(self, key=None, kid="kid-1", alg="RS256", **overrides):
        now = int(time.time())
        claims = {
            "iss": ISSUER, "sub": "subject-1", "aud": "client-1", "iat": now, "exp": now + 300,
            "nonce": NONCE, "email": "Ana@Acme.com", "name": "Ana Pérez",
        }
        claims.update(overrides)
        claims = {k: v for k, v in claims.items() if v is not None}
        return jwt.encode(claims, key or self.key, algorithm=alg, headers={"kid": kid} if kid else {})


@pytest.fixture
def idp():
    return FakeIdp()


# ----------------------------------------------------------------- authorization

def test_authorization_url_carries_pkce_s256_state_and_nonce(idp):
    request = idp.client().build_authorization_request(CONFIG, "https://app.test/auth/sso/callback")

    url = urlparse(request.url)
    params = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert f"{url.scheme}://{url.netloc}{url.path}" == idp.metadata["authorization_endpoint"]
    assert params["response_type"] == "code"
    assert params["client_id"] == "client-1"
    assert params["redirect_uri"] == "https://app.test/auth/sso/callback"
    assert params["scope"] == "openid email profile"
    assert params["state"] == request.state
    assert params["nonce"] == request.nonce
    assert params["code_challenge_method"] == "S256"
    assert params["code_challenge"] == pkce_challenge(request.code_verifier)
    assert request.code_verifier not in request.url


def test_pkce_challenge_is_unpadded_base64url_sha256():
    import hashlib
    verifier = "a" * 64
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()

    challenge = pkce_challenge(verifier)

    assert challenge == expected
    assert len(challenge) == 43 and "=" not in challenge and "+" not in challenge and "/" not in challenge


def test_each_request_gets_fresh_secrets(idp):
    client = idp.client()
    first = client.build_authorization_request(CONFIG, "https://app.test/cb")
    second = client.build_authorization_request(CONFIG, "https://app.test/cb")

    assert first.state != second.state
    assert first.nonce != second.nonce
    assert first.code_verifier != second.code_verifier


# ----------------------------------------------------------------------- discovery

def test_discovery_is_cached(idp):
    client = idp.client()
    client.discover(ISSUER)
    client.discover(ISSUER + "/")

    assert idp.fetches.count(ISSUER + "/.well-known/openid-configuration") == 1

    idp.now += METADATA_TTL_SECONDS + 1
    client.discover(ISSUER)
    assert idp.fetches.count(ISSUER + "/.well-known/openid-configuration") == 2


def test_discovery_rejects_an_http_issuer(idp):
    with pytest.raises(OidcError) as exc:
        idp.client().discover("http://login.example-idp.com/tenant-1")

    assert exc.value.reason_code == "OIDC_ISSUER_NOT_HTTPS"
    assert idp.fetches == []


def test_discovery_rejects_a_document_for_another_issuer(idp):
    # Entra's multi-tenant /common endpoint publishes a templated issuer.
    idp.metadata["issuer"] = "https://login.example-idp.com/{tenantid}/v2.0"

    with pytest.raises(OidcError) as exc:
        idp.client().discover(ISSUER)

    assert exc.value.reason_code == "OIDC_DISCOVERY_ISSUER_MISMATCH"


def test_discovery_rejects_non_https_endpoints(idp):
    idp.metadata["token_endpoint"] = "http://login.example-idp.com/token"

    with pytest.raises(OidcError) as exc:
        idp.client().discover(ISSUER)

    assert exc.value.reason_code == "OIDC_DISCOVERY_INCOMPLETE"


def test_discovery_blocked_by_the_ssrf_guard_is_reported_as_unavailable():
    def fetch_json(url):
        raise IAToolkitException(IAToolkitException.ErrorType.INVALID_PARAMETER, "private address")

    with pytest.raises(OidcError) as exc:
        OidcClient(fetch_json=fetch_json).discover("https://idp.internal-looking.example")

    assert exc.value.reason_code == "OIDC_DISCOVERY_URL_REJECTED"
    assert exc.value.message_key == "errors.auth.sso_not_available"


# ------------------------------------------------------------------- code exchange

def test_code_exchange_returns_the_identity(idp):
    idp.token_response = {"id_token": idp.id_token(), "access_token": "at"}

    identity = idp.client().exchange_code(
        CONFIG, code="code-1", redirect_uri="https://app.test/cb", code_verifier="verifier-1", nonce=NONCE)

    assert (identity.issuer, identity.subject, identity.email) == (ISSUER, "subject-1", "ana@acme.com")
    assert identity.email_verified is None          # the provider did not say
    assert identity.full_name == "Ana Pérez"
    url, data, auth = idp.posts[0]
    assert url == TOKEN_URI
    assert data == {"grant_type": "authorization_code", "code": "code-1",
                    "redirect_uri": "https://app.test/cb", "code_verifier": "verifier-1"}
    assert auth == ("client-1", "secret-1")


@pytest.mark.parametrize("claim, expected", [(True, True), (False, False), ("true", True), ("false", False)])
def test_email_verified_is_read_when_the_provider_sends_it(idp, claim, expected):
    idp.token_response = {"id_token": idp.id_token(email_verified=claim)}

    identity = idp.client().exchange_code(
        CONFIG, code="c", redirect_uri="https://app.test/cb", code_verifier="v", nonce=NONCE)

    assert identity.email_verified is expected


def test_code_exchange_without_id_token_fails(idp):
    idp.token_response = {"access_token": "at"}

    with pytest.raises(OidcError) as exc:
        idp.client().exchange_code(CONFIG, code="c", redirect_uri="https://app.test/cb",
                                   code_verifier="v", nonce=NONCE)

    assert exc.value.reason_code == "OIDC_ID_TOKEN_MISSING"


def test_code_exchange_requires_code_and_session_state(idp):
    client = idp.client()
    with pytest.raises(OidcError) as missing_code:
        client.exchange_code(CONFIG, code="", redirect_uri="x", code_verifier="v", nonce=NONCE)
    with pytest.raises(OidcError) as missing_verifier:
        client.exchange_code(CONFIG, code="c", redirect_uri="x", code_verifier="", nonce=NONCE)

    assert missing_code.value.reason_code == "OIDC_CODE_MISSING"
    assert missing_verifier.value.reason_code == "OIDC_SESSION_STATE_MISSING"
    assert idp.posts == []


# -------------------------------------------------------------- id_token validation

def _reason(idp, token, nonce=NONCE):
    with pytest.raises(OidcError) as exc:
        idp.client().validate_id_token(CONFIG, token, nonce=nonce)
    return exc.value.reason_code


def test_a_valid_token_passes(idp):
    claims = idp.client().validate_id_token(CONFIG, idp.id_token(), nonce=NONCE)
    assert claims["sub"] == "subject-1"


def test_another_issuer_is_rejected(idp):
    assert _reason(idp, idp.id_token(iss="https://evil.example.com")) == "OIDC_ID_TOKEN_ISSUER_MISMATCH"


def test_another_audience_is_rejected(idp):
    assert _reason(idp, idp.id_token(aud="someone-else")) == "OIDC_ID_TOKEN_AUDIENCE_MISMATCH"


def test_several_audiences_need_azp_to_be_us(idp):
    assert _reason(idp, idp.id_token(aud=["client-1", "other"])) == "OIDC_ID_TOKEN_AZP_MISMATCH"
    claims = idp.client().validate_id_token(
        CONFIG, idp.id_token(aud=["client-1", "other"], azp="client-1"), nonce=NONCE)
    assert claims["azp"] == "client-1"


def test_an_expired_token_is_rejected(idp):
    past = int(time.time()) - 3600
    assert _reason(idp, idp.id_token(iat=past - 300, exp=past)) == "OIDC_ID_TOKEN_EXPIRED"


def test_a_different_nonce_is_rejected(idp):
    assert _reason(idp, idp.id_token(), nonce="other-nonce") == "OIDC_NONCE_MISMATCH"
    assert _reason(idp, idp.id_token(nonce=None)) == "OIDC_NONCE_MISMATCH"


def test_missing_required_claims_are_rejected(idp):
    assert _reason(idp, idp.id_token(exp=None)) == "OIDC_ID_TOKEN_INVALID"
    assert _reason(idp, idp.id_token(sub=None)) == "OIDC_ID_TOKEN_INVALID"


def test_alg_none_is_rejected(idp):
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none", "kid": "kid-1"}).encode()).rstrip(b"=")
    body = base64.urlsafe_b64encode(json.dumps({"iss": ISSUER, "sub": "x"}).encode()).rstrip(b"=")
    token = f"{header.decode()}.{body.decode()}."

    assert _reason(idp, token) == "OIDC_ID_TOKEN_ALGORITHM_REJECTED"


def test_hmac_signed_with_the_public_key_is_rejected(idp):
    # Algorithm confusion: HS256 keyed with the provider's public key.
    token = jwt.encode({"iss": ISSUER, "sub": "x"}, "any-shared-secret", algorithm="HS256",
                       headers={"kid": "kid-1"})

    assert _reason(idp, token) == "OIDC_ID_TOKEN_ALGORITHM_REJECTED"


def test_a_token_signed_by_another_key_is_rejected(idp):
    assert _reason(idp, idp.id_token(key=_rsa_key())) == "OIDC_ID_TOKEN_SIGNATURE_INVALID"


def test_a_malformed_token_is_rejected(idp):
    assert _reason(idp, "not-a-jwt") == "OIDC_ID_TOKEN_MALFORMED"


def test_an_es256_provider_works(idp):
    ec_key = ec.generate_private_key(ec.SECP256R1())
    idp.keys = [_jwk(ec_key, "ec-1", alg="ES256")]

    claims = idp.client().validate_id_token(CONFIG, idp.id_token(key=ec_key, kid="ec-1", alg="ES256"), nonce=NONCE)

    assert claims["sub"] == "subject-1"


# ------------------------------------------------------------------- key rotation

def test_an_unknown_kid_refreshes_the_keys_once(idp):
    client = idp.client()
    client.validate_id_token(CONFIG, idp.id_token(), nonce=NONCE)   # caches kid-1

    idp.now += JWKS_FORCED_REFRESH_SECONDS + 1
    new_key = _rsa_key()
    idp.keys = [_jwk(new_key, "kid-2")]

    claims = client.validate_id_token(CONFIG, idp.id_token(key=new_key, kid="kid-2"), nonce=NONCE)

    assert claims["sub"] == "subject-1"
    assert idp.fetches.count(JWKS_URI) == 2


def test_made_up_kids_do_not_hammer_the_provider(idp):
    client = idp.client()
    client.validate_id_token(CONFIG, idp.id_token(), nonce=NONCE)

    for i in range(5):
        with pytest.raises(OidcError) as exc:
            client.validate_id_token(CONFIG, idp.id_token(kid=f"made-up-{i}"), nonce=NONCE)
        assert exc.value.reason_code == "OIDC_SIGNING_KEY_NOT_FOUND"

    assert idp.fetches.count(JWKS_URI) == 1


def test_without_kid_only_a_single_key_is_accepted(idp):
    assert idp.client().validate_id_token(CONFIG, idp.id_token(kid=None), nonce=NONCE)["sub"] == "subject-1"

    other = _rsa_key()
    idp.keys.append(_jwk(other, "kid-2"))
    fresh = idp.client()
    assert _reason_with(fresh, idp.id_token(kid=None)) == "OIDC_SIGNING_KEY_NOT_FOUND"


def test_encryption_keys_are_not_used_for_signatures(idp):
    idp.keys[0]["use"] = "enc"
    assert _reason(idp, idp.id_token()) == "OIDC_SIGNING_KEY_NOT_FOUND"


def _reason_with(client, token):
    with pytest.raises(OidcError) as exc:
        client.validate_id_token(CONFIG, token, nonce=NONCE)
    return exc.value.reason_code


def test_probe_reports_the_provider(idp):
    idp.metadata["code_challenge_methods_supported"] = ["S256"]

    report = idp.client().probe(ISSUER)

    assert report == {"issuer": ISSUER, "authorization_endpoint": idp.metadata["authorization_endpoint"],
                      "token_endpoint": TOKEN_URI, "signing_keys": 1, "pkce_s256_advertised": True}


def test_probe_fails_without_signing_keys(idp):
    idp.keys[0]["use"] = "enc"

    with pytest.raises(OidcError) as exc:
        idp.client().probe(ISSUER)

    assert exc.value.reason_code == "OIDC_NO_SIGNING_KEYS"
