"""CLI program for exercising the NAAS normalization pipeline with a fixed event set.

Submits six login events (OIDC, SAML, LDAP) to the event ingestion service,
polls for normalization results via direct PostgreSQL reads, and renders a
comparison table using rich.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

# ---------------------------------------------------------------------------
# Optional soft import — naas_shared is not required at runtime.
# ---------------------------------------------------------------------------
try:
    from naas_shared.models import NormalizedAttributes  # noqa: F401

    NAAS_SHARED_AVAILABLE = True
except ImportError:
    NAAS_SHARED_AVAILABLE = False

# ---------------------------------------------------------------------------
# SQL query constants — parameterized, never interpolated.
# ---------------------------------------------------------------------------

POLL_QUERY = (
    "SELECT id, protocol, normalized_attributes FROM events WHERE id = ANY(%(ids)s)"
)
CLEANUP_QUERY = "DELETE FROM events WHERE id = ANY(%(ids)s)"

# ---------------------------------------------------------------------------
# Unified-schema attribute names (render order) and the protocol-native raw
# key that feeds each one (§2.2 of the ingestion contract). Used to align the
# before/after table rows and to show canonicalization transforms.
# ---------------------------------------------------------------------------

UNIFIED_ATTRIBUTES = [
    "display_name",
    "primary_email",
    "department",
    "employee_type",
    "groups",
]

RAW_KEY_BY_PROTOCOL: dict[str, dict[str, str]] = {
    "oidc": {
        "display_name": "name",
        "primary_email": "email",
        "department": "department",
        "employee_type": "employee_type",
        "groups": "groups",
    },
    "saml": {
        "display_name": "displayName",
        "primary_email": "email",
        "department": "dept",
        "employee_type": "employeeType",
        "groups": "groups",
    },
    "ldap": {
        "display_name": "cn",
        "primary_email": "mail",
        "department": "departmentNumber",
        "employee_type": "employeeType",
        "groups": "memberOf",
    },
}

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
        "caption": "OIDC login · token and directory agree — unanimous resolution lifts confidence",
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
        "caption": "OIDC login · token and directory disagree — per-attribute authority splits the winners",
        "raw_attributes": {
            "name": "Di Prince",
            "email": "diana@corp.com",
            "department": "Marketing",
            "employee_type": "vendor",
            "groups": ["engineering", "oncall"],
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

    Precedence: --db-dsn flag > POSTGRES_* env vars. Non-secret connection
    parameters fall back to local-dev defaults; the password has no default —
    POSTGRES_PASSWORD must be set when --db-dsn is not supplied.
    """
    if args.db_dsn:
        return args.db_dsn

    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    dbname = os.environ.get("POSTGRES_DB", "naas")
    user = os.environ.get("POSTGRES_USER", "naas")
    password = os.environ.get("POSTGRES_PASSWORD")
    if not password:
        sys.exit(
            "POSTGRES_PASSWORD is not set. Export it (see .env / .env.example) "
            "or pass a full DSN via --db-dsn."
        )
    return f"host={host} port={port} dbname={dbname} user={user} password={password}"


# ---------------------------------------------------------------------------
# Shared console — single output medium for status lines and scene panels
# ---------------------------------------------------------------------------

_console: Any = None


def get_console() -> Any:
    """Return the shared Rich Console used for all demo output.

    Lazily created on first use so the module stays importable without
    paying the rich import cost up front (matching the local-import style
    used for httpx/psycopg). Status lines and scene panels share this one
    console so the recording has a single, consistent output medium.
    """
    global _console
    if _console is None:
        from rich.console import Console  # local import

        _console = Console()
    return _console


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
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"Preflight failed: could not connect to PostgreSQL: {exc}")


def run_preflight(ingest_url: str, norm_url: str, db_dsn: str) -> None:
    """Run all preflight checks; exit on the first failure."""
    _check_health(ingest_url, "event-ingestion")
    _check_health(norm_url, "identity-normalization")
    _check_db(db_dsn)


# ---------------------------------------------------------------------------
# Confidence style helper
# ---------------------------------------------------------------------------


def confidence_style(value: float) -> str:
    """Return a Rich markup style string for a normalization confidence value.

    Thresholds: green >= 0.80, yellow (amber) 0.50–0.79, red < 0.50.
    """
    if value >= 0.80:
        return "green"
    if value >= 0.50:
        return "yellow"
    return "red"


