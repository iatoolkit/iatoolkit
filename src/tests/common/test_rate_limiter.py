# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import pytest

from iatoolkit.common import rate_limiter


class _FakeRedis:
    """Just the RedisSessionManager surface the limiter uses."""

    def __init__(self):
        self.values, self.ttls = {}, {}

    def pipeline(self):
        fake = self

        class _Pipe:
            def __init__(self):
                self.ops = []

            def incr(self, key):
                self.ops.append(("incr", key)); return self

            def ttl(self, key):
                self.ops.append(("ttl", key)); return self

            def expire(self, key, seconds):
                self.ops.append(("expire", key, seconds)); return self

            def execute(self):
                out = []
                for op in self.ops:
                    if op[0] == "incr":
                        fake.values[op[1]] = fake.values.get(op[1], 0) + 1
                        out.append(fake.values[op[1]])
                    elif op[0] == "ttl":
                        out.append(fake.ttls.get(op[1], -1))
                    else:
                        fake.ttls[op[1]] = op[2]
                        out.append(True)
                return out
        return _Pipe()

    def get(self, key, default=""):
        return str(self.values[key]) if key in self.values else default

    def remove(self, key):
        self.values.pop(key, None)


@pytest.fixture
def redis(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(rate_limiter, "RedisSessionManager", fake)
    monkeypatch.delenv("IAT_RATE_LIMITS", raising=False)
    return fake


def test_over_limit_counts_hits_in_a_window(redis):
    limit = (3, 60)
    results = [rate_limiter.over_limit("login_ip", "1.2.3.4", limit) for _ in range(4)]

    assert results == [False, False, False, True]
    assert list(redis.ttls.values()) == [60]


def test_failures_block_an_account_until_cleared(redis):
    limit = (2, 900)
    assert not rate_limiter.is_blocked("login_account", "ana@acme.com", limit)

    rate_limiter.record_failure("login_account", "ana@acme.com", limit)
    rate_limiter.record_failure("login_account", "ANA@acme.com ", limit)  # same mailbox
    assert rate_limiter.is_blocked("login_account", "ana@acme.com", limit)

    rate_limiter.clear("login_account", "ana@acme.com")
    assert not rate_limiter.is_blocked("login_account", "ana@acme.com", limit)


def test_keys_do_not_carry_emails_or_ips(redis):
    rate_limiter.over_limit("login_ip", "10.0.0.7", (5, 60))
    rate_limiter.record_failure("login_account", "ana@acme.com", (5, 60))

    keys = " ".join(redis.values)
    assert "10.0.0.7" not in keys and "ana@acme.com" not in keys


def test_off_switch(redis, monkeypatch):
    monkeypatch.setenv("IAT_RATE_LIMITS", "off")

    assert not any(rate_limiter.over_limit("login_ip", "1.2.3.4", (1, 60)) for _ in range(5))
    assert redis.values == {}


def test_without_an_identity_nothing_is_counted(redis):
    assert not rate_limiter.over_limit("login_ip", None, (0, 60))
    assert redis.values == {}


def test_fails_open_when_redis_is_down(monkeypatch):
    class _Down:
        def pipeline(self):
            raise ConnectionError("redis down")

        def get(self, *args):
            raise ConnectionError("redis down")

    monkeypatch.setattr(rate_limiter, "RedisSessionManager", _Down())

    assert not rate_limiter.over_limit("login_ip", "1.2.3.4", (0, 60))
    assert not rate_limiter.is_blocked("login_account", "ana@acme.com", (0, 60))
