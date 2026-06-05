from __future__ import annotations

import logging
import os
import sys
import time

LOG_FORMAT = "%(asctime)s - IATOOLKIT - %(name)s - %(levelname)s - %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
RUNTIME_LOGGER_NAME = "iatoolkit.runtime"

_ORIGINAL_BASIC_CONFIG = logging.basicConfig
_BASIC_CONFIG_PATCHED = False


def configure_runtime_logging() -> None:
    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    log_level = _runtime_log_level()

    _ensure_stdout_handler(logging.getLogger(), formatter, log_level)
    _ensure_stdout_handler(logging.getLogger(RUNTIME_LOGGER_NAME), formatter, log_level)
    _preserve_stdout_handler_across_basic_config(formatter)

    seen_handlers: set[int] = set()
    for runtime_logger in _runtime_loggers():
        runtime_logger.setLevel(min(runtime_logger.level or log_level, log_level))
        for handler in runtime_logger.handlers:
            handler_id = id(handler)
            if handler_id in seen_handlers:
                continue
            seen_handlers.add(handler_id)
            handler.setFormatter(formatter)

    logging.getLogger("httpx").setLevel(logging.WARNING)


def install_flask_request_logging(app) -> None:
    from flask import g, request

    if app.config.get("_IATOOLKIT_REQUEST_LOGGING_INSTALLED"):
        return

    @app.before_request
    def _record_request_start():
        g._iatoolkit_request_started_at = time.perf_counter()

    @app.after_request
    def _log_request(response):
        started_at = getattr(g, "_iatoolkit_request_started_at", None)
        latency_ms = "-"
        if started_at is not None:
            latency_ms = int((time.perf_counter() - started_at) * 1000)

        logging.getLogger(RUNTIME_LOGGER_NAME).info(
            "event=http_request method=%s path=%s status_code=%s latency_ms=%s remote_addr=%s endpoint=%s",
            request.method,
            _request_path(request),
            response.status_code,
            latency_ms,
            request.headers.get("X-Forwarded-For", request.remote_addr or "-"),
            request.endpoint or "-",
        )
        return response

    app.config["_IATOOLKIT_REQUEST_LOGGING_INSTALLED"] = True


def _ensure_stdout_handler(
    logger: logging.Logger,
    formatter: logging.Formatter,
    log_level: int,
) -> None:
    logger.setLevel(min(logger.level or log_level, log_level))
    for handler in logger.handlers:
        if getattr(handler, "_iatoolkit_stdout_handler", False):
            handler.setFormatter(formatter)
            return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler._iatoolkit_stdout_handler = True
    logger.addHandler(handler)


def _preserve_stdout_handler_across_basic_config(formatter: logging.Formatter) -> None:
    global _BASIC_CONFIG_PATCHED
    if _BASIC_CONFIG_PATCHED:
        return

    def _basic_config_with_stdout_preservation(*args, **kwargs):
        handlers = list(kwargs.get("handlers") or [])
        if not any(getattr(handler, "_iatoolkit_stdout_handler", False) for handler in handlers):
            stdout_handler = logging.StreamHandler(sys.stdout)
            stdout_handler.setFormatter(formatter)
            stdout_handler._iatoolkit_stdout_handler = True
            handlers.append(stdout_handler)
        kwargs["handlers"] = handlers
        _ORIGINAL_BASIC_CONFIG(*args, **kwargs)

    logging.basicConfig = _basic_config_with_stdout_preservation
    _BASIC_CONFIG_PATCHED = True


def _runtime_log_level() -> int:
    raw_level = (os.getenv("LOG_LEVEL") or "INFO").strip().upper()
    level = getattr(logging, raw_level, None)
    if isinstance(level, int):
        return level
    try:
        return int(raw_level)
    except ValueError:
        return logging.INFO


def _runtime_loggers() -> list[logging.Logger]:
    logger_names = {
        "",
        RUNTIME_LOGGER_NAME,
        "gunicorn",
        "gunicorn.error",
        "gunicorn.access",
        "werkzeug",
        "flask.app",
        "rq",
        "iatoolkit",
        "iat_enterprise",
    }
    for name in logging.Logger.manager.loggerDict:
        if str(name).startswith(("gunicorn", "iatoolkit", "iat_enterprise", "rq")):
            logger_names.add(str(name))
    return [logging.getLogger(name) for name in sorted(logger_names)]


def _request_path(request) -> str:
    query_string = (request.query_string or b"").decode("utf-8", errors="ignore")
    if not query_string:
        return request.path
    return f"{request.path}?{query_string}"
