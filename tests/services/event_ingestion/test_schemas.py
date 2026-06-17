"""Pydantic request/response schema contracts for event-ingestion."""

import uuid

# third-party
import pytest

# ---------------------------------------------------------------------------
# Repo-root discovery (needed to locate app/schemas.py under test)
# ---------------------------------------------------------------------------
from tests.helpers import REPO_ROOT

SERVICE_DIR = REPO_ROOT / "services" / "event-ingestion"


# Deterministic test UUID per the project test-data reference values
_TEST_UUID_1 = uuid.UUID("12345678-1234-5678-1234-567812345678")
_TEST_UUID_2 = uuid.UUID("12345678-1234-5678-1234-567812345679")


# ===========================================================================
# CLASS 1 — Import: app.schemas exposes IngestAccepted and BulkIngestAccepted
# ===========================================================================


class TestSchemasModuleImport:
    """app/schemas.py must be importable and expose the two response models.

    WHY: routes.py and main.py both import these models to type-annotate the
    response_model parameter of the FastAPI endpoints. A ModuleNotFoundError
    here means the HTTP layer cannot be wired and all requests would fail.
    """

    def test_ingest_accepted_is_importable(self) -> None:
        """from app.schemas import IngestAccepted must succeed.

        WHY: POST /events/ingest uses IngestAccepted as its response_model.
        If IngestAccepted is missing, FastAPI cannot serialize the 202 response.
        """
        from app.schemas import IngestAccepted  # noqa: F401

    def test_bulk_ingest_accepted_is_importable(self) -> None:
        """from app.schemas import BulkIngestAccepted must succeed.

        WHY: POST /events/bulk uses BulkIngestAccepted as its response_model.
        If BulkIngestAccepted is missing, the bulk endpoint returns no structured body.
        """
        from app.schemas import BulkIngestAccepted  # noqa: F401

    def test_both_schemas_importable_together(self) -> None:
        """from app.schemas import IngestAccepted, BulkIngestAccepted must succeed."""
        from app.schemas import BulkIngestAccepted, IngestAccepted  # noqa: F401


# ===========================================================================
# CLASS 2 — IngestAccepted behavior
# ===========================================================================


class TestIngestAccepted:
    """IngestAccepted must behave per spec §5.6.

    Contract: IngestAccepted(id=<uuid>).status == 'accepted'
    The `status` field must have a Literal["accepted"] default — callers never
    provide it, and FastAPI serializes it without the caller specifying it.
    """

    def test_ingest_accepted_status_defaults_to_accepted(self) -> None:
        """IngestAccepted(id=uuid).status must equal 'accepted' without being set.

        WHY: The spec §3.3 and §5.6 define the body as {"id":"...","status":"accepted"}.
        The status field must be a Literal default so callers never set it explicitly;
        the service simply returns IngestAccepted(id=record.id) and FastAPI serializes
        the default. A missing default forces every callsite to pass status="accepted",
        which is redundant and error-prone.
        """
        from app.schemas import IngestAccepted

        result = IngestAccepted(id=_TEST_UUID_1)
        assert result.status == "accepted", (
            f"IngestAccepted(id=...).status must be 'accepted', got {result.status!r}. "
            "The spec §3.3 mandates status='accepted' in the single-ingest response."
        )

    def test_ingest_accepted_id_field_stores_the_provided_uuid(self) -> None:
        """IngestAccepted.id must equal the UUID passed at construction.

        WHY: The route handler builds IngestAccepted(id=record.id) where record.id
        is the UUID assigned to the event row. The caller uses this id to correlate
        the response with the PostgreSQL row. A wrong or coerced id breaks downstream
        correlation.
        """
        from app.schemas import IngestAccepted

        result = IngestAccepted(id=_TEST_UUID_1)
        assert result.id == _TEST_UUID_1, (
            f"IngestAccepted.id must store the provided UUID. "
            f"Expected {_TEST_UUID_1}, got {result.id!r}."
        )

    def test_ingest_accepted_is_pydantic_basemodel(self) -> None:
        """IngestAccepted must be a Pydantic BaseModel subclass.

        WHY: FastAPI's response_model serialization relies on Pydantic for JSON
        encoding, field validation, and OpenAPI schema generation. A plain dataclass
        or TypedDict would bypass Pydantic validation and break OpenAPI docs.
        """
        from app.schemas import IngestAccepted
        from pydantic import BaseModel

        assert issubclass(IngestAccepted, BaseModel), (
            "IngestAccepted must inherit from pydantic.BaseModel for FastAPI "
            "response_model serialization to work."
        )

    def test_ingest_accepted_serializes_to_json_with_correct_keys(self) -> None:
        """IngestAccepted.model_dump() must contain 'id' and 'status' keys.

        WHY: FastAPI calls model_dump(mode='json') on the response model to build
        the JSON body. The spec §3.3 defines the exact body shape:
        {"id": "<uuid>", "status": "accepted"}. Missing either key breaks any
        consumer that parses the 202 response body.
        """
        from app.schemas import IngestAccepted

        result = IngestAccepted(id=_TEST_UUID_1)
        dumped = result.model_dump()
        assert "id" in dumped, "IngestAccepted.model_dump() must include an 'id' key."
        assert "status" in dumped, (
            "IngestAccepted.model_dump() must include a 'status' key."
        )
        assert dumped["status"] == "accepted", (
            f"Serialized status must be 'accepted', got {dumped['status']!r}."
        )

    def test_ingest_accepted_status_is_not_settable_to_non_accepted(self) -> None:
        """IngestAccepted.status must reject values other than 'accepted'.

        WHY: Literal["accepted"] as the type means Pydantic validates the value.
        If status were a plain str, callers could set status="deny" and the service
        would silently return a misleading response. Literal enforces the contract.
        """
        from app.schemas import IngestAccepted
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            IngestAccepted(id=_TEST_UUID_1, status="rejected")  # type: ignore[arg-type]


