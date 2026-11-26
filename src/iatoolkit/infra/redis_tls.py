# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""
TLS options for Redis connections (rediss://).

The certificate of a TLS Redis is validated, with the hostname, against the system
CA bundle or the one in IAT_REDIS_TLS_CA_CERTS. Without validation, TLS encrypts but
does not tell the real server from an intermediary in the network.

IAT_REDIS_TLS_VERIFY=false turns validation off for a provider whose certificate
cannot be validated (a self-signed one with no CA to point at); it is logged as a
warning at every connection. A redis:// URL (no TLS) is not affected.
"""

import logging
import os
from urllib.parse import urlparse

_FALSE_VALUES = ("0", "false", "no", "off")


def redis_tls_kwargs(redis_url: str | None) -> dict:
    """Keyword arguments for redis-py's TLS settings, for `redis.Redis(...)` or `from_url`."""
    if urlparse(str(redis_url or "")).scheme != "rediss":
        return {}
    if os.getenv("IAT_REDIS_TLS_VERIFY", "true").strip().lower() in _FALSE_VALUES:
        logging.warning("Redis TLS without certificate validation (IAT_REDIS_TLS_VERIFY=false).")
        return {"ssl_cert_reqs": None}
    kwargs = {"ssl_cert_reqs": "required", "ssl_check_hostname": True}
    ca_certs = os.getenv("IAT_REDIS_TLS_CA_CERTS", "").strip()
    if ca_certs:
        kwargs["ssl_ca_certs"] = ca_certs
    return kwargs
