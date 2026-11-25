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


# Domain errors whose message is written for the person: shown as they are. Matched
# by name so the core and Enterprise exception classes both qualify.
USER_FACING_ERROR_TYPES = frozenset({
    "INVALID_PARAMETER", "MISSING_PARAMETER", "PARAM_NOT_FILLED", "PERMISSION", "EXIST",
    "DOCUMENT_NOT_FOUND", "NOT_FOUND", "TASK_NOT_FOUND", "INVALID_NAME", "DUPLICATE_ENTRY",
    "INVALID_OPERATION", "INVALID_STATE", "INVALID_USER", "FILE_FORMAT_ERROR", "INVALID_SQL",
})
INTERNAL_KEY = "errors.general.internal_error_ref"


def is_user_facing(exc: BaseException) -> bool:
    error_type = getattr(getattr(exc, "error_type", None), "name", None)
    if error_type is not None:
        return error_type in USER_FACING_ERROR_TYPES
    return type(exc) is ValueError  # validation raised by our own code


def public_error_text(exc: BaseException, where: str = "") -> str:
    """The text an HTTP response may carry for `exc`.

    A domain error written for the person keeps its message. Anything else (a
    database, library or system error) goes to the log under a reference, and the
    response says only "internal error (reference …)" (BL-030, gap #24).
    """
    if is_user_facing(exc):
        return str(exc)
    ref = new_error_ref()
    logging.error("Unexpected error in %s [ref=%s]: %s", where or "request", ref, exc, exc_info=exc)
    try:
        from iatoolkit.core import current_iatoolkit
        from iatoolkit.services.i18n_service import I18nService
        return current_iatoolkit().get_injector().get(I18nService).t(INTERNAL_KEY, ref=ref)
    except Exception:
        return f"internal error (reference {ref})"