# ===========================================================================
# CLASS 3 — BulkIngestAccepted behavior
# ===========================================================================


class TestBulkIngestAccepted:
    """BulkIngestAccepted must behave per spec §5.6.

    Contract: BulkIngestAccepted(accepted=2, event_ids=[uuid1,uuid2]).status == 'accepted'
    """

    def test_bulk_ingest_accepted_status_defaults_to_accepted(self) -> None:
        """BulkIngestAccepted(accepted=N, event_ids=[...]).status must equal 'accepted'.

        WHY: The spec §3.3 defines the bulk body as
        {"accepted": N, "event_ids": [...], "status": "accepted"}.
        The default must be set at the model level, not at every callsite.
        """
        from app.schemas import BulkIngestAccepted

        result = BulkIngestAccepted(accepted=2, event_ids=[_TEST_UUID_1, _TEST_UUID_2])
        assert result.status == "accepted", (
            f"BulkIngestAccepted.status must default to 'accepted', got {result.status!r}."
        )

    def test_bulk_ingest_accepted_accepted_field_stores_count(self) -> None:
        """BulkIngestAccepted.accepted must store the integer count passed in.

        WHY: The 'accepted' field is what callers check to know how many events
        were persisted. An incorrect count causes silent data loss (caller thinks
        fewer events were accepted than were actually written).
        """
        from app.schemas import BulkIngestAccepted

        result = BulkIngestAccepted(accepted=2, event_ids=[_TEST_UUID_1, _TEST_UUID_2])
        assert result.accepted == 2, (
            f"BulkIngestAccepted.accepted must equal 2, got {result.accepted!r}."
        )

    def test_bulk_ingest_accepted_event_ids_stores_the_uuid_list(self) -> None:
        """BulkIngestAccepted.event_ids must contain the UUIDs passed in, in order.

        WHY: The 'event_ids' list is the correlation handle callers use to map
        response positions back to their original request events. Order must be
        preserved to match request-order position semantics.
        """
        from app.schemas import BulkIngestAccepted

        result = BulkIngestAccepted(accepted=2, event_ids=[_TEST_UUID_1, _TEST_UUID_2])
        assert result.event_ids == [_TEST_UUID_1, _TEST_UUID_2], (
            f"BulkIngestAccepted.event_ids must preserve UUID order. "
            f"Got: {result.event_ids!r}"
        )

    def test_bulk_ingest_accepted_is_pydantic_basemodel(self) -> None:
        """BulkIngestAccepted must be a Pydantic BaseModel subclass."""
        from app.schemas import BulkIngestAccepted
        from pydantic import BaseModel

        assert issubclass(BulkIngestAccepted, BaseModel), (
            "BulkIngestAccepted must inherit from pydantic.BaseModel."
        )

    def test_bulk_ingest_accepted_serializes_to_json_with_correct_keys(self) -> None:
        """BulkIngestAccepted.model_dump() must contain 'accepted', 'event_ids', 'status'.

        WHY: FastAPI serializes the response using model_dump. The spec §3.3 specifies
        exactly these three keys. Missing any key breaks consumers parsing the bulk body.
        """
        from app.schemas import BulkIngestAccepted

        result = BulkIngestAccepted(accepted=2, event_ids=[_TEST_UUID_1, _TEST_UUID_2])
        dumped = result.model_dump()
        for key in ("accepted", "event_ids", "status"):
            assert key in dumped, (
                f"BulkIngestAccepted.model_dump() must include '{key}' key. "
                f"Got keys: {list(dumped.keys())}"
            )
        assert dumped["status"] == "accepted"
        assert dumped["accepted"] == 2

    def test_bulk_ingest_accepted_status_is_not_settable_to_non_accepted(self) -> None:
        """BulkIngestAccepted.status must reject values other than 'accepted'."""
        from app.schemas import BulkIngestAccepted
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            BulkIngestAccepted(
                accepted=1,
                event_ids=[_TEST_UUID_1],
                status="error",  # type: ignore[arg-type]
            )


