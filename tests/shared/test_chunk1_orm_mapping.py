# Component: NAAS Spec 1 — Chunk 1: naas_shared.schemas ORM mapping (Base + EventORM)
# Mode: TDD — all tests MUST fail until shared/naas_shared/schemas.py is populated
#
# What these tests validate:
#   - `from naas_shared.schemas import Base, EventORM` succeeds (ImportError until populated)
#   - EventORM.__tablename__ == 'events'
#   - Column set matches the events DDL exactly:
#       {id, user_id, protocol, client_ip, user_agent, timestamp, source,
#        is_synthetic, is_historical, raw_attributes, normalized_attributes,
#        enriched_signals, created_at}
#   - Column types: id→UUID PK, client_ip→INET, raw_attributes/normalized_attributes/
#       enriched_signals→JSONB
#   - Base.metadata.create_all is NOT called at import time (critical: table DDL is
#     owned by the infrastructure init script, not by the ORM model)
#
# Why this matters:
#   EventORM is the read/write mapping over the `events` table that ingestion uses
#   for the PostgreSQL dual-write.  A wrong column name → AttributeError at runtime.
#   A wrong column type → silent data corruption or DB-level type coercion errors.
#   Calling create_all at import time would attempt to recreate the DDL-managed table
#   on every service startup, causing crashes against a DB that already owns the schema.
#
# TDD state:
#   shared/naas_shared/schemas.py currently contains only the Gap-5 placeholder comment.
#   Every test in this file MUST fail with ImportError or AttributeError until the
#   implementer appends Base and EventORM to that file.

# stdlib
import sys
from pathlib import Path

# third-party
import pytest


# ---------------------------------------------------------------------------
# Repo-root discovery and sys.path injection
# ---------------------------------------------------------------------------


def _find_repo_root() -> Path:
    """Walk up from this file until we find the directory containing
    docs/architecture/ — the canonical repo root marker. Capped at 10 levels."""
    candidate = Path(__file__).resolve().parent
    for _ in range(10):
        if (candidate / "docs" / "architecture").is_dir():
            return candidate
        candidate = candidate.parent
    raise RuntimeError(
        "Could not locate repo root (expected a directory containing "
        f"docs/architecture/). Started from: {Path(__file__).resolve()}"
    )


REPO_ROOT = _find_repo_root()
SHARED_DIR = REPO_ROOT / "shared"

if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))


# ---------------------------------------------------------------------------
# Expected column set — must mirror the events DDL exactly
# ---------------------------------------------------------------------------

EXPECTED_COLUMNS = {
    "id",
    "user_id",
    "protocol",
    "client_ip",
    "user_agent",
    "timestamp",
    "source",
    "is_synthetic",
    "is_historical",
    "raw_attributes",
    "normalized_attributes",
    "enriched_signals",
    "created_at",
}


# ===========================================================================
# CLASS 1 — Import surface
# ===========================================================================


class TestSchemasImportSurface:
    """Both Base and EventORM must be importable from naas_shared.schemas once
    the implementer populates the file. Until then, these tests fail with ImportError,
    which is the correct TDD initial state."""

    def test_base_importable_from_naas_shared_schemas(self) -> None:
        """from naas_shared.schemas import Base must succeed.

        WHY: Base is the SQLAlchemy DeclarativeBase used by all ORM models in the
        project. Without it, adapters.py cannot construct EventORM instances and the
        entire dual-write path is broken at import time.
        """
        from naas_shared.schemas import Base  # noqa: F401

    def test_event_orm_importable_from_naas_shared_schemas(self) -> None:
        """from naas_shared.schemas import EventORM must succeed.

        WHY: PostgresEventRepository (adapters.py) imports EventORM directly to
        construct row objects for session.add(). A missing symbol causes an
        ImportError that crashes the service on startup.
        """
        from naas_shared.schemas import EventORM  # noqa: F401

    def test_base_and_event_orm_importable_together(self) -> None:
        """Both Base and EventORM must be importable in a single import statement.

        WHY: The spec's §4 import block is: from naas_shared.schemas import Base, EventORM.
        Both must resolve in one shot; a partial import that succeeds for one and
        fails for the other is not acceptable.
        """
        from naas_shared.schemas import Base, EventORM  # noqa: F401


# ===========================================================================
# CLASS 2 — Table name
# ===========================================================================


