# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import pytest
from flask import Flask, jsonify, request, session

from iatoolkit.common import oauth_state_store
from iatoolkit.infra.redis_session_manager import RedisSessionManager


class FakeRedis:
    def __init__(self):
        self.data = {}
        self.ttls = {}

    def set(self, key, value, ex=None, **kwargs):
        self.data[key] = value
        self.ttls[key] = ex
        return True

    def get(self, key):
        return self.data.get(key)

    def delete(self, key):
        return 1 if self.data.pop(key, None) is not None else 0


class BrokenRedis:
    def __getattr__(self, name):
        raise ConnectionError("redis down")


@pytest.fixture
def redis_store():
    fake = FakeRedis()
    RedisSessionManager.set_client(fake)
    yield fake
    RedisSessionManager.clear_client()


@pytest.fixture
def app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["SESSION_COOKIE_SECURE"] = True

    @app.get("/start/<state>")
    def start(state):
        oauth_state_store.save("google", state, {"nonce": f"nonce-{state}", "lang": request.args.get("lang", "en")})
        return oauth_state_store.with_binding_cookie(jsonify(ok=True))

    @app.get("/peek/<state>")
    def peek(state):
        return jsonify(entry=oauth_state_store.peek("google", state))

    @app.get("/take/<state>")
    def take(state):
        return jsonify(entry=oauth_state_store.take("google", state))

    @app.get("/overwrite-session")
    def overwrite_session():
        # What a slow request that read the session before the sign-in does when it ends.
        session.clear()
        session["user_identifier"] = "someone@example.com"
        return jsonify(ok=True)

    return app


def test_a_pending_sign_in_survives_a_request_that_rewrites_the_session(app, redis_store):
    """The production failure: another tab wrote back a stale session while the person was at Google."""
    client = app.test_client()
    client.get("/start/s1?lang=es")

    client.get("/overwrite-session")

    assert client.get("/take/s1").json["entry"] == {"nonce": "nonce-s1", "lang": "es"}


def test_each_sign_in_is_its_own_redis_key_with_a_ttl(app, redis_store):
    client = app.test_client()
    client.get("/start/s1")
    client.get("/start/s2")

    assert set(redis_store.data) == {"oauth_state:google:s1", "oauth_state:google:s2"}
    assert set(redis_store.ttls.values()) == {oauth_state_store.TTL_SECONDS}
    # parallel sign-ins (two tabs) both finish
    assert client.get("/take/s1").json["entry"]["nonce"] == "nonce-s1"
    assert client.get("/take/s2").json["entry"]["nonce"] == "nonce-s2"


def test_a_state_is_used_once(app, redis_store):
    client = app.test_client()
    client.get("/start/s1")

    assert client.get("/take/s1").json["entry"] is not None
    assert client.get("/take/s1").json["entry"] is None
    assert redis_store.data == {}


def test_another_browser_cannot_use_the_state(app, redis_store):
    client = app.test_client()
    client.get("/start/s1")

    other_browser = app.test_client()
    assert other_browser.get("/peek/s1").json["entry"] is None

    forged = app.test_client()
    forged.set_cookie(oauth_state_store.BINDING_COOKIE, "not-the-binding")
    assert forged.get("/peek/s1").json["entry"] is None

    assert client.get("/peek/s1").json["entry"] is not None


def test_an_expired_sign_in_is_refused(app, redis_store, monkeypatch):
    client = app.test_client()
    client.get("/start/s1")
    real_time = oauth_state_store.time.time
    monkeypatch.setattr(oauth_state_store.time, "time", lambda: real_time() + oauth_state_store.TTL_SECONDS + 1)

    assert client.get("/peek/s1").json["entry"] is None


def test_the_binding_cookie_is_http_only_lax_and_short_lived(app, redis_store):
    response = app.test_client().get("/start/s1")

    cookie = response.headers["Set-Cookie"]
    assert cookie.startswith(f"{oauth_state_store.BINDING_COOKIE}=")
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie
    assert "Secure" in cookie
    assert f"Max-Age={oauth_state_store.TTL_SECONDS}" in cookie


def test_the_browser_keeps_its_binding_across_sign_ins(app, redis_store):
    client = app.test_client()
    first = client.get("/start/s1").headers["Set-Cookie"].split(";")[0]
    second = client.get("/start/s2").headers["Set-Cookie"].split(";")[0]

    assert first == second


def test_without_redis_the_session_keeps_the_sign_in(app):
    RedisSessionManager.set_client(BrokenRedis())
    try:
        client = app.test_client()
        client.get("/start/s1")

        assert client.get("/take/s1").json["entry"]["nonce"] == "nonce-s1"
        assert client.get("/take/s1").json["entry"] is None
    finally:
        RedisSessionManager.clear_client()
