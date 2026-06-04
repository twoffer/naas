# A12 Document Change Manifest
## Shared-Library Docker Packaging — SPEC_0 §4 Reconciliation

**Purpose:** Reconcile the shared-library Docker packaging strategy in `docs/architecture/SPEC_0_Project_Scaffold_and_Shared_Foundation.md` §4 with the self-contained, copy-at-build (Option A) pattern established by Spec 1 (the Event Ingestion Service). SPEC_0 §4 currently describes installing `naas_shared` via a **runtime volume mount** (`./shared:/app/shared`); the project has since standardized on **copying the shared package into each service image at build time**, producing a self-contained image with no runtime source mounts. This manifest removes the volume-mount sketch from §4 so the foundation document and the service-image pattern agree.

**Important:** Per project convention, this manifest is a supplemental design document and will NOT be added to the NAAS project repo's standard branches. All necessary information is captured in the repo-resident document without cross-references to A-series or other meta documents.

**Scope:** A single repo-resident document (`SPEC_0` §4). No code changes — Spec 1's `services/event-ingestion/Dockerfile` and its `docker-compose.yml` entry already implement the copy-at-build pattern and require no edits.

---

## 1. docs/architecture/SPEC_0_Project_Scaffold_and_Shared_Foundation.md (repo document)

### 1a. Update the install-comment in the §4 import block

**Location:** § 4 Shared Imports, the comment lines at the top of the `python` import code block.

**Current text:**
```python
# Every service's requirements.txt (or pyproject.toml) includes:
#   -e /app/shared   (mounted via Docker volume)
```

**Replace with:**
```python
# The shared package is copied into each service image and installed at build time
# (pip install -e on the copied shared/ dir); it is NOT listed in requirements.txt.
```

**Rationale:** The comment described the shared package as mounted via a Docker volume and listed in `requirements.txt`. Under the copy-at-build pattern the package is copied into the image and installed by a dedicated `RUN pip install -e` step in the Dockerfile, not declared as a requirement. The corrected comment reflects how services actually obtain `naas_shared`.

### 1b. Replace the "Shared Library Installation Strategy" prose and volume-mount block

**Location:** § 4 Shared Imports, the "### Shared Library Installation Strategy" subsection — the sentence introducing the strategy, the `yaml` volume-mount block, and the `dockerfile` block.

**Current text:**
```
The `shared/` directory is a pip-installable package. In Docker, each service mounts it as a volume and installs it in editable mode:

```yaml
# docker-compose.yml pattern for each service:
volumes:
  - ./shared:/app/shared
```

```dockerfile
# Each service's Dockerfile:
COPY shared/ /app/shared/
RUN pip install -e /app/shared/
```
```

**Replace with:**
```
The `shared/` directory is a pip-installable package. Each service image copies it in at build time and installs it in editable mode, producing a self-contained image with no runtime source mounts. Because the Dockerfile must see both `shared/` and the service directory, the Docker build context is the repository root:

```yaml
# docker-compose.yml pattern for each service:
build:
  context: .                                  # repo root, so shared/ is in the build context
  dockerfile: services/<service-name>/Dockerfile
```

```dockerfile
# Each service's Dockerfile (paths relative to the repo-root build context):
COPY shared/ /app/shared/
RUN pip install -e /app/shared/
```

A repo-root `.dockerignore` keeps the build context lean.
```

**Rationale:** Replaces the runtime-volume-mount approach with the self-contained copy-at-build approach. The `dockerfile` block (`COPY shared/` + editable install) was already the correct core and is retained verbatim; what changes is (1) the prose, which now describes a self-contained image rather than a mounted volume, (2) the `yaml` block, which now shows the repo-root `build.context` that makes `COPY shared/` resolve (replacing the `volumes` mount), and (3) a note pointing at the repo-root `.dockerignore`. The `⚠️ CRITICAL — Do not duplicate` callout that follows this subsection is unaffected and must be left in place.

---

## Verification

After applying:

1. Search `SPEC_0` for `./shared:` and for the phrases `mounted via Docker volume` and `mounts it as a volume` — none should remain.
2. Confirm the `COPY shared/ /app/shared/` + `RUN pip install -e /app/shared/` Dockerfile block in §4 is intact, now introduced by the build-context `yaml` block rather than the volume-mount block.
3. Repo-wide: confirm no `docker-compose.yml` service entry mounts `./shared` into a container (the `event-ingestion` entry uses `build.context: .`, no shared volume). The infrastructure services are unaffected.

---

## Summary of Changes

| Document | In Repo? | Section | Nature of Change |
|----------|----------|---------|------------------|
| `docs/architecture/SPEC_0_*.md` | Yes | § 4 import-block comment | Replace "mounted via Docker volume / in requirements.txt" comment with copy-at-build comment |
| `docs/architecture/SPEC_0_*.md` | Yes | § 4 Installation Strategy | Replace volume-mount prose + `volumes: ./shared` yaml with self-contained copy-at-build prose + repo-root `build.context` yaml; retain the Dockerfile block |

---

## Items Deliberately Out of Scope

| Item | Reason for exclusion |
|------|----------------------|
| `services/event-ingestion/Dockerfile`, `docker-compose.yml` event-ingestion entry | Spec 1 already specifies the copy-at-build Dockerfile and the `build.context: .` compose entry. No change needed. |
| The §4 `⚠️ CRITICAL — Do not duplicate` callout | Independent of the packaging mechanism; correct as written. Retained. |
| `.claude/agent-memory/*` references to a "shared volume mount" | Agent memory is self-maintained and regenerated; the runtime check it describes (importing `naas_shared` succeeds inside the container) holds for copy-at-build as well. Updating it is optional and not required for repo correctness. |
| Any later service spec (Specs 2–6) | Not yet written; each will follow the copy-at-build pattern Spec 1 establishes. No retroactive edits required. |

---

*End of A12 Change Manifest.*
