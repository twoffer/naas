# A8 Document Change Manifest
## A-Series Reconciliation Remediation — Document Updates

**Purpose:** Address the discrepancies identified by the A-Series Intent-vs-Application Reconciliation (`docs/audit/A_Series_Reconciliation_Report.md`) by applying targeted remediations to repo-resident documents. This manifest is the diagnostic-to-remediation handoff for the reconciliation findings, scoped to mechanical and structural corrections that do not require new architectural decisions.

**Important:** Per project convention, this manifest itself is a supplemental design document and will NOT be added to the NAAS project repo's standard branches. All necessary information is captured in the repo-resident documents without cross-references to A1–A8 documents or other meta documents.

---

## 1. CLAUDE.md (repo document)

### 1a. Remove duplicate Event Pipeline diagram line

**Location:** § Event Pipeline (async, Redis Streams) — the first two lines inside the diagram code block (currently lines 72–73)

**Current text:**
```
Ingestion → [login_events] → Normalization → [normalized_events] → Enrichment → [enriched_events] → Risk Evaluator
Ingestion → [login_events] → Normalization (+ LDAP enrichment for OIDC/SAML) → [normalized_events] → Enrichment → [enriched_events] → Risk Evaluator
```

**Replace with:**
```
Ingestion → [login_events] → Normalization (+ LDAP enrichment for OIDC/SAML) → [normalized_events] → Enrichment → [enriched_events] → Risk Evaluator
```

**Rationale:** The cross-protocol enrichment update to the Event Pipeline diagram was intended as a REPLACE operation but was applied as an ADD, leaving both the original unannotated pipeline line and the updated annotated line in place. The annotated line is the correct version (LDAP enrichment is part of normalization for OIDC/SAML events); the unannotated line is now stale and contradicts the annotated one. Removing it eliminates the conflicting duplicate.

### 1b. Add `config/` to the Project Structure tree

**Location:** § Project Structure tree, after the `shared/` block and before `dashboard/`

**Add:**
```
├── config/
│   └── normalization_authority.yaml  # Normalization authority weights, attribute importance, enrichment source config
```

**Rationale:** `config/normalization_authority.yaml` is referenced in CLAUDE.md's Key Conventions section (cross-protocol enrichment bullet) but does not appear in the project structure tree, even though `scripts/train_bootstrap_model.py` — added under the same general principle — does. Adding `config/` to the tree restores consistency between the tree and the Key Conventions text and gives agents a complete picture of the top-level project layout from CLAUDE.md alone.

---

## 2. docs/architecture/SPEC_0_Project_Scaffold_and_Shared_Foundation.md (repo document)

### 2a. Update the project tree to include all current top-level directories and files

**Location:** § 1. Scope Boundary, "Files and Directories Created" — the project tree (currently lines 20–63)

**Current text:**
```
naas/
├── docker-compose.yml
├── .env.example
├── .env                              # Copy of .env.example (gitignored)
├── .gitignore
├── CLAUDE.md                         # Agent reference (copy from project docs)
├── README.md                         # Minimal quick-start placeholder
├── infrastructure/
│   ├── postgres/
│   │   └── init.sql                  # Full DDL: all tables, indexes, extensions
│   ├── redis/
│   │   └── redis.conf                # Custom Redis config (maxmemory, streams)
│   ├── keycloak/
│   │   └── naas-realm-export.json    # Realm import file (realm, client, users)
│   └── openldap/
│       └── bootstrap.ldif            # OU structure + test users
├── shared/
│   ├── pyproject.toml                # Package metadata (installable via pip -e)
│   └── naas_shared/
│       ├── __init__.py
│       ├── database.py               # Async SQLAlchemy engine + session factory
│       ├── redis_client.py           # Redis connection, stream helpers, pub/sub helpers
│       ├── models.py                 # Base Pydantic models (LoginEvent, etc.)
│       ├── schemas.py                # SQLAlchemy ORM table definitions
│       ├── logging.py                # Structlog configuration
│       ├── config.py                 # Pydantic Settings (env-driven config)
│       └── constants.py              # Stream names, channel names, consumer groups
        └── simulation_tools.py       # Shared tool definitions + ToolExecutor (P0: definitions, P2: executor)
└── services/                         # Empty subdirs with placeholder READMEs
    ├── api-gateway/
    │   └── README.md
    ├── event-ingestion/
    │   └── README.md
    ├── identity-normalization/
    │   └── README.md
    ├── signal-enrichment/
    │   └── README.md
    ├── risk-evaluator/
    │   └── README.md
    ├── policy-management/
    │   └── README.md
    ├── alert-service/
    │   └── README.md
    └── persona-simulator/
        └── README.md
```

