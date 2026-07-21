from __future__ import annotations

import logging
import os
import sys
import time
from urllib.parse import urlsplit

LOG_FORMAT = "%(asctime)s - IATOOLKIT - %(name)s - %(levelname)s - %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
RUNTIME_LOGGER_NAME = "iatoolkit.runtime"

_ORIGINAL_BASIC_CONFIG = logging.basicConfig
_BASIC_CONFIG_PATCHED = False


try:
    from gunicorn.glogging import Logger as _GunicornLogger

    class QuietLivenessGunicornLogger(_GunicornLogger):
        """
        Drop-in replacement for gunicorn's default access logger that
        silences the liveness endpoint ('/', see common/routes.py) - load
        balancer/orchestrator health checks hit it every ~10-15s and would
        otherwise flood the access log forever with nothing of value.
        Everything else logs exactly as gunicorn's default Logger would.

        Reference from a gunicorn.conf.py:
            logger_class = "iatoolkit.runtime_logging.QuietLivenessGunicornLogger"
        """

        _SILENCED_PATHS = {"/"}

        def access(self, resp, req, environ, request_time):
            if environ.get("PATH_INFO") in self._SILENCED_PATHS:
                return
            super().access(resp, req, environ, request_time)
except ImportError:
    # gunicorn isn't necessarily installed in every context that imports this
    # module (e.g. plain `flask run` in local dev without the [server] extra).
    QuietLivenessGunicornLogger = None


_QUIET_RQ_MESSAGE_SUBSTRINGS = (
    "cleaning registries for queue",
    "Job OK",
)


class _QuietRQMaintenanceFilter(logging.Filter):
    """
    RQ logs its own per-job success ('Job OK') and per-queue maintenance
    ('cleaning registries for queue: ...') lines at INFO unconditionally -
    with several queues x several workers this floods production logs with
    nothing actionable. Suppressed unless LOG_LEVEL=DEBUG (or
    IATOOLKIT_LOG_RQ_MAINTENANCE=true) is explicitly requested. Genuine
    failures (AbandonedJobError, job exceptions) go through RQ's own
    WARNING/ERROR calls and are untouched by this filter.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno != logging.INFO:
            return True
        if _runtime_log_level() <= logging.DEBUG:
            return True
        if _parse_bool_env("IATOOLKIT_LOG_RQ_MAINTENANCE", default=False):
            return True
        message = record.getMessage()
        return not any(substring in message for substring in _QUIET_RQ_MESSAGE_SUBSTRINGS)


_RQ_LOGGER_NAMES_WITH_OWN_HANDLERS = ("rq.worker", "rq.job")


def _dedupe_rq_loghandlers() -> None:
    """
    RQ's own Worker.bootstrap() calls setup_loghandlers(), which attaches a
    StreamHandler directly to 'rq.worker'/'rq.job' UNLESS it detects an
    existing handler anywhere in the logger hierarchy at that exact moment.
    During a worker's boot sequence, our own root stdout handler may not be
    in place yet the first time that runs (logging gets configured more than
    once - at worker.py's top, then again inside enterprise.create() - and
    the exact ordering isn't guaranteed) - RQ's own handler then sticks
    around even after our root handler shows up, and every RQ log record
    (e.g. the per-job start/"Successfully completed" lines) gets printed
    twice: once by RQ's handler, once via propagation to root. These two
    loggers propagate to root, which already carries our canonical handler,
    so it's always safe to drop their own direct handlers here.
    """
    for logger_name in _RQ_LOGGER_NAMES_WITH_OWN_HANDLERS:
        rq_logger = logging.getLogger(logger_name)
        if not rq_logger.propagate:
            continue
        for handler in list(rq_logger.handlers):
            rq_logger.removeHandler(handler)


def configure_runtime_logging() -> None:
    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    log_level = _runtime_log_level()

    _ensure_stdout_handler(logging.getLogger(), formatter, log_level)
    logging.getLogger(RUNTIME_LOGGER_NAME).propagate = True
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

    _dedupe_rq_loghandlers()

    rq_worker_logger = logging.getLogger("rq.worker")
    if not any(isinstance(f, _QuietRQMaintenanceFilter) for f in rq_worker_logger.filters):
        rq_worker_logger.addFilter(_QuietRQMaintenanceFilter())


def install_flask_request_logging(app) -> None:
    from flask import g, request

    if app.config.get("_IATOOLKIT_REQUEST_LOGGING_INSTALLED"):
        return

    @app.before_request
    def _record_request_start():
        g._iatoolkit_request_started_at = time.perf_counter()

    @app.after_request
    def _log_request(response):
        if not _should_log_request(request, response):
            return response

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
    canonical_handler = None

    for handler in logger.handlers:
        if getattr(handler, "_iatoolkit_stdout_handler", False):
            handler.setFormatter(formatter)
            canonical_handler = handler
            break

    if canonical_handler is None:
        for handler in logger.handlers:
            if _is_root_stdio_handler(handler):
                handler.setFormatter(formatter)
                _set_handler_stream(handler, sys.stdout)
                handler._iatoolkit_stdout_handler = True
                canonical_handler = handler
                break

    if canonical_handler is None:
        canonical_handler = logging.StreamHandler(sys.stdout)
        canonical_handler.setFormatter(formatter)
        canonical_handler._iatoolkit_stdout_handler = True
        logger.addHandler(canonical_handler)

    for handler in list(logger.handlers):
        if handler is canonical_handler:
            continue
        if _is_root_stdio_handler(handler):
            logger.removeHandler(handler)


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


def _is_root_stdio_handler(handler: logging.Handler) -> bool:
    if not isinstance(handler, logging.StreamHandler):
        return False
    stream = getattr(handler, "stream", None)
    return stream in {sys.stdout, sys.stderr}


def _set_handler_stream(handler: logging.StreamHandler, stream) -> None:
    try:
        handler.setStream(stream)
    except AttributeError:
        handler.stream = stream


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


def _should_log_request(request, response) -> bool:
    method = (request.method or "").upper()
    path = _normalized_path(request.path)
    endpoint = str(request.endpoint or "")

    if method in {"GET", "HEAD"}:
        if not _parse_bool_env("IATOOLKIT_LOG_STATIC_REQUESTS", default=False):
            if endpoint in {"static", "iat_enterprise_static.static"}:
                return False
            if path.startswith("/static/") or _has_static_extension(path):
                return False
            if path in {"/favicon.ico", "/robots.txt", "/apple-touch-icon.png"}:
                return False

        if not _parse_bool_env("IATOOLKIT_LOG_MONITORING_REQUESTS", default=False):
            if "/api/monitoring/" in path:
                return False

        if not _parse_bool_env("IATOOLKIT_LOG_LIVENESS_REQUESTS", default=False):
            if endpoint == "liveness":
                return False

    return True


def _has_static_extension(path: str) -> bool:
    return path.endswith(
        (
            ".css",
            ".js",
            ".mjs",
            ".map",
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".svg",
            ".ico",
            ".webp",
            ".woff",
            ".woff2",
            ".ttf",
            ".eot",
        )
    )


def _parse_bool_env(name: str, *, default: bool) -> bool:
    raw_value = (os.getenv(name) or "").strip().lower()
    if not raw_value:
        return default
    return raw_value in {"1", "true", "yes", "on"}


def _normalized_path(path: str) -> str:
    return urlsplit(path or "/").path or "/"


def _request_path(request) -> str:
    query_string = (request.query_string or b"").decode("utf-8", errors="ignore")
    if not query_string:
        return request.path
    return f"{request.path}?{query_string}"
