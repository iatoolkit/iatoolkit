# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import ipaddress
from unittest.mock import MagicMock, patch

import pytest

from iatoolkit.common.exceptions import IAToolkitException
from iatoolkit.common.url_safety import (
    assert_public_http_url,
    classify_ip,
    fetch_with_safe_redirects,
)


class TestClassifyIp:
    @pytest.mark.parametrize("ip, expected", [
        ("127.0.0.1", "blocked"),
        ("::1", "blocked"),
        ("169.254.169.254", "blocked"),   # cloud metadata / link-local
        ("0.0.0.0", "blocked"),
        ("224.0.0.1", "blocked"),
        ("10.1.2.3", "private"),
        ("192.168.0.10", "private"),
        ("172.16.5.5", "private"),
        ("::ffff:10.0.0.1", "private"),    # IPv4-mapped IPv6 judged by the embedded IPv4
        ("8.8.8.8", "public"),
        ("2606:4700:4700::1111", "public"),
    ])
    def test_classification(self, ip, expected):
        assert classify_ip(ipaddress.ip_address(ip)) == expected


class TestAssertPublicHttpUrl:
    @pytest.mark.parametrize("url", [
        "https://127.0.0.1/x",
        "https://[::1]/x",
        "https://10.0.0.5/",
        "https://169.254.169.254/latest/meta-data",
        "https://localhost/x",
        "https://LOCALHOST./x",
        "https://svc.local/x",
        "https://svc.internal/x",
        "https://svc.localhost/x",
    ])
    def test_rejects_local_and_private_targets(self, url):
        with pytest.raises(IAToolkitException) as excinfo:
            assert_public_http_url(url)
        assert excinfo.value.error_type == IAToolkitException.ErrorType.INVALID_PARAMETER
        assert "host is not allowed" in excinfo.value.message

    def test_rejects_disallowed_scheme_and_missing_host(self):
        with pytest.raises(IAToolkitException) as excinfo:
            assert_public_http_url("http://example.com/x")
        assert "must use HTTPS" in excinfo.value.message

        with pytest.raises(IAToolkitException) as excinfo:
            assert_public_http_url("https:///nohost")
        assert "host is required" in excinfo.value.message

    def test_allows_http_when_explicitly_enabled(self):
        assert_public_http_url("http://8.8.8.8/x", allowed_schemes=("http", "https"))

    def test_custom_error_type_and_label(self):
        with pytest.raises(IAToolkitException) as excinfo:
            assert_public_http_url(
                "http://8.8.8.8/x",
                error_type=IAToolkitException.ErrorType.FILE_IO_ERROR,
                label="Attachment URL",
            )
        assert excinfo.value.error_type == IAToolkitException.ErrorType.FILE_IO_ERROR
        assert excinfo.value.message == "Attachment URL must use HTTPS."

    def test_rejects_hostname_that_resolves_to_private_address(self):
        """The literal-IP check alone is bypassable with any DNS name pointing at
        10.x or the metadata endpoint - resolution must be checked too."""
        resolved = [(2, 1, 6, "", ("10.1.2.3", 0))]
        with patch("iatoolkit.common.url_safety.socket.getaddrinfo", return_value=resolved):
            with pytest.raises(IAToolkitException) as excinfo:
                assert_public_http_url("https://evil.example.com/x")
        assert "resolves to a private or reserved address" in excinfo.value.message

    def test_rejects_hostname_when_any_resolved_address_is_private(self):
        resolved = [
            (2, 1, 6, "", ("93.184.216.34", 0)),
            (2, 1, 6, "", ("192.168.1.1", 0)),
        ]
        with patch("iatoolkit.common.url_safety.socket.getaddrinfo", return_value=resolved):
            with pytest.raises(IAToolkitException):
                assert_public_http_url("https://mixed.example.com/x")

    def test_allows_hostname_resolving_to_public_addresses(self):
        resolved = [(2, 1, 6, "", ("93.184.216.34", 0)), (30, 1, 6, "", ("2606:2800:220:1:248:1893:25c8:1946", 0, 0, 0))]
        with patch("iatoolkit.common.url_safety.socket.getaddrinfo", return_value=resolved):
            parsed = assert_public_http_url("https://example.com/x")
        assert parsed.hostname == "example.com"

    def test_unresolvable_hostname_is_left_to_the_request(self):
        # Fail-open only on resolution *failure*: nothing can be reached anyway,
        # and the outbound request will fail on its own.
        with patch("iatoolkit.common.url_safety.socket.getaddrinfo", side_effect=OSError("nxdomain")):
            assert_public_http_url("https://does-not-exist.example.test/x")

    def test_allows_public_literal_ip(self):
        assert_public_http_url("https://8.8.8.8/x")