# ---------------------------------------------------------------------------
# Flow functions
# ---------------------------------------------------------------------------


def submit_scenes(
    scenes: list[dict[str, Any]],
    ingest_url: str,
    *,
    http_client: Any = None,
) -> list[str]:
    """Submit each scene to the ingest service and return a list of event IDs.

    Posts scenes sequentially to {ingest_url}/events/ingest. Expects 202
    with {"id": ..., "status": "accepted"} per scene. Pacing (--pace/--step)
    is applied at render time, not here — submission produces no output, so
    pausing here would just look like a hang.
    """
    import httpx  # local import

    event_ids: list[str] = []
    owns_client = http_client is None
    client = http_client or httpx.Client()

    try:
        for i, scene in enumerate(scenes):
            body: dict[str, Any] = {
                "user_id": scene["user_id"],
                "protocol": scene["protocol"],
                "client_ip": scene["client_ip"],
                "source": scene.get("source", "api"),
                "is_synthetic": scene.get("is_synthetic", True),
                "raw_attributes": scene.get("raw_attributes", {}),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            try:
                resp = client.post(
                    f"{ingest_url}/events/ingest", json=body, timeout=10.0
                )
                resp.raise_for_status()
                data = resp.json()
                event_ids.append(str(data["id"]))
            except Exception as exc:  # noqa: BLE001
                sys.exit(f"Failed to submit scene {i + 1} ({scene['user_id']}): {exc}")
    finally:
        if owns_client:
            client.close()

    return event_ids


def _poll_loop(
    event_ids: list[str],
    timeout: float,
    db_fetch: Any,
) -> list[dict[str, Any]]:
    """Drive the poll cycle against a fetch callable.

    db_fetch(query, params) must return rows of (id, protocol,
    normalized_attributes). Runs on ~0.5s intervals until every captured id
    has non-null normalized_attributes, or timeout elapses. Parses
    normalized_attributes as plain JSON. Exits non-zero on timeout. Returns
    results in event_ids (submission) order.
    """
    deadline = time.monotonic() + timeout
    interval = 0.5

    while True:
        rows = db_fetch(POLL_QUERY, {"ids": event_ids})

        # Build a map from id -> row
        row_map: dict[str, dict[str, Any]] = {}
        for row in rows:
            row_id, protocol, normalized_attributes = row[0], row[1], row[2]
            if normalized_attributes is not None:
                if isinstance(normalized_attributes, str):
                    normalized_attributes = json.loads(normalized_attributes)
                row_map[str(row_id)] = {
                    "id": str(row_id),
                    "protocol": protocol,
                    "normalized_attributes": normalized_attributes,
                }

        if all(eid in row_map for eid in event_ids):
            return [row_map[eid] for eid in event_ids]

        if time.monotonic() >= deadline:
            unprocessed = [eid for eid in event_ids if eid not in row_map]
            get_console().print(
                f"Timeout: the following event IDs have not been normalized: {unprocessed}",
                style="bold red",
                markup=False,
                highlight=False,
            )
            sys.exit(1)

        time.sleep(interval)


def poll_results(
    event_ids: list[str],
    db_dsn: str,
    timeout: float,
    *,
    db_fetch: Any = None,
) -> list[dict[str, Any]]:
    """Poll PostgreSQL for normalized results for the given event IDs.

    Holds a single connection open for the lifetime of the poll (rather than
    reconnecting per interval); READ COMMITTED takes a fresh snapshot per
    statement, so each poll sees newly committed rows. If db_fetch is
    provided (a callable(query, params) -> rows), it is used instead of a
    live psycopg connection — enabling offline testing.
    """
    if db_fetch is not None:
        return _poll_loop(event_ids, timeout, db_fetch)

    import psycopg  # local import

    try:
        with psycopg.connect(db_dsn) as conn:

            def _live_fetch(query: str, params: dict[str, Any]) -> list[Any]:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    return cur.fetchall()

            return _poll_loop(event_ids, timeout, _live_fetch)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"Database error during polling: {exc}")


