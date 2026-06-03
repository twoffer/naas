# 8. Enrich OIDC and SAML Events via Live OpenLDAP Lookup, Correlated by a Unified-Schema Key

* Status: accepted
* Date: 2026-05-01
* Deciders: Tony

## Context and Problem Statement

NAAS demonstrates a unified view of identity across heterogeneous protocols (OIDC, SAML, LDAP). The Docker Compose stack includes a live OpenLDAP container, but in earlier design iterations OpenLDAP was used only as the source of simulated LDAP events — its presence in the architecture was largely decorative. In real-world enterprise IAM, LDAP serves a different role: it is the authoritative HR directory, and modern identity flows (OIDC, SAML) are routinely cross-referenced against it to merge directory data with token or assertion claims.

A login event arriving via OIDC carries the claims Keycloak chose to mint into the token, but the authoritative employee record — including the current department from the HR sync — lives in LDAP. Without cross-referencing, NAAS produces single-source normalization for OIDC and SAML events even when richer data exists right next door.

How should NAAS make use of the live OpenLDAP container in the normalization pipeline?

## Decision Drivers

* The live OpenLDAP container should serve a real architectural purpose, not merely exist as a decorative legacy-protocol prop
* Multi-source normalization is the headline differentiator NAAS demonstrates; the demo is more compelling when real conflicts can be shown
* Cross-protocol enrichment must not become a hard pipeline dependency — LDAP outages must not block event processing
* The normalization service must remain source-agnostic: it must not branch on whether an event is real or simulator-generated
* Configuration should not introduce a second source of truth for the protocol-to-schema mapping

## Considered Options

* **Cross-protocol enrichment with a unified-schema `correlation_key` and adapter-internal reverse-mapping** (chosen): Identity Normalization queries OpenLDAP for OIDC and SAML events; the correlation field is named in unified-schema terms (e.g., `primary_email`); the LDAP adapter reverse-maps that field name to the corresponding LDAP attribute (e.g., `mail`) using its existing protocol-to-schema mapping table
* **Cross-protocol enrichment with explicit LDAP attribute names in the enrichment configuration**: enrichment config directly specifies LDAP attributes (e.g., `correlation_attribute: "mail"`), creating a parallel mapping that lives outside the LDAP adapter
* **No enrichment**: leave the LDAP container as a source of simulated events only
* **Enrich every event including LDAP self-events**: query LDAP for all events regardless of source protocol
* **Push enrichment to the downstream Signal Enrichment Service**: relocate the cross-protocol lookup into the existing enrichment service rather than the normalization service

## Decision Outcome

Chosen option: **Cross-protocol enrichment with a unified-schema `correlation_key` and adapter-internal reverse-mapping.** The Identity Normalization Service performs an LDAP lookup for OIDC and SAML events. The enrichment configuration specifies the correlation field in unified-schema terms (`correlation_key: "primary_email"`), and the LDAP adapter is responsible for reverse-mapping that to the corresponding LDAP attribute (`mail`) using the same mapping table it already uses for forward mapping. Both the primary protocol's attributes and the LDAP attributes flow into the existing per-attribute conflict-resolution algorithm, producing a multi-source normalized identity with per-attribute confidence scores.

LDAP results are cached in Redis with a 60-second TTL, keyed by the correlation value. On any LDAP failure (connection error, timeout, no match), enrichment is skipped and normalization proceeds with single-source data; a structured warning is logged but the pipeline continues. LDAP-protocol events skip enrichment entirely — directory data is already in their payload, so re-querying the same directory is redundant.

The normalization service does not branch on `is_synthetic`. Real and simulated OIDC/SAML events are enriched identically.

### Positive Consequences

* OpenLDAP serves a real, ongoing architectural purpose: it is the authoritative source of HR data that OIDC and SAML events are cross-referenced against. The legacy-protocol container is no longer decorative.
* The demo can show genuine multi-source conflicts (e.g., OIDC says department X, LDAP says Y, conflict resolution picks Y with reduced confidence, lower confidence raises risk score). This is exactly the differentiator the project is built to demonstrate.
* The protocol-to-schema mapping has a single source of truth: the LDAP adapter. Enrichment configuration speaks unified-schema, and the adapter handles all translation. There is no risk of the enrichment config and the adapter mapping drifting apart.
* Graceful degradation is built in by design. LDAP availability is a quality knob, not a binary up/down dependency.
* Source-agnostic processing eliminates an entire class of conditional bugs and keeps the normalization layer's behavior consistent across real and simulated events.

