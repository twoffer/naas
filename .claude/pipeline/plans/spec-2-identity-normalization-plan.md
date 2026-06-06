PLAN: Identity Normalization Service (Spec 2)
SPEC REFERENCE: docs/architecture/SPEC_2_Identity_Normalization_Service.md
PREREQUISITES:
- Spec 0 (shared foundation) complete: shared/naas_shared/{config,constants,models,schemas,database,redis_client,logging}.py present; infrastructure/postgres/init.sql (events table) applied; infrastructure/openldap (test users alice/bob/charlie/diana/eve under ou=users,dc=corp,dc=com) running.
- Spec 1 (event-ingestion) complete and is the reference pattern for service structure, hexagonal layout (ports.py / adapters / service.py / main.py), the Option A Dockerfile (repo-root build context, COPY shared/ + pip install -e), requirements.txt, /health handler, and the docker-compose service entry.
- .env / .env.example already carry LDAP_POOL_SIZE=3 and IDENTITY_NORMALIZATION_PORT=8002 (verified). The shared Settings does NOT yet expose ldap_pool_size (currently dropped by extra="ignore"); this spec adds it.
- The shared models are the contract and already exist: LoginEventRecord, NormalizedAttributes + the four resolution sub-models (UnanimousResolution, PriorityResolution, SingleSourceResolution, ListMergeResolution), EnrichmentApplied/EnrichmentSkipped (+ EnrichmentSkipReason literal), HealthResponse, EventORM. DO NOT redefine any of them.

This service is BOTH a FastAPI app (GET /health on port 8002) AND a long-lived background Redis Stream consumer. It consumes login_events (group normalization_workers), maps OIDC/SAML/LDAP raw_attributes into the unified schema, optionally enriches OIDC/SAML events via a live OpenLDAP lookup, resolves cross-source conflicts with confidence scoring, UPDATEs events.normalized_attributes by id, and republishes the full LoginEventRecord to normalized_events (ADR-0011). Hexagonal architecture (ADR-0009): domain logic + port Protocols in the core, concrete I/O in adapters, a thin composition root.

STEPS:

Step 1: Service scaffold, FastAPI app, /health, port definitions
  Files:
    services/identity-normalization/Dockerfile
    services/identity-normalization/requirements.txt
    services/identity-normalization/app/__init__.py
    services/identity-normalization/app/main.py
    services/identity-normalization/app/ports.py
    docker-compose.yml (add identity-normalization entry only)
  Details:
    - Dockerfile: follow the Spec 1 Option A pattern (FROM python:3.12-slim; WORKDIR /app; COPY shared/ /app/shared/; RUN pip install --no-cache-dir -e /app/shared/; COPY services/identity-normalization/requirements.txt; pip install -r; COPY app/; WORKDIR /app/svc; EXPOSE 8002; CMD uvicorn app.main:app --host 0.0.0.0 --port 8002). ⚠️ python-ldap needs system build deps NOT in the Spec 1 image — add `RUN apt-get update && apt-get install -y --no-install-recommends gcc libldap2-dev libsasl2-dev && rm -rf /var/lib/apt/lists/*` BEFORE `pip install -r requirements.txt` (and ideally before `pip install -e /app/shared/` so the layer is cached). Without these, the python-ldap wheel build fails (spec §5.8).
    - requirements.txt: fastapi>=0.115, uvicorn[standard]>=0.30, python-ldap>=3.4, pyyaml>=6.0. Data-layer deps (sqlalchemy, asyncpg, redis, pydantic, structlog) come transitively via naas_shared.
    - main.py: composition root. create_app() calls setup_logging("identity-normalization"), builds FastAPI(title="identity-normalization", version="2.0.0", lifespan=lifespan), and includes a router that exposes ONLY GET /health. In THIS chunk the lifespan is a minimal stub (yield only) — the consumer-loop launch + ensure_consumer_group + config load are wired in the final chunk. Expose module-level `app`.
    - /health: GET /health → HealthResponse(service="identity-normalization"). Use request-scoped get_db_session for a `SELECT 1` (text("SELECT 1")) and `get_redis().ping()`. PG OK + Redis OK → "healthy"; PG OK + Redis down → "degraded"; PG down → "unhealthy". Always HTTP 200; status in body (never 500 on dependency outage). Access get_db_session / get_redis through the naas_shared.* module references at call time so tests can patch them (mirror the Spec 1 routes.py health handler exactly).
    - ports.py: define typing.Protocol classes (structural, no implementation) for the hexagonal seams: ProtocolAdapter (extract(raw_attributes: dict) -> dict), LdapEnricher (extract(...) -> dict; async enrich(correlation_field: str, lookup_value: str) -> dict | None), NormalizationRepository (async write(event_id, normalized: NormalizedAttributes) -> None), EventPublisher (async publish_normalized(record: LoginEventRecord, normalized: NormalizedAttributes) -> None). These are the contracts later chunks implement; keep signatures stable.
  Shared imports:
    from naas_shared.logging import setup_logging, get_logger
    from naas_shared.models import HealthResponse, LoginEventRecord, NormalizedAttributes  (NormalizedAttributes/LoginEventRecord used only as type hints in ports.py)
    from naas_shared.database import get_db_session
    from naas_shared.redis_client import get_redis
  Verify:
    - `docker compose build identity-normalization` succeeds (proves python-ldap system deps are present).
    - `docker compose up -d identity-normalization` then `curl -s http://localhost:8002/health` returns {"status":"healthy","service":"identity-normalization",...} (spec validation §6.8).
    - `python -c "import app.main; assert app.main.app"` inside the service image; ports.py imports cleanly.