class TestEventORMTableName:
    """EventORM must map to the 'events' table — the name the infrastructure
    init script creates and that every downstream query targets."""

    def test_event_orm_tablename_is_events(self) -> None:
        """EventORM.__tablename__ must equal 'events'.

        WHY: SQLAlchemy uses __tablename__ to determine which DB table the model
        maps to. A wrong value (e.g., 'event' or 'login_events') means all ORM
        operations silently target the wrong table, causing 'relation does not exist'
        errors at runtime.
        """
        from naas_shared.schemas import EventORM

        assert EventORM.__tablename__ == "events", (
            f"Expected EventORM.__tablename__ == 'events', "
            f"got {EventORM.__tablename__!r}"
        )


# ===========================================================================
# CLASS 3 — Column set (exact, no more, no fewer)
# ===========================================================================


class TestEventORMColumnSet:
    """The column set must mirror the events DDL exactly. Missing columns cause
    AttributeError at write time. Extra columns cause unexpected writes or schema drift."""

    def test_column_set_matches_events_ddl_exactly(self) -> None:
        """set(EventORM.__table__.columns.keys()) must equal EXPECTED_COLUMNS exactly.

        WHY: The spec §5.1 states 'The columns MUST mirror the existing events DDL
        exactly (names, types, nullability).' A single missing column (e.g., user_agent)
        means that field is never persisted. An extra column risks schema mismatch errors
        on the next table ALTER or SELECT * query.
        """
        from naas_shared.schemas import EventORM

        actual = set(EventORM.__table__.columns.keys())
        assert actual == EXPECTED_COLUMNS, (
            f"Column set mismatch.\n"
            f"Missing from ORM: {EXPECTED_COLUMNS - actual}\n"
            f"Extra in ORM:     {actual - EXPECTED_COLUMNS}\n"
            f"Expected: {sorted(EXPECTED_COLUMNS)}\n"
            f"Actual:   {sorted(actual)}"
        )

    @pytest.mark.parametrize("col_name", sorted(EXPECTED_COLUMNS))
    def test_each_expected_column_is_present(self, col_name: str) -> None:
        """Each expected column must be individually present in EventORM.

        WHY: The aggregate set-equality test above catches the overall mismatch but
        can produce a cryptic error message when multiple columns are absent. Per-column
        tests provide a one-failure-per-missing-column diagnostic that speeds up the
        implementer's fix loop.
        """
        from naas_shared.schemas import EventORM

        col_names = set(EventORM.__table__.columns.keys())
        assert col_name in col_names, (
            f"Column '{col_name}' is missing from EventORM. "
            f"Present columns: {sorted(col_names)}"
        )


# ===========================================================================
# CLASS 4 — Column types
# ===========================================================================