**Replace with:**
```
naas/
├── docker-compose.yml
├── .env.example
├── .env                              # Copy of .env.example (gitignored)
├── .gitignore
├── CLAUDE.md                         # Agent reference (copy from project docs)
├── README.md                         # Minimal quick-start placeholder
├── config/
│   └── normalization_authority.yaml  # Normalization authority weights, attribute importance, enrichment source config (file content created by Spec 2)
├── infrastructure/
│   ├── postgres/
│   │   └── init.sql                  # Full DDL: all tables, indexes, extensions
│   ├── redis/
│   │   └── redis.conf                # Custom Redis config (maxmemory, streams)
│   ├── keycloak/
│   │   └── naas-realm-export.json    # Realm import file (realm, client, users)
│   └── openldap/
│       └── bootstrap.ldif            # OU structure + test users
├── scripts/
│   └── train_bootstrap_model.py      # ML model bootstrap — generates random_forest.pkl (script content created by Spec 3)
├── shared/
│   ├── pyproject.toml                # Package metadata (installable via pip -e)
│   └── naas_shared/
│       ├── __init__.py
│       ├── database.py               # Async SQLAlchemy engine + session factory
│       ├── redis_client.py           # Redis connection, stream helpers, pub/sub helpers
│       ├── models.py                 # Base Pydantic models (LoginEvent, etc.)
│       ├── schemas.py                # SQLAlchemy ORM table definitions
│       ├── logging.py                # Structlog configuration
│       ├── config.py                 # Pydantic Settings (env-driven config)
│       ├── constants.py              # Stream names, channel names, consumer groups
│       ├── ml_features.py            # ML feature column ordering contract (16-feature vector — used by training script and Risk Evaluator)
│       └── simulation_tools.py       # Shared tool definitions + ToolExecutor (P0: definitions, P2: executor)
└── services/                         # Empty subdirs with placeholder READMEs
    ├── api-gateway/
    │   └── README.md
    ├── event-ingestion/
    │   └── README.md
    ├── identity-normalization/
    │   └── README.md
    ├── signal-enrichment/
    │   └── README.md
    ├── risk-evaluator/
    │   └── README.md
    ├── policy-management/
    │   └── README.md
    ├── alert-service/
    │   └── README.md
    └── persona-simulator/
        └── README.md
```

**Rationale:** Four corrections combined into a single tree replacement.

1. **Add `config/` directory and `normalization_authority.yaml`.** The file is referenced in §3 of `SYSTEM_ARCHITECTURE.md` (cross-protocol enrichment bullet), in CLAUDE.md's Key Conventions section, and in the Spec 2 scope of `NAAS_System_Decomposition_Guide.md`, but has no home in the scaffold tree. `config/` at the repo root is the correct location: the file is application-level configuration (consumed by the normalization service at runtime), distinct from `infrastructure/` (which is reserved for bootstrap data mounted into infrastructure containers). The directory is scaffolded by Spec 0; the file content is defined and created by Spec 2 (Identity Normalization).

2. **Add `scripts/` directory and `train_bootstrap_model.py`.** The script is referenced in CLAUDE.md's project structure, in `SYSTEM_ARCHITECTURE.md`'s ML Bootstrap Script section, and in System Decomposition Spec 3, but has no home in the scaffold tree. The directory is scaffolded by Spec 0; the script content is defined and created by Spec 3 (Risk Evaluator).