Step 2: Value normalization tables + protocol adapters (OIDC/SAML/LDAP extract)
  Files:
    services/identity-normalization/app/normalization_values.py
    services/identity-normalization/app/adapters/__init__.py
    services/identity-normalization/app/adapters/oidc.py
    services/identity-normalization/app/adapters/saml.py
    services/identity-normalization/app/adapters/ldap.py (extract method ONLY in this chunk; enrich added in Step 4)
  Details:
    - normalization_values.py: TRANSCRIBE EXACTLY the DEPARTMENT_CANONICAL and EMPLOYEE_TYPE_CANONICAL dicts from spec §5.2. Provide case-insensitive lookup helpers:
        * normalize_department(value) -> str: lower/strip key lookup in DEPARTMENT_CANONICAL; on hit return the canonical value; on MISS return value.title() (retained, title-cased) and the caller logs a structured `unmapped_attribute_value` warning. Expose a way to tell the caller whether the value was mapped (e.g., return (value, was_mapped) or a sentinel) so resolution can apply the 0.2 penalty only when an unmapped department value wins (§5.2, §5.5).
        * normalize_employee_type(value) -> Optional[Literal["FTE","contractor","vendor"]]: lower/strip lookup in EMPLOYEE_TYPE_CANONICAL; on hit return canonical; on MISS return None (DISCARD — never store a non-Literal value; caller logs `unmapped_attribute_value` warning). No numeric penalty (§5.2).
      Lookups are case-insensitive. The canonical TARGET values must be byte-identical across all three adapters so cross-protocol values compare equal.
    - Mapping table (TRANSCRIBE EXACTLY, spec §5.2):
        display_name  ← oidc:name        saml:displayName  ldap:cn
        primary_email ← oidc:email       saml:email        ldap:mail
        department    ← oidc:department  saml:dept         ldap:departmentNumber   (value-normalized)
        employee_type ← oidc:employee_type saml:employeeType ldap:employeeType     (normalized to FTE|contractor|vendor)
        groups        ← oidc:groups      saml:groups       ldap:memberOf            (list)
    - oidc.py / saml.py: OidcAdapter / SamlAdapter implement ProtocolAdapter.extract(raw_attributes) → dict with keys display_name, primary_email, department, employee_type, groups. Apply normalize_department / normalize_employee_type. Any absent raw key → that unified field omitted/None (absence handled later by single-source resolution). groups: pass through as a list (default []).
    - ldap.py: LdapAdapter.extract(raw_attributes) → same unified dict. ⚠️ groups: ldap `memberOf` values are typically full DNs (e.g., `cn=engineering,ou=groups,dc=corp,dc=com`). Reduce each memberOf DN to its group name (the cn RDN value). Use a robust DN parse (e.g., ldap.dn.str2dn or split on the first `cn=` RDN), not a naive string slice. If memberOf is a bare name (already a cn), pass it through. ⚠️ Confirm the actual memberOf format against infrastructure/openldap/bootstrap.ldif — see KNOWN RISKS: the bootstrap users currently carry NO memberOf attribute, so live LDAP groups will be empty; the DN-reduction logic must still be correct and unit-testable against synthetic DN inputs.
    - extract is deterministic, NO network I/O. The LDAP adapter's extract is reused internally by enrich (Step 4) to normalize query results.
  Shared imports:
    from naas_shared.logging import get_logger
    (no shared model import strictly required for extract; adapters return plain dicts)
  Verify:
    - Unit: OidcAdapter().extract({"name":"Alice Smith","email":"alice@corp.com","department":"eng","employee_type":"E","groups":["admin"]}) → {"display_name":"Alice Smith","primary_email":"alice@corp.com","department":"Engineering","employee_type":"FTE","groups":["admin"]}.
    - Unit: SAML displayName→display_name, dept→department, employeeType→employee_type mapping holds.
    - Unit: LDAP cn→display_name, mail→primary_email, departmentNumber→department, employeeType→employee_type; memberOf ["cn=engineering,ou=groups,dc=corp,dc=com"] → groups ["engineering"].
    - Unit: department "eng" → "Engineering"; employee_type "E" → "FTE"; unmapped employee_type "XYZ" → None; unmapped department "Astrophysics" → "Astrophysics" (title-cased, retained, was_mapped=False).

