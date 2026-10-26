"""Structured logging.

JSON outside development, so Langfuse, Loki or CloudWatch can parse it.
Human-readable in development.

Every log record passes through a redaction processor. On an engagement
handling board material, a stray `log.info("auth", password=pw)` must not
write a credential to disk - and the person who writes that line will not be
thinking about it at the time. The processor is the safety net.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, Processor

# Substring match on the KEY, not the value. Catches password, db_password,
# jwt_secret, api_key, preshared_key, authorization, refresh_token, ...
SENSITIVE_KEY_PARTS: tuple[str, ...] = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "auth_header",
    "preshared",
    "private_key",
    "cookie",
    "session_id",
    "credential",
)

REDACTED = "[redacted]"
_MAX_DEPTH = 4


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def _scrub(value: Any, depth: int = 0) -> Any:
    """Walk dicts and sequences, redacting anything under a sensitive key."""
    if depth >= _MAX_DEPTH:
        return value
    if isinstance(value, dict):
        return {
            k: (REDACTED if _is_sensitive(str(k)) else _scrub(v, depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        scrubbed = [_scrub(v, depth + 1) for v in value]
        return type(value)(scrubbed) if isinstance(value, tuple) else scrubbed
    return value


def redact_sensitive(_logger: Any, _method_name: str, event_dict: EventDict) -> EventDict:
    """structlog processor: redact sensitive keys at any nesting level."""
    for key in list(event_dict.keys()):
        if _is_sensitive(str(key)):
            event_dict[key] = REDACTED
        else:
            event_dict[key] = _scrub(event_dict[key], depth=1)
    return event_dict


def configure_logging(level: str = "INFO", json_logs: bool = False) -> None:
    """Configure structlog, and route stdlib logging through the same pipeline.

    uvicorn and sqlalchemy log through stdlib. Routing them through
    ProcessorFormatter means every line in the process - ours and theirs -
    gets the same shape, the same timestamp format, and the same redaction.

    Safe to call more than once; later calls replace the configuration.
    """
    log_level = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)

    # Shared by structlog calls and by foreign stdlib records.
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
        redact_sensitive,
    ]

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        # Not cached: configure_logging() is called again per app instance in
        # tests, and a cached logger would keep the previous configuration.
        cache_logger_on_first_use=False,
    )

    final: list[Processor] = [structlog.stdlib.ProcessorFormatter.remove_processors_meta]
    if json_logs:
        # ConsoleRenderer formats exceptions itself; JSONRenderer does not.
        final.append(structlog.processors.format_exc_info)
        final.append(structlog.processors.JSONRenderer())
    else:
        final.append(structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()))

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(foreign_pre_chain=shared, processors=final)
    )

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(log_level)

    # Let these propagate to the root handler instead of writing their own
    # differently-shaped lines.
    for noisy in ("uvicorn", "uvicorn.error", "uvicorn.access", "sqlalchemy.engine"):
        logger = logging.getLogger(noisy)
        logger.handlers.clear()
        logger.propagate = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """A bound logger. Pass __name__ from the calling module."""
    return structlog.get_logger(name)  # type: ignore[no-any-return]
