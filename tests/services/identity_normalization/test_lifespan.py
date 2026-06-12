"""main.py lifespan wiring: consumer-group creation and resource initialization."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from naas_shared.constants import STREAM_LOGIN_EVENTS, GROUP_NORMALIZATION


# ===========================================================================
# E.12. Health endpoint regression
# ===========================================================================


class TestHealthRegression:
    """/health endpoint must remain functional after lifespan wiring is added."""

    async def test_health_endpoint_returns_200_with_healthy_deps(self):
        """GET /health returns 200 and service='identity-normalization' when deps are up."""
        # Import the module-level app (create_app() must remain intact)
        import app.main as _main

        the_app = _main.create_app()

        async def _run_health():
            import naas_shared.database as _db_mod
            import naas_shared.redis_client as _redis_mod

            mock_session = AsyncMock()
            mock_session.execute = AsyncMock()

            async def _fake_session_gen():
                yield mock_session

            with (
                patch.object(
                    _db_mod, "get_db_session", return_value=_fake_session_gen()
                ),
                patch.object(
                    _redis_mod, "get_redis", return_value=AsyncMock(ping=AsyncMock())
                ),
                patch(
                    "naas_shared.redis_client.ensure_consumer_group", new=AsyncMock()
                ),
                patch("app.main.run_consumer_loop", new=AsyncMock()),
            ):
                async with ASGITransport(app=the_app) as transport:
                    async with AsyncClient(
                        transport=transport, base_url="http://testserver"
                    ) as ac:
                        resp = await ac.get("/health")
                        return resp

        resp = await _run_health()
        assert resp.status_code == 200, (
            f"GET /health must return 200, got {resp.status_code}"
        )
        body = resp.json()
        assert body.get("service") == "identity-normalization", (
            f"service field must be 'identity-normalization', got {body.get('service')!r}"
        )
        assert body.get("status") in ("healthy", "degraded", "unhealthy"), (
            f"status must be one of healthy/degraded/unhealthy, got {body.get('status')!r}"
        )

    def test_create_app_returns_fastapi_app(self):
        """create_app() must remain importable and return a FastAPI instance."""
        from fastapi import FastAPI
        import app.main as _main

        the_app = _main.create_app()
        assert isinstance(the_app, FastAPI), (
            f"create_app() must return a FastAPI instance, got {type(the_app)}"
        )

    def test_module_level_app_exists(self):
        """The module-level `app` attribute must exist for uvicorn."""
        import app.main as _main

        assert hasattr(_main, "app"), (
            "app.main must have a module-level `app` attribute for `uvicorn app.main:app`"
        )


# ===========================================================================
# E.11. Invalid config aborts startup
# ===========================================================================


class TestInvalidConfigAbortsStartup:
    """§5.1: invalid normalization.yaml must abort startup with a descriptive error."""

    async def test_invalid_config_propagates_during_lifespan_startup(self):
        """If load_config() raises, the lifespan must let the exception propagate.

        We simulate by patching load_config to raise ValueError and running
        the lifespan startup phase.
        """
        from fastapi import FastAPI
        import app.main as _main

        # We need to exercise the lifespan context manager startup phase.
        # Strategy: use a fresh FastAPI app and run lifespan manually.
        startup_raised = [False]
        startup_error = [None]

        async def _run_startup_only():
            # Patch ensure_consumer_group (we test it separately)
            # Patch run_consumer_loop to be a no-op background task
            # Patch load_config to raise
            with (
                patch(
                    "app.main.load_config",
                    side_effect=ValueError("Invalid correlation_key 'favorite_color'"),
                ),
                patch(
                    "naas_shared.redis_client.ensure_consumer_group",
                    new_callable=AsyncMock,
                ),
                patch("app.main.run_consumer_loop", new_callable=AsyncMock),
            ):
                try:
                    # Run the lifespan startup
                    async with _main.lifespan(FastAPI()):
                        pass
                except (ValueError, Exception) as e:
                    startup_raised[0] = True
                    startup_error[0] = e

        await _run_startup_only()

        assert startup_raised[0], (
            "Invalid config must cause an exception during lifespan startup — "
            "startup must abort, not silently swallow the error"
        )
        assert startup_error[0] is not None, (
            "A descriptive error must be raised on invalid config"
        )

    async def test_valid_config_does_not_raise_during_startup(self):
        """Valid normalization.yaml allows startup to proceed without exception."""
        from fastapi import FastAPI
        import app.main as _main

        startup_raised = [False]

        async def _run_startup():
            with (
                patch(
                    "naas_shared.redis_client.ensure_consumer_group",
                    new_callable=AsyncMock,
                ),
                patch("app.main.run_consumer_loop", new_callable=AsyncMock),
            ):
                # patch prevents the real consumer from starting
                try:
                    async with _main.lifespan(FastAPI()):
                        pass  # immediately exit
                except Exception:
                    startup_raised[0] = True

        await _run_startup()

        assert not startup_raised[0], (
            "Valid config must not raise during lifespan startup"
        )


# ===========================================================================
# E.12. Startup: ensure_consumer_group called once on startup
# ===========================================================================


class TestLifespanEnsuresConsumerGroup:
    """§5.1, §2.1: ensure_consumer_group(STREAM_LOGIN_EVENTS, GROUP_NORMALIZATION) on startup."""

    async def test_ensure_consumer_group_called_on_startup(self):
        """ensure_consumer_group must be called exactly once during lifespan startup."""
        from fastapi import FastAPI
        import app.main as _main

        ensure_calls: list[tuple] = []

        async def _mock_ensure(stream, group):
            ensure_calls.append((stream, group))

        async def _run_startup():
            with (
                patch(
                    "naas_shared.redis_client.ensure_consumer_group",
                    side_effect=_mock_ensure,
                ),
                patch("app.main.run_consumer_loop", new_callable=AsyncMock),
            ):
                async with _main.lifespan(FastAPI()):
                    pass

        await _run_startup()

        assert len(ensure_calls) == 1, (
            f"ensure_consumer_group must be called exactly once on startup, called {len(ensure_calls)} times"
        )
        stream_arg, group_arg = ensure_calls[0]
        assert stream_arg == STREAM_LOGIN_EVENTS, (
            f"ensure_consumer_group stream must be {STREAM_LOGIN_EVENTS!r}, got {stream_arg!r}"
        )
        assert group_arg == GROUP_NORMALIZATION, (
            f"ensure_consumer_group group must be {GROUP_NORMALIZATION!r}, got {group_arg!r}"
        )


# ===========================================================================
# E.12. Startup: consumer loop launched as background task
# ===========================================================================


class TestLifespanLaunchesConsumerLoop:
    """Consumer loop is launched as a background task on startup."""

    async def test_consumer_loop_launched_on_startup(self):
        """The consumer loop function is called/scheduled during lifespan startup."""
        from fastapi import FastAPI
        import app.main as _main

        loop_started = [False]

        async def _mock_loop(**kwargs):
            loop_started[0] = True
            # Immediately return (we don't want infinite loop in tests)

        mock_loop_holder = [None]

        async def _run_startup():
            with (
                patch(
                    "naas_shared.redis_client.ensure_consumer_group",
                    new_callable=AsyncMock,
                ),
                patch(
                    "app.main.run_consumer_loop", side_effect=_mock_loop
                ) as mock_loop,
            ):
                async with _main.lifespan(FastAPI()):
                    pass  # yield point — consumer task already created
                mock_loop_holder[0] = mock_loop

        await _run_startup()

        # The lifespan must launch run_consumer_loop via asyncio.create_task.
        # With create_task, the mock coroutine runs (and sets loop_started=True)
        # when the event loop processes the scheduled task during the lifespan body.
        # Either the mock was called (create_task path, where task ran during lifespan),
        # or the mock was scheduled (verified by call_count on mock_loop_holder).
        mock_loop = mock_loop_holder[0]
        assert mock_loop is not None, (
            "run_consumer_loop mock was not captured — ensure the lifespan patch is valid"
        )
        assert mock_loop.called or loop_started[0], (
            "run_consumer_loop must be called/scheduled during lifespan startup. "
            "The lifespan must launch it as a background task (asyncio.create_task) "
            "so it runs concurrently without blocking the lifespan yield. "
            f"mock.called={mock_loop.called}, loop_started={loop_started[0]}"
        )

    async def test_lifespan_imports_run_consumer_loop(self):
        """app.main must import (or reference) run_consumer_loop for the lifespan to wire it."""
        import app.main as _main

        # The lifespan must have access to run_consumer_loop.
        # It can be imported at module level or inside the function.
        # We verify that the lifespan at minimum has access to the consumer module.
        # One way: check the module reference exists via main's globals or imports.
        # We do this by patching run_consumer_loop and verifying the patch path is correct.
        from fastapi import FastAPI

        with (
            patch("app.main.run_consumer_loop", new_callable=AsyncMock),
            patch(
                "naas_shared.redis_client.ensure_consumer_group", new_callable=AsyncMock
            ),
        ):

            async def _run_inner():
                async with _main.lifespan(FastAPI()):
                    pass  # startup done

            try:
                await _run_inner()
            except Exception:
                pass  # may fail if other deps are missing, but we want to confirm the patch is valid

        # The patch path "app.main.run_consumer_loop" must be valid.
        # If it weren't, patch() would raise AttributeError during context entry.
        # Reaching this point confirms the attribute exists on app.main.
        # Additionally verify that the attribute is callable (it must be the function).
        assert hasattr(_main, "run_consumer_loop"), (
            "app.main must expose 'run_consumer_loop' at module level "
            "(imported from app.consumer) so the lifespan can reference and launch it. "
            "patch('app.main.run_consumer_loop', ...) requires this attribute to exist."
        )


# ===========================================================================
# E.12. Shutdown: consumer task cancelled cleanly
# ===========================================================================


class TestLifespanShutdown:
    """Consumer background task is cancelled cleanly on shutdown."""

    async def test_consumer_task_cancelled_on_shutdown(self):
        """When the lifespan exits, the background consumer task must be cancelled.

        We verify this by making the consumer loop block forever until cancelled,
        and confirming the lifespan exits cleanly (no hang).
        """
        from fastapi import FastAPI
        import app.main as _main

        cancel_observed = [False]

        async def _blocking_loop(**kwargs):
            try:
                await asyncio.sleep(3600)  # simulate long-running loop
            except asyncio.CancelledError:
                cancel_observed[0] = True
                raise  # re-raise so task completes

        async def _run_lifecycle():
            with (
                patch(
                    "naas_shared.redis_client.ensure_consumer_group",
                    new_callable=AsyncMock,
                ),
                patch("app.main.run_consumer_loop", side_effect=_blocking_loop),
            ):
                async with _main.lifespan(FastAPI()):
                    # lifespan is now at the yield point
                    pass  # immediately proceed to shutdown
                # lifespan has exited — task should have been cancelled

        # Must complete without hanging (timeout)
        try:
            await asyncio.wait_for(_run_lifecycle(), timeout=5.0)
        except asyncio.TimeoutError:
            pytest.fail(
                "Lifespan shutdown timed out — the consumer task must be cancelled cleanly on shutdown"
            )

        assert cancel_observed[0], (
            "Consumer loop must receive CancelledError on shutdown — "
            "the lifespan must cancel the background task, not just abandon it"
        )
