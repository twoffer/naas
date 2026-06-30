import logging
import sys

import structlog


def setup_logging(service_name: str, log_level: str = "INFO") -> None:
    """Configure structlog for JSON output with correlation ID support.

    Call once at service startup.  Subsequent calls are harmless (structlog
    configure is idempotent) but redundant.
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """Get a structlog logger.

    Per-request ``correlation_id`` is bound into the logging context by
    ``naas_shared.middleware.CorrelationIdMiddleware`` and merged into every log
    line via ``merge_contextvars`` (configured in :func:`setup_logging`).
    """
    return structlog.get_logger(name or __name__)