### Negative Consequences

* Each OIDC/SAML event now incurs a Redis cache check and, on miss, an LDAP query. Mitigated by the 60-second cache TTL — within a typical demo session, most lookups for a given user resolve from cache.
* Configuration validation must run at service startup to catch invalid `correlation_key` values (a unified-schema field name with no LDAP reverse-mapping). The startup error message must be specific enough to be self-correcting.
* The LDAP connection pool is a new operational concern. Mitigated by sizing it conservatively (default 3 connections, configurable via `LDAP_POOL_SIZE`) and wrapping the synchronous `python-ldap` library in `asyncio.to_thread()` to avoid blocking the async event loop.

## Pros and Cons of the Options

### Cross-protocol enrichment with unified-schema `correlation_key`

* Good, because it makes the LDAP container architecturally load-bearing
* Good, because the protocol-to-schema mapping has a single source of truth
* Good, because demos can show real attribute conflicts and confidence scoring
* Good, because graceful degradation is a first-class property
* Bad, because each enrichable event incurs cache + (sometimes) LDAP overhead
* Bad, because adapter reverse-mapping is one more code path to test

### Cross-protocol enrichment with explicit LDAP attribute names in config

* Good, because enrichment configuration is more directly readable to LDAP-experienced operators
* Bad, because it creates a second mapping (config-side `mail`) parallel to the adapter's existing forward mapping (`mail` → `primary_email`). Both must agree, and there is no mechanical enforcement that they do
* Bad, because it spreads protocol-specific knowledge across multiple files
* Bad, because changing an LDAP attribute mapping now requires updating two places

### No enrichment

* Good, because it requires no new code
* Bad, because the LDAP container's role in the architecture remains unconvincing
* Bad, because the demo's most compelling visual — a real attribute conflict resolved across protocols — is not possible
* Bad, because single-source normalization for OIDC and SAML wastes the directory data sitting one container over

### Enrich every event including LDAP self-events

* Good, because the rule "always enrich" is simpler than "enrich some, not others"
* Bad, because LDAP events already carry directory data — re-querying the same directory for the same data is pure overhead
* Bad, because the redundancy is visible to anyone reviewing the architecture and would invite questions with no good answer

### Push enrichment to the Signal Enrichment Service

* Good, because the Signal Enrichment Service is already named "enrichment" and could plausibly host this logic
* Bad, because Signal Enrichment is conceptually about adding *external risk signals* (IP reputation, geolocation, device fingerprinting), not about reconciling identity attributes across protocols
* Bad, because it would put cross-protocol identity reconciliation downstream of identity normalization, which is upside-down — the normalization layer is precisely where multi-source identity data should be combined
* Bad, because the per-attribute conflict-resolution algorithm lives in the normalization service; pushing the second source elsewhere splits the algorithm across services

## More Information

The decision to use a single unified-schema field as the correlation key is intentionally restrictive. A more flexible design would allow composable expressions (e.g., `"{uid}@{LDAP_DOMAIN}"`) for environments where the correlation key must be constructed from multiple raw attributes. That capability is deferred as a future enhancement, and when it lands, it belongs in the protocol adapter (which is the single source of truth for protocol-to-schema translation), not in the enrichment configuration.

The cache TTL of 60 seconds is short enough that LDAP changes propagate quickly during a demo session and long enough that bursts of activity for the same user are absorbed by the cache. Production deployments would tune this based on the expected frequency of authoritative-source updates.

The bidirectional question — should LDAP events ever be enriched from OIDC tokens? — is intentionally out of scope. LDAP authentication completes against the directory; if the directory is the authoritative source, there is nothing OIDC could add. A future "user identity graph" feature might revisit this, but not in the current scope.
