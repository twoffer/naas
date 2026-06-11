"""tests/integration/test_demo_script_live.py

End-to-end test for demo/demo_normalization.py against the live docker
compose stack.

The demo script:
  1. POSTs six login events to event-ingestion (OIDC, SAML, LDAP protocols)
  2. Polls PostgreSQL until normalized_attributes is populated for all events
  3. Renders a Rich comparison table showing before/after attribute values
  4. Cleans up its own inserted rows (DELETE FROM events WHERE id = ANY(...))

The demo runs exactly ONCE per module (module-scoped fixture) using
sys.executable; every test asserts against that single captured run. The CI
runner / local developer ensures demo dependencies (rich, httpx, psycopg) are
installed in the invoking environment — this test does NOT install them.

Connection parameters (--ingest-url, --db-dsn) come from the compose_stack
fixture, which resolves them from the same .env docker compose uses.

The demo cleans up its own event rows — no explicit cleanup needed here.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

# ---------------------------------------------------------------------------
# Module-level markers
# ---------------------------------------------------------------------------

pytestmark = [
    pytest.mark.integration,
    # 300s: 6 events × (ingest + normalization + LDAP enrichment) + render
    pytest.mark.timeout(300),
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_connection(compose_stack: dict):
    """Synchronous psycopg3 connection for this module."""
    import psycopg  # noqa: PLC0415

    conn = psycopg.connect(**compose_stack["pg_conninfo"])
    conn.autocommit = True
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def demo_run(compose_stack: dict, pg_connection) -> dict:
    """Run demo_normalization.py once against the live stack; share the result.

    Returns a dict with:
      result   — the CompletedProcess of the single demo run
      combined — stdout + stderr
      start_ts — PostgreSQL's clock (SELECT now()) captured immediately before
                 the run, so the cleanup test compares created_at against the
                 same clock that assigned it (no host↔container skew).
    """
    demo_script = compose_stack["repo_root"] / "demo" / "demo_normalization.py"
    assert demo_script.exists(), (
        f"demo/demo_normalization.py not found at {demo_script}."
    )

    with pg_connection.cursor() as cur:
        cur.execute("SELECT now()")
        start_ts = cur.fetchone()[0]

    result = subprocess.run(
        [
            sys.executable,
            str(demo_script),
            "--ingest-url",
            compose_stack["event_ingestion_url"],
            "--db-dsn",
            compose_stack["pg_dsn"],
            "--timeout",
            "60",
            "--pace",
            "0",  # No inter-event sleep — faster CI run
        ],
        capture_output=True,
        text=True,
        cwd=str(compose_stack["repo_root"]),
        timeout=290,  # inner timeout < outer pytest timeout (300s)
    )

    return {
        "result": result,
        "combined": result.stdout + result.stderr,
        "start_ts": start_ts,
    }


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestDemoScriptLive:
    """demo/demo_normalization.py must complete successfully against the live stack.

    The demo is the integration showpiece for the normalization pipeline.
    A failing demo run against a healthy stack indicates a contract violation
    between the event-ingestion API, the normalization service, and/or the
    PostgreSQL schema.
    """

    def test_demo_script_exists(self, compose_stack: dict) -> None:
        """demo/demo_normalization.py must exist before we attempt to run it.

        Fail clearly rather than getting a confusing subprocess FileNotFoundError.
        """
        demo_script = compose_stack["repo_root"] / "demo" / "demo_normalization.py"
        assert demo_script.exists(), (
            f"demo/demo_normalization.py not found at {demo_script}."
        )

    def test_demo_exits_zero(self, demo_run: dict) -> None:
        """demo_normalization.py must exit with code 0 against the live stack."""
        result = demo_run["result"]
        assert result.returncode == 0, (
            f"demo_normalization.py exited with code {result.returncode}.\n"
            f"--- stdout ---\n{result.stdout}\n"
            f"--- stderr ---\n{result.stderr}"
        )

        # Verify the demo produced meaningful output — not a silent no-op.
        # The demo's render_results function outputs a Rich table or summary.
        # We check for at least one of the canonical output markers.
        output_markers = [
            "Normalization",  # Table title / section header
            "normalized",  # Any mention of normalization result
            "display_name",  # Column header in the comparison table
            "primary_email",  # Column header in the comparison table
            "alice",  # Known user that always appears (scene 4)
            "diana",  # Known user that always appears (scene 5)
            "frank",  # Known user that always appears (scenes 0, 1)
        ]
        combined = demo_run["combined"]
        found_markers = [m for m in output_markers if m.lower() in combined.lower()]
        assert found_markers, (
            f"Demo output did not contain any expected content markers "
            f"({output_markers!r}).\n"
            f"Combined output:\n{combined}"
        )

    def test_demo_output_mentions_all_protocols(self, demo_run: dict) -> None:
        """Demo output must reference all three protocols processed.

        The six SCENES cover oidc (×3), saml (×2), ldap (×1). The output
        table or logging should mention all three protocol names.
        """
        result = demo_run["result"]
        assert result.returncode == 0, (
            f"Demo exited {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

        combined = demo_run["combined"]
        for protocol in ("oidc", "saml", "ldap"):
            assert protocol in combined.lower(), (
                f"Protocol '{protocol}' not found in demo output. "
                f"All three protocols (oidc, saml, ldap) must appear.\n"
                f"Combined output:\n{combined}"
            )

    def test_demo_cleans_up_its_rows(self, demo_run: dict, pg_connection) -> None:
        """demo_normalization.py must delete the events it inserts.

        The demo's cleanup_events function runs unconditionally (inside a
        finally block). This test verifies no orphaned rows remain after a
        successful run.

        Strategy: the demo_run fixture records PostgreSQL's own clock
        immediately before the run; assert that no events for the demo's fixed
        user_ids (frank, grace, mallory, alice, diana) with source='api' and
        is_synthetic=True exist with created_at >= that instant.

        Using the demo's specific user_ids rather than a global count avoids
        false failures from other integration tests inserting events with the
        same source/is_synthetic combination.
        """
        result = demo_run["result"]
        assert result.returncode == 0, (
            f"Demo exited {result.returncode}. Cannot verify cleanup.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

        # Fixed user_ids submitted by the demo's SCENES list (frank appears twice).
        demo_user_ids = ["frank", "grace", "mallory", "alice", "diana"]

        with pg_connection.cursor() as cur:
            cur.execute(
                "SELECT id, user_id FROM events"
                " WHERE user_id = ANY(%s)"
                "   AND source = %s"
                "   AND is_synthetic = %s"
                "   AND created_at >= %s",
                (demo_user_ids, "api", True, demo_run["start_ts"]),
            )
            orphaned = cur.fetchall()

        assert not orphaned, (
            f"Demo left {len(orphaned)} orphaned event(s) in the database after "
            f"cleanup_events ran: {[(str(r[0]), r[1]) for r in orphaned]}. "
            "cleanup_events must delete all submitted event rows."
        )
