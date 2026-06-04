# A11 Document Change Manifest
## Single-UUID Event Identity & IPv4 Address Validation — Foundation Updates

**Purpose:** Apply two coordinated foundation changes to repo-resident code and documents:

1. **Remove the redundant `events.event_id` business-key column** and the corresponding `LoginEventRecord.event_id` field, consolidating event identity on the single, app-generated UUID primary key `events.id`. Every pipeline stage correlates on `id`; the foreign-reference fields and columns that are *named* `event_id` (in `risk_assessments`, `alerts`, `RiskDecision`, `AlertMessage`) are retained, since they reference `events.id` and now carry its stringified value.
2. **Tighten the `LoginEventBase.client_ip` validation regex** so it accepts only well-formed IPv4 addresses (each octet `0`–`255`), replacing the prior shape-only pattern that accepted numerically invalid values such as `999.999.999.999`.

**Important:** Per project convention, this manifest is a supplemental design document and will NOT be added to the NAAS project repo's standard branches. All necessary information is captured in the repo-resident code and documents without cross-references to A-series or other meta documents.

**Application order and gating:**
- The canonical event schema lives in two code files (`infrastructure/postgres/init.sql`, `shared/naas_shared/models.py`) and is mirrored in two documents (`SPEC_0` §3.1/§3.4, `SYSTEM_ARCHITECTURE.md`). Apply the code edits and their document mirrors together so the DDL, the Pydantic models, and the prose never disagree.
- Then update the Spec 0 test suite.
- **This manifest MUST be fully applied and the Spec 0 test suite green BEFORE the Event Ingestion Service (Spec 1) is implemented.** An `events` table that still requires a `NOT NULL` `event_id` will reject every insert the new ingestion code makes.

---

## 1. infrastructure/postgres/init.sql (repo code)

### 1a. Remove the `event_id` business-key column from the `events` table

**Location:** § EVENTS TABLE — the `CREATE TABLE ... events` column list, second column.

**Current text:**
```sql
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id VARCHAR(255) UNIQUE NOT NULL,
    user_id VARCHAR(255) NOT NULL,
```

**Replace with:**
```sql
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL,
```

**Rationale:** `events.id` is the surrogate UUID primary key and the only identity the pipeline needs. The separate `event_id` string was never externally supplied (`LoginEventIngest` has no such field) and duplicated the identity, creating a standing risk that different consumers correlate on different keys. The `risk_assessments.event_id` and `alerts.event_id` foreign-key columns reference `events(id)` and are unaffected by this removal.

---

## 2. shared/naas_shared/models.py (repo code)

### 2a. Remove `event_id` from `LoginEventRecord`

**Location:** `class LoginEventRecord(LoginEventBase)`.

**Current text:**
```python
class LoginEventRecord(LoginEventBase):
    """Full event record after ingestion (has IDs assigned)."""

    id: UUID = Field(default_factory=uuid4)
    event_id: str
    normalized_attributes: Optional[Dict[str, Any]] = None
    enriched_signals: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

**Replace with:**
```python
class LoginEventRecord(LoginEventBase):
    """Full event record after ingestion (has the UUID id assigned)."""

    id: UUID = Field(default_factory=uuid4)
    normalized_attributes: Optional[Dict[str, Any]] = None
    enriched_signals: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

**Rationale:** The record now carries exactly one identity, the UUID `id`, which is serialized into the `login_events` stream payload and used by every downstream stage for correlation. The docstring is corrected from the plural "IDs" to reflect the single identity.

### 2b. Tighten the `client_ip` validation regex on `LoginEventBase`

**Location:** `class LoginEventBase(BaseModel)`, the `client_ip` field.

**Current text:**
```python
    client_ip: str = Field(..., pattern=r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
```

**Replace with:**
```python
    client_ip: str = Field(
        ...,
        pattern=r"^((25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])\.){3}(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])$",
    )
```

**Rationale:** The prior pattern validated only the *shape* of the value (four dot-separated groups of one-to-three digits) and accepted numerically invalid addresses like `256.300.999.0`. The replacement bounds each octet to `0`–`255` and disallows leading-zero forms, so a malformed address is rejected at the ingestion boundary rather than failing silently downstream in the geolocation, IP-reputation, and impossible-travel enrichers. The field remains typed as `str` (no change to how the value is stored or transported). The address family is IPv4-only by decision (see ADR-0010).

---

## 3. docs/architecture/SPEC_0_Project_Scaffold_and_Shared_Foundation.md (repo document)

