"""API response models for the Event Ingestion Service.

These are Pydantic models used exclusively as HTTP response bodies.  They are
DISTINCT from shared/naas_shared/schemas.py (which holds SQLAlchemy ORM
definitions).  Do NOT import or expose ORM symbols here (spec §1).
"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class IngestAccepted(BaseModel):
    """202 Accepted response body for POST /events/ingest (spec §3.3, §5.6).

    The `status` field is a Literal with a default so callers never set it;
    FastAPI serializes the default automatically.
    """

    id: UUID
    status: Literal["accepted"] = "accepted"


class BulkIngestAccepted(BaseModel):
    """202 Accepted response body for POST /events/bulk (spec §3.3, §5.6).

    `accepted` is the count of events written; `event_ids` preserves
    input-order position semantics so callers can correlate response positions
    back to their original request events.
    """

    accepted: int
    event_ids: list[UUID]
    status: Literal["accepted"] = "accepted"
