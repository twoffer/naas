# Spec: Identity Normalization Demo Showcase (`demo_normalization.py`)

**Deliverable:** A standalone, polished command-line demonstration script that exercises the live NAAS pipeline (Specs 0–2) to showcase cross-protocol identity normalization, confidence-scored conflict resolution, and graceful degradation. Targeted at a technical audience and at producing a ~60-second screen recording.

**Audience for this spec:** the technical-architect agent (to produce the chunked implementation plan) and the per-chunk implementation agents (as source of truth).

**Conventions:** Sections marked **⚠️ CRITICAL** are hard requirements. Crafted event payloads and expected outputs are marked **[GROUND TRUTH]** — reproduce them exactly; the confidence values are computed from the committed authority weights with the §5.4 `display_name.priority` change applied, and are the implementer's verification target. Where the spec is silent on internal structure, apply measured judgement consistent with the project's conventions.

---

## 1. Scope Boundary

### 1.1 What this builds

A new top-level `demo/` area plus two small supporting artifacts, all repo-resident:

| Path | Purpose |
|------|---------|
| `demo/demo_normalization.py` | The demonstration script (the deliverable). |
| `demo/requirements.txt` | Pinned runtime deps for the script (see §5.9). |
| `demo/README.md` | Setup + run instructions (start the stack, install deps, run, flags). |
| `config/normalization.yaml` | **Modify (`display_name` block only):** reorder `display_name.priority` to `[oidc, saml, ldap]` and compress its weights to `{ ldap: 0.85, saml: 0.75, oidc: 0.70 }`, with an updated rationale (§5.4). A deliberate product-default decision, not a demo shim. |
| `docs/architecture/SPEC_2_Identity_Normalization_Service.md` | **Modify (§5.6 only):** mirror the `display_name.priority` change (and its rationale) into the repo-resident config documentation, in lockstep (§5.4). No other section of SPEC_2 is touched. |
| `infrastructure/openldap/bootstrap.ldif` | **Modify (additive only):** add proper `groupOfNames` group entries under `ou=groups` and assign the seeded users as members (§5.6). No existing **user** attribute is changed. |
| `infrastructure/openldap/` (overlay config) | **Add:** configuration enabling the `memberof` (and recommended `refint`) overlay so `memberOf` is back-populated on member users (§5.6). Exact file/mechanism per the `osixia/openldap` image, verified against the live container. |
| `docs/architecture/SPEC_0_Project_Scaffold_and_Shared_Foundation.md` | **Modify (§5.3 only):** mirror the new group entries and overlay configuration into the repo-resident scaffold documentation, in lockstep, so the committed doc matches the actual bootstrap (§5.6). No other section of SPEC_0 is touched. |

> Group membership in the directory is a **real product capability**, not a demo-only artifact: the LDAP enrichment path reads `memberOf`, and a directory with genuine group structure is useful across the whole product (and mirrors the `engineering`/`product`/`security` groups already defined in the Keycloak realm). It is configured here as proper LDAP groups rather than synthetic per-user attributes.

### 1.2 Behavioral scope

The script performs, in order: preflight checks → POST a fixed set of six crafted login events through the ingestion API → poll PostgreSQL until each event is normalized → verify the results against the frozen narrative (§5.5) → render a Rich before/after report per event with confidence and provenance → render a final summary → clean up its own events (unless `--keep`).

### 1.3 Hard boundaries

- The script is **strictly read-only with respect to the running pipeline**: it POSTs events through the public ingestion API and reads/deletes **only the rows it itself created**. It does not, and must not, modify the normalization service, the shared models, the resolution algorithm, the adapters, or any other service.
- The script depends on the committed default config producing the frozen narrative. It likewise depends on the committed pipeline's resolution-detail shape — in particular, `list_merge` details carrying the persisted `sources` provenance field (SPEC_2 §5.5), an existing baseline capability the script reads and verifies, **not** something this spec builds; against an older pipeline build the §5.5 checks abort. Rather than gate on the config file, the script **verifies the actual normalized results against the narrative's structural and ordering expectations (§5.5) after normalization and before rendering**, aborting with a clear message if they don't match. The script's curated static text (e.g. the Scene-6 "Why the split?" annotation, §3.4) assumes those outcomes, so refusing to render a mismatched narrative is the correct behavior. The script still renders **actual** persisted output for every scene — it never fabricates values.
- ⚠️ The `display_name.priority` change in `config/normalization.yaml` (§5.4) is a **deliberate product-default decision**, applied to the committed config and mirrored in SPEC_2 §5.6. It is the *only* config change, and it is not a demo-only override.

---

## 2. Input Contracts

### 2.1 Ingestion API

The script submits each event via `POST {INGEST_URL}/events/ingest` (default `INGEST_URL=http://localhost:8001`). The request body is the documented ingestion envelope:

