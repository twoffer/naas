"""Unit tests for naas_shared.middleware.CorrelationIdMiddleware.

Verifies that the ASGI middleware binds a per-request ``correlation_id`` into the
structlog context (visible to the route handler), honors an inbound
``X-Request-ID`` header, echoes the id back on the response, mints a fresh id
when none is supplied, and clears the context after each request so ids never
leak across requests.
"""

from __future__ import annotations

import re

import pytest
import structlog
from fastapi import FastAPI
from fastapi.testclient import TestClient
from naas_shared.middleware import CorrelationIdMiddleware

# Shape of a freshly minted id: uuid4().hex is 32 lowercase hex characters.
_HEX32 = re.compile(r"[0-9a-f]{32}")


def _build_app() -> FastAPI:
    """A minimal FastAPI app wired exactly as the real services wire it."""
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/probe")
    async def probe() -> dict:
        # Report the structlog context the middleware bound for THIS request.
        ctx = structlog.contextvars.get_contextvars()
        return {"correlation_id": ctx.get("correlation_id")}

    return app


class TestCorrelationIdBinding:
    """The middleware binds an id the handler can see and echoes it on the response."""

    def test_correlation_id_is_visible_to_the_handler(self) -> None:
        """A handler running under the middleware sees a bound correlation_id.

        This is the whole point: merge_contextvars only emits a correlation_id on
        log lines if something populated the context — this middleware is that
        something.
        """
        resp = TestClient(_build_app()).get("/probe")

        assert resp.status_code == 200
        assert resp.json()["correlation_id"], (
            "the route handler saw no correlation_id in the structlog context — "
            "the middleware did not bind one for the request"
        )

    def test_response_echoes_the_correlation_id_header(self) -> None:
        """The bound id is echoed on the response as X-Request-ID."""
        resp = TestClient(_build_app()).get("/probe")

        echoed = resp.headers.get("x-request-id")
        assert echoed, "response did not echo an X-Request-ID header"
        assert echoed == resp.json()["correlation_id"], (
            "the echoed header must match the id bound for the handler"
        )

    def test_inbound_header_is_honored(self) -> None:
        """An inbound X-Request-ID is adopted as the correlation_id (cross-hop tracing)."""
        resp = TestClient(_build_app()).get(
            "/probe", headers={"X-Request-ID": "trace-abc-123"}
        )

        assert resp.json()["correlation_id"] == "trace-abc-123"
        assert resp.headers.get("x-request-id") == "trace-abc-123"

    def test_blank_inbound_header_falls_back_to_a_generated_id(self) -> None:
        """A blank/whitespace inbound header is replaced by a generated uuid4 hex."""
        resp = TestClient(_build_app()).get("/probe", headers={"X-Request-ID": "   "})

        bound = resp.json()["correlation_id"]
        assert bound and _HEX32.fullmatch(bound), (
            "a blank inbound id must be replaced by a generated uuid4 hex, not used "
            f"verbatim — got {bound!r}"
        )

    def test_generated_ids_differ_across_requests(self) -> None:
        """Each request without an inbound id mints a unique correlation_id."""
        client = TestClient(_build_app())

        first = client.get("/probe").json()["correlation_id"]
        second = client.get("/probe").json()["correlation_id"]

        assert first and second
        assert first != second, (
            "each request must mint its own id when none is supplied"
        )


# ===========================================================================
# Context lifecycle + protocol passthrough (driven through the raw ASGI layer
# so the test shares the request's context and can observe binding + clearing)
# ===========================================================================


async def _drive_asgi(
    scope_type: str = "http",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> tuple[str | None, list[dict]]:
    """Drive one request through the raw middleware in the caller's context.

    Returns (correlation_id the downstream app saw, list of sent ASGI messages).
    """
    seen: dict[str, str | None] = {}
    sent: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        sent.append(message)

    async def downstream(scope, receive, send) -> None:
        seen["id"] = structlog.contextvars.get_contextvars().get("correlation_id")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    scope = {"type": scope_type, "headers": headers or []}
    await CorrelationIdMiddleware(downstream)(scope, receive, send)
    return seen.get("id"), sent


class TestContextLifecycle:
    """The middleware must not leak the bound id beyond the request."""

    async def test_context_is_cleared_after_the_request(self) -> None:
        """After the request unwinds, no correlation_id remains in the context."""
        structlog.contextvars.clear_contextvars()

        seen_id, _ = await _drive_asgi()

        assert seen_id, "downstream app should have seen a bound correlation_id"
        assert "correlation_id" not in structlog.contextvars.get_contextvars(), (
            "correlation_id leaked past the request — the finally-clear did not run"
        )

    async def test_non_http_scope_passes_through_unbound(self) -> None:
        """Lifespan/websocket scopes are forwarded without binding a correlation_id."""
        structlog.contextvars.clear_contextvars()

        seen_id, sent = await _drive_asgi(scope_type="lifespan")

        assert seen_id is None, "non-http scopes must not bind a correlation_id"
        assert sent, "the downstream app must still be invoked for non-http scopes"

    async def test_context_is_cleared_when_the_handler_raises(self) -> None:
        """The finally-clear runs even when the downstream app raises.

        This is the leak-prevention guarantee that matters most: a handler that
        raises must not leave its correlation_id bound for the next request that
        reuses the worker. A clear placed anywhere but a ``finally`` would fail
        this.
        """
        structlog.contextvars.clear_contextvars()

        async def receive() -> dict:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: dict) -> None:
            pass

        async def boom(scope, receive, send) -> None:
            raise RuntimeError("handler failure")

        scope = {"type": "http", "headers": []}
        with pytest.raises(RuntimeError, match="handler failure"):
            await CorrelationIdMiddleware(boom)(scope, receive, send)

        assert "correlation_id" not in structlog.contextvars.get_contextvars(), (
            "correlation_id leaked after the handler raised — the clear must be in "
            "a finally block"
        )