# ===========================================================================
# CLASS 4 — Isolation: app.schemas must NOT expose ORM symbols
# ===========================================================================


class TestSchemasModuleDoesNotExposeORMSymbols:
    """app/schemas.py must not contain EventORM or Base.

    WHY: The spec §1 warns explicitly: 'app/schemas.py (API response models)
    and shared/naas_shared/schemas.py (ORM table definitions) are different files
    with the same basename.' If EventORM or Base leak into app.schemas, the service's
    HTTP layer becomes coupled to the ORM layer, creating circular import risks and
    exposing SQLAlchemy internals to the response serialization path.

    We assert absence both statically (file source text) and dynamically (module attrs).
    """

    def test_app_schemas_does_not_expose_event_orm_attribute(self) -> None:
        """app.schemas module must not have an EventORM attribute.

        WHY: EventORM is a SQLAlchemy declarative model. It belongs in
        shared/naas_shared/schemas.py. Having it in app.schemas means the API
        response layer directly references the ORM, which is an architectural
        violation and creates risk of accidentally serializing ORM objects
        as HTTP response bodies (SQLAlchemy objects are not JSON-serializable).
        """
        import importlib

        schemas_mod = importlib.import_module("app.schemas")
        assert not hasattr(schemas_mod, "EventORM"), (
            "app.schemas must not expose 'EventORM'. "
            "ORM models belong in shared/naas_shared/schemas.py, not the API response module."
        )

    def test_app_schemas_does_not_expose_base_attribute(self) -> None:
        """app.schemas module must not have a SQLAlchemy Base attribute.

        WHY: DeclarativeBase ('Base') is a SQLAlchemy ORM concept that has no place
        in the API response schema module. Exposing it would mean ORM and API layers
        are merged, making it impossible to change the DB schema independently of the
        response contract.
        """
        import importlib

        schemas_mod = importlib.import_module("app.schemas")
        # Check no attribute named 'Base' that is a SQLAlchemy DeclarativeBase
        base_attr = getattr(schemas_mod, "Base", None)
        if base_attr is not None:
            # If there's a 'Base' attribute, it must NOT be a DeclarativeBase subclass
            try:
                from sqlalchemy.orm import DeclarativeBase

                assert not (
                    isinstance(base_attr, type)
                    and issubclass(base_attr, DeclarativeBase)
                ), (
                    "app.schemas must not expose a SQLAlchemy DeclarativeBase as 'Base'. "
                    "ORM base classes belong in shared/naas_shared/schemas.py."
                )
            except ImportError:
                pass  # SQLAlchemy not installed — skip the isinstance check

    def test_app_schemas_source_does_not_import_event_orm(self) -> None:
        """app/schemas.py source must not import EventORM from naas_shared.schemas.

        WHY: A static check catches import-time coupling before it manifests as a
        runtime error. If the implementer accidentally adds
        'from naas_shared.schemas import EventORM' to app/schemas.py, this test
        catches it immediately rather than waiting for a circular import failure.
        """
        schemas_path = SERVICE_DIR / "app" / "schemas.py"
        assert schemas_path.exists(), f"app/schemas.py not found at {schemas_path}."
        source = schemas_path.read_text()
        assert "EventORM" not in source, (
            "app/schemas.py source must not reference 'EventORM'. "
            "ORM models are separate from API response schemas (spec §1)."
        )