class TestFetchWithSafeRedirects:
    def _response(self, status_code, location=None):
        response = MagicMock()
        response.status_code = status_code
        response.headers = {"Location": location} if location else {}
        return response

    def test_never_lets_requests_follow_redirects_itself(self):
        final = self._response(200)
        with patch("iatoolkit.common.url_safety.requests.get", return_value=final) as mock_get:
            result = fetch_with_safe_redirects("https://8.8.8.8/x", timeout=(1, 2), stream=True, allow_redirects=True)

        assert result is final
        assert mock_get.call_args.kwargs["allow_redirects"] is False
        assert mock_get.call_args.kwargs["timeout"] == (1, 2)
        assert mock_get.call_args.kwargs["stream"] is True

    def test_blocks_redirect_to_internal_address(self):
        hop = self._response(302, "http://169.254.169.254/latest/meta-data")
        with patch("iatoolkit.common.url_safety.requests.get", return_value=hop):
            with pytest.raises(IAToolkitException) as excinfo:
                fetch_with_safe_redirects("https://8.8.8.8/start", allowed_schemes=("http", "https"))
        assert "host is not allowed" in excinfo.value.message
        hop.close.assert_called_once()

    def test_blocks_redirect_that_downgrades_to_disallowed_scheme(self):
        hop = self._response(301, "http://1.1.1.1/plain")
        with patch("iatoolkit.common.url_safety.requests.get", return_value=hop):
            with pytest.raises(IAToolkitException) as excinfo:
                fetch_with_safe_redirects("https://8.8.8.8/start")   # https only
        assert "must use HTTPS" in excinfo.value.message

    def test_follows_public_redirects_and_resolves_relative_location(self):
        hop = self._response(302, "/moved/here")
        final = self._response(200)
        with patch("iatoolkit.common.url_safety.requests.get", side_effect=[hop, final]) as mock_get:
            result = fetch_with_safe_redirects("https://8.8.8.8/start")

        assert result is final
        assert mock_get.call_args_list[1].args[0] == "https://8.8.8.8/moved/here"

    def test_gives_up_after_max_redirects(self):
        hop = self._response(302, "https://1.1.1.1/again")
        with patch("iatoolkit.common.url_safety.requests.get", return_value=hop):
            with pytest.raises(IAToolkitException) as excinfo:
                fetch_with_safe_redirects("https://8.8.8.8/start", max_redirects=2)
        assert "redirected too many times" in excinfo.value.message


