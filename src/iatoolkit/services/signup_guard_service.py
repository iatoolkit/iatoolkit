# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""Bot detection for the public signup form.

Bots fill the signup form with random names and real people's emails, so every
attempt makes us send a verification email nobody asked for. The checks here run
before any user is created or any email is sent, and add no step for a person:

- a signed form token issued when the page is rendered: a POST without it never
  loaded the page, and one submitted a few seconds after render was not typed;
- a honeypot field hidden from people, which bots fill in;
- per-IP and per-email rate limits in Redis.

A rejected bot is answered exactly like a successful signup (see SignupView), so
it cannot learn which check stopped it. Only an expired token is reported, since
that is a person who left the page open.
"""

import logging
import os
import time

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from iatoolkit.infra.redis_session_manager import RedisSessionManager


class SignupGuardService:
    FORM_TOKEN_FIELD = 'form_token'
    HONEYPOT_FIELD = 'website'

    MIN_FILL_SECONDS = 3
    FORM_TOKEN_MAX_AGE_SECONDS = 2 * 60 * 60
    MAX_SIGNUPS_PER_IP = 5
    IP_WINDOW_SECONDS = 60 * 60
    MAX_SIGNUPS_PER_EMAIL = 3
    EMAIL_WINDOW_SECONDS = 24 * 60 * 60

    # outcomes of check()
    ALLOWED = None
    EXPIRED = 'form_expired'

    _FORM_TOKEN_SALT = 'signup-form'
    _GMAIL_DOMAINS = {'gmail.com', 'googlemail.com'}

    def __init__(self):
        self.serializer = URLSafeTimedSerializer(os.getenv("IATOOLKIT_SECRET_KEY"))

    @staticmethod
    def is_enabled() -> bool:
        # automated end-to-end tests submit the form faster than a person
        return os.getenv('IATOOLKIT_SIGNUP_BOT_GUARD', 'on').strip().lower() not in ('off', 'false', '0')

    def issue_form_token(self, company_short_name: str) -> str:
        return self.serializer.dumps(company_short_name, salt=self._FORM_TOKEN_SALT)

    def check(self, company_short_name: str, form, client_ip: str | None, email: str | None) -> str | None:
        """Return None when the signup may proceed, or the reason it was rejected."""
        if not self.is_enabled():
            return self.ALLOWED

        reason = self._check_form(company_short_name, form)
        if reason is None:
            reason = self._check_rate_limits(company_short_name, client_ip, email)

        if reason is not None:
            email_domain = (email or '').rpartition('@')[2].lower() or '-'
            logging.warning(
                "signup rejected: reason=%s company=%s ip=%s email_domain=%s",
                reason, company_short_name, client_ip or '-', email_domain,
            )
        return reason

    def _check_form(self, company_short_name: str, form) -> str | None:
        if (form.get(self.HONEYPOT_FIELD) or '').strip():
            return 'honeypot'

        token = form.get(self.FORM_TOKEN_FIELD)
        if not token:
            return 'missing_form_token'
        try:
            token_company, issued_at = self.serializer.loads(
                token,
                salt=self._FORM_TOKEN_SALT,
                max_age=self.FORM_TOKEN_MAX_AGE_SECONDS,
                return_timestamp=True,
            )
        except SignatureExpired:
            return self.EXPIRED
        except BadSignature:
            return 'invalid_form_token'

        if token_company != company_short_name:
            return 'invalid_form_token'
        if time.time() - issued_at.timestamp() < self.MIN_FILL_SECONDS:
            return 'too_fast'
        return None

    def _check_rate_limits(self, company_short_name: str, client_ip: str | None, email: str | None) -> str | None:
        if client_ip and self._hit(f'signup_guard:ip:{client_ip}', self.IP_WINDOW_SECONDS) > self.MAX_SIGNUPS_PER_IP:
            return 'ip_rate_limit'

        normalized_email = self.normalize_email(email)
        if normalized_email and self._hit(
                f'signup_guard:email:{normalized_email}', self.EMAIL_WINDOW_SECONDS) > self.MAX_SIGNUPS_PER_EMAIL:
            return 'email_rate_limit'
        return None

    @staticmethod
    def _hit(key: str, window_seconds: int) -> int:
        """Count one attempt in a fixed window. Fails open: Redis down never blocks a signup."""
        try:
            pipe = RedisSessionManager.pipeline()
            pipe.incr(key)
            pipe.ttl(key)
            count, ttl = pipe.execute()
            if ttl is None or int(ttl) < 0:
                # first hit of the window (or a key left without expiry)
                RedisSessionManager.pipeline().expire(key, window_seconds).execute()
            return int(count)
        except Exception as e:
            logging.warning("signup guard: rate limit unavailable (%s)", e)
            return 0

    @classmethod
    def normalize_email(cls, email: str | None) -> str:
        """One key per mailbox: Gmail ignores dots and +tags, so bots vary them."""
        local, _, domain = str(email or '').strip().lower().partition('@')
        if not local or not domain:
            return ''
        local = local.split('+', 1)[0]
        if domain in cls._GMAIL_DOMAINS:
            local = local.replace('.', '')
            domain = 'gmail.com'
        return f'{local}@{domain}'

    @staticmethod
    def client_ip(request) -> str | None:
        """The client IP as seen by our own proxy.

        Behind Cloudflare (Render's edge) the last X-Forwarded-For entry is a
        Cloudflare node shared by many visitors, so CF-Connecting-IP wins: Cloudflare
        always overwrites it with the visitor's address.

        Otherwise the app sits behind one proxy (the platform router) that appends
        the real client to X-Forwarded-For; anything to its left was sent by the
        client and can be forged. IATOOLKIT_TRUSTED_PROXY_HOPS covers an extra
        proxy in front.
        """
        cf_ip = request.headers.get('CF-Connecting-IP', '').strip()
        if cf_ip:
            return cf_ip

        forwarded = [part.strip() for part in request.headers.get('X-Forwarded-For', '').split(',') if part.strip()]
        try:
            hops = max(1, int(os.getenv('IATOOLKIT_TRUSTED_PROXY_HOPS', '1')))
        except ValueError:
            hops = 1
        if forwarded:
            return forwarded[-hops] if len(forwarded) >= hops else forwarded[0]
        return request.remote_addr
