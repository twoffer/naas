"""CLI program for exercising the NAAS normalization pipeline with a fixed event set.

Submits six login events (OIDC, SAML, LDAP) to the event ingestion service,
polls for normalization results via direct PostgreSQL reads, and renders a
comparison table using rich.

The submit/poll/verify/render/cleanup flow functions are stubs in this version
and will be implemented in a subsequent chunk.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Optional soft import — naas_shared is not required at runtime.
# ---------------------------------------------------------------------------
try:
    from naas_shared.models import LoginEventIngest, NormalizedAttributes  # type: ignore[import]

    NAAS_SHARED_AVAILABLE = True
except ImportError:
    LoginEventIngest = None  # type: ignore[assignment,misc]
    NormalizedAttributes = None  # type: ignore[assignment,misc]
    NAAS_SHARED_AVAILABLE = False

# ---------------------------------------------------------------------------
# Ground-truth scenes — protocol-native key shapes, exact values.
# ---------------------------------------------------------------------------

SCENES: list[dict[str, Any]] = [
    {
        "user_id": "frank",
        "protocol": "oidc",
        "client_ip": "203.0.113.10",
        "source": "api",
        "is_synthetic": True,
        "caption": "OIDC login · single source, no directory enrichment yet",
        "raw_attributes": {
            "name": "Frank Castle",
            "email": "frank@corp.com",
            "department": "eng",
            "employee_type": "E",
            "groups": ["engineering", "vpn-users"],
        },
    },
    {
        "user_id": "frank",
        "protocol": "saml",
        "client_ip": "203.0.113.10",
        "source": "api",
        "is_synthetic": True,
        "caption": "SAML login · same user, SAML-native attribute keys",
        "raw_attributes": {
            "displayName": "Frank Castle",
            "email": "frank@corp.com",
            "dept": "Engineering",
            "employeeType": "FTE",
            "groups": ["engineering", "vpn-users"],
        },
    },
    {
        "user_id": "grace",
        "protocol": "ldap",
        "client_ip": "203.0.113.11",
        "source": "api",
        "is_synthetic": True,
        "caption": "LDAP bind · directory-native attrs, DN-encoded group membership",
        "raw_attributes": {
            "cn": "Grace Hopper",
            "mail": "grace@corp.com",
            "departmentNumber": "r&d",
            "employeeType": "C",
            "memberOf": [
                "cn=engineering,ou=groups,dc=corp,dc=com",
                "cn=admins,ou=groups,dc=corp,dc=com",
            ],
        },
    },
    {
        "user_id": "mallory",
        "protocol": "saml",
        "client_ip": "203.0.113.12",
        "source": "api",
        "is_synthetic": True,
        "caption": "SAML login · unknown department and non-standard employee type",
        "raw_attributes": {
            "displayName": "Mallory Quinn",
            "email": "mallory@corp.com",
            "dept": "Sorcery",
            "employeeType": "wizard",
            "groups": ["temp-access"],
        },
    },
    {
        "user_id": "alice",
        "protocol": "oidc",
        "client_ip": "203.0.113.20",
        "source": "api",
        "is_synthetic": True,
        "caption": "OIDC login · FTE with elevated group membership",
        "raw_attributes": {
            "name": "Alice Smith",
            "email": "alice@corp.com",
            "department": "eng",
            "employee_type": "FTE",
            "groups": ["engineering", "vpn-users", "product-admins"],
        },
    },
    {
        "user_id": "diana",
        "protocol": "oidc",
        "client_ip": "203.0.113.21",
        "source": "api",
        "is_synthetic": True,
        "caption": "OIDC login · vendor account with cross-team group overlap",
        "raw_attributes": {
            "name": "Di Prince",
            "email": "diana@corp.com",
            "department": "Marketing",
            "employee_type": "vendor",
            "groups": ["engineering", "vpn-users", "oncall"],
        },
    },
]

# ---------------------------------------------------------------------------
# Environment resolution helpers
# ---------------------------------------------------------------------------


def _resolve_ingest_url(args: argparse.Namespace) -> str:
    """Return the event ingestion service base URL.

    Precedence: --ingest-url flag > INGEST_URL env var > default.
    """
    if args.ingest_url:
        return args.ingest_url.rstrip("/")
    return os.environ.get("INGEST_URL", "http://localhost:8001").rstrip("/")


def _resolve_norm_url() -> str:
    """Return the normalization service base URL from NORM_URL env var."""
    return os.environ.get("NORM_URL", "http://localhost:8002").rstrip("/")


def _resolve_db_dsn(args: argparse.Namespace) -> str:
    """Return the psycopg DSN for direct PostgreSQL access.

    Precedence: --db-dsn flag > POSTGRES_* env vars.
    """
    if args.db_dsn:
        return args.db_dsn

    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    dbname = os.environ.get("POSTGRES_DB", "naas")
    user = os.environ.get("POSTGRES_USER", "naas")
    password = os.environ.get("POSTGRES_PASSWORD", "naas")
    return f"host={host} port={port} dbname={dbname} user={user} password={password}"


# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------


def _check_health(url: str, service_name: str) -> None:
    """GET {url}/health and assert status == 'healthy'.

    Exits the process with a non-zero code on the first failure.
    """
    import httpx  # local import keeps top-level import-time cost near zero

    try:
        response = httpx.get(f"{url}/health", timeout=5.0)
        response.raise_for_status()
        data = response.json()
        if data.get("status") != "healthy":
            sys.exit(
                f"Preflight failed: {service_name} at {url} reported status="
                f"{data.get('status')!r} (expected 'healthy')"
            )
    except httpx.HTTPError as exc:
        sys.exit(f"Preflight failed: could not reach {service_name} at {url}: {exc}")
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"Preflight failed: unexpected error checking {service_name}: {exc}")


def _check_db(dsn: str) -> None:
    """Open a psycopg connection and execute SELECT 1.

    Exits the process with a non-zero code on the first failure.
    """
    import psycopg  # local import

    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"Preflight failed: could not connect to PostgreSQL: {exc}")


def run_preflight(ingest_url: str, norm_url: str, db_dsn: str) -> None:
    """Run all preflight checks; exit on the first failure."""
    _check_health(ingest_url, "event-ingestion")
    _check_health(norm_url, "identity-normalization")
    _check_db(db_dsn)


# ---------------------------------------------------------------------------
# Flow stubs — implemented in a later chunk
# ---------------------------------------------------------------------------


def submit_scenes(
    scenes: list[dict[str, Any]],
    ingest_url: str,
    args: argparse.Namespace,
) -> list[str]:
    """Submit each scene to the ingest service and return a list of event IDs.

    Not yet implemented.
    """
    raise NotImplementedError("submit_scenes is not yet implemented")


def poll_results(
    event_ids: list[str],
    db_dsn: str,
    timeout: float,
) -> list[dict[str, Any]]:
    """Poll PostgreSQL for normalized results for the given event IDs.

    Not yet implemented.
    """
    raise NotImplementedError("poll_results is not yet implemented")


def verify_results(
    scenes: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compare normalization results against scene expectations.

    Not yet implemented.
    """
    raise NotImplementedError("verify_results is not yet implemented")


