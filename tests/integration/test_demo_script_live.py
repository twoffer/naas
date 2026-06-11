"""tests/integration/test_demo_script_live.py

End-to-end test for demo/demo_normalization.py against the live docker
compose stack.

The demo script:
  1. POSTs six login events to event-ingestion (OIDC, SAML, LDAP protocols)
  2. Polls PostgreSQL until normalized_attributes is populated for all events
  3. Renders a Rich comparison table showing before/after attribute values
  4. Cleans up its own inserted rows (DELETE FROM events WHERE id = ANY(...))

This test runs the demo as a subprocess using sys.executable (same Python
interpreter as the test runner). The CI runner / local developer ensures
demo dependencies (rich, httpx, psycopg) are installed in the invoking
environment — this test does NOT install them.

Assertions:
  - Exit code 0 (full run succeeded)
  - Output contains evidence of the comparison table or success indication
  - Output contains "passed" or the normalization result summary expected by
    the demo's render_results function

The demo cleans up its own event rows — no explicit cleanup needed here.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Repo-root discovery
# ---------------------------------------------------------------------------


def _find_repo_root() -> Path:
    candidate = Path(__file__).resolve().parent
    for _ in range(10):
        if (candidate / "docs" / "architecture").is_dir():
            return candidate
        candidate = candidate.parent
    raise RuntimeError(f"Cannot locate repo root from {Path(__file__).resolve()}")


REPO_ROOT = _find_repo_root()
DEMO_SCRIPT = REPO_ROOT / "demo" / "demo_normalization.py"

# ---------------------------------------------------------------------------
# Module-level markers
# ---------------------------------------------------------------------------

pytestmark = [
    pytest.mark.integration,
    # 300s: 6 events × (ingest + normalization + LDAP enrichment) + render
    pytest.mark.timeout(300),
]


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
        assert DEMO_SCRIPT.exists(), (
            f"demo/demo_normalization.py not found at {DEMO_SCRIPT}. "
            "Feature-implementer must create this file."
        )

    def test_demo_exits_zero(self, compose_stack: dict) -> None:
        """demo_normalization.py must exit with code 0 against the live stack.

        Runs with --skip-verify suppressed so the comparison table renders
        even if an edge-case user's normalization confidence is lower than
        expected. The demo cleans up its own rows regardless of --skip-verify.

        The demo reads PostgreSQL directly (no query API yet). The db-dsn
        matches the compose defaults exposed on localhost.
        """
        assert DEMO_SCRIPT.exists(), f"demo script not found at {DEMO_SCRIPT}"

        result = subprocess.run(
            [
                sys.executable,
                str(DEMO_SCRIPT),
                "--ingest-url",
                "http://localhost:8001",
                "--db-dsn",
                (
                    "host=localhost port=5432 dbname=naas "
                    "user=naas password=naas_dev_password"
                ),
                "--timeout",
                "60",
                "--pace",
                "0",  # No inter-event sleep — faster CI run
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=290,  # inner timeout < outer pytest timeout (300s)
        )

        combined = result.stdout + result.stderr

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
        found_markers = [m for m in output_markers if m.lower() in combined.lower()]
        assert found_markers, (
            f"Demo output did not contain any expected content markers "
            f"({output_markers!r}).\n"
            f"Combined output:\n{combined}"
        )

    def test_demo_output_mentions_all_protocols(self, compose_stack: dict) -> None:
        """Demo output must reference all three protocols processed.

        The six SCENES cover oidc (×3), saml (×2), ldap (×1). The output
        table or logging should mention all three protocol names.
        """
        assert DEMO_SCRIPT.exists(), f"demo script not found at {DEMO_SCRIPT}"

        result = subprocess.run(
            [
                sys.executable,
                str(DEMO_SCRIPT),
                "--ingest-url",
                "http://localhost:8001",
                "--db-dsn",
                (
                    "host=localhost port=5432 dbname=naas "
                    "user=naas password=naas_dev_password"
                ),
                "--timeout",
                "60",
                "--pace",
                "0",
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=290,
        )

        assert result.returncode == 0, (
            f"Demo exited {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

        combined = result.stdout + result.stderr
        for protocol in ("oidc", "saml", "ldap"):
            assert protocol in combined.lower(), (
                f"Protocol '{protocol}' not found in demo output. "
                f"All three protocols (oidc, saml, ldap) must appear.\n"
                f"Combined output:\n{combined}"
            )

    def test_demo_cleans_up_its_rows(self, compose_stack: dict, pg_connection) -> None:
        """demo_normalization.py must delete the events it inserts.

        The demo's cleanup_events function runs unconditionally (inside a
        finally block). This test verifies no orphaned rows remain after a
        successful run.

        Strategy: record the start timestamp immediately before the demo run,
        then assert that no events for the demo's fixed user_ids (frank, grace,
        mallory, alice, diana) with source='api' and is_synthetic=True exist
        with a created_at >= that start time after the run completes.

        Using the demo's specific user_ids rather than a global count avoids
        false failures from other integration tests inserting events with the
        same source/is_synthetic combination.
        """
        import datetime

        assert DEMO_SCRIPT.exists(), f"demo script not found at {DEMO_SCRIPT}"

        # Fixed user_ids submitted by the demo's SCENES list (frank appears twice).
        demo_user_ids = ["frank", "grace", "mallory", "alice", "diana"]

        # Capture the wall-clock instant before the demo submits anything.
        # Use UTC so the comparison is timezone-safe regardless of PG session TZ.
        start_ts = datetime.datetime.now(datetime.timezone.utc)

        result = subprocess.run(
            [
                sys.executable,
                str(DEMO_SCRIPT),
                "--ingest-url",
                "http://localhost:8001",
                "--db-dsn",
                (
                    "host=localhost port=5432 dbname=naas "
                    "user=naas password=naas_dev_password"
                ),
                "--timeout",
                "60",
                "--pace",
                "0",
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=290,
        )

        assert result.returncode == 0, (
            f"Demo exited {result.returncode}. Cannot verify cleanup.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

        with pg_connection.cursor() as cur:
            cur.execute(
                "SELECT id, user_id FROM events"
                " WHERE user_id = ANY(%s)"
                "   AND source = %s"
                "   AND is_synthetic = %s"
                "   AND created_at >= %s",
                (demo_user_ids, "api", True, start_ts),
            )
            orphaned = cur.fetchall()

        assert not orphaned, (
            f"Demo left {len(orphaned)} orphaned event(s) in the database after "
            f"cleanup_events ran: {[(str(r[0]), r[1]) for r in orphaned]}. "
            "cleanup_events must delete all submitted event rows."
        )


# ---------------------------------------------------------------------------
# Fixture: pg_connection for cleanup verification test
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_connection(compose_stack: dict):
    """Synchronous psycopg3 connection for this module."""
    import psycopg  # noqa: PLC0415

    info = compose_stack["pg_conninfo"]
    conn = psycopg.connect(
        host=info["host"],
        port=info["port"],
        dbname=info["dbname"],
        user=info["user"],
        password=info["password"],
    )
    conn.autocommit = True
    yield conn
    conn.close()
