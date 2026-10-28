import logging
import sys

import structlog

_HANDLER_MARK = "_rag_log_handler"


def configure_logging(level: str = "INFO", json_logs: bool = False) -> None:
    """Routes standard-library logging and structlog through one format, with the request id
    (bound by the request id middleware) on every line. Safe to call more than once."""
    shared = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    structlog.configure(
        processors=shared + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    renderer = (
        structlog.processors.JSONRenderer()
        if json_logs
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,  # applies the same fields to plain logging.getLogger() calls
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            renderer,
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    setattr(handler, _HANDLER_MARK, True)

    root = logging.getLogger()
    # Replace only our own handler from an earlier call; leave others (pytest's caplog) alone.
    root.handlers = [h for h in root.handlers if not getattr(h, _HANDLER_MARK, False)]
    root.addHandler(handler)
    root.setLevel(level.upper())