### 3a. § 3.1 PostgreSQL Schema — remove the `event_id` column from the `events` DDL

**Location:** § 3.1, the `infrastructure/postgres/init.sql` code block, EVENTS TABLE.

**Current text:**
```sql
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id VARCHAR(255) UNIQUE NOT NULL,
    user_id VARCHAR(255) NOT NULL,
```

**Replace with:**
```sql
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL,
```

**Rationale:** SPEC_0 § 3.1 is the canonical mirror of `init.sql`. It must match the code change in §1a exactly.

### 3b. § 3.4 Base Pydantic Models — remove `event_id` from `LoginEventRecord`

**Location:** § 3.4, the `shared/naas_shared/models.py` code block, `LoginEventRecord` class.

**Current text:**
```python
class LoginEventRecord(LoginEventBase):
    """Full event record after ingestion (has IDs assigned)."""
    id: UUID = Field(default_factory=uuid4)
    event_id: str
    normalized_attributes: Optional[Dict[str, Any]] = None
    enriched_signals: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

**Replace with:**
```python
class LoginEventRecord(LoginEventBase):
    """Full event record after ingestion (has the UUID id assigned)."""
    id: UUID = Field(default_factory=uuid4)
    normalized_attributes: Optional[Dict[str, Any]] = None
    enriched_signals: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

**Rationale:** SPEC_0 § 3.4 is the canonical mirror of `models.py`. It must match the code change in §2a exactly.

### 3c. § 3.4 Base Pydantic Models — tighten the `client_ip` regex on `LoginEventBase`

**Location:** § 3.4, the `shared/naas_shared/models.py` code block, `LoginEventBase` class, the `client_ip` field.

**Current text:**
```python
    client_ip: str = Field(..., pattern=r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
```

**Replace with:**
```python
    client_ip: str = Field(
        ...,
        pattern=r"^((25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])\.){3}(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])$",
    )
```

**Rationale:** SPEC_0 § 3.4 is the canonical mirror of `models.py`. It must match the code change in §2b exactly.

---

## 4. docs/architecture/SYSTEM_ARCHITECTURE.md (repo document)

### 4a. Database Schema — remove the `event_id` column from the `events` table sketch

**Location:** § Database Schema (PostgreSQL) → Core Tables, the `events ( ... )` block.

**Current text:**
```
  id UUID PK,
  event_id VARCHAR(255) UNIQUE,
  user_id VARCHAR(255),
```

**Replace with:**
```
  id UUID PK,
  user_id VARCHAR(255),
```

**Rationale:** Keeps the architecture document's schema sketch consistent with the DDL. No other location in `SYSTEM_ARCHITECTURE.md` references the `event_id` column (the Service Catalog and data-flow sections describe ingestion without naming it).

---

## 5. tests/spec_0/test_chunk_2_shared_library.py (repo tests)

### 5a. Add an out-of-range-octet rejection test

**Location:** `class TestLoginEventIngestValidation`, alongside the existing `client_ip` rejection tests.

**Add:**
```python
    def test_login_event_ingest_rejects_out_of_range_octet(self):
        """
        client_ip='256.0.0.1' must raise ValidationError.
        The tightened pattern accepts only octets in 0-255; a value that is
        well-shaped (four dot-separated groups) but numerically invalid must be
        rejected at the ingestion boundary so malformed IPs never reach the
        geolocation, IP-reputation, or impossible-travel enrichers.
        """
        from pydantic import ValidationError

        from naas_shared.models import LoginEventIngest

        with pytest.raises(ValidationError):
            LoginEventIngest(
                user_id=VALID_USER_ID,
                client_ip="256.0.0.1",
                protocol="oidc",
                timestamp=VALID_TIMESTAMP,
            )
```

**Rationale:** Locks in the tightened validation. The existing tests (`rejects_invalid_ip_not_dotted_quad`, `rejects_hostname_as_ip`, and the valid dotted-quad happy path) remain correct under the new pattern and require no change.

### 5b. Remove any `LoginEventRecord(event_id=...)` construction (conditional)

**Directive:** Search this file for any instantiation of `LoginEventRecord` that passes an `event_id` keyword argument. If present, delete the `event_id=...` argument — the model no longer defines that field. The `TestRiskDecisionValidation` fixtures that pass `event_id="evt-001"` to `RiskDecision` are unaffected and MUST NOT be changed; `RiskDecision.event_id` is retained as a reference to `events.id`.