```jsonc
{
  "user_id": "<string>",
  "client_ip": "<IPv4 dotted-quad>",
  "protocol": "oidc | saml | ldap",
  "timestamp": "<ISO-8601 UTC, e.g. 2026-06-06T12:00:00Z>",
  "user_agent": "<string, optional>",
  "source": "api",
  "is_synthetic": true,
  "raw_attributes": { /* protocol-specific, opaque to ingestion */ }
}
```

Response is `202 Accepted` with body `{ "id": "<uuid>", "status": "accepted" }`. The script **captures each returned `id`** — these are the correlation keys it reads back and later deletes. All demo events MUST be tagged `source: "api"` and `is_synthetic: true`.

`client_ip` must be a valid IPv4 dotted-quad (each octet 0–255) or ingestion returns `422`. Use a documentation-range value (e.g. `203.0.113.10`).

### 2.2 Protocol-specific `raw_attributes` key shapes

- **OIDC:** `name`, `email`, `department`, `employee_type`, `groups`
- **SAML:** `displayName`, `email`, `dept`, `employeeType`, `groups`
- **LDAP:** `cn`, `mail`, `departmentNumber`, `employeeType`, `memberOf` (list of DNs)

### 2.3 The six crafted events **[GROUND TRUTH]**

Display order below is the on-screen / recording order (single-source cases first, building to the enriched finale). Emails are chosen so that `frank`, `grace`, and `mallory` are **absent** from the seeded directory (no enrichment match), while `alice` and `diana` are **present** (enrichment matches). Inputs deliberately include value-normalization triggers (`eng`→`Engineering`, `E`/`C`→`FTE`/`contractor`, `memberOf` DN→group name).

**Scene 1 — OIDC, single source (no directory match)**
```jsonc
{ "user_id": "frank", "protocol": "oidc", "client_ip": "203.0.113.10",
  "raw_attributes": {
    "name": "Frank Castle", "email": "frank@corp.com",
    "department": "eng", "employee_type": "E",
    "groups": ["engineering", "vpn-users"] } }
```

**Scene 2 — SAML, single source, SAME identity as Scene 1 (no directory match)**
```jsonc
{ "user_id": "frank", "protocol": "saml", "client_ip": "203.0.113.10",
  "raw_attributes": {
    "displayName": "Frank Castle", "email": "frank@corp.com",
    "dept": "Engineering", "employeeType": "FTE",
    "groups": ["engineering", "vpn-users"] } }
```
*Identical normalized identity to Scene 1, delivered via SAML — the only difference on screen is confidence, driven purely by source authority.*

**Scene 3 — Native LDAP, single source (no enrichment lookup)**
```jsonc
{ "user_id": "grace", "protocol": "ldap", "client_ip": "203.0.113.11",
  "raw_attributes": {
    "cn": "Grace Hopper", "mail": "grace@corp.com",
    "departmentNumber": "r&d", "employeeType": "C",
    "memberOf": ["cn=engineering,ou=groups,dc=corp,dc=com",
                 "cn=admins,ou=groups,dc=corp,dc=com"] } }
```
*`protocol: "ldap"` events are NOT enriched (no live directory round-trip). Demonstrates LDAP value normalization (`r&d`→`Engineering`, `C`→`contractor`) and `memberOf` DN reduction.*

**Scene 4 — SAML, single source, unrecognized values (no directory match)**
```jsonc
{ "user_id": "mallory", "protocol": "saml", "client_ip": "203.0.113.12",
  "raw_attributes": {
    "displayName": "Mallory Quinn", "email": "mallory@corp.com",
    "dept": "Sorcery", "employeeType": "wizard",
    "groups": ["temp-access"] } }
```
*`Sorcery` is not in `DEPARTMENT_CANONICAL` → retained, title-cased, with the **subtractive `−0.2` normalization-failure penalty** applied (it wins as the sole source). `wizard` is not in `EMPLOYEE_TYPE_CANONICAL` → **discarded to `None`** (enum-safe), contributing `0.0` with **no** numeric penalty. The two different unmapped-handling policies must both be visible (see §3.3). Note: the `−0.2` here is the flat normalization-failure penalty, **not** the multiplicative `×0.8` conflict penalty — Scene 4 is single-source, so there is no conflict and no `×0.8` factor.*

**Scene 5 — OIDC + LDAP match, all sources agree (directory user `alice`)**
```jsonc
{ "user_id": "alice", "protocol": "oidc", "client_ip": "203.0.113.20",
  "raw_attributes": {
    "name": "Alice Smith", "email": "alice@corp.com",
    "department": "eng", "employee_type": "FTE",
    "groups": ["engineering", "vpn-users", "product-admins"] } }
```
*Correlates to `alice@corp.com` in the directory (`cn=Alice Smith`, `departmentNumber=Engineering`, `employeeType=FTE`, `memberOf`→`{engineering, vpn-users}` per §5.6). Value normalization (`eng`→`Engineering`) is what makes OIDC and LDAP **agree** → unanimous. Groups differ by one token-only entry → `list_merge`.*