def render_results(
    scenes: list[dict[str, Any]],
    results: list[dict[str, Any]],
    verification: list[dict[str, Any]] | None,
) -> None:
    """Render a rich comparison table to stdout.

    Not yet implemented.
    """
    raise NotImplementedError("render_results is not yet implemented")


def cleanup_events(event_ids: list[str], db_dsn: str) -> None:
    """Delete submitted events from PostgreSQL when --keep is not set.

    Not yet implemented.
    """
    raise NotImplementedError("cleanup_events is not yet implemented")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser for the CLI."""
    parser = argparse.ArgumentParser(
        description="Submit a fixed set of login events through the NAAS normalization pipeline.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        default=False,
        help="Retain submitted events in the database after the run (default: delete).",
    )
    parser.add_argument(
        "--pace",
        metavar="SECONDS",
        type=float,
        default=1.5,
        help="Delay in seconds between scenes. Set to 0 to disable.",
    )
    parser.add_argument(
        "--step",
        action="store_true",
        default=False,
        help="Wait for Enter between scenes. Overrides --pace.",
    )
    parser.add_argument(
        "--timeout",
        metavar="SECONDS",
        type=float,
        default=30,
        help="Maximum seconds to wait for a normalization result.",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        default=False,
        help="Skip normalization output verification.",
    )
    parser.add_argument(
        "--ingest-url",
        metavar="URL",
        default=None,
        help="Base URL for the event ingestion service (default: INGEST_URL env or http://localhost:8001).",
    )
    parser.add_argument(
        "--db-dsn",
        metavar="DSN",
        default=None,
        help=(
            "Full psycopg DSN for direct PostgreSQL reads. "
            "Overrides POSTGRES_* env vars."
        ),
    )
    return parser


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    """Parse arguments, run preflight checks, and invoke the flow."""
    parser = _build_parser()
    args = parser.parse_args()

    ingest_url = _resolve_ingest_url(args)
    norm_url = _resolve_norm_url()
    db_dsn = _resolve_db_dsn(args)

    run_preflight(ingest_url, norm_url, db_dsn)

    event_ids = submit_scenes(SCENES, ingest_url, args)
    results = poll_results(event_ids, db_dsn, args.timeout)
    verification = verify_results(SCENES, results) if not args.skip_verify else None
    render_results(SCENES, results, verification)

    if not args.keep:
        cleanup_events(event_ids, db_dsn)


if __name__ == "__main__":
    main()
