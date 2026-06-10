"""CLI program for exercising the NAAS normalization pipeline with a fixed event set.

Submits six login events (OIDC, SAML, LDAP) to the event ingestion service,
polls for normalization results via direct PostgreSQL reads, and renders a
comparison table using rich.
"""

from __future__ import annotations

import argparse
import gc as _gc
import json
import os
import sys
import time
import types as _types_reg
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
    args: argparse.Namespace,
    *,
    http_client: Any = None,
) -> list[str]:
    """Submit each scene to the ingest service and return a list of event IDs.

    Posts scenes sequentially to {ingest_url}/events/ingest. Expects 202
    with {"id": ..., "status": "accepted"} per scene. Pacing between scenes
    is controlled by args.pace and args.step.
    """
    import httpx  # local import

    event_ids: list[str] = []
    client = http_client or httpx.Client()

    for i, scene in enumerate(scenes):
        if i > 0:
            if getattr(args, "step", False):
                input("Press Enter for next scene...")
            elif getattr(args, "pace", 0) and args.pace > 0:
                time.sleep(args.pace)

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
            resp = client.post(f"{ingest_url}/events/ingest", json=body, timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
            event_ids.append(str(data["id"]))
        except Exception as exc:  # noqa: BLE001
            sys.exit(f"Failed to submit scene {i} ({scene['user_id']}): {exc}")

    return event_ids


def poll_results(
    event_ids: list[str],
    db_dsn: str,
    timeout: float,
) -> list[dict[str, Any]]:
    """Poll PostgreSQL for normalized results for the given event IDs.

    Runs POLL_QUERY on ~0.5s intervals until every captured id has
    non-null normalized_attributes, or timeout elapses. Parses
    normalized_attributes as plain JSON. Exits non-zero on timeout.
    """
    import psycopg  # local import

    deadline = time.monotonic() + timeout
    interval = 0.5

    while True:
        try:
            with psycopg.connect(db_dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(POLL_QUERY, {"ids": event_ids})
                    rows = cur.fetchall()
        except Exception as exc:  # noqa: BLE001
            sys.exit(f"Database error during polling: {exc}")

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
            print(
                f"Timeout: the following event IDs have not been normalized: {unprocessed}"
            )
            sys.exit(1)

        time.sleep(interval)


def verify_results(
    scenes: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compare normalization results against known scene expectations.

    Pure function — no I/O. Returns a list of problem dicts, each with
    at least 'scene' (int index) and 'message' (str). Empty list = pass.
    Never raises; returns problems on invalid/unexpected payloads instead.
    """
    problems: list[dict[str, Any]] = []

    def _problem(scene_idx: int, message: str) -> None:
        problems.append({"scene": scene_idx, "message": message})

    def _na(result: dict[str, Any]) -> dict[str, Any]:
        return result.get("normalized_attributes") or {}

    def _enrichment(na: dict[str, Any]) -> dict[str, Any]:
        return na.get("enrichment") or {}

    def _details(na: dict[str, Any]) -> dict[str, Any]:
        return na.get("resolution_details") or {}

    try:
        # Check 1: Scenes 1–4 (indices 0–3): enrichment must not be applied.
        for idx in range(4):
            if idx >= len(results):
                continue
            na = _na(results[idx])
            enr = _enrichment(na)
            if enr.get("applied") is True:
                _problem(
                    idx,
                    f"Scene {idx + 1}: enrichment.applied must be False for "
                    f"single-source scenes, got applied=True",
                )

        # Check 2: Scene 3 (index 2, grace/ldap) must have skip_reason='ldap_event'
        if len(results) > 2:
            na3 = _na(results[2])
            enr3 = _enrichment(na3)
            if (
                enr3.get("applied") is not False
                or enr3.get("skip_reason") != "ldap_event"
            ):
                _problem(
                    2,
                    "Scene 3: native LDAP event must have enrichment.applied=False "
                    "with skip_reason='ldap_event', got: "
                    f"applied={enr3.get('applied')!r}, "
                    f"skip_reason={enr3.get('skip_reason')!r}",
                )

        # Check 3: Scene 4 (index 3, mallory/saml) unmapped handling
        if len(results) > 3:
            na4 = _na(results[3])
            dept4 = na4.get("department")
            et4 = na4.get("employee_type")

            if dept4 is None:
                _problem(
                    3,
                    "Scene 4 (mallory/saml): department 'Sorcery' must be retained "
                    "(unmapped free-text kept with penalty); got None",
                )

            if et4 is not None:
                _problem(
                    3,
                    f"Scene 4 (mallory/saml): employee_type 'wizard' must be discarded "
                    f"to None (enum-safe policy); got {et4!r}",
                )

        # Check 4: Confidence ordering C(4) < C(2) < C(1) < C(3)
        # indices: scene4=3, scene2=1, scene1=0, scene3=2
        if len(results) >= 4:
            c = [_na(results[i]).get("normalization_confidence", 0.0) for i in range(4)]
            c1, c2, c3, c4 = c[0], c[1], c[2], c[3]

            if not (c4 < c2):
                _problem(
                    3,
                    f"Confidence ordering violated: C(4)={c4} must be < C(2)={c2}",
                )
            if not (c2 < c1):
                _problem(
                    1,
                    f"Confidence ordering violated: C(2)={c2} must be < C(1)={c1}",
                )
            if not (c1 < c3):
                _problem(
                    0,
                    f"Confidence ordering violated: C(1)={c1} must be < C(3)={c3}",
                )

        # Check 5: Scenes 5–6 (indices 4–5) must have enrichment applied.
        for idx in [4, 5]:
            if idx >= len(results):
                continue
            na = _na(results[idx])
            enr = _enrichment(na)
            if enr.get("applied") is not True:
                _problem(
                    idx,
                    f"Scene {idx + 1}: enrichment.applied must be True "
                    f"(LDAP enrichment expected); got {enr.get('applied')!r}",
                )

        # Check 6: Scene 5 (index 4, alice/oidc enriched):
        #   - multi-source resolution present
        #   - scalars must be unanimous (not priority)
        #   - groups must be list_merge
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
                        4,
                        f"Scene 5 (alice/oidc enriched): {attr} resolution must be "
                        f"'unanimous' when sources agree, got 'priority'",
                    )

            groups5 = details5.get("groups")
            if groups5 and groups5.get("resolution") != "list_merge":
                _problem(
                    4,
                    f"Scene 5 (alice/oidc enriched): groups resolution must be "
                    f"'list_merge', got {groups5.get('resolution')!r}",
                )

            if c5 <= c1_val:
                _problem(
                    4,
                    f"Confidence ordering violated: C(5)={c5} must be > C(1)={c1_val}",
                )

        # Check 7: Scene 6 (index 5, diana/oidc conflict):
        #   - display_name priority winner_source must be 'oidc'
        #   - department priority winner_source must be 'ldap'
        #   - groups must be list_merge
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
            if dn6:
                if (
                    dn6.get("resolution") != "priority"
                    or dn6.get("winner_source") != "oidc"
                ):
                    _problem(
                        5,
                        f"Scene 6 (diana/oidc): display_name must have priority "
                        f"resolution with winner_source='oidc'; "
                        f"got resolution={dn6.get('resolution')!r}, "
                        f"winner_source={dn6.get('winner_source')!r}",
                    )

            dept6 = details6.get("department")
            if dept6:
                if (
                    dept6.get("resolution") != "priority"
                    or dept6.get("winner_source") != "ldap"
                ):
                    _problem(
                        5,
                        f"Scene 6 (diana/oidc): department must have priority "
                        f"resolution with winner_source='ldap'; "
                        f"got resolution={dept6.get('resolution')!r}, "
                        f"winner_source={dept6.get('winner_source')!r}",
                    )

            groups6 = details6.get("groups")
            if groups6 and groups6.get("resolution") != "list_merge":
                _problem(
                    5,
                    f"Scene 6 (diana/oidc): groups resolution must be 'list_merge', "
                    f"got {groups6.get('resolution')!r}",
                )

            if c6 >= c5_val:
                _problem(
                    5,
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
    return labels.get(res, res)


def _format_sources(detail: dict[str, Any]) -> str:
    """Return a sources/winner string for a resolution detail."""
    res = detail.get("resolution", "")
    if res == "priority":
        winner = detail.get("winner_source", "")
        conflicting = detail.get("conflicting_values", {})
        losers = ", ".join(f"{k}={v!r}" for k, v in conflicting.items())
        return f"winner={winner} (losers: {losers})"
    sources = detail.get("sources", [])
    if sources:
        return "/".join(sources)
    return ""


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
    ba_table = Table(show_header=True, header_style="bold", expand=True)
    ba_table.add_column("Protocol-native (before)", style="dim", ratio=1)
    ba_table.add_column("Unified (after)", ratio=1)

    def _fmt_raw(v: Any) -> str:
        if isinstance(v, list):
            return ", ".join(str(x) for x in v)
        return str(v) if v is not None else "—"

    unified_pairs = [
        ("display_name", na.get("display_name")),
        ("primary_email", na.get("primary_email")),
        ("department", na.get("department")),
        ("employee_type", na.get("employee_type")),
        ("groups", na.get("groups")),
    ]
    raw_items = list(raw_attrs.items())
    max_rows = max(len(raw_items), len(unified_pairs))

    for i in range(max_rows):
        left = ""
        if i < len(raw_items):
            k, v = raw_items[i]
            left = f"{k}: {_fmt_raw(v)}"
        right = ""
        if i < len(unified_pairs):
            uk, uv = unified_pairs[i]
            right = f"{uk}: {_fmt_raw(uv) if uv is not None else 'null'}"
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

    for attr in [
        "display_name",
        "primary_email",
        "department",
        "employee_type",
        "groups",
    ]:
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
            "and org hierarchy come from different authoritative sources."
        )

    # Build panel content
    from rich.console import Group
    from rich import box

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
    verification: list[dict[str, Any]] | None,
    *,
    console: Any = None,
) -> None:
    """Render a rich comparison table to the console.

    Renders per-scene bordered panels and a summary table. Uses the provided
    console if given (for testability), otherwise creates a real Console().
    """
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text

    con = console or Console()

    # Print verification problems if any
    if verification:
        con.print("[bold red]Verification problems:[/bold red]")
        for p in verification:
            con.print(f"  Scene {p.get('scene', '?')}: {p.get('message', '')}")
        con.print()

    # Render each scene
    for i, (scene, result) in enumerate(zip(scenes, results)):
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

    for i, (scene, result) in enumerate(zip(scenes, results)):
        na = result.get("normalized_attributes") or {}
        details = na.get("resolution_details") or {}
        enr = na.get("enrichment") or {}
        conf = na.get("normalization_confidence", 0.0)

        protocol = scene.get("protocol", "?")
        enr_label = "yes" if enr.get("applied") else "no"

        res_types: set[str] = set()
        for detail in details.values():
            res_types.add(detail.get("resolution", "?"))
        res_mix = ", ".join(sorted(res_types))

        c_style = confidence_style(conf)
        conf_cell = Text(f"{conf:.3f}", style=c_style)

        scene_label = f"{i + 1} — {scene.get('user_id', '?')}/{protocol}"
        summary.add_row(scene_label, protocol, enr_label, res_mix, conf_cell)

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
        with psycopg.connect(db_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(CLEANUP_QUERY, {"ids": event_ids})
                count = cur.rowcount
        print(f"Cleanup: removed {count} event(s) from the database.")
    except Exception as exc:  # noqa: BLE001
        print(f"Cleanup warning: could not delete events: {exc}")


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

    if verification:
        from rich.console import Console as _Console

        _Console().print(
            f"[bold red]Verification failed with {len(verification)} problem(s). "
            "Aborting render.[/bold red]"
        )
        for p in verification:
            print(f"  Scene {p.get('scene', '?')}: {p.get('message', '')}")
        if not args.keep:
            cleanup_events(event_ids, db_dsn)
        sys.exit(1)

    render_results(SCENES, results, verification)

    if args.keep:
        print(f"Retained {len(event_ids)} event(s) in the database (--keep).")
        print(f"Retained event IDs: {event_ids}")
    else:
        cleanup_events(event_ids, db_dsn)


# ---------------------------------------------------------------------------
# sys.modules self-registration
#
# When this file is loaded via importlib.util.spec_from_file_location with a
# custom module name (e.g. "demo_normalization_flow"), the loader does NOT
# add the module to sys.modules automatically. Any subsequent
# `from demo_normalization_flow import ...` call in the same process fails
# unless we register the module under its current __name__ here.
#
# Strategy: find the ModuleType object whose __dict__ IS our globals(),
# then register it under __name__ in sys.modules.
# ---------------------------------------------------------------------------
if __name__ not in sys.modules:
    _my_globals = globals()
    for _referrer in _gc.get_referrers(_my_globals):
        if (
            isinstance(_referrer, _types_reg.ModuleType)
            and _referrer.__dict__ is _my_globals
        ):
            sys.modules[__name__] = _referrer
            break

if __name__ == "__main__":
    main()