Step 3: Normalization config model + loader/validator (config/normalization.yaml)
  Files:
    services/identity-normalization/app/normalization_config.py
    config/normalization.yaml (CREATE — directory scaffolded by Spec 0)
  Details:
    - config/normalization.yaml: TRANSCRIBE EXACTLY the YAML from spec §5.6 (defaults.source_weights ldap=0.7/saml=0.6/oidc=0.8; per-attribute priority + weights + rationale for display_name, primary_email, department, employee_type; groups merge_strategy union; enrichment.sources.ldap with enabled=true, correlation_key=primary_email, timeout_ms=2000, on_failure=continue, cache_ttl_seconds=60, commented optional enrich_attributes). These weights tune demo behaviour and the §3.3 example payload assumes them — do not change values.
    - normalization_config.py: Pydantic models mirroring the YAML structure:
        * AttributeConfig: priority: list[str] (optional), weights: dict[str,float] (optional), merge_strategy: Optional[Literal["union","intersection","priority"]], rationale: str.
        * Defaults: source_weights: dict[str,float].
        * LdapEnrichmentConfig: enabled: bool, correlation_key: str, timeout_ms: int, on_failure: str, cache_ttl_seconds: int, enrich_attributes: Optional[list[str]] = None.
        * EnrichmentConfig: sources: { ldap: LdapEnrichmentConfig }.
        * NormalizationConfig: defaults: Defaults, attributes: dict[str, AttributeConfig], enrichment: EnrichmentConfig.
      Provide helper accessors used by resolution (Step 5): weight_for(attribute, source) → per-attribute weight or defaults.source_weights[source]; priority_for(attribute) → priority list; merge_strategy_for(attribute) → strategy (default "union").
    - load_config(path) function: read YAML (pyyaml safe_load), validate with NormalizationConfig.model_validate, then apply ⚠️ STARTUP VALIDATION (spec §5.6) that ABORTS startup with a descriptive error on any of:
        * correlation_key not in the reverse-mappable unified set {display_name, primary_email, department, employee_type, groups}.
        * on_failure not in {"continue","fail"}.
        * enrich_attributes (if present) containing any name not in that unified set.
        * cache_ttl_seconds not a positive integer.
      Define the reverse-mappable unified field set as a module constant shared with the LDAP adapter (single source of truth: unified→ldap-attr map). Raise a clear exception (e.g., ValueError / a ConfigError) with the offending value in the message.
  Shared imports: none required (pydantic + pyyaml only).
  Verify:
    - Unit: load_config(<valid yaml>) returns a NormalizationConfig with weight_for("department","ldap")==0.90 and weight_for("display_name","oidc")==0.60; merge_strategy_for("groups")=="union"; weight_for(<attr with no entry>,"ldap") falls back to defaults 0.7.
    - Unit: load_config of a yaml with correlation_key: favorite_color raises a descriptive error (spec §6.9).
    - Unit: on_failure: "explode" and cache_ttl_seconds: 0 and enrich_attributes: [bogus] each abort with a descriptive error.