class TestPrivateHostAllowlist:
    """``allowed_private_hosts`` exists for the deployment whose callback target is
    internal on purpose (portal-api on 172.19.x). It opens the *private* ranges for
    a named host and nothing else: the ranges an SSRF payload wants stay shut even
    when listed, because this list comes from tenant configuration."""

    PRIVATE_PAIR = [
        (2, 1, 6, "", ("172.19.169.164", 0)),
        (2, 1, 6, "", ("172.19.164.97", 0)),
    ]

    def test_allows_listed_host_that_resolves_to_private_addresses(self):
        with patch("iatoolkit.common.url_safety.socket.getaddrinfo", return_value=self.PRIVATE_PAIR):
            parsed = assert_public_http_url(
                "https://portal-api.example.com/hook",
                allowed_private_hosts=("portal-api.example.com",),
            )
        assert parsed.hostname == "portal-api.example.com"

    def test_same_host_is_still_rejected_when_not_listed(self):
        with patch("iatoolkit.common.url_safety.socket.getaddrinfo", return_value=self.PRIVATE_PAIR):
            with pytest.raises(IAToolkitException) as excinfo:
                assert_public_http_url("https://portal-api.example.com/hook")
        assert "resolves to a private or reserved address" in excinfo.value.message

    @pytest.mark.parametrize("entry", [
        "https://portal-api.example.com/hook",   # the whole URL, pasted from a config
        "http://portal-api.example.com",
        "portal-api.example.com:8443",
        "portal-api.example.com/hook",
        "  PORTAL-API.example.com.  ",
    ])
    def test_entry_is_reduced_to_the_bare_hostname(self, entry):
        # A listed entry that never matched would look like correct config while
        # the callback kept failing with the same opaque error.
        with patch("iatoolkit.common.url_safety.socket.getaddrinfo", return_value=self.PRIVATE_PAIR):
            assert_public_http_url(
                "https://portal-api.example.com/hook", allowed_private_hosts=(entry,)
            )

    def test_listing_does_not_open_loopback_or_metadata_ranges(self):
        # 169.254.169.254 is the whole point of the guard; configuration must not
        # be able to reach it, so a listed host that resolves there still fails.
        resolved = [(2, 1, 6, "", ("169.254.169.254", 0))]
        with patch("iatoolkit.common.url_safety.socket.getaddrinfo", return_value=resolved):
            with pytest.raises(IAToolkitException) as excinfo:
                assert_public_http_url(
                    "https://sneaky.example.com/x",
                    allowed_private_hosts=("sneaky.example.com",),
                )
        assert "loopback, link-local or reserved" in excinfo.value.message

    @pytest.mark.parametrize("url, host", [
        ("https://127.0.0.1/x", "127.0.0.1"),
        ("https://169.254.169.254/latest/meta-data", "169.254.169.254"),
        ("https://localhost/x", "localhost"),
        ("https://svc.internal/x", "svc.internal"),
    ])
    def test_listing_does_not_open_blocked_literals_or_local_names(self, url, host):
        with pytest.raises(IAToolkitException) as excinfo:
            assert_public_http_url(url, allowed_private_hosts=(host,))
        assert "host is not allowed" in excinfo.value.message

    def test_allows_listed_private_literal_ip(self):
        assert_public_http_url("https://172.19.1.160/x", allowed_private_hosts=("172.19.1.160",))

        with pytest.raises(IAToolkitException):
            assert_public_http_url("https://172.19.1.160/x")

    def test_empty_and_blank_entries_are_ignored(self):
        with patch("iatoolkit.common.url_safety.socket.getaddrinfo", return_value=self.PRIVATE_PAIR):
            with pytest.raises(IAToolkitException):
                assert_public_http_url(
                    "https://portal-api.example.com/hook",
                    allowed_private_hosts=("", "   ", None),
                )

    def test_redirect_hops_honour_the_allowlist(self):
        # fetch_with_safe_redirects re-validates every hop, so it has to carry the
        # allowlist too or an internal download would fail on the second hop only.
        hop = MagicMock()
        hop.status_code = 302
        hop.headers = {"Location": "https://portal-api.example.com/file"}
        final = MagicMock()
        final.status_code = 200
        final.headers = {}

        with patch("iatoolkit.common.url_safety.socket.getaddrinfo", return_value=self.PRIVATE_PAIR):
            with patch("iatoolkit.common.url_safety.requests.get", side_effect=[hop, final]):
                result = fetch_with_safe_redirects(
                    "https://8.8.8.8/start",
                    allowed_private_hosts=("portal-api.example.com",),
                )
        assert result is final
