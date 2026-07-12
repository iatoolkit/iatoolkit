import logging
import sys

from iatoolkit.runtime_logging import configure_runtime_logging


def test_configure_runtime_logging_reuses_existing_root_stderr_handler():
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level

    try:
        root_logger.handlers = []
        duplicate_handler = logging.StreamHandler(sys.stderr)
        root_logger.addHandler(duplicate_handler)

        configure_runtime_logging()

        assert len(root_logger.handlers) == 1
        handler = root_logger.handlers[0]
        assert handler is duplicate_handler
        assert getattr(handler, "_iatoolkit_stdout_handler", False) is True
        assert handler.stream is sys.stdout
    finally:
        root_logger.handlers = original_handlers
        root_logger.setLevel(original_level)
