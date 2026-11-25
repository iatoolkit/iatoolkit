# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

import logging
import re
from unittest.mock import MagicMock

from iatoolkit.common.user_errors import GENERAL_KEY, PAGE_KEY, unexpected_error_message


def _i18n():
    i18n = MagicMock()
    i18n.t.side_effect = lambda key, **kwargs: f"{key}|ref={kwargs.get('ref')}"
    return i18n


def test_the_user_message_carries_a_reference_and_never_the_exception():
    secret = "column iat_users.temp_code_expires_at does not exist"

    message = unexpected_error_message(_i18n(), RuntimeError(secret), where="test")

    assert secret not in message
    assert message.startswith(GENERAL_KEY)
    assert re.search(r"ref=[0-9a-f]{8}$", message)


def test_the_exception_goes_to_the_log_under_the_same_reference(caplog):
    with caplog.at_level(logging.ERROR):
        message = unexpected_error_message(_i18n(), ValueError("db down"), where="profile_service")

    ref = message.rsplit("ref=", 1)[1]
    assert any(ref in record.getMessage() and "db down" in record.getMessage() and record.exc_info
               for record in caplog.records)


def test_a_page_error_uses_the_page_message():
    message = unexpected_error_message(_i18n(), Exception("x"), where="home_view", key=PAGE_KEY)

    assert message.startswith(PAGE_KEY)


def test_each_error_gets_its_own_reference():
    i18n = _i18n()
    first = unexpected_error_message(i18n, Exception("a"), where="t")
    second = unexpected_error_message(i18n, Exception("b"), where="t")

    assert first != second
