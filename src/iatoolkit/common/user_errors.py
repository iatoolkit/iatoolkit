# Copyright (c) 2024 Fernando Libedinsky
# Product: IAToolkit
#
# IAToolkit is open source software.

"""
Unexpected errors as a person sees them.

The text of an exception can carry SQL, table and column names, file paths or
configuration: shown to the user it maps the system for anyone probing it. So the
person gets a generic message with a short reference, and the exception goes to the
log under that same reference, where support can find it (BL-030, gap #24).
"""

import logging
import secrets

GENERAL_KEY = "errors.general.unexpected_error_ref"
PAGE_KEY = "errors.templates.processing_error"


def new_error_ref() -> str:
    """A short reference that ties what the person sees to the log line."""
    return secrets.token_hex(4)


def unexpected_error_message(i18n_service, exc: BaseException, *, where: str, key: str = GENERAL_KEY) -> str:
    """Logs `exc` with a reference and returns the translated generic message for it.

    `key` must be a translation that takes `{ref}` and never shows the exception.
    """
    ref = new_error_ref()
    logging.error("Unexpected error in %s [ref=%s]: %s", where, ref, exc, exc_info=exc)
    return i18n_service.t(key, ref=ref)