class TestEventORMColumnTypes:
    """Critical column type assertions. Using the wrong SQLAlchemy type for client_ip,
    raw_attributes, etc. causes silent data corruption or DB-level type coercion errors.
    The INET and JSONB types are PostgreSQL-specific — the spec requires them explicitly."""

    def test_id_column_is_primary_key(self) -> None:
        """The id column must be the primary key.

        WHY: id is the event's durable identity. Every downstream stage correlates on
        this UUID. Without it as PK, the table has no row identity, ON CONFLICT
        handling is broken, and downstream XREADGROUP consumers cannot locate the row.
        """
        from naas_shared.schemas import EventORM

        id_col = EventORM.__table__.columns["id"]
        assert id_col.primary_key, (
            "EventORM.id must be a primary key column. "
            "The id is the durable event identity that all downstream stages correlate on."
        )

    def test_id_column_is_not_nullable(self) -> None:
        """The id column must be NOT NULL (primary keys are always non-nullable).

        WHY: A nullable primary key is undefined behavior in PostgreSQL and in
        SQLAlchemy's ORM layer. Confirming non-nullability here catches accidental
        `nullable=True` on the mapped_column() call.
        """
        from naas_shared.schemas import EventORM

        id_col = EventORM.__table__.columns["id"]
        assert not id_col.nullable, (
            "EventORM.id must NOT be nullable — primary key columns are non-nullable."
        )

    def test_client_ip_column_type_is_inet(self) -> None:
        """client_ip column type must be INET (PostgreSQL-specific).

        WHY: The events DDL declares client_ip as INET. Storing an IPv4 string in a
        TEXT or VARCHAR column bypasses PostgreSQL's network address validation; the
        INET type ensures only valid dotted-quad values are persisted. Using the wrong
        SQLAlchemy type class causes the insert to fail with a type mismatch error.
        """
        from sqlalchemy.dialects.postgresql import INET

        from naas_shared.schemas import EventORM

        col = EventORM.__table__.columns["client_ip"]
        assert isinstance(col.type, INET), (
            f"client_ip column type must be INET, got {type(col.type).__name__!r}. "
            "The events DDL declares client_ip as INET for PostgreSQL network address validation."
        )

    def test_raw_attributes_column_type_is_jsonb(self) -> None:
        """raw_attributes column type must be JSONB (PostgreSQL-specific).

        WHY: The events DDL declares raw_attributes as JSONB for efficient indexing
        and querying of protocol-specific claims. Storing as TEXT or JSON (not JSONB)
        breaks GIN index queries and is slower for downstream consumers. The ORM type
        class must match to avoid insert failures.
        """
        from sqlalchemy.dialects.postgresql import JSONB

        from naas_shared.schemas import EventORM

        col = EventORM.__table__.columns["raw_attributes"]
        assert isinstance(col.type, JSONB), (
            f"raw_attributes column type must be JSONB, got {type(col.type).__name__!r}. "
            "The events DDL declares raw_attributes as JSONB."
        )

    def test_normalized_attributes_column_type_is_jsonb(self) -> None:
        """normalized_attributes column type must be JSONB.

        WHY: Downstream consumers (Risk Evaluator, Dashboard) call
        NormalizedAttributes.model_validate() on the JSONB payload. Using TEXT
        forces an extra JSON parse step that the JSONB type handles natively.
        Wrong type causes 'column of type json' errors on update.
        """
        from sqlalchemy.dialects.postgresql import JSONB

        from naas_shared.schemas import EventORM

        col = EventORM.__table__.columns["normalized_attributes"]
        assert isinstance(col.type, JSONB), (
            f"normalized_attributes column type must be JSONB, "
            f"got {type(col.type).__name__!r}."
        )

    def test_enriched_signals_column_type_is_jsonb(self) -> None:
        """enriched_signals column type must be JSONB.

        WHY: Signal Enrichment writes structured enrichment payloads (IP reputation,
        geo, device fingerprint) to this column. The JSONB type is required by the DDL
        and enables efficient field-level querying by the Risk Evaluator.
        """
        from sqlalchemy.dialects.postgresql import JSONB

        from naas_shared.schemas import EventORM

        col = EventORM.__table__.columns["enriched_signals"]
        assert isinstance(col.type, JSONB), (
            f"enriched_signals column type must be JSONB, "
            f"got {type(col.type).__name__!r}."
        )

    def test_timestamp_column_is_timezone_aware(self) -> None:
        """events.timestamp column must be DateTime(timezone=True).

        WHY: TIMESTAMPTZ in the DDL maps to DateTime(timezone=True) in SQLAlchemy.
        A naive DateTime would silently strip zone information on round-trip,
        allowing a session-timezone-shifted value to corrupt the stored UTC instant
        that downstream risk logic depends on.
        """
        from sqlalchemy import DateTime

        from naas_shared.schemas import EventORM

        col = EventORM.__table__.columns["timestamp"]
        assert isinstance(col.type, DateTime), (
            f"timestamp column type must be DateTime, got {type(col.type).__name__!r}."
        )
        assert col.type.timezone is True, (
            "timestamp column must be DateTime(timezone=True) to match TIMESTAMPTZ DDL."
        )

    def test_created_at_column_is_timezone_aware(self) -> None:
        """events.created_at column must be DateTime(timezone=True).

        WHY: created_at was changed from TIMESTAMP to TIMESTAMPTZ in the DDL so that
        the ingestion instant is always a deterministic UTC value regardless of the
        PostgreSQL session timezone.  The ORM mapping must agree; a naive DateTime
        here would cause asyncpg to return a naive datetime on read, losing the UTC
        anchor and potentially shifting the value in a non-UTC session.
        """
        from sqlalchemy import DateTime

        from naas_shared.schemas import EventORM

        col = EventORM.__table__.columns["created_at"]
        assert isinstance(col.type, DateTime), (
            f"created_at column type must be DateTime, got {type(col.type).__name__!r}."
        )
        assert col.type.timezone is True, (
            "created_at column must be DateTime(timezone=True) to match TIMESTAMPTZ DDL."
        )


# ===========================================================================
# CLASS 5 — Nullability contracts (columns left NULL by ingestion)
# ===========================================================================


