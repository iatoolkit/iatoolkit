# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""
Shared SSRF guard for URLs that arrive from tenants or API callers and that the
server will then connect to itself: task callback URLs, attachment downloads,
MCP image fetches, and similar.

Checking only literal IPs (``https://10.0.0.5/...``) is not enough - an
attacker-controlled hostname can resolve to 10.x / 169.254.169.254 / ::1 just
as well, and a public URL can 302 to one. This module therefore:

* requires an absolute URL with an allowed scheme and a hostname;
* rejects well-known local names (localhost, *.local, *.localhost, *.internal);
* rejects literal IPs that are private, loopback, link-local, multicast,
  reserved or unspecified;
* resolves hostnames and rejects them when ANY resolved address falls in those
  ranges (fail-closed on a private answer; fail-open only when the name cannot
  be resolved at all, since that request could not have reached anything);
* offers ``fetch_with_safe_redirects`` which never lets ``requests`` follow a
  redirect blindly: every hop is re-validated with the same rules.

Validate-then-connect still leaves a small DNS-rebinding window (the resolver
may return a different address at connect time); closing it fully needs
connection-level IP pinning, which is out of scope here. Callers should also
disable redirects on the actual request or use ``fetch_with_safe_redirects``.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import ParseResult, urljoin, urlparse

import requests

from iatoolkit.common.exceptions import IAToolkitException

_BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain"}
_BLOCKED_HOST_SUFFIXES = (".local", ".localhost", ".internal")
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


def classify_ip(ip_value: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    """'blocked' for loopback/link-local/multicast/reserved/unspecified,
    'private' for RFC1918 & friends, 'public' otherwise."""
    if (
        ip_value.is_loopback
        or ip_value.is_link_local
        or ip_value.is_multicast
        or ip_value.is_reserved
        or ip_value.is_unspecified
    ):
        return "blocked"
    if ip_value.is_private:
        return "private"
    # IPv4-mapped IPv6 (::ffff:10.0.0.1) must be judged by the embedded IPv4.
    mapped = getattr(ip_value, "ipv4_mapped", None)
    if mapped is not None:
        return classify_ip(mapped)
    return "public"


def _to_ip_or_none(host: str):
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def resolve_host_classifications(hostname: str) -> list[str] | None:
    """Resolves ``hostname`` and classifies every address. Returns None when the
    name cannot be resolved (caller decides how to treat that)."""
    try:
        entries = socket.getaddrinfo(hostname, None)
    except Exception:
        return None

    classifications: list[str] = []
    for entry in entries:
        sockaddr = entry[4]
        if not sockaddr:
            continue
        ip_value = _to_ip_or_none(str(sockaddr[0]).split("%", 1)[0])
        if ip_value is not None:
            classifications.append(classify_ip(ip_value))
    return classifications


def assert_public_http_url(
    url: str,
    *,
    allowed_schemes: tuple[str, ...] = ("https",),
    error_type: IAToolkitException.ErrorType = IAToolkitException.ErrorType.INVALID_PARAMETER,
    label: str = "URL",
) -> ParseResult:
    """
    Raises IAToolkitException(error_type) unless ``url`` is an absolute URL with
    an allowed scheme whose host is a public internet address (literal or via
    DNS). Returns the parsed URL on success.
    """
    normalized = str(url or "").strip()
    parsed = urlparse(normalized)
    scheme = (parsed.scheme or "").strip().lower()
    hostname = (parsed.hostname or "").strip().lower().rstrip(".")

    if scheme not in allowed_schemes:
        raise IAToolkitException(
            error_type,
            f"{label} must use {'/'.join(s.upper() for s in allowed_schemes)}.",
        )
    if not hostname:
        raise IAToolkitException(error_type, f"{label} host is required.")
    if hostname in _BLOCKED_HOSTNAMES or hostname.endswith(_BLOCKED_HOST_SUFFIXES):
        raise IAToolkitException(error_type, f"{label} host is not allowed.")

    ip_value = _to_ip_or_none(hostname)
    if ip_value is not None:
        if classify_ip(ip_value) != "public":
            raise IAToolkitException(error_type, f"{label} host is not allowed.")
        return parsed

    classifications = resolve_host_classifications(hostname)
    if classifications and any(kind != "public" for kind in classifications):
        raise IAToolkitException(
            error_type,
            f"{label} host is not allowed (resolves to a private or reserved address).",
        )
    return parsed


def fetch_with_safe_redirects(
    url: str,
    *,
    allowed_schemes: tuple[str, ...] = ("https",),
    error_type: IAToolkitException.ErrorType = IAToolkitException.ErrorType.INVALID_PARAMETER,
    label: str = "URL",
    max_redirects: int = 3,
    **requests_kwargs,
) -> requests.Response:
    """
    ``requests.get`` that validates the initial URL and every redirect hop with
    ``assert_public_http_url`` instead of letting ``requests`` follow them
    blindly (a public URL that 302s to http://169.254.169.254/ would otherwise
    sail through). Extra kwargs (timeout, stream, headers, ...) are passed to
    ``requests.get``; ``allow_redirects`` is always forced to False.
    """
    requests_kwargs.pop("allow_redirects", None)
    current_url = str(url or "").strip()
    for _ in range(max_redirects + 1):
        assert_public_http_url(
            current_url, allowed_schemes=allowed_schemes, error_type=error_type, label=label
        )
        response = requests.get(current_url, allow_redirects=False, **requests_kwargs)
        location = response.headers.get("Location") if response.status_code in _REDIRECT_STATUSES else None
        if not location:
            return response
        response.close()
        current_url = urljoin(current_url, location)

    raise IAToolkitException(error_type, f"{label} redirected too many times.")
