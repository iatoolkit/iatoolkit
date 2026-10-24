# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import os
from unittest.mock import MagicMock, patch

import pytest

from iatoolkit.services.signup_guard_service import SignupGuardService


class FakeRedisPipeline:
    def __init__(self, store: dict):
        self.store = store
        self.ops = []

    def incr(self, key):
        self.ops.append(('incr', key))
        return self

    def ttl(self, key):
        self.ops.append(('ttl', key))
        return self

    def expire(self, key, seconds):
        self.ops.append(('expire', key, seconds))
        return self

    def execute(self):
        results = []
        for op in self.ops:
            if op[0] == 'incr':
                self.store[op[1]] = self.store.get(op[1], 0) + 1
                results.append(self.store[op[1]])
            elif op[0] == 'ttl':
                results.append(self.store.get(('ttl', op[1]), -1))
            else:
                self.store[('ttl', op[1])] = op[2]
                results.append(True)
        return results


class TestSignupGuardService:
    @pytest.fixture(autouse=True)
    def setup(self):
        env = {"IATOOLKIT_SECRET_KEY": "test-secret"}
        with patch.dict(os.environ, env):
            os.environ.pop('IATOOLKIT_SIGNUP_BOT_GUARD', None)
            os.environ.pop('IATOOLKIT_TRUSTED_PROXY_HOPS', None)
            self.redis_store = {}
            with patch('iatoolkit.services.signup_guard_service.RedisSessionManager.pipeline',
                       side_effect=lambda: FakeRedisPipeline(self.redis_store)):
                self.service = SignupGuardService()
                yield

    def _form(self, company='acme', issued_ago=10, **extra):
        with patch('itsdangerous.timed.time.time', return_value=1_000_000 - issued_ago):
            token = self.service.issue_form_token(company)
        return {'form_token': token, 'website': '', **extra}

    def _check(self, form, ip='203.0.113.7', email='juan@example.com', company='acme'):
        with patch('itsdangerous.timed.time.time', return_value=1_000_000), \
                patch('iatoolkit.services.signup_guard_service.time.time', return_value=1_000_000):
            return self.service.check(company, form, client_ip=ip, email=email)

    def test_person_who_loaded_the_page_passes(self):
        assert self._check(self._form()) is None

    def test_post_without_form_token_is_rejected(self):
        assert self._check({'website': ''}) == 'missing_form_token'

    def test_tampered_token_is_rejected(self):
        form = self._form()
        form['form_token'] += 'x'
        assert self._check(form) == 'invalid_form_token'

    def test_token_from_another_company_is_rejected(self):
        assert self._check(self._form(company='other')) == 'invalid_form_token'

    def test_honeypot_filled_is_rejected(self):
        assert self._check(self._form(website='http://spam.example')) == 'honeypot'

    def test_form_submitted_too_fast_is_rejected(self):
        assert self._check(self._form(issued_ago=1)) == 'too_fast'

    def test_expired_form_is_reported_as_expired(self):
        form = self._form(issued_ago=SignupGuardService.FORM_TOKEN_MAX_AGE_SECONDS + 60)
        assert self._check(form) == SignupGuardService.EXPIRED

    def test_ip_rate_limit(self):
        for i in range(SignupGuardService.MAX_SIGNUPS_PER_IP):
            assert self._check(self._form(), email=f'user{i}@example.com') is None
        assert self._check(self._form(), email='another@example.com') == 'ip_rate_limit'
        # the window expiry is set once, on the first hit
        assert self.redis_store[('ttl', 'signup_guard:ip:203.0.113.7')] == SignupGuardService.IP_WINDOW_SECONDS

    def test_email_rate_limit_ignores_gmail_dots_and_tags(self):
        variants = ['r.oz.adickso@gmail.com', 'roz.a.di.ckso@gmail.com', 'rozadickso+x@googlemail.com']
        for i, email in enumerate(variants):
            assert self._check(self._form(), ip=f'198.51.100.{i}', email=email) is None
        assert self._check(self._form(), ip='198.51.100.9', email='R.O.Z.adickso@gmail.com') == 'email_rate_limit'

    def test_redis_down_does_not_block_signup(self):
        with patch('iatoolkit.services.signup_guard_service.RedisSessionManager.pipeline',
                   side_effect=ConnectionError('redis down')):
            assert self._check(self._form()) is None

    def test_guard_can_be_disabled_for_automated_tests(self):
        with patch.dict(os.environ, {'IATOOLKIT_SIGNUP_BOT_GUARD': 'off'}):
            assert self._check({}) is None

    def test_normalize_email(self):
        assert SignupGuardService.normalize_email(' J.Uan+promo@Gmail.com ') == 'juan@gmail.com'
        assert SignupGuardService.normalize_email('j.uan+promo@nxedgeinc.com') == 'j.uan@nxedgeinc.com'
        assert SignupGuardService.normalize_email('not-an-email') == ''
        assert SignupGuardService.normalize_email(None) == ''

    def test_client_ip_uses_the_entry_added_by_our_proxy(self):
        request = MagicMock()
        request.remote_addr = '10.0.0.1'
        request.headers = {'X-Forwarded-For': '1.1.1.1, 203.0.113.7'}
        assert SignupGuardService.client_ip(request) == '203.0.113.7'

        with patch.dict(os.environ, {'IATOOLKIT_TRUSTED_PROXY_HOPS': '2'}):
            assert SignupGuardService.client_ip(request) == '1.1.1.1'

        request.headers = {}
        assert SignupGuardService.client_ip(request) == '10.0.0.1'