**Rationale:** `LoginEventRecord` is the only model losing the `event_id` field. As currently written, the chunk-2 suite does not appear to construct `LoginEventRecord` with `event_id`, so this is expected to be a no-op; the directive exists to catch any such construction added since.

---

## 6. tests/spec_0/test_chunk_3_postgres_redis.py (repo tests)

### 6a. Remove any `events.event_id` column or UNIQUE-constraint assertion (conditional)

**Directive:** Search this file for any assertion that the `events` table contains an `event_id` column or a `UNIQUE` constraint on `event_id`. If present, remove it. The five-table count (`test_exactly_five_create_table_statements`) and table-name-set (`test_create_table_names_match_expected_set`) assertions are unaffected — no table is removed.

**Rationale:** As currently written, `TestInitSqlEventsTable` asserts only the `user_agent` column and the `protocol` CHECK constraint, so this is expected to be a no-op; the directive exists to catch any `event_id` assertion added since.

---

## Verification

After applying all changes:

1. Run a repo-wide search for `event_id`. The only remaining occurrences should be:
   - the `risk_assessments.event_id` and `alerts.event_id` foreign-key columns (in `init.sql`, `SPEC_0` § 3.1, and `SYSTEM_ARCHITECTURE.md`) — UUID references to `events(id)`;
   - the `idx_risk_assessments_event_id` index;
   - the `event_id` field on `RiskDecision` and `AlertMessage` (in `models.py` and `SPEC_0` § 3.4);
   - `RiskDecision` / `AlertMessage` test fixtures.
   No occurrence of an `events.event_id` *business-key column* should remain anywhere.
2. Install the shared package (`pip install -e ./shared`) and run `pytest tests/spec_0/` — confirm green.
3. Run `ruff check` and `ruff format --check` on `shared/naas_shared/models.py` — confirm clean (the wrapped `Field(...)` call is multi-line for readability).

---

## Summary of Changes

| File | In Repo? | Section | Nature of Change |
|------|----------|---------|------------------|
| `infrastructure/postgres/init.sql` | Yes | EVENTS TABLE | Remove `event_id VARCHAR(255) UNIQUE NOT NULL` column |
| `shared/naas_shared/models.py` | Yes | `LoginEventRecord` | Remove `event_id: str` field; correct docstring |
| `shared/naas_shared/models.py` | Yes | `LoginEventBase.client_ip` | Replace shape-only regex with octet-bounded IPv4 regex |
| `docs/architecture/SPEC_0_*.md` | Yes | § 3.1 init.sql block | Remove `event_id` column (mirror of init.sql) |
| `docs/architecture/SPEC_0_*.md` | Yes | § 3.4 models.py block | Remove `event_id` from `LoginEventRecord`; tighten `client_ip` regex (mirror of models.py) |
| `docs/architecture/SYSTEM_ARCHITECTURE.md` | Yes | Database Schema, events sketch | Remove `event_id` column line |
| `tests/spec_0/test_chunk_2_shared_library.py` | Yes | `TestLoginEventIngestValidation` | Add out-of-range-octet rejection test; remove any `LoginEventRecord(event_id=...)` (conditional) |
| `tests/spec_0/test_chunk_3_postgres_redis.py` | Yes | `TestInitSqlEventsTable` | Remove any `events.event_id` column/UNIQUE assertion (conditional) |

---

## Items Deliberately Out of Scope

| Item | Reason for exclusion |
|------|----------------------|
| `risk_assessments.event_id`, `alerts.event_id` (FK columns) | UUID columns referencing `events(id)`; they never referenced the removed business key. Retained unchanged. The column name is the conventional "id of the referenced event" and remains accurate. |
| `RiskDecision.event_id`, `AlertMessage.event_id` (message fields) | Foreign references to the originating event, now carrying `str(events.id)`. Idiomatic; renaming would be churn without benefit. |
| `CLAUDE.md` | Carries the project tree, pipeline diagram, and Key Conventions, but no column-level `events` schema and no `event_id` reference to update. (Confirm via the Verification search.) |
| `.claude/agent-memory/code-security-reviewer/naas-shared-structure.md` | Quotes the prior `client_ip` regex. Agent memory is self-maintained and regenerated; updating it is optional and not required for repo correctness. |
| IPv6 support | Out of scope by decision (see ADR-0010). The tightened regex is IPv4-only by intent, not omission. |

---

*End of A11 Change Manifest.*