**Scene 6 — OIDC + LDAP match, two conflicts, split winners — MONEY SHOT (directory user `diana`)**
```jsonc
{ "user_id": "diana", "protocol": "oidc", "client_ip": "203.0.113.21",
  "raw_attributes": {
    "name": "Di Prince", "email": "diana@corp.com",
    "department": "Marketing", "employee_type": "vendor",
    "groups": ["engineering", "oncall"] } }
```
*Correlates to `diana@corp.com` (`cn=Diana Prince`, `departmentNumber=Engineering`, `employeeType=vendor`, `memberOf`→`{engineering, vpn-users}` per §5.6). Two conflicts resolved to **two different winning sources**: OIDC wins `display_name` (preferred name "Di Prince" over directory legal name "Diana Prince"); LDAP wins `department` ("Engineering" over the login's stale "Marketing" claim). Both conflicting values are canonically mappable, so neither resolution carries an unmapped-value penalty — only the conflict (`×0.8`) penalty. The token also **omits** `vpn-users`, which the directory back-populates: the merged group set (`{engineering, oncall, vpn-users}`) is a strict **superset** of the token's, with only 1 of 3 merged groups corroborated by both sources (fraction ⅓ → `list_merge` confidence 0.80, visibly below Scene 5's 0.90).*

> **⚠️ CRITICAL — the principle behind the split (this is what Scene 6 must teach).** The split is not arbitrary; it is the entire reason per-attribute authority exists. The most trustworthy *source* differs by *attribute*, so each attribute is resolved to its own configured authority instead of picking one global winner source:
> - **`display_name` → OIDC wins.** The modern cloud IdP is authoritative for identity *presentation*. Users curate their own display/preferred name in the IdP, so it reflects how they currently identify ("Di"), while the HR-synced directory carries the slower-moving legal name ("Diana"). Authority for `display_name` is therefore configured to the IdP (`display_name.priority = [oidc, saml, ldap]` in the default config, §5.4).
> - **`department` → LDAP wins.** The HR-synced directory is authoritative for organizational *facts*. Department is owned by HR and pushed to the directory; a department claim riding along in a login token can be stale or wrong. Authority for `department` is therefore configured to LDAP (`department.priority = [ldap, …]`).
>
> The takeaway a viewer should leave with: **a global "trust LDAP" or "trust the IdP" priority would be wrong about half the attributes.** NAAS resolves each field to the system that actually owns it — keeping the IdP's preferred name *and* the directory's department in the same identity — and the confidence score reflects that the sources disagreed. The low resolved confidence on `display_name` (0.56) is itself informative: OIDC is not a strongly-trusted source for names, and there was an active conflict, so the system is openly uncertain about the value it kept.

### 2.4 PostgreSQL read-back surface

There is **no query API** in Specs 0–2, so the script reads results directly from the `events` table. Connection parameters come from the same environment the stack uses (`POSTGRES_HOST`/`POSTGRES_PORT`/`POSTGRES_DB`/`POSTGRES_USER`/`POSTGRES_PASSWORD`, defaulting to `localhost`/`5432`). Read query:

```sql
SELECT id, protocol, normalized_attributes
FROM events
WHERE id = ANY(%(ids)s);
```

`normalized_attributes` is the serialized `NormalizedAttributes` JSONB (NULL until the normalization stage has processed the row). The completion signal is `normalized_attributes IS NOT NULL` for every captured id.

---

## 3. Output Contracts

### 3.1 Rendering medium

A `rich`-rendered terminal report. Visual quality is a primary objective (this drives the recording). Use color, panels, tables, and confidence bars. Keep output legible to a non-NAAS reader: lead each scene with a one-line plain-English caption.

### 3.2 Per-scene layout

Each scene renders a bordered Rich `Panel` containing:

1. **Caption** — scene number + a one-line description (e.g., `Scene 2 · SAML login · single source — same identity as Scene 1, lower confidence`).
2. **Before → After** — a two-column table. **Left ("Raw / protocol-native"):** the attributes exactly as submitted, using their **protocol-native key names** (`cn`/`mail`/`departmentNumber`/`memberOf` for LDAP; `displayName`/`dept`/`employeeType` for SAML; `name`/`department`/`employee_type` for OIDC). **Right ("Normalized / unified"):** the resolved unified-schema values (`display_name`, `primary_email`, `department`, `employee_type`, `groups`). Where a value was canonicalized, show the transform visibly (e.g., `eng → Engineering`, `cn=engineering,… → engineering`).
3. **Enrichment status** — render the `enrichment` substructure verbatim: applied + source + cache_hit when applied; "skipped — `<skip_reason>`" when skipped; and for native LDAP, whatever the field reports (see §6.5).
4. **Resolution detail** — a table over `resolution_details`: `attribute | resolution | resolved value | source(s)/winner | confidence`. Confidence is rendered as a color-coded value **and** a small bar. The source(s) column is **data-driven for every resolution type**: `single_source`/`unanimous` rows render their `sources` field, `priority` rows their `winner_source`, and `list_merge` rows their persisted `sources` field (the protocols that contributed at least one group, alphabetically sorted — e.g. `ldap, oidc` in Scenes 5–6) — never inferred by the script. For `priority` (conflict) rows: highlight the winner and its source, and render the losing `conflicting_values` dimmed with their source labels. For the Scene-4 unmapped department, annotate the penalty — note the −0.2 penalty is **not persisted as a flag** on `single_source` details (only `PriorityResolution` carries `penalty_applied`); it is visible only in the depressed confidence, so the annotation is authored scene text (per the §3.3 fixed-narrative stance), not data-driven.
5. **Overall `normalization_confidence`** — a prominent, color-coded number with a bar. Color thresholds: **green ≥ 0.80**, **amber 0.50–0.79**, **red < 0.50**.

### 3.3 Scene-4 annotation (⚠️ CRITICAL — the subtle expert beat)

Scene 4 must make the **two distinct unmapped-handling policies** legible side by side:
- `department: "Sorcery"` → retained as `Sorcery`, **−0.2 penalty** applied (free-text field, value kept).
- `employee_type: "wizard"` → **discarded to `null`** (typed enum, value dropped), contributing `0.0` with **no** penalty.

If `employee_type` simply renders as `null` with no explanation it will read as a bug; the annotation must state that the discard is the enum-safe policy.

### 3.4 Scene-6 emphasis (⚠️ CRITICAL — the money shot)

Scene 6 is the centerpiece; allocate the most visual weight to it (distinct border accent, an explicit callout that **two different sources won two different attributes**, and a compact provenance view). The expected resolution under the default config is: `display_name` → **OIDC** wins ("Di Prince"); `department` → **LDAP** wins ("Engineering"); `primary_email` and `employee_type` → unanimous; `groups` → `list_merge`.

**Mandatory explanatory annotation.** Scene 6 must render a short "Why the split?" annotation (a clearly set-off line/block beneath the resolution table). Keep it to ~1–2 lines — render copy equivalent to:

> **Why the split?** `display_name` → **OIDC** owns identity presentation / preferred names · `department` → **LDAP** owns organizational facts. A single global LDAP-or-OIDC rule couldn't capture both.

The annotation is authored into the script (the demo narrative is fixed); it is not read from config. The implementer may adjust wording for fit but must keep it brief and preserve the two ownership points plus the "a global rule couldn't capture this" punchline.

### 3.5 Final summary

After the scenes, render a single summary table — one row per scene: scene, protocol(s), enrichment (yes/no), resolution mix, overall confidence (color-coded). This is the "whole story in one frame" closing shot for the recording.

### 3.6 Cleanup output

On successful completion the script deletes its own events (§5.8) and prints a brief confirmation of how many rows were removed. With `--keep`, it instead prints the retained event ids.

---

## 4. Shared Imports

This is a **standalone script**, intentionally decoupled from `naas_shared` so it can be run by anyone with the three pip dependencies and a reachable stack. It communicates over the documented HTTP/JSON contract (§2.1–§2.2) and raw SQL (§2.4); it does **not** import service code.

- It **may** optionally import `naas_shared.models` (`LoginEventIngest`, `NormalizedAttributes`) for typed payload construction/parsing if the package is installed, but must degrade to plain `dict`/JSON handling when it is not. Default to the plain-dict path to preserve portability.

Runtime third-party dependencies (declared in `demo/requirements.txt`, §5.9): `rich`, `httpx`, `psycopg[binary]`.

---

## 5. Implementation Requirements

### 5.1 CLI surface

```
python demo/demo_normalization.py [--keep] [--pace SECONDS] [--step]
                                  [--timeout SECONDS] [--skip-verify]
                                  [--ingest-url URL] [--db-dsn DSN]
```
- `--keep` — preserve the demo events instead of deleting them (default: delete).
- `--pace SECONDS` — delay between scenes for recording rhythm (default `1.5`; `0` = no delay).
- `--step` — wait for Enter between scenes (overrides `--pace`); for live/manual control.
- `--timeout SECONDS` — max wait for the pipeline to normalize all events (default `30`).
- `--skip-verify` — skip the post-normalization narrative checks (§5.5); for development only. Default is to verify and abort on mismatch.
- `--ingest-url`, `--db-dsn` — overrides; otherwise read from environment (§2.1, §2.4).

### 5.2 Preflight (lightweight per Q4)

Before submitting the scene events, verify and **fail fast with a single clear message + non-zero exit** on the first failure (no multi-step remediation prose):
1. `GET {INGEST_URL}/health` returns `200` with status `healthy` (event ingestion).
2. `GET {NORM_URL}/health` returns `200` with status `healthy` (identity normalization; default `http://localhost:8002`). This single check reflects the service's reachability to PostgreSQL, Redis, and OpenLDAP.
3. A direct PostgreSQL connection succeeds and `SELECT 1` returns.

(Config correctness is not probed here; it is verified against the actual results after normalization — see §5.5.)

### 5.3 Submit → poll → verify → render flow

1. Submit the six events **sequentially in display order** via `POST /events/ingest`; capture each `id`. (Sequential submission gives deterministic enrichment negative-cache behavior between Scenes 1 and 2; correctness does not depend on it.)
2. Poll the read-back query (§2.4) on a short interval (≈ 0.5 s) until every captured id has non-null `normalized_attributes`, or `--timeout` elapses. On timeout: print which ids are still unprocessed and exit non-zero.
3. **Verify the narrative (§5.5)** against the normalized results, unless `--skip-verify`. On any failed check: print the specific mismatch and exit non-zero **before rendering** — do not show a narrative the data doesn't support.
4. Render scenes in display order (§3.2), then the summary (§3.5).

### 5.4 Default authority config — the single required change to `config/normalization.yaml` **[GROUND TRUTH]**

Change only the `display_name` attribute block of the committed default config: (1) reorder `display_name.priority` so the cloud IdP wins display-name conflicts, and (2) compress the `display_name` weights into a tighter band so the IdP isn't conspicuously last, and update the rationale. The weight *order* (`ldap > saml > oidc`) is preserved — this is still the priority-only winner flip in spirit; only the magnitudes tighten, because a display name is soft, user-mutable data where a wide trust spread overclaims precision (see the note below). All other attributes, `defaults`, and the entire `enrichment` block are untouched.

```yaml
# config/normalization.yaml — display_name attribute block (only this block changes)
  display_name:
    priority: [oidc, saml, ldap]   # ← changed from [ldap, saml, oidc]
    weights: { ldap: 0.85, saml: 0.75, oidc: 0.70 }   # ← compressed band (was 0.90/0.70/0.60); order preserved
    rationale: >-
      The cloud IdP is the system of record for user-presented identity: users curate
      their own preferred/display name there, so the IdP value wins on disagreement.
      Weights are intentionally decoupled from priority for this attribute — they encode
      source reliability for the canonical record, where the directory's verified legal
      name remains the most reliable, so a contested IdP-sourced name resolves at
      correspondingly modest confidence.
```

**Why priority-only, and why the compressed weights (the decoupling note).** Every other attribute in the default config has its priority order and weight order agree. Flipping only `display_name.priority` makes it the one attribute where they diverge (OIDC wins, yet still carries the lowest weight). This is deliberate and is what preserves the demo's single-source confidence arc (OIDC 0.75 < LDAP 0.81) and the money-shot's informative `display_name` confidence (0.56). The weights are compressed into a tight band (`0.85 / 0.75 / 0.70`) rather than left wide so the divergence reads as "comparably-trusted sources, priority breaks the tie" instead of "the lowest-trust source was chosen" — and because a display name is soft data that doesn't justify a wide trust spread. The rationale string **must** still explain the policy-vs-confidence decoupling, as above, so a reader who cross-references priority and weight sees intent rather than inconsistency; compression softens the surprise but does not remove the inversion. (The alternative — raising OIDC's `display_name` weight to the *highest* — would remove the divergence entirely but compress the single-source arc to a near-tie, OIDC ≈ LDAP ≈ 0.78; not chosen here.)

**Lockstep doc mirror + test reconciliation.**
- Mirror this change (priority list + rationale) into the repo-resident config documentation in **SPEC_2 §5.6**, in the same pipeline run. Touch no other part of SPEC_2.
- Any existing test or ADR that asserts the prior default behavior (display-name conflicts resolving to LDAP) must be reconciled to the new default as part of this change; the architect identifies and updates them.

### 5.5 Narrative verification (post-normalization) **[GROUND TRUTH]**

After all six scenes are normalized and before rendering (§5.3 step 3), the script validates the actual results against the frozen narrative, unless `--skip-verify`. Checks are **structural and relative** — never exact confidence numbers — so they're robust to minor numeric drift but catch config drift, pipeline bugs, or a wrong config. On the first failed check, print the specific mismatch (expected vs actual) and exit non-zero before any scene renders.

Let `C(n)` = overall `normalization_confidence` for scene *n*. Required checks:

1. **Single-source scenes (1–4):** every present **scalar** attribute in each of Scenes 1, 2, 3, 4 is a `single_source` resolution, and `groups` is a `list_merge` with **exactly one contributing source** — asserted directly via the detail's persisted `sources` field: `sources == [<the event's protocol>]` (the pipeline resolves groups via the merge path even for a single source); `enrichment.applied` is false (skipped or not attempted) for all four.
2. **Scene 3 has no enrichment lookup:** the native-LDAP event's `enrichment` reflects that no live directory lookup was performed (per the field's representation for `protocol: "ldap"`; see §6.5).
3. **Scene 4 unmapped handling:** `department` is present, `single_source`, with unmapped semantics: resolved value retained, and — since the penalty is not persisted as a flag on `single_source` details — its confidence strictly below Scene 2's clean SAML `department` confidence (same source weight, no penalty); `employee_type` is `null`/absent (discarded). Both conditions must hold.
4. **Single-source ordering:** `C(4) < C(2) < C(1) < C(3)` — sketchy SAML < clean SAML < OIDC < LDAP. (Strict `<`; this is the arc the priority-only flip in §5.4 preserves.)
5. **Enriched scenes (5–6):** `enrichment.applied` is true for both; each has at least one multi-source resolution.
6. **Scene 5 is agreement:** the multi-source scalar resolutions are `unanimous` (no `priority`/conflict resolution present); `groups` is `list_merge` with `sources == ["ldap", "oidc"]` (both the token and the directory contributed groups; the field is persisted alphabetically sorted). And `C(5) > C(1)` (enrichment + agreement lifts confidence above the OIDC single-source baseline).
7. **Scene 6 is the split (⚠️ the core check):** `display_name` is a `priority` resolution with `winner_source == "oidc"`; `department` is a `priority` resolution with `winner_source == "ldap"`; `groups` is `list_merge` with `sources == ["ldap", "oidc"]`; and `C(6) < C(5)` (conflicts depress confidence relative to the agreement scene). The two-different-winners condition is the single most important assertion — if it fails, the loaded config is not producing the narrative.
8. **Scenes 5–6 group merges are directory-corroborated:** the multi-source groups confidence formula is `0.7 + 0.3 × (fraction of merged groups present in more than one source)` (SPEC_2 §5.5), so the corroborated fraction is recoverable from the groups `confidence` without exact-number assertions. Scene 5's implied corroborated fraction must be ≥ ½ (the narrative expects ⅔: two of three merged groups present in both token and directory); Scene 6's must be ≥ ¼ (the narrative expects ⅓: the token omits `vpn-users`, so only `engineering` corroborates). This complements the `sources` assertions in checks 6–7: a token-only union — LDAP enrichment that ran but merged nothing from the directory, such as broken `memberOf` back-population — already surfaces there as `ldap` missing from the groups `sources` (a protocol is listed only when it contributed at least one group), while the fraction bound catches the subtler failure where the directory *did* contribute groups but the wrong ones — a merge whose members barely corroborate (fraction 0 → confidence 0.70) is still structurally a two-source `list_merge` that checks 6–7 would pass.
9. **Scene 6 groups are back-populated (superset + lower confidence):** Scene 6's merged group set must be a **strict superset** of its token groups (the directory contributes `vpn-users`, which the token omits), and Scene 6's groups `confidence` must be strictly below Scene 5's (partial token/directory overlap vs. Scene 5's fuller overlap). Together these make the list-merge mechanism itself visible: the merge *adds* a group, and the confidence quantifies how well the sources agreed.

If any check fails, the message should name the scene and the violated expectation (e.g., *"Scene 6: expected display_name winner 'oidc', got 'ldap' — config/normalization.yaml display_name.priority is not [oidc, …]"*), so the cause is obvious.

### 5.6 LDAP group infrastructure — proper groups + `memberof` overlay (product capability)

The seeded directory currently defines **no group objects and no `memberOf`** on any user, so live enrichment returns empty groups and `list_merge` cannot occur. Rather than injecting synthetic `memberOf` attributes onto user entries, set up **real LDAP groups** and let the directory back-populate `memberOf` the way a production directory does. This is a genuine product capability (the enrichment path reads `memberOf`; group structure is useful project-wide and mirrors the Keycloak realm's `engineering`/`product`/`security` groups), not a demo shim.

**Three additive changes (no existing user attribute is modified):**

**(a) Group entries — `infrastructure/openldap/bootstrap.ldif`.** Add `groupOfNames` entries under `ou=groups,dc=corp,dc=com`, each with one or more `member` DNs referencing existing users. The group set mirrors the Keycloak realm and adds a cross-cutting access group: **[GROUND TRUTH]**

| Group (`cn`) | Members (user DNs under `ou=users,dc=corp,dc=com`) |
|---|---|
| `engineering` | `alice`, `diana` |
| `product` | `bob` |
| `security` | `charlie` |
| `vpn-users` | `alice`, `diana` |

This yields, for the two enriched demo users, `memberOf` reducing to exactly `{engineering, vpn-users}`. For `alice` (Scene 5, token `{engineering, vpn-users, product-admins}`) this is a **strict subset** of the token, so the union adds nothing but corroborates 2 of 3 groups (`list_merge` ≈ 0.90). For `diana` (Scene 6, token `{engineering, oncall}`) the token **omits** `vpn-users`, so the directory back-populates it and the union (`{engineering, oncall, vpn-users}`) is a strict **superset** of the token with only 1 of 3 groups corroborated (`list_merge` ≈ 0.80) — the merge mechanism visibly adds a group and the confidence visibly drops. `groupOfNames` requires at least one `member`, so every group above has members. The token-only groups (`product-admins`, `oncall`) are intentionally **not** directory groups.

**(b) Overlay configuration — `infrastructure/openldap/`.** Enable the **`memberof` overlay** so that adding a user to a `groupOfNames` automatically maintains the reverse `memberOf` attribute on that user (which is what the enrichment adapter reads). The **`refint` (referential integrity) overlay** is recommended alongside it so membership stays consistent if entries change. In `osixia/openldap`, overlays and the `memberOf` attribute type are configured against the `cn=config` database; the exact file(s) and load mechanism differ from ordinary data-LDIF and **must be implemented and verified against the running image** — do not assume the data-bootstrap LDIF path applies to config changes.

**(c) Documentation mirror — `docs/architecture/SPEC_0_Project_Scaffold_and_Shared_Foundation.md` §5.3 only.** Because SPEC_0 §5.3 transcribes the OpenLDAP bootstrap, update **only** that section in lockstep to reflect the new group entries and the overlay configuration, so the committed scaffold documentation matches the actual infrastructure. Touch no other part of SPEC_0.

⚠️ **Ordering and verification.**
- LDIF is processed top-to-bottom: the `ou=groups` organizational unit must precede the group entries, and member DNs must reference users that already exist. Keep the existing rule that `dc=corp,dc=com` is **not** declared (the image auto-creates it).
- The bootstrap is baked into the OpenLDAP image, so these changes require an **image rebuild**.
- **Verify with a live `ldapsearch`** that (i) the four group entries exist with the listed members, and (ii) an enrichment-style lookup of `alice` and `diana` returns `memberOf` reducing to `{engineering, vpn-users}`. Enrichment producing non-empty groups for these two users is the acceptance signal for `list_merge` in Scenes 5 and 6.
- Existing tests/assumptions that the directory returns `memberOf=[]` for all users no longer hold for `alice` and `diana`; the architect must reconcile any such test or note as part of this change.

### 5.7 Decoupling and robustness

- Construct payloads as plain dicts; parse `normalized_attributes` as plain JSON. No coupling to service internals.
- Network/DB calls use sane timeouts. Any unexpected error surfaces a single clear message and a non-zero exit (no stack-trace dumps to the recording).
- The script is idempotent across runs: it tags its events (`source: "api"`, `is_synthetic: true`) and operates only on the ids it captured this run.

### 5.8 Cleanup

Default behavior deletes exactly the rows this run created:
```sql
DELETE FROM events WHERE id = ANY(%(ids)s);
```
With `--keep`, skip the delete and print the retained ids. Cleanup runs only after rendering completes; if rendering aborts early, captured ids should still be cleaned up (unless `--keep`) so repeated runs don't accumulate rows.

### 5.9 `demo/requirements.txt`

Pin compatible versions of `rich`, `httpx`, and `psycopg[binary]`. `demo/README.md` documents: (a) start the stack (`docker compose up -d`) and wait for healthy services; (b) `pip install -r demo/requirements.txt`; (c) run the script; (d) the flags; (e) a one-line honesty note that the script reads PostgreSQL directly because the query API is designed-but-not-yet-built.

---

## 6. Validation Criteria

All confidence values below are the expected results **under the committed default config (with the §5.4 `display_name.priority` change applied)** and serve as the implementer's correctness target (verify within ±0.01). The script itself checks the *structural/relative* expectations at runtime (§5.5), not these exact numbers.

1. **Preflight** passes against a healthy running stack and fails fast (single message, non-zero exit) when ingestion, normalization, or PostgreSQL is unreachable.
2. **Scene 1 (OIDC single):** all scalar attributes `single_source` (`groups` resolves as a single-source `list_merge` with `sources=["oidc"]`; Scenes 2–4 likewise persist their own event protocol as the sole `sources` entry); per-attribute confidences = OIDC weights (`display_name` 0.70, `primary_email` 0.95, `department` 0.70, `employee_type` 0.60, `groups` 0.80); overall ≈ **0.75**. `eng`→`Engineering`, `E`→`FTE` visible.
3. **Scene 2 (SAML single):** identical normalized values to Scene 1; per-attribute = SAML weights (0.75 / 0.75 / 0.50 / 0.80 / 0.60); overall ≈ **0.69**. Lower than Scene 1 purely on source authority.
4. **Scene 3 (native LDAP single):** no enrichment lookup; per-attribute = LDAP weights (0.85 / 0.65 / 0.90 / 0.95 / 0.70); overall ≈ **0.81**. `r&d`→`Engineering`, `C`→`contractor`, `memberOf` DNs reduced to `{engineering, admins}`.
5. **Scene 4 (sketchy SAML):** `department` = `Sorcery`, `single_source`, confidence = `0.50 − 0.2` = **0.30** (the **subtractive** `−0.2` normalization-failure penalty on the SAML department weight, visible only in the confidence — `single_source` details persist no penalty flag; **no** `×0.8` factor — single-source events have no conflict); `employee_type` = `null` (discarded), contributes `0.0`, no penalty; overall ≈ **0.45**. Both unmapped policies annotated (§3.3).
6. **Scene 5 (enriched, unanimous):** `display_name`/`department`/`employee_type`/`primary_email` all `unanimous` at the max agreeing weight (0.85 / 0.90 / 0.95 / 0.95); `groups` = `list_merge`, confidence ≈ **0.90** (union of 3, two corroborated), `sources=["ldap", "oidc"]`; `enrichment.applied=true`, `source=ldap`; overall ≈ **0.92**.
7. **Scene 6 (money shot):** `display_name` = `priority`, **winner OIDC** ("Di Prince"), confidence = 0.70 × 0.8 = **0.56**, `conflicting_values={ldap:"Diana Prince"}`; `department` = `priority`, **winner LDAP** ("Engineering"), confidence = 0.90 × 0.8 = **0.72**, `conflicting_values={oidc:"Marketing"}`; `primary_email`/`employee_type` `unanimous` (0.95 each); `groups` = `list_merge` ≈ **0.80**, `sources=["ldap", "oidc"]` (union of 3, one corroborated; the directory back-populates `vpn-users`, absent from the token, so the merged set is a strict superset of the token's and the confidence sits visibly below Scene 5's 0.90); overall ≈ **0.82**. Two different sources win two different attributes — rendered prominently.
8. **Read-back/cleanup:** all six ids reach non-null `normalized_attributes` within the timeout; default run deletes exactly those six rows; `--keep` preserves them and prints the ids.
9. **Narrative verification (§5.5):** after normalization and before rendering, the script runs the structural/relative checks and **aborts with a specific message** on any mismatch (e.g., a config that didn't apply the §5.4 change → Scene 6 `display_name` winner is `ldap` → abort naming that expectation). `--skip-verify` bypasses the checks (development only). The two-different-winners check on Scene 6 and the `C(4) < C(2) < C(1) < C(3)` ordering check are both included.
10. **Recording UX:** `--pace`/`--step` control scene cadence; confidence color thresholds (green ≥ 0.80 / amber 0.50–0.79 / red < 0.50) apply consistently; the final summary table shows the full confidence arc.
11. **LDAP group infrastructure (§5.6):** a live `ldapsearch` confirms the four `groupOfNames` groups exist with the listed members, and that enrichment lookups of `alice` and `diana` return `memberOf` reducing to `{engineering, vpn-users}`. SPEC_0 §5.3 is updated in lockstep to match the actual bootstrap + overlay. No existing user attribute is altered.
12. **Scene-6 explanatory annotation (§3.4):** the rendered Scene 6 includes the "Why the split?" annotation conveying both per-attribute rationales (display_name→OIDC presentation; department→LDAP org-fact) and the "a global priority would be wrong" point.

---

## 7. What NOT to Build

- **No new API endpoints** (no `GET /events`, no read service). The script reads PostgreSQL directly.
- **Only one `config/normalization.yaml` change is permitted:** the `display_name.priority` reorder + rationale (§5.4), mirrored in SPEC_2 §5.6. Do not change any other attribute, weight, `defaults`, or `enrichment` setting, and do not introduce a separate demo config file or compose override (the prior overlay approach is removed).
- **No changes to service code, shared models, the resolution algorithm, the protocol adapters, or the value-normalization tables.** The demo is read-only with respect to the pipeline.
- **No changes to existing seeded *user* attributes.** §5.6 adds `groupOfNames` group entries, member assignments, and the `memberof`/`refint` overlay configuration; it must not modify any existing user's `cn`, `mail`, `departmentNumber`, `employeeType`, or `uid`, and must not remove or alter existing user or OU entries.
- **No SPEC_0 edits beyond §5.3.** The only permitted SPEC_0 change is mirroring the new group entries and overlay config into §5.3 (§5.6); leave all other sections untouched.
- **Verify the narrative, don't fabricate it.** The script **must** run the post-normalization narrative checks (§5.5) and abort on mismatch (bypassable only via `--skip-verify`). Beyond that, per-scene rendering shows **actual** persisted output — do not hardcode or fake per-scene confidence values or winners in the rendered tables.
- **No authentication, dashboard, WebSocket, risk scoring, or signal enrichment** — out of scope for a Specs 0–2 normalization demo.
- **No demo-only branches inside any service.** Demo-specific behavior lives in the `demo/` artifacts; the config and LDIF/overlay changes are deliberate product changes, not service-level demo switches.
- **No coupling** to `naas_shared` that would prevent the script from running with only the three declared pip dependencies.