def verify_results(
    scenes: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compare normalization results against the frozen demo narrative.

    Pure function — no I/O. Returns a list of problem dicts, each with
    'scene' (1-based scene number; -1 for internal errors) and 'message'
    (str, self-contained — no scene prefix). Empty list = pass.
    Never raises; returns problems on invalid/unexpected payloads instead.

    Checks are structural and relative — never exact confidence numbers —
    so they are robust to minor numeric drift but catch config drift,
    pipeline bugs, or a wrong config. An expected resolution detail that is
    absent is a failure, not a skip: a missing detail means the pipeline did
    not produce the narrative at all.
    """
    problems: list[dict[str, Any]] = []

    def _problem(scene_no: int, message: str) -> None:
        problems.append({"scene": scene_no, "message": message})

    def _na(result: dict[str, Any]) -> dict[str, Any]:
        return result.get("normalized_attributes") or {}

    def _enrichment(na: dict[str, Any]) -> dict[str, Any]:
        return na.get("enrichment") or {}

    def _details(na: dict[str, Any]) -> dict[str, Any]:
        return na.get("resolution_details") or {}

    def _corroborated_fraction(groups_detail: dict[str, Any]) -> float:
        # Multi-source list_merge confidence is 0.7 + 0.3 × (fraction of merged
        # groups present in more than one source), so the corroborated fraction
        # is recoverable from the confidence without exact-number assertions.
        conf = float(groups_detail.get("confidence") or 0.0)
        return (conf - 0.7) / 0.3

    try:
        # Check 1: Scenes 1–4: enrichment must not be applied, every scalar
        # attribute must be a single_source resolution, and groups (which the
        # pipeline always resolves as a list_merge, even for one source) must
        # have at most one contributing source.
        for idx in range(4):
            if idx >= len(results):
                continue
            na = _na(results[idx])
            enr = _enrichment(na)
            if enr.get("applied") is True:
                _problem(
                    idx + 1,
                    "enrichment.applied must be False for single-source scenes, "
                    "got applied=True",
                )
            for attr, detail in _details(na).items():
                res = (detail or {}).get("resolution")
                if attr == "groups":
                    srcs = (detail or {}).get("sources") or []
                    if res != "list_merge" or len(srcs) > 1:
                        _problem(
                            idx + 1,
                            f"groups must be a single-source list_merge in a "
                            f"single-source scene, got resolution={res!r} "
                            f"with sources={srcs!r}",
                        )
                elif res != "single_source":
                    _problem(
                        idx + 1,
                        f"{attr} must be a single_source resolution in a "
                        f"single-source scene, got {res!r}",
                    )

        # Check 2: Scene 3 (grace/ldap) must have skip_reason='ldap_event'
        if len(results) > 2:
            na3 = _na(results[2])
            enr3 = _enrichment(na3)
            if (
                enr3.get("applied") is not False
                or enr3.get("skip_reason") != "ldap_event"
            ):
                _problem(
                    3,
                    "(grace/ldap) native LDAP event must have "
                    "enrichment.applied=False with skip_reason='ldap_event', got: "
                    f"applied={enr3.get('applied')!r}, "
                    f"skip_reason={enr3.get('skip_reason')!r}",
                )

        # Check 3: Scene 4 (mallory/saml) unmapped handling. The −0.2
        # normalization-failure penalty is not persisted as a flag on
        # single_source details, so it is verified relatively: Scene 4's
        # department confidence must sit strictly below Scene 2's clean SAML
        # department (same source weight, no penalty).
        if len(results) > 3:
            na4 = _na(results[3])
            dept4 = na4.get("department")
            et4 = na4.get("employee_type")

            if dept4 is None:
                _problem(
                    4,
                    "(mallory/saml) department 'Sorcery' must be retained "
                    "(unmapped free-text kept with penalty); got None",
                )

            dept4_detail = _details(na4).get("department")
            if not dept4_detail:
                _problem(
                    4,
                    "(mallory/saml) department resolution detail is missing — "
                    "expected a single_source resolution carrying the unmapped "
                    "penalty",
                )
            elif len(results) > 1:
                dept2_detail = _details(_na(results[1])).get("department")
                if dept2_detail:
                    d4_conf = float(dept4_detail.get("confidence") or 0.0)
                    d2_conf = float(dept2_detail.get("confidence") or 0.0)
                    if not (d4_conf < d2_conf):
                        _problem(
                            4,
                            f"(mallory/saml) unmapped department confidence "
                            f"({d4_conf}) must be strictly below Scene 2's clean "
                            f"SAML department ({d2_conf}) — the −0.2 "
                            f"normalization-failure penalty is not visible",
                        )

            if et4 is not None:
                _problem(
                    4,
                    f"(mallory/saml) employee_type 'wizard' must be discarded "
                    f"to None (enum-safe policy); got {et4!r}",
                )

        # Check 4: Confidence ordering C(4) < C(2) < C(1) < C(3)
        if len(results) >= 4:
            c = [_na(results[i]).get("normalization_confidence", 0.0) for i in range(4)]
            c1, c2, c3, c4 = c[0], c[1], c[2], c[3]

            if not (c4 < c2):
                _problem(
                    4,
                    f"Confidence ordering violated: C(4)={c4} must be < C(2)={c2}",
                )
            if not (c2 < c1):
                _problem(
                    2,
                    f"Confidence ordering violated: C(2)={c2} must be < C(1)={c1}",
                )
            if not (c1 < c3):
                _problem(
                    1,
                    f"Confidence ordering violated: C(1)={c1} must be < C(3)={c3}",
                )

        # Check 5: Scenes 5–6 must have enrichment applied, and at least one
        # multi-source resolution (§5.5 check 5) — enrichment that ran but
        # merged nothing would leave every attribute single_source.
        for idx in [4, 5]:
            if idx >= len(results):
                continue
            na = _na(results[idx])
            enr = _enrichment(na)
            if enr.get("applied") is not True:
                _problem(
                    idx + 1,
                    f"enrichment.applied must be True (LDAP enrichment expected); "
                    f"got {enr.get('applied')!r}",
                )
            multi_source = [
                attr
                for attr, detail in _details(na).items()
                if (detail or {}).get("resolution") != "single_source"
            ]
            if not multi_source:
                _problem(
                    idx + 1,
                    "expected at least one multi-source resolution "
                    "(unanimous/priority/list_merge); every attribute resolved "
                    "single_source — enrichment merged nothing from the directory",
                )

        # Check 6: Scene 5 (alice/oidc enriched):
        #   - scalars must be unanimous (not priority)
        #   - groups must be present and list_merge, directory-corroborated
        #   - C(5) > C(1)
        if len(results) >= 5:
            na5 = _na(results[4])
            details5 = _details(na5)
            c5 = na5.get("normalization_confidence", 0.0)
            c1_val = _na(results[0]).get("normalization_confidence", 0.0)

            scalar_attrs = [
                "display_name",
                "primary_email",
                "department",
                "employee_type",
            ]
            for attr in scalar_attrs:
                detail = details5.get(attr)
                if detail and detail.get("resolution") == "priority":
                    _problem(
                        5,
                        f"(alice/oidc enriched) {attr} resolution must be "
                        f"'unanimous' when sources agree, got 'priority'",
                    )

            groups5 = details5.get("groups")
            if not groups5:
                _problem(
                    5,
                    "(alice/oidc enriched) groups resolution detail is missing — "
                    "expected a list_merge of token and directory groups",
                )
            elif groups5.get("resolution") != "list_merge":
                _problem(
                    5,
                    f"(alice/oidc enriched) groups resolution must be "
                    f"'list_merge', got {groups5.get('resolution')!r}",
                )
            elif _corroborated_fraction(groups5) < 0.5:
                _problem(
                    5,
                    f"(alice/oidc enriched) merged groups must be "
                    f"directory-corroborated (≥ half of merged groups present in "
                    f"both token and directory); implied corroborated fraction is "
                    f"{_corroborated_fraction(groups5):.2f} — LDAP enrichment "
                    f"merged little or nothing from the directory (memberOf "
                    f"back-population broken?)",
                )

            if c5 <= c1_val:
                _problem(
                    5,
                    f"Confidence ordering violated: C(5)={c5} must be > C(1)={c1_val}",
                )

        # Check 7: Scene 6 (diana/oidc conflict) — the core check. Each
        # expected detail must be PRESENT; a missing detail means the
        # narrative was not produced and must fail, not pass silently.
        #   - display_name priority winner_source must be 'oidc'
        #   - department priority winner_source must be 'ldap'
        #   - groups must be list_merge, corroborated, strict superset of token
        #   - C(6) < C(5)
        if len(results) >= 6:
            na6 = _na(results[5])
            details6 = _details(na6)
            c6 = na6.get("normalization_confidence", 0.0)
            c5_val = (
                _na(results[4]).get("normalization_confidence", 0.0)
                if len(results) >= 5
                else 1.0
            )

            dn6 = details6.get("display_name")
            if not dn6:
                _problem(
                    6,
                    "(diana/oidc) display_name resolution detail is missing — "
                    "expected a priority resolution won by 'oidc'",
                )
            elif (
                dn6.get("resolution") != "priority"
                or dn6.get("winner_source") != "oidc"
            ):
                _problem(
                    6,
                    f"(diana/oidc) display_name must have priority resolution "
                    f"with winner_source='oidc'; "
                    f"got resolution={dn6.get('resolution')!r}, "
                    f"winner_source={dn6.get('winner_source')!r} — "
                    f"config/normalization.yaml display_name.priority is not "
                    f"[oidc, …]?",
                )

            dept6 = details6.get("department")
            if not dept6:
                _problem(
                    6,
                    "(diana/oidc) department resolution detail is missing — "
                    "expected a priority resolution won by 'ldap'",
                )
            elif (
                dept6.get("resolution") != "priority"
                or dept6.get("winner_source") != "ldap"
            ):
                _problem(
                    6,
                    f"(diana/oidc) department must have priority resolution "
                    f"with winner_source='ldap'; "
                    f"got resolution={dept6.get('resolution')!r}, "
                    f"winner_source={dept6.get('winner_source')!r} — "
                    f"config/normalization.yaml department.priority is not "
                    f"[ldap, …]?",
                )

            groups6 = details6.get("groups")
            if not groups6:
                _problem(
                    6,
                    "(diana/oidc) groups resolution detail is missing — "
                    "expected a list_merge of token and directory groups",
                )
            elif groups6.get("resolution") != "list_merge":
                _problem(
                    6,
                    f"(diana/oidc) groups resolution must be 'list_merge', "
                    f"got {groups6.get('resolution')!r}",
                )
            elif _corroborated_fraction(groups6) < 0.25:
                _problem(
                    6,
                    f"(diana/oidc) merged groups must be "
                    f"directory-corroborated (expected fraction ⅓: only "
                    f"'engineering' is in both token and directory); implied "
                    f"corroborated fraction is "
                    f"{_corroborated_fraction(groups6):.2f} — LDAP enrichment "
                    f"merged little or nothing from the directory (memberOf "
                    f"back-population broken?)",
                )

            # Scene 6 token omits a directory group (vpn-users), so the merged
            # set must be a strict superset of the token groups.
            token_groups6 = set(scenes[5].get("raw_attributes", {}).get("groups") or [])
            merged_groups6 = set(na6.get("groups") or [])
            if not (token_groups6 < merged_groups6):
                _problem(
                    6,
                    f"(diana/oidc) merged groups must be a strict "
                    f"superset of the token groups (directory back-population "
                    f"must add at least one group); token={sorted(token_groups6)}, "
                    f"merged={sorted(merged_groups6)}",
                )

            groups5_detail = _details(_na(results[4])).get("groups") or {}
            g5_conf = float(groups5_detail.get("confidence") or 0.0)
            g6_conf = float(groups6.get("confidence") or 0.0) if groups6 else 0.0
            if groups6 and groups5_detail and not (g6_conf < g5_conf):
                _problem(
                    6,
                    f"(diana/oidc) groups confidence must be < Scene 5's "
                    f"(Scene 6's token only partially matches the directory); "
                    f"got Scene 6 groups={g6_conf} vs Scene 5 groups={g5_conf}",
                )

            if c6 >= c5_val:
                _problem(
                    6,
                    f"Confidence ordering violated: C(6)={c6} must be < C(5)={c5_val}",
                )

    except Exception as exc:  # noqa: BLE001
        problems.append(
            {"scene": -1, "message": f"Unexpected error in verify_results: {exc}"}
        )

    return problems


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------


def _render_bar(value: float, width: int = 10) -> str:
    """Return a simple ASCII bar representing a 0.0–1.0 confidence value."""
    filled = round(value * width)
    return "[" + "#" * filled + "." * (width - filled) + "]"


def _render_enrichment_status(enr: dict[str, Any]) -> str:
    """Return a human-readable enrichment status string."""
    if enr.get("applied") is True:
        source = enr.get("source", "unknown")
        cache_hit = enr.get("cache_hit", False)
        cache_label = "cache hit" if cache_hit else "live lookup"
        return f"applied — source={source}, {cache_label}"
    reason = enr.get("skip_reason", "unknown")
    return f"skipped — {reason}"


def _render_resolution_type(detail: dict[str, Any]) -> str:
    """Return a short label for a resolution type."""
    res = detail.get("resolution", "unknown")
    labels = {
        "single_source": "single",
        "unanimous": "unanimous",
        "priority": "priority",
        "list_merge": "list_merge",
    }
    return labels.get(res, str(res))


def _format_sources(detail: dict[str, Any]) -> str:
    """Return a sources/winner string for a resolution detail.

    Priority rows highlight the winner and render the losing
    conflicting_values dimmed, labeled with their source.
    """
    res = detail.get("resolution", "")
    if res == "priority":
        winner = detail.get("winner_source", "")
        conflicting = detail.get("conflicting_values", {})
        losers = ", ".join(f"{k}={v!r}" for k, v in conflicting.items())
        return f"winner={winner} [dim](losers: {losers})[/dim]"
    sources = detail.get("sources", [])
    if sources:
        return "/".join(sources)
    return ""


def _abbrev_dn(value: str) -> str:
    """Abbreviate an LDAP DN to its first RDN (e.g. 'cn=engineering,…')."""
    if value.lower().startswith("cn=") and "," in value:
        return value.split(",", 1)[0] + ",…"
    return value


def _fmt_transform(raw_value: Any, normalized: Any) -> str:
    """Render a normalized value, showing the change visibly when the raw
    value differs (e.g. 'eng → Engineering', 'wizard → null').

    For lists the comparison is set-wise; raw DN elements are abbreviated
    to their first RDN so 'cn=engineering,… → engineering, admins' stays
    legible.
    """
    if isinstance(normalized, list):
        raw_list = raw_value if isinstance(raw_value, list) else []
        if raw_list and set(raw_list) != set(normalized):
            raw_str = ", ".join(_abbrev_dn(str(x)) for x in raw_list)
            return f"{raw_str} → {', '.join(normalized)}"
        return ", ".join(normalized) if normalized else "—"
    if normalized is None:
        if raw_value is not None:
            return f"{raw_value} → null"
        return "null"
    if raw_value is not None and str(raw_value) != str(normalized):
        return f"{raw_value} → {normalized}"
    return str(normalized)


def _render_scene_panel(
    scene_idx: int,
    scene: dict[str, Any],
    result: dict[str, Any],
    console: Any,
) -> None:
    """Render a single scene as a Rich Panel with before/after table and resolution details."""
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    na = result.get("normalized_attributes") or {}
    details = na.get("resolution_details") or {}
    enr = na.get("enrichment") or {}
    conf = na.get("normalization_confidence", 0.0)
    caption = scene.get("caption", f"Scene {scene_idx + 1}")
    raw_attrs = scene.get("raw_attributes", {})

    is_scene6 = scene_idx == 5
    border_style = "bold cyan" if is_scene6 else "dim"

    # --- Before/After table ---
    # Rows are aligned per unified attribute: the protocol-native raw key
    # feeding each unified attribute sits on the same row, and canonicalized
    # values show the transform visibly (e.g. 'eng → Engineering').
    ba_table = Table(show_header=True, header_style="bold", expand=True)
    ba_table.add_column("Raw / protocol-native", style="dim", ratio=1)
    ba_table.add_column("Normalized / unified", ratio=1)

    def _fmt_raw(v: Any) -> str:
        if isinstance(v, list):
            return ", ".join(str(x) for x in v)
        return str(v) if v is not None else "—"

    raw_key_map = RAW_KEY_BY_PROTOCOL.get(scene.get("protocol", ""), {})
    for attr in UNIFIED_ATTRIBUTES:
        raw_key = raw_key_map.get(attr)
        left = ""
        raw_value = None
        if raw_key is not None and raw_key in raw_attrs:
            raw_value = raw_attrs[raw_key]
            left = f"{raw_key}: {_fmt_raw(raw_value)}"
        right = f"{attr}: {_fmt_transform(raw_value, na.get(attr))}"
        ba_table.add_row(left, right)

    # --- Enrichment status ---
    enr_str = _render_enrichment_status(enr)

    # --- Resolution details table ---
    res_table = Table(show_header=True, header_style="bold", expand=True)
    res_table.add_column("Attribute")
    res_table.add_column("Resolution")
    res_table.add_column("Value")
    res_table.add_column("Source(s)/Winner")
    res_table.add_column("Confidence")

    for attr in UNIFIED_ATTRIBUTES:
        detail = details.get(attr)
        if detail is None:
            continue
        res_type = _render_resolution_type(detail)
        val = detail.get("resolved_value")
        val_str = _fmt_raw(val) if val is not None else "null"
        sources_str = _format_sources(detail)
        c = detail.get("confidence", 0.0)
        c_style = confidence_style(c)
        c_str = f"[{c_style}]{c:.2f}[/{c_style}] {_render_bar(c, 8)}"

        row_style = ""
        if detail.get("resolution") == "priority":
            row_style = "bold"

        res_table.add_row(attr, res_type, val_str, sources_str, c_str, style=row_style)

    # --- Overall confidence ---
    c_style = confidence_style(conf)
    conf_text = Text()
    conf_text.append("Overall confidence: ", style="bold")
    conf_text.append(f"{conf:.3f} ", style=f"bold {c_style}")
    conf_text.append(_render_bar(conf, 20), style=c_style)

    # --- Scene 4 annotations ---
    scene4_note = ""
    if scene_idx == 3:
        scene4_note = (
            "\nAttribute handling notes:\n"
            "  department 'Sorcery': retained (unmapped free-text kept) with −0.2 penalty applied\n"
            "  employee_type 'wizard': discarded to null — enum-safe policy "
            "(non-standard values dropped, not stored)"
        )

    # --- Scene 6 split-source annotation ---
    scene6_note = ""
    if is_scene6:
        scene6_note = (
            "\nWhy the split?\n"
            "  display_name → OIDC wins: token claims hold the user's current preferred/presented name\n"
            "  department   → LDAP wins: the directory holds authoritative org structure facts\n"
            "  No single OIDC-or-LDAP rule could capture both: identity presentation "
            "and org hierarchy come from different authoritative sources.\n"
            "Groups merge:\n"
            "  The token omitted vpn-users; the directory back-populated it, so the "
            "merged set is a superset of the token's.\n"
            "  Only 1 of 3 merged groups appears in both sources (vs 2 of 3 in "
            "Scene 5), so the merge confidence is lower."
        )

    # Build panel content
    from rich import box
    from rich.console import Group

    panel_content_parts: list[Any] = [
        ba_table,
        Text(f"\nEnrichment: {enr_str}"),
        Text("\nResolution details:"),
        res_table,
        conf_text,
    ]
    if scene4_note:
        panel_content_parts.append(Text(scene4_note, style="italic"))
    if scene6_note:
        panel_content_parts.append(Text(scene6_note, style="bold yellow"))

    panel_group = Group(*panel_content_parts)

    title = f"Scene {scene_idx + 1} — {caption}"
    panel = Panel(
        panel_group,
        title=title,
        border_style=border_style,
        box=box.DOUBLE_EDGE if is_scene6 else box.ROUNDED,
    )
    console.print(panel)


def render_results(
    scenes: list[dict[str, Any]],
    results: list[dict[str, Any]],
    *,
    console: Any = None,
    pace: float = 0.0,
    step: bool = False,
) -> None:
    """Render a rich comparison table to the console.

    Renders per-scene bordered panels and a summary table. Uses the provided
    console if given (for testability), otherwise the shared module console.
    Between panels, waits for Enter when step is True, else sleeps pace
    seconds when pace > 0. Verification problems are reported by main()
    before rendering is reached — a failed narrative is never rendered.
    """
    from rich.table import Table
    from rich.text import Text

    con = console or get_console()

    # Render each scene
    for i, (scene, result) in enumerate(zip(scenes, results, strict=True)):
        con.print()
        if i > 0:
            if step:
                con.input("[dim italic]Press Enter for next scene…[/dim italic]")
            elif pace and pace > 0:
                time.sleep(pace)
        _render_scene_panel(i, scene, result, con)

    # Summary table
    con.print()
    summary = Table(
        title="Normalization Summary", show_header=True, header_style="bold"
    )
    summary.add_column("Scene")
    summary.add_column("Protocol(s)")
    summary.add_column("Enrichment")
    summary.add_column("Resolution mix")
    summary.add_column("Confidence")

    for i, (scene, result) in enumerate(zip(scenes, results, strict=True)):
        na = result.get("normalized_attributes") or {}
        details = na.get("resolution_details") or {}
        enr = na.get("enrichment") or {}
        conf = na.get("normalization_confidence", 0.0)

        protocol = scene.get("protocol", "?")
        enr_label = "yes" if enr.get("applied") else "no"

        res_types: set[str] = set()
        proto_set: set[str] = set()
        for detail in details.values():
            res_types.add(detail.get("resolution", "?"))
            proto_set.update(detail.get("sources") or [])
            if detail.get("resolution") == "priority":
                if detail.get("winner_source"):
                    proto_set.add(detail["winner_source"])
                proto_set.update((detail.get("conflicting_values") or {}).keys())
        res_mix = ", ".join(sorted(res_types))
        protocols = "/".join(sorted(proto_set)) if proto_set else protocol

        c_style = confidence_style(conf)
        conf_cell = Text(f"{conf:.3f}", style=c_style)

        scene_label = f"{i + 1} — {scene.get('user_id', '?')}/{protocol}"
        summary.add_row(scene_label, protocols, enr_label, res_mix, conf_cell)

    con.print(summary)


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def cleanup_events(
    event_ids: list[str],
    db_dsn: str,
    *,
    db_execute: Any = None,
) -> None:
    """Delete submitted events from PostgreSQL.

    If db_execute is provided (a callable(query, params)), uses that seam
    instead of a live psycopg connection — enabling offline testing.
    Prints the count of rows removed (or IDs retained for --keep path).
    """
    if db_execute is not None:
        db_execute(CLEANUP_QUERY, {"ids": event_ids})
        return

    import psycopg  # local import

    try:
        with psycopg.connect(db_dsn) as conn, conn.cursor() as cur:
            cur.execute(CLEANUP_QUERY, {"ids": event_ids})
            count = cur.rowcount
        get_console().print(
            f"Cleanup: removed {count} event(s) from the database.",
            style="dim",
            highlight=False,
        )
    except Exception as exc:  # noqa: BLE001
        get_console().print(
            f"Cleanup warning: could not delete events: {exc}",
            style="yellow",
            markup=False,
            highlight=False,
        )


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

    console = get_console()
    console.print(
        f"Submitting {len(SCENES)} scene(s) to {ingest_url}...",
        style="dim",
        highlight=False,
    )
    event_ids = submit_scenes(SCENES, ingest_url)

    # From here on the run owns rows in the events table: whatever happens
    # (poll timeout, verification failure, render error), the finally block
    # cleans them up — unless --keep — so repeated runs don't accumulate rows.
    try:
        console.print("Waiting for normalization results...", style="dim")
        results = poll_results(event_ids, db_dsn, args.timeout)
        problems = verify_results(SCENES, results) if not args.skip_verify else []

        if problems:
            console.print(
                f"Verification failed with {len(problems)} problem(s). "
                "Aborting render.",
                style="bold red",
                highlight=False,
            )
            for p in problems:
                console.print(
                    f"  Scene {p.get('scene', '?')}: {p.get('message', '')}",
                    style="red",
                    markup=False,
                    highlight=False,
                )
            sys.exit(1)

        render_results(SCENES, results, console=console, pace=args.pace, step=args.step)
    finally:
        if args.keep:
            console.print(
                f"Retained {len(event_ids)} event(s) in the database (--keep).",
                style="dim",
                highlight=False,
            )
            console.print(
                f"Retained event IDs: {event_ids}",
                style="dim",
                markup=False,
                highlight=False,
            )
        else:
            cleanup_events(event_ids, db_dsn)


if __name__ == "__main__":
    main()
