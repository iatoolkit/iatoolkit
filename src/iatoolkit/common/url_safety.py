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
* accepts an operator-configured ``allowed_private_hosts`` list, so a deployment
  whose callback or download target is legitimately internal (portal-backend on
  172.19.x and the like) can name that host instead of loosening the guard for
  everyone - loopback, link-local and reserved stay unreachable even when listed;
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


def _normalize_host_allowlist(allowed_hosts) -> frozenset[str]:
    """Reduces every entry to the bare hostname ``urlparse`` will hand us, so the
    comparison cannot silently miss.

    Accepts what an operator actually types in a config file: a hostname, a
    hostname with a port, or the whole callback URL
    (``https://portal-api.example.com/hook``). An entry that never matched would
    look like correct configuration while the target kept failing with the same
    opaque error, which is the worst outcome available here.
    """
    normalized = set()
    for entry in allowed_hosts or ():
        text = str(entry or "").strip().lower()
        if not text:
            continue
        if "://" in text:
            text = urlparse(text).hostname or ""
        elif text.startswith("["):
            # Bracketed IPv6 literal ("[fd00::1]:8443") - the colons are part of
            # the address, so it cannot go through the host:port split below.
            text = text[1:].split("]", 1)[0]
        else:
            # host[:port][/path] with no scheme: urlparse would read the whole
            # thing as a path, so strip the port and path by hand.
            text = text.split("/", 1)[0].split(":", 1)[0]
        text = text.strip().rstrip(".")
        if text:
            normalized.add(text)
    return frozenset(normalized)


def assert_public_http_url(
    url: str,
    *,
    allowed_schemes: tuple[str, ...] = ("https",),
    allowed_private_hosts: tuple[str, ...] = (),
    error_type: IAToolkitException.ErrorType = IAToolkitException.ErrorType.INVALID_PARAMETER,
    label: str = "URL",
) -> ParseResult:
    """
    Raises IAToolkitException(error_type) unless ``url`` is an absolute URL with
    an allowed scheme whose host is a public internet address (literal or via
    DNS). Returns the parsed URL on success.

    ``allowed_private_hosts`` is the operator's escape hatch for the legitimate
    case this guard otherwise blocks: a target that is internal on purpose, such
    as a callback back into the deployment's own network. A host named there is
    accepted when it is **private** (RFC1918 & friends), by literal IP or via
    DNS. It is still rejected when it is loopback, link-local, multicast,
    reserved or unspecified - those are the ranges an SSRF payload actually
    wants (127.0.0.1, ::1, 169.254.169.254), and the tenant configuration that
    feeds this list is editable by tenant admins, who are not the platform
    operator. The blocked local *names* stay blocked for the same reason.
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

    host_allows_private = hostname in _normalize_host_allowlist(allowed_private_hosts)

    ip_value = _to_ip_or_none(hostname)
    if ip_value is not None:
        classification = classify_ip(ip_value)
        if classification == "public" or (classification == "private" and host_allows_private):
            return parsed
        raise IAToolkitException(error_type, f"{label} host is not allowed.")

    classifications = resolve_host_classifications(hostname)
    if classifications:
        # 'blocked' is never openable from configuration - see the docstring.
        if any(kind == "blocked" for kind in classifications):
            raise IAToolkitException(
                error_type,
                f"{label} host is not allowed "
                "(resolves to a loopback, link-local or reserved address).",
            )
        if any(kind == "private" for kind in classifications) and not host_allows_private:
            raise IAToolkitException(
                error_type,
                f"{label} host is not allowed (resolves to a private or reserved address).",
            )
    return parsed


def fetch_with_safe_redirects(
    url: str,
    *,
    allowed_schemes: tuple[str, ...] = ("https",),
    allowed_private_hosts: tuple[str, ...] = (),
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
            current_url,
            allowed_schemes=allowed_schemes,
            allowed_private_hosts=allowed_private_hosts,
            error_type=error_type,
            label=label,
        )
        response = requests.get(current_url, allow_redirects=False, **requests_kwargs)
        location = response.headers.get("Location") if response.status_code in _REDIRECT_STATUSES else None
        if not location:
            return response
        response.close()
        current_url = urljoin(current_url, location)

    raise IAToolkitException(error_type, f"{label} redirected too many times.")