3. **Add `ml_features.py` to `shared/naas_shared/`.** The file is referenced in CLAUDE.md (project structure and Key Conventions), in `SYSTEM_ARCHITECTURE.md` (ML Bootstrap Script section, §6 ML-based bullet), in `NAAS_v2.0_Tech_Stack.md` (Scikit-learn section), and in System Decomposition Spec 3 — but is not represented in the shared library tree. The file content (the `ML_FEATURE_COLUMNS` ordering contract) is part of the shared library and is created by Spec 0 so that Spec 3 can import it without redefinition.

4. **Fix the `simulation_tools.py` tree-character defect.** In the current tree, `constants.py` uses `└──` (last-child marker) and the line for `simulation_tools.py` then drops the left-rail spine entirely (no leading `│`). This produces a visually broken tree where two consecutive entries both claim to be the last child. The corrected ordering uses `├──` for `constants.py`, restores the `│` spine for `simulation_tools.py`, and inserts `ml_features.py` between them.

### 2b. Update "Files NOT Created by This Spec"

**Location:** § 1. Scope Boundary, "Files NOT Created by This Spec" list (immediately following the project tree)

**Current text:**
```
- No service `Dockerfile` files (each spec creates its own)
- No service `app/` directories or Python code inside `services/*/`
- No `dashboard/` directory (Spec 6)
- No `docs/` directory beyond README.md (Phase 6 polish)
- No monitoring stack (Prometheus/Grafana) — deferred to a polish pass
```

**Replace with:**
```
- No service `Dockerfile` files (each spec creates its own)
- No service `app/` directories or Python code inside `services/*/`
- No `dashboard/` directory (Spec 6)
- No `docs/` directory beyond README.md (Phase 6 polish)
- No monitoring stack (Prometheus/Grafana) — deferred to a polish pass
- No `config/normalization_authority.yaml` content (the directory is scaffolded; file content is defined and created by Spec 2)
- No `scripts/train_bootstrap_model.py` content (the directory is scaffolded; script is defined and created by Spec 3)
- No `services/risk-evaluator/models/random_forest.pkl` (the pre-trained model artifact is generated by running the bootstrap script during Spec 3 implementation)
```

**Rationale:** With the project tree now showing `config/` and `scripts/`, this list explicitly clarifies that Spec 0 creates the scaffolding (directories and placeholder file paths) but defers content creation to the spec that owns the corresponding service. This preserves the existing separation of concerns (Spec 0 is foundational scaffolding only) while keeping the canonical project tree complete and referentially consistent with CLAUDE.md.

---

## Summary of Changes

| Document | Section Changed | Nature of Change |
|----------|-----------------|------------------|
| CLAUDE.md | Event Pipeline diagram (lines 72–73) | Remove duplicate unannotated pipeline line |
| CLAUDE.md | Project Structure tree | Add `config/` directory with `normalization_authority.yaml` |
| SPEC_0 | § 1 Project tree (lines 20–63) | Add `config/`, `scripts/`, `ml_features.py`; fix `simulation_tools.py` tree characters |
| SPEC_0 | § 1 "Files NOT Created" list | Add three entries clarifying which downstream spec creates each new file's content |

---

## Items Deliberately Out of Scope

The following discrepancies from the reconciliation report are NOT addressed by this manifest. Each is excluded for an explicit reason:

| Item (from reconciliation report) | Reason for exclusion |
|-----------------------------------|----------------------|
| `NormalizedIdentity` model formalization (A2 + A7 tier-2 output-provenance gap) | Packaging the `events.normalized_attributes` JSONB shape as a typed Pydantic model is a deliberate architectural decision, not a mechanical fix. Deferred to a separate design discussion. |
| Vision Document line 161 (A4 6a — ML ensemble bullet) | The bullet is embedded in an ASCII line-drawing diagram. The expanded wording does not fit the box width, and no shorter substitute carries the additional information meaningfully. Current text retained. |
| `SYSTEM_ARCHITECTURE.md` Communication Patterns "Event Submission" row (A1 1e) | The merged form under "Synchronous REST" is architecturally more consistent than the split form: every other row in the table is a transport pattern, not a logical operation. The merged form is the preferred outcome. |
| Implementation plan documents under `docs/implementation-plans/` | These chunked plans are stale and slated for removal. They are intentionally not regenerated or edited by this manifest. |

---

*End of A8 Change Manifest.*