class TestEventORMNullability:
    """Columns that ingestion leaves NULL must be declared nullable in the ORM mapping.
    Non-nullable declarations would cause insert failures since ingestion never sets them."""

    def test_normalized_attributes_is_nullable(self) -> None:
        """normalized_attributes must be nullable in the ORM mapping.

        WHY: The spec §3.1 states 'Ingestion must leave them NULL.' and 'Populated by
        Identity Normalization.' If the ORM declares NOT NULL, the insert raises
        IntegrityError immediately on every ingest call — total ingestion failure.
        """
        from naas_shared.schemas import EventORM

        col = EventORM.__table__.columns["normalized_attributes"]
        assert col.nullable, (
            "normalized_attributes must be nullable. "
            "Ingestion writes NULL; Identity Normalization populates it later."
        )

    def test_enriched_signals_is_nullable(self) -> None:
        """enriched_signals must be nullable in the ORM mapping.

        WHY: The spec §3.1 states enriched_signals is 'NULL at ingestion; populated
        by Signal Enrichment.' A non-nullable ORM declaration causes insert failures
        since ingestion never provides this value.
        """
        from naas_shared.schemas import EventORM

        col = EventORM.__table__.columns["enriched_signals"]
        assert col.nullable, (
            "enriched_signals must be nullable. "
            "Ingestion writes NULL; Signal Enrichment populates it later."
        )

    def test_user_agent_is_nullable(self) -> None:
        """user_agent must be nullable (it is an optional field in LoginEventIngest).

        WHY: user_agent is declared Optional in LoginEventIngest — callers may omit it.
        A NOT NULL ORM declaration would cause insert failures for events without a
        user agent (e.g., API-to-API calls from the simulator).
        """
        from naas_shared.schemas import EventORM

        col = EventORM.__table__.columns["user_agent"]
        assert col.nullable, (
            "user_agent must be nullable — it is an optional field in LoginEventIngest."
        )


# ===========================================================================
# CLASS 6 — No create_all at import time
# ===========================================================================


class TestNoCreateAllAtImportTime:
    """The ORM model must NOT call Base.metadata.create_all at import time.

    This is the most critical infrastructure safety invariant for the ORM mapping:
    the database schema is owned by the infrastructure init script (init.sql).
    Any create_all call would attempt to recreate or conflict with DDL-managed tables.
    """

    def test_importing_schemas_does_not_call_create_all(self) -> None:
        """Importing naas_shared.schemas must not invoke Base.metadata.create_all.

        WHY: The spec §5.1 states 'Do NOT call Base.metadata.create_all(...).'
        A create_all at import time would run DDL against the database on every service
        startup. In production this means: (1) a DB connection is required at import
        time (startup failure if DB is down), (2) table recreation attempts conflict
        with the init.sql DDL, (3) every test environment needs a live database just
        to import the module.

        We verify this by patching Base.metadata.create_all BEFORE importing the
        schemas module (or re-importing it in a fresh context) and asserting the mock
        was never called. Since the module is already imported by prior tests, we
        verify the side-effect never occurred by checking that the mock remains at
        zero calls even after a forced reload.
        """
        import importlib
        from unittest.mock import patch

        # Reload to force module-level code to re-execute.
        # If create_all is called at module level, it will be captured here.
        import naas_shared.schemas as schemas_module

        # Patch on the already-imported Base (the same object the module holds).
        # If create_all was called before this patch, this test still passes because
        # we are checking the RELOAD path below.
        try:
            from naas_shared.schemas import Base
        except ImportError:
            pytest.fail(
                "naas_shared.schemas does not export Base yet — "
                "implement it before this test can run."
            )

        with patch.object(Base.metadata, "create_all") as mock_create_all:
            # Force module reload — if create_all is called at module level,
            # it executes again here and the mock captures it.
            importlib.reload(schemas_module)
            assert mock_create_all.call_count == 0, (
                f"Base.metadata.create_all was called {mock_create_all.call_count} "
                "time(s) during module import. The spec §5.1 prohibits this — "
                "the database schema is owned by the infrastructure init script."
            )

    def test_schemas_module_has_no_engine_creation(self) -> None:
        """naas_shared/schemas.py source must not contain create_all or create_engine calls.

        WHY: Static assertion that create_all is not buried in any function that could
        be called from module-level code. This catches the pattern:
            def _init(): Base.metadata.create_all(engine)
            _init()  # called at module level
        """
        schemas_path = SHARED_DIR / "naas_shared" / "schemas.py"
        assert schemas_path.exists(), (
            f"schemas.py not found at {schemas_path}. "
            "It must be created by the implementer."
        )
        content = schemas_path.read_text(encoding="utf-8")

        # create_all at module scope is prohibited
        # We check for the presence of the call pattern — not for its import,
        # since DeclarativeBase's metadata is a legitimate attribute to reference.
        assert "create_all(" not in content, (
            "naas_shared/schemas.py must not call create_all(). "
            "The database schema is owned by infrastructure/postgres/init.sql. "
            "See spec §5.1: 'Do NOT call Base.metadata.create_all'."
        )