# ===========================================================================
# Inbound-id validation: a hostile X-Request-ID must be rejected, not echoed
# into the response or bound into the logs verbatim
# ===========================================================================


def _response_start(sent: list[dict]) -> dict:
    """Return the http.response.start message from a captured ASGI send stream."""
    return next(m for m in sent if m["type"] == "http.response.start")


class TestInboundIdValidation:
    """An attacker-controlled inbound id is echoed + logged, so it must be vetted."""

    async def test_crlf_injection_value_is_rejected(self) -> None:
        """A CRLF-bearing inbound id is replaced and never echoed with raw CR/LF.

        CRLF in a header value is the response-splitting / header-injection
        vector (it can ride in over HTTP/2 and be echoed into an HTTP/1.1
        response on downgrade). The middleware must drop it and mint a fresh id.
        """
        seen_id, sent = await _drive_asgi(
            headers=[(b"x-request-id", b"abc\r\nset-cookie: pwned")]
        )

        assert seen_id and _HEX32.fullmatch(seen_id), (
            "a CRLF-bearing inbound id must be replaced by a generated uuid4 hex, "
            f"got {seen_id!r}"
        )
        echoed = dict(_response_start(sent)["headers"]).get(b"x-request-id", b"")
        assert b"\r" not in echoed and b"\n" not in echoed, (
            f"the echoed correlation header must contain no CR/LF, got {echoed!r}"
        )
        assert b"set-cookie" not in echoed.lower(), (
            "the hostile payload must not survive into the echoed header"
        )

    async def test_over_length_value_is_rejected(self) -> None:
        """An over-length inbound id is replaced by a bounded generated id."""
        seen_id, _ = await _drive_asgi(headers=[(b"x-request-id", b"x" * 200)])

        assert seen_id and _HEX32.fullmatch(seen_id), (
            "an over-length inbound id must be replaced by a generated uuid4 hex, "
            f"got a {len(seen_id) if seen_id else 0}-char value"
        )

    async def test_length_boundary_128_accepted_129_rejected(self) -> None:
        """The length bound is exactly 128: a 128-char id is kept, 129 is replaced.

        Both values use only allowlist characters, so length is the sole variable
        — this pins the off-by-one edge of ``_SAFE_ID``'s ``{1,128}`` quantifier.
        """
        at_limit = b"a" * 128
        over_limit = b"a" * 129

        kept, _ = await _drive_asgi(headers=[(b"x-request-id", at_limit)])
        assert kept == at_limit.decode(), (
            "a 128-char allowlisted id is within the bound and must be adopted verbatim"
        )

        replaced, _ = await _drive_asgi(headers=[(b"x-request-id", over_limit)])
        assert replaced and _HEX32.fullmatch(replaced), (
            "a 129-char id exceeds the bound and must be replaced by a generated id, "
            f"not adopted or truncated — got a {len(replaced) if replaced else 0}-char value"
        )

    async def test_control_char_value_is_rejected(self) -> None:
        """An inbound id with control characters is replaced by a generated id."""
        seen_id, _ = await _drive_asgi(headers=[(b"x-request-id", b"a\x00b")])

        assert seen_id and _HEX32.fullmatch(seen_id), (
            f"a control-char inbound id must be replaced by a generated id, got {seen_id!r}"
        )

    async def test_well_formed_inbound_id_is_still_honored(self) -> None:
        """A well-formed inbound id (allowlisted chars) is adopted verbatim.

        Guards against the validation being so strict it rejects legitimate ids
        (e.g. a UUID-with-dashes or a proxy-issued trace id).
        """
        seen_id, sent = await _drive_asgi(
            headers=[(b"x-request-id", b"3fa85f64-5717-4562-b3fc-2c963f66afa6")]
        )

        assert seen_id == "3fa85f64-5717-4562-b3fc-2c963f66afa6"
        echoed = dict(_response_start(sent)["headers"]).get(b"x-request-id", b"")
        assert echoed == b"3fa85f64-5717-4562-b3fc-2c963f66afa6"
