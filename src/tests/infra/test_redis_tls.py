# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import logging
import ssl

import redis

from iatoolkit.infra.redis_tls import redis_tls_kwargs


def test_a_plain_redis_url_gets_no_tls_options(monkeypatch):
    monkeypatch.delenv("IAT_REDIS_TLS_VERIFY", raising=False)
    assert redis_tls_kwargs("redis://:pw@localhost:6379/0") == {}
    assert redis_tls_kwargs(None) == {}


def test_a_tls_url_validates_the_certificate_and_the_hostname(monkeypatch):
    monkeypatch.delenv("IAT_REDIS_TLS_VERIFY", raising=False)
    monkeypatch.delenv("IAT_REDIS_TLS_CA_CERTS", raising=False)

    assert redis_tls_kwargs("rediss://:pw@redis.example.com:6380") == {
        "ssl_cert_reqs": "required", "ssl_check_hostname": True}


def test_a_custom_ca_bundle_is_passed(monkeypatch):
    monkeypatch.delenv("IAT_REDIS_TLS_VERIFY", raising=False)
    monkeypatch.setenv("IAT_REDIS_TLS_CA_CERTS", "/etc/ssl/redis-ca.pem")

    assert redis_tls_kwargs("rediss://redis.example.com")["ssl_ca_certs"] == "/etc/ssl/redis-ca.pem"


def test_validation_can_be_turned_off_and_is_logged(monkeypatch, caplog):
    monkeypatch.setenv("IAT_REDIS_TLS_VERIFY", "false")

    with caplog.at_level(logging.WARNING):
        kwargs = redis_tls_kwargs("rediss://redis.example.com")

    assert kwargs == {"ssl_cert_reqs": None}
    assert "without certificate validation" in caplog.text


def test_redis_py_builds_a_verifying_tls_connection_from_the_options(monkeypatch):
    """The options are ones redis-py accepts and turns into CERT_REQUIRED + hostname check."""
    monkeypatch.delenv("IAT_REDIS_TLS_VERIFY", raising=False)
    monkeypatch.delenv("IAT_REDIS_TLS_CA_CERTS", raising=False)
    url = "rediss://:pw@redis.example.com:6380/0"

    client = redis.from_url(url, **redis_tls_kwargs(url))

    kwargs = client.connection_pool.connection_kwargs
    connection = client.connection_pool.make_connection()
    assert connection.cert_reqs == ssl.CERT_REQUIRED
    assert connection.check_hostname is True
    assert kwargs["host"] == "redis.example.com"
