"""ASGI middleware binding a per-request correlation ID into structlog contextvars.

The pipeline's structured logging is configured (in :func:`naas_shared.logging.setup_logging`)
with ``structlog.contextvars.merge_contextvars``, which merges any context-local
variables into every log line.  This middleware is what populates that context
for HTTP requests: it reads an inbound correlation/request-id header (or mints a
UUID4 when absent), binds it as ``correlation_id`` for the lifetime of the
request, echoes it back on the response, and clears the context when the request
ends — so every log line emitted while serving a request carries the same id.

Implemented as a pure ASGI middleware rather than a Starlette
``BaseHTTPMiddleware``: contextvars bound inside a ``BaseHTTPMiddleware.dispatch``
do NOT propagate to the route handler (Starlette runs the downstream app in a
separate task), so the bound ``correlation_id`` would never reach endpoint logs.
A raw ASGI callable runs in the same task and context as the handler, so the
binding is visible to every log line emitted while serving the request.

Scope note: this binds a ``correlation_id`` within a single service's HTTP
request scope.  Correlation across the async Redis Streams pipeline (ingestion →
normalization) is carried by ``event_id`` on the stream payload and the DB row,
not by this header.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any
from uuid import uuid4

import structlog

# Inbound header carrying the request/correlation id.  X-Request-ID is the de
# facto standard emitted by load balancers and proxies; accepting it as the
# correlation id lets a single id be traced across hops.
_DEFAULT_HEADER = "x-request-id"

# An inbound id is echoed into a response header AND bound into every log line
# for the request, so it is adopted only if it matches a bounded allowlist of
# id-safe characters.  This is defense in depth: it forecloses header/response
# splitting (CRLF can ride in over HTTP/2 and be echoed into an HTTP/1.1
# response on downgrade), log-line forgery, and unbounded log bloat — anything
# that does not match is treated as absent and a fresh UUID is minted instead.
_SAFE_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")

_Scope = MutableMapping[str, Any]
_Message = MutableMapping[str, Any]
_Receive = Callable[[], Awaitable[_Message]]
_Send = Callable[[_Message], Awaitable[None]]
_ASGIApp = Callable[[_Scope, _Receive, _Send], Awaitable[None]]


class CorrelationIdMiddleware:
    """Bind a ``correlation_id`` into structlog contextvars for each HTTP request."""

    def __init__(self, app: _ASGIApp, header_name: str = _DEFAULT_HEADER) -> None:
        self.app = app
        self._header_bytes = header_name.lower().encode("latin-1")

    async def __call__(self, scope: _Scope, receive: _Receive, send: _Send) -> None:
        # Only HTTP requests carry a correlation id; pass websockets/lifespan through.
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        correlation_id = self._inbound_id(scope) or uuid4().hex

        # Clear any context left over from a crashed prior request on this worker,
        # then bind the id for the lifetime of this request.
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)

        async def send_with_correlation_header(message: _Message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.append((self._header_bytes, correlation_id.encode("latin-1")))
            await send(message)

        try:
            await self.app(scope, receive, send_with_correlation_header)
        finally:
            structlog.contextvars.clear_contextvars()

    def _inbound_id(self, scope: _Scope) -> str | None:
        """Return the inbound correlation id if present and well-formed, else None.

        The value is validated against ``_SAFE_ID`` before adoption: anything
        absent, blank, over-length, or containing control/CRLF/other characters
        is treated as absent so the caller mints a fresh UUID instead of echoing
        and logging attacker-controlled bytes.
        """
        for name, value in scope.get("headers", []):
            if name == self._header_bytes:
                candidate = value.decode("latin-1").strip()
                return candidate if _SAFE_ID.fullmatch(candidate) else None
        return None