Step 4: LDAP enrichment adapter (live query, pool, sanitization, three-state cache) + shared-module additions + SPEC_0 mirrors
  Files:
    services/identity-normalization/app/adapters/ldap.py (ADD enrich(...) + pool + cache; extract from Step 2 stays)
    shared/naas_shared/constants.py (ADD one constant)
    shared/naas_shared/config.py (ADD one Settings field)
    docs/architecture/SPEC_0_Project_Scaffold_and_Shared_Foundation.md (§3.3 + §3.8 mirrors ONLY)
  Details:
    ⚠️ This is the lockstep chunk: the shared-module additions and their SPEC_0 mirrors MUST land together (spec §1). The constant and field are CONSUMED by the enrich method here, which is why they belong in this chunk rather than the scaffold.
    - shared/naas_shared/constants.py: add exactly `LDAP_ENRICHMENT_CACHE_PREFIX = "ldap_enrichment:"` to the cache-prefix block (after CACHE_FEATURE_FLAGS_TTL). The TTL is NOT a constant (it comes from normalization.yaml). Add nothing else.
    - shared/naas_shared/config.py: add exactly `ldap_pool_size: int = Field(default=3, ge=1, le=10)` to the LDAP block of Settings (after ldap_admin_password). Field is already imported in config.py. Reads LDAP_POOL_SIZE which already exists in .env.example (currently dropped by extra="ignore"). Add nothing else.
    - SPEC_0 §3.3 (line ~371, after `CACHE_FEATURE_FLAGS_TTL = 60` inside the python code block): add `LDAP_ENRICHMENT_CACHE_PREFIX = "ldap_enrichment:"` so the doc mirror matches the module.
    - SPEC_0 §3.8 (line ~732, after `ldap_admin_password: str = "admin"` in the LDAP block of the Settings snippet): add `ldap_pool_size: int = Field(default=3, ge=1, le=10)`. Do NOT touch any other part of SPEC_0.
    - ldap.py enrich(correlation_field, lookup_value) -> dict | None (async):
        * Reverse-map the UNIFIED correlation_field to its LDAP attribute via the adapter's own mapping (the single source of truth): display_name→cn, primary_email→mail, department→departmentNumber, employee_type→employeeType, groups→memberOf. If correlation_field is not reverse-mappable → return None.
        * Connection: a small pool of get_settings().ldap_pool_size connections to `ldap://{settings.ldap_host}:{settings.ldap_port}`, bound with settings.ldap_admin_dn / settings.ldap_admin_password. ⚠️ There is NO LDAP_URI / LDAP_BIND_DN / LDAP_BIND_PASSWORD — construct the URI and bind from these fields (spec §4).
        * python-ldap is SYNCHRONOUS — ⚠️ wrap every blocking LDAP call (initialize, bind, search_s) in asyncio.to_thread(...) so the event loop is never blocked.
        * ⚠️ LDAP injection sanitization REQUIRED: build the filter as f"({ldap_attr}={ldap.filter.escape_filter_chars(lookup_value)})". Never interpolate a raw value.
        * Search: search_s(settings.ldap_base_dn, ldap.SCOPE_SUBTREE, filter_str, attrlist) where attrlist is the reverse-mapped set of unified fields to fetch (all mapped attrs unless enrich_attributes narrows them — but enrich_attributes selection is config-driven, passed in by the orchestration layer).
        * On a match: pass the returned LDAP attributes through self.extract(...) and return the unified-schema dict. Return None on no match, query failure, or an un-reverse-mappable field.
        * Apply a search time bound from timeout_ms (config) — surface timeout distinctly so the orchestration layer can map it to skip_reason="ldap_timeout".
      ⚠️ Caching (Redis) — three-state negative cache:
        * Key: f"{LDAP_ENRICHMENT_CACHE_PREFIX}{correlation_value}" (e.g. ldap_enrichment:alice@corp.com).
        * TTL: enrichment.sources.ldap.cache_ttl_seconds (passed in; default 60). Not a constant.
        * (a) MISS — GET returns None → query LDAP. (b) NEGATIVE HIT — key present holding the sentinel for "no such user" (the JSON string "null") → treat as no-match WITHOUT querying. (c) POSITIVE HIT — key present holding a JSON attribute object → use it.
        * Cache BOTH positive (unified dict) and negative (sentinel) results with the same TTL, so repeated logins for an unknown user do not hammer the directory.
        * ⚠️ Transient failures (timeout / connection_error / search_error) are NOT negative-cached, so the service recovers automatically when LDAP returns.
      NOTE: enrich returns the unified dict OR None plus enough signal for the orchestration layer to choose the skip_reason; the EnrichmentApplied/EnrichmentSkipped MODEL mapping itself is decided in the orchestration layer (Step 6, §5.4), not inside the adapter. Whether a positive result came from cache (cache_hit) must be conveyable to the caller.
    - The enrichment DECISION (enabled? protocol in oidc/saml?) and the skip-reason mapping are NOT in this chunk — they live in the service orchestration (Step 6). This chunk only provides the adapter's enrich + cache mechanics and is unit-testable in isolation (mock the LDAP connection and the Redis client).
  Shared imports:
    from naas_shared.config import get_settings
    from naas_shared.constants import LDAP_ENRICHMENT_CACHE_PREFIX
    from naas_shared.redis_client import get_redis
    from naas_shared.logging import get_logger
    import ldap, ldap.filter, ldap.dn  (python-ldap)
  Verify:
    - `python -c "from naas_shared.constants import LDAP_ENRICHMENT_CACHE_PREFIX; assert LDAP_ENRICHMENT_CACHE_PREFIX=='ldap_enrichment:'"`.
    - `python -c "from naas_shared.config import get_settings; get_settings.cache_clear(); s=get_settings(); assert s.ldap_pool_size==3"` (default) and with LDAP_POOL_SIZE=5 env → 5; LDAP_POOL_SIZE=0 → validation error (ge=1).
    - grep SPEC_0 §3.3 shows LDAP_ENRICHMENT_CACHE_PREFIX and §3.8 shows ldap_pool_size (mirror parity).
    - Unit (mocked): build_search_filter escapes a value containing `*()\` correctly (no raw interpolation).
    - Unit (mocked LDAP + fake redis): a no-match writes the negative sentinel "null" with the configured TTL; a second enrich for the same value returns no-match WITHOUT a second LDAP search_s call; a positive match caches the unified dict and a second call returns it with cache_hit=True; a simulated connection error does NOT write a negative-cache entry.

Step 5: Conflict resolution + confidence scoring (the algorithmic core)
  Files:
    services/identity-normalization/app/resolution.py
  Details:
    Input: per unified attribute, a map {source_protocol: normalized_value} for every source that supplied a NON-NULL value (plus, for department, whether the value was an unmapped/retained value), the NormalizationConfig (weights/priority/merge_strategy), and the primary event protocol. Output: a fully-formed NormalizedAttributes (minus enrichment, which the orchestration layer attaches — OR accept the enrichment metadata as a parameter; keep the boundary explicit and consistent with Step 6).
    ⚠️ CRITICAL — emit ONLY the four shared resolution literals: unanimous, priority, single_source, list_merge. NEVER emit no_data/fallback or any other discriminator (would fail NormalizedAttributes validation). resolution_details is Dict[str, ResolutionDetail].
    SCALAR attributes (display_name, primary_email, department, employee_type) — resolve over present (non-null) sources:
      * 0 present sources → unified attribute None; contributes 0.0 to overall confidence; NO entry written to resolution_details (omit the key).
      * exactly 1 present → SingleSourceResolution(resolution="single_source", resolved_value=<value>, confidence=weight_for(attr, that source), sources=[that protocol]).
      * ≥2 present, all agree (after value normalization) → UnanimousResolution(resolution="unanimous", resolved_value=<agreed value>, confidence=max(weight_for(attr, s) for agreeing s), sources=[agreeing protocols]).
      * ≥2 present, disagree → PriorityResolution(resolution="priority", resolved_value=<winner value>, confidence=winner_weight × 0.8, winner_source=<protocol>, conflicting_values={loser protocol: loser non-null value, ...}, penalty_applied=True). Winner = highest-priority source (priority_for(attr)) that has a value; if no configured-priority source has a value, the highest-weight present source wins. conflicting_values contains ONLY losing NON-NULL values.
    NORMALIZATION-FAILURE PENALTY (0.2): attaches to a resolution's confidence ONLY when the resolved (winning) value is itself an UNMAPPED value (clamp result to [0.0,1.0]). This can happen ONLY for department (unmapped retained). It can NEVER happen for employee_type (unmapped discarded to None, so that source is simply absent from the present-set). A discarded source neither contributes nor penalizes — a surviving valid source resolves at its own FULL confidence; if none survives the attribute is None contributing 0.0.
    LIST attribute groups → ListMergeResolution:
      * merge per merge_strategy_for("groups") (default "union"; also intersection, priority). resolved_value = merged, DE-DUPLICATED, SORTED group list. total_unique_groups = len(resolved_value).
      * confidence: if ONE source contributed → that source's weight; if MULTIPLE → 0.7 + 0.3 × (fraction of merged groups present in MORE THAN ONE source). If 0 sources → 0.0 contribution and (consistent with scalar 0-source rule) no entry; but groups defaults to [] on the model — emit no resolution_details["groups"] entry when no source supplied groups.
    OVERALL normalization_confidence (spec §5.5.2): importance-weighted average of per-attribute confidences; attributes with no present source contribute 0.0. TRANSCRIBE EXACTLY:
        ATTRIBUTE_IMPORTANCE = {display_name:0.15, primary_email:0.25, department:0.20, employee_type:0.25, groups:0.15} (sum 1.0).
        confidence = sum(ATTRIBUTE_IMPORTANCE[a] * per_attr_conf.get(a, 0.0) for a in ATTRIBUTE_IMPORTANCE); normalization_confidence = max(0.0, min(1.0, confidence)).
    source_protocol on the output = the PRIMARY event's protocol (oidc/saml/ldap), even when LDAP enrichment contributed.
    Keep this module pure/deterministic (no I/O). The orchestration (select adapter, attempt enrich, attach enrichment metadata, persist, publish) lives in service/consumer (Step 6), not here.
  Shared imports:
    from naas_shared.models import (NormalizedAttributes, UnanimousResolution, PriorityResolution, SingleSourceResolution, ListMergeResolution)
    (EnrichmentApplied/EnrichmentSkipped imported here only if resolution builds the full model; otherwise imported in Step 6)
  Verify:
    - Unit: single source (one protocol, no enrichment) → every present attr is single_source with confidence == that source's per-attr weight; absent attrs omitted from resolution_details; groups empty → no groups entry.
    - Unit: two agreeing sources (oidc+ldap, same department after canonicalization) → unanimous, confidence == max weight, sources lists both.
    - Unit: two disagreeing sources on department (oidc "Product" vs ldap "Engineering") → priority, winner_source per priority list ["ldap","oidc","saml"] = ldap, confidence == ldap_weight×0.8, conflicting_values={"oidc":"Product"}, penalty_applied=True.
    - Unit: resolved winning department is an UNMAPPED retained value → 0.2 penalty applied and clamped to [0,1]; resolved winning employee_type can never carry the 0.2 penalty.
    - Unit: groups union de-dup+sort; multi-source groups confidence == 0.7 + 0.3×(shared fraction); single-source groups confidence == that source's weight.
    - Unit: normalization_confidence == importance-weighted average; matches a hand-computed value for the §3.3 example shape (~0.87 region given those weights).

Step 6: Service orchestration, enrichment decision/skip mapping, repository, consumer loop + publish wiring (integration-facing)
  Files:
    services/identity-normalization/app/service.py
    services/identity-normalization/app/repository.py
    services/identity-normalization/app/consumer.py
    services/identity-normalization/app/main.py (UPDATE lifespan only — wire ensure_consumer_group + config load + consumer task; /health unchanged)
  Details:
    - service.py NormalizationService.normalize(record: LoginEventRecord) -> NormalizedAttributes (domain orchestration, spec §5.7):
        * Select the primary adapter by record.protocol (oidc→OidcAdapter, saml→SamlAdapter, ldap→LdapAdapter). extract the primary attributes (deterministic).
        * Enrichment DECISION (§5.4, ⚠️ source-agnostic — NEVER branch on is_synthetic): attempt LDAP enrichment IFF enrichment.sources.ldap.enabled AND record.protocol in ("oidc","saml"). Map outcome to EXACTLY ONE enrichment variant via the closed skip_reason enum:
            - match (live or positive cache hit) → EnrichmentApplied(applied=True, source="ldap", cache_hit=<bool>)
            - disabled → EnrichmentSkipped(skip_reason="ldap_disabled")
            - protocol == ldap → EnrichmentSkipped(skip_reason="ldap_event")
            - correlation value missing/empty in primary attrs → EnrichmentSkipped(skip_reason="invalid_correlation_key")
            - no match (live or negative cache hit) → EnrichmentSkipped(skip_reason="no_ldap_match")
            - search exceeded timeout_ms → EnrichmentSkipped(skip_reason="ldap_timeout")
            - connection refused / network error → EnrichmentSkipped(skip_reason="ldap_connection_error")
            - other LDAP-side error → EnrichmentSkipped(skip_reason="ldap_search_error")
          The correlation lookup value = the primary attrs' value for config correlation_key (default primary_email). When enrichment applies and returns a unified dict, add "ldap" as a source for each attribute it supplied, then run resolution over the combined {source: value} maps (Step 5).
        * ⚠️ Graceful degradation (ADR-0008): on ANY enrichment failure/miss the event is NEVER rejected or delayed — proceed with primary-source-only data and the appropriate EnrichmentSkipped variant. Log levels: no_ldap_match→INFO; invalid_correlation_key / ldap_timeout→WARNING; connection/search errors→ERROR (rate-limit connection-refused logging to first occurrence). DO NOT branch on is_synthetic anywhere.
        * Run resolution (Step 5) → NormalizedAttributes; attach the enrichment metadata variant; set source_protocol = record.protocol. Return it.
    - repository.py PostgresNormalizationRepository(session) implements NormalizationRepository.write(event_id, normalized): UPDATE events SET normalized_attributes = normalized.model_dump(mode="json") WHERE id = event_id, using the shared EventORM + an AsyncSession from get_session_factory(); explicit await session.commit(). ⚠️ UPDATE by id ONLY — no INSERT, no SELECT-before-update, no create_all/migrations, no schema changes (§3.1, §7). Idempotent: reprocessing overwrites the same row equivalently. normalization_confidence is a field INSIDE the JSONB, not a column.
    - publisher: an EventPublisher implementation (may live in service.py or a small adapter) publish_normalized(record, normalized): record.normalized_attributes = normalized.model_dump(mode="json"); await publish_to_stream(STREAM_NORMALIZED_EVENTS, record.model_dump(mode="json")). Full LoginEventRecord with normalized_attributes populated, id as correlation key (ADR-0011). Use the shared helper — do NOT hand-roll XADD.
    - consumer.py — the background worker (spec §5.1). Unique consumer name per instance (e.g., container hostname). Loop:
        msgs = XREADGROUP(group=GROUP_NORMALIZATION, consumer=<name>, {STREAM_LOGIN_EVENTS: ">"}, count≈10, block≈2000ms)
        for (msg_id, fields):
          try:
            record = LoginEventRecord.model_validate(json.loads(fields["data"]))   # parse
            normalized = await service.normalize(record)                           # extract→enrich→resolve
            await repository.write(record.id, normalized)  # COMMIT (point of no return)
            await publisher.publish_normalized(record, normalized)                 # XADD normalized_events
            XACK(STREAM_LOGIN_EVENTS, GROUP_NORMALIZATION, msg_id)                 # ACK only after persist AND publish succeed
          except Exception:
            log.error(...); DO NOT XACK — message stays pending and is redelivered
      ⚠️ CRITICAL ordering (ADR-0002 dual-write): persist + commit BEFORE publish; XACK ONLY after BOTH succeed. On any raise, DO NOT ack (at-least-once redelivery is safe because UPDATE is idempotent and the stream carries the full record). DO NOT drop/skip/dead-letter a message merely because LDAP enrichment failed — that is handled by graceful degradation, not by failing the event. The worker obtains DB sessions from get_session_factory() directly (one session per event), NOT the request-scoped get_db_session (which is reserved for /health).
    - main.py lifespan (UPDATE only): on startup (1) setup_logging already called in create_app; (2) load+validate config/normalization.yaml (Step 3) — ⚠️ INVALID CONFIG ABORTS STARTUP; (3) ensure_consumer_group(STREAM_LOGIN_EVENTS, GROUP_NORMALIZATION) — ⚠️ this service OWNS group creation; (4) build NormalizationService wiring the adapters + LdapAdapter + config, build repository + publisher, launch the consumer loop as an asyncio background task. On shutdown cancel the task cleanly. Leave /health and create_app() structure from Step 1 intact.
  Shared imports:
    from naas_shared.config import get_settings
    from naas_shared.constants import STREAM_LOGIN_EVENTS, STREAM_NORMALIZED_EVENTS, GROUP_NORMALIZATION
    from naas_shared.database import get_session_factory
    from naas_shared.redis_client import get_redis, publish_to_stream, ensure_consumer_group
    from naas_shared.logging import get_logger
    from naas_shared.models import (LoginEventRecord, NormalizedAttributes, EnrichmentApplied, EnrichmentSkipped)
    from naas_shared.schemas import EventORM
  Verify (spec §6 end-to-end, after `docker compose up -d --build`):
    - §6.1 mapping: ingest one event per protocol; events.normalized_attributes carries the unified fields per the mapping table.
    - §6.2 value normalization: department "eng"→"Engineering"; employee_type "E"→"FTE"; unmapped employee_type "XYZ"→null and excluded from resolution; unmapped department title-cased + retained, penalized 0.2 only when it wins.
    - §6.3 enrichment applied + conflict: OIDC event for a user that EXISTS in OpenLDAP with department "Product" in token vs LDAP "Engineering" → enrichment.applied=true, source_protocol="oidc", priority resolution on department (winner_source="ldap", penalty_applied=true), both oidc+ldap shown as sources for agreeing attrs.
    - §6.4 enrichment skipped — no match: OIDC event for an absent user → enrichment.applied=false, skip_reason="no_ldap_match", single-source throughout, event still processed (not dropped).
    - §6.5 ldap event skips enrichment: protocol "ldap" → applied=false, skip_reason="ldap_event", source_protocol="ldap".
    - §6.6 negative cache: two successive OIDC logins for the same absent user → only ONE LDAP query (second from negative cache) within TTL.
    - §6.7 pipeline + ACK: XINFO GROUPS login_events shows normalization_workers; success → ACKed (pending→0); failure → stays pending and is redelivered; normalized_events gains one full-record message per processed event with normalized_attributes populated.
    - §6.9 config validation: starting with invalid correlation_key (e.g. favorite_color) aborts startup with a descriptive error.

INTEGRATION NOTES:
- Upstream: consumes login_events (group normalization_workers, ⚠️ this service creates the group via ensure_consumer_group on startup; Event Ingestion does NOT create it). Envelope: stream field "data" holds a JSON string; json.loads then LoginEventRecord.model_validate; record.id (UUID-as-string) is the correlation key and the events PK.
- Downstream: publishes the FULL LoginEventRecord (normalized_attributes populated) to normalized_events via the shared publish_to_stream helper (ADR-0011). Signal Enrichment (a later spec) consumes it under group enrichment_workers — this service does NOT create that group.
- Shared state / caching: Redis keyspace ldap_enrichment:<correlation_value> (three-state cache, TTL from normalization.yaml, default 60s). Negative sentinel = JSON "null". Positive = JSON unified dict. Transient failures NOT cached. Distinct from the ip_rep:/geo:/policy: prefixes owned by other services.
- DB: UPDATE events.normalized_attributes by id only. PostgreSQL is the system of record (ADR-0002); the stream copy is a transport convenience and benign because normalized_attributes is write-once (ADR-0011 "Conditions for Revisiting"). The worker uses get_session_factory() per event; /health uses request-scoped get_db_session.
- Dual-write ordering (ADR-0002): commit to PG BEFORE publishing to normalized_events; XACK only after BOTH. Unacked-on-failure → at-least-once redelivery, safe via idempotent UPDATE + full-record stream.
- LDAP: live read-only subtree search from settings.ldap_base_dn (covers ou=users). Bound with ldap_admin_dn/ldap_admin_password. NO LDAP_URI/BIND_DN env — construct from ldap_host/ldap_port. python-ldap is synchronous → wrap in asyncio.to_thread. NO writes, NO reverse enrichment, NO AD.
- Config: loaded once at startup; NO hot-reload. Mounted read-only at /app/config via the compose `./config:/app/config:ro` mount. Invalid config aborts startup (fail-fast, distinct from graceful enrichment degradation).
- Compose: depends_on postgres + redis + openldap with condition: service_healthy; env_file .env; ${IDENTITY_NORMALIZATION_PORT:-8002}:8002; /health healthcheck on 8002; ./config:/app/config:ro mount. Do NOT modify infrastructure or event-ingestion entries.
- No HTTP API beyond /health. No auth (handled upstream in a later spec).

KNOWN RISKS:
- ⚠️ bootstrap.ldif test users have NO memberOf attribute and there are no member-populated group entries under ou=groups. CONSEQUENCE: live LDAP enrichment will return cn/sn/mail/uid/departmentNumber/employeeType but NO groups for enriched OIDC/SAML events — so the §3.3 example payload (groups ["admin","engineering","vpn-users"]) is illustrative, not reproducible from the seeded directory. The memberOf→cn DN-reduction logic is still required and MUST be unit-tested against synthetic DN inputs (the spec §5.2 note itself says "confirm against bootstrap.ldif"). The §6.3 acceptance test only asserts a department conflict + agreeing attrs, which the seeded users DO support (e.g., bob: departmentNumber=Product). Recommended: do NOT make any test assert non-empty enriched groups from the live directory; assert DN-reduction at the unit level instead. This is a spec/fixture gap to surface, not a blocker.
- ⚠️ Seeded LDAP departments are stored as full words that are partly OUTSIDE DEPARTMENT_CANONICAL: alice/diana=Engineering (maps), bob=Product (NOT a key → retained+title-cased as "Product"), charlie=Security (NOT a key → "Security"), eve=External (NOT a key → "External"). The §6.3 test uses bob's "Product" only as the OIDC-token value vs LDAP "Engineering"; pick a user whose LDAP department IS canonical (alice=Engineering) for the LDAP side of that conflict, and put a conflicting canonical value (e.g. "Product") in the OIDC token. Implementers/test authors must choose fixtures deliberately so "winning value is unmapped" cases are tested explicitly and separately from the canonical-conflict case.
- correlation_key default is primary_email; the seeded users' mail values (alice@corp.com, etc.) are the lookup values. An OIDC token whose email does not match any LDAP mail yields no_ldap_match (the §6.4 path). Tests must use a known-absent email to exercise the negative cache (§6.6).
- python-ldap build deps (gcc, libldap2-dev, libsasl2-dev) are the most common build failure for this service. If the slim image still fails, add build-essential (spec §5.8 explicitly permits this). Flagged so the scaffold chunk does not silently produce an unbuildable image.
- timeout_ms enforcement: python-ldap's search timeout is set via conn.set_option(ldap.OPT_NETWORK_TIMEOUT, ...) / the timeout arg of search_st, not search_s. Implementer should use search_st(...) or set OPT_TIMEOUT to honor timeout_ms and map a TIMEOUT exception to skip_reason="ldap_timeout". Spec uses search_s in its EXEMPLARY snippet; treat the timeout requirement (§5.4) as authoritative over the exemplary call name.
- Boundary between resolution.py (Step 5) and service.py (Step 6) re: who constructs the final NormalizedAttributes and attaches enrichment metadata: the plan assigns resolution to BUILD the model from the {source:value} maps and the service to ATTACH the enrichment variant + source_protocol. Either split is defensible; the chunks fix this boundary explicitly (resolution returns the model sans-enrichment OR takes enrichment as a param) so Step 5 and Step 6 do not both try to own it. Implementers must keep the two chunks consistent with whichever signature Step 5 ships.
- ListMergeResolution.confidence formula "fraction of merged groups present in more than one source" is precise for union; for intersection/priority strategies the spec gives the formula generically. Default is union (only strategy exercised by the demo config). Implement union fully; implement intersection/priority per merge semantics but they are not on the acceptance path.
- ADR-0011 write-once assumption: this service writes normalized_attributes exactly once per event and never mutates it, so the stream-borne copy cannot drift. Do NOT add any re-normalization/back-fill that mutates an already-written normalized_attributes (would violate the ADR's "Conditions for Revisiting").
