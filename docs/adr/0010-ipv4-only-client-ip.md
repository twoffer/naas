# 10. Accept Only IPv4 Addresses for Login-Event `client_ip` in the Initial Release

* Status: accepted
* Date: 2026-06-03
* Deciders: Tony

## Context and Problem Statement

Every login event entering NAAS carries a `client_ip`. That single field is the seed for three downstream signals in the enrichment stage — geolocation (IP → city/country/lat/lon), IP reputation, and impossible-travel detection (great-circle distance between consecutive logins) — and it is persisted in the `events.client_ip` column.

The address-family scope for `client_ip` must be decided deliberately, because it determines what the ingestion boundary validates, what the enrichers can reason about, and what the demo and any reviewers will see end to end. The question is whether the initial release should support IPv4 only, support both IPv4 and IPv6 from the outset, or accept any string and defer validation.

## Decision Drivers

* Deliver a complete, correct first increment rather than partial coverage of two address families.
* `client_ip` feeds geolocation, IP reputation, and impossible-travel — every one of those paths must reason over a consistent, validated format.
* Validation at the ingestion boundary should be unambiguous: a malformed address must be rejected where it enters, not fail silently three stages downstream.
* Avoid spreading half-finished IPv6 handling across validation, persistence, and three enrichers before any of it is exercised end to end.
* Keep the demonstrable surface honest: what the system claims to support, it should support completely.

## Considered Options

* **IPv4-only for the initial release** (chosen): `client_ip` is validated as a well-formed IPv4 address; IPv6 is a planned later increment.
* **IPv4 + IPv6 from the outset**: support both address families in the first release.
* **Accept any string, no address validation**: store whatever arrives and let downstream stages cope.

## Decision Outcome

Chosen option: **IPv4-only for the initial release.** The `client_ip` field on the shared login-event model is validated against a regex that accepts only well-formed IPv4 addresses, with each octet bounded to `0`–`255`. This is framed as the first complete increment of address handling, not as a permanent restriction: IPv6 is a planned follow-on, and the system is designed so that adding it is an additive change rather than a rework.

### Positive Consequences

* One address family is supported completely and consistently end to end — ingestion validation, persistence, geolocation, IP reputation, and impossible-travel all reason over the same well-formed format.
* Strict boundary validation rejects malformed input (including numerically invalid values such as `256.0.0.1` and shape-only junk) at ingestion, so no enricher has to defend against a value it cannot interpret.
* The first increment is shippable and demonstrable without partial behavior or "works for v4, untested for v6" caveats.
* The scope is explicit and documented, so the absence of IPv6 reads as a deliberate sequencing decision rather than an oversight.

### Negative Consequences

* Events whose source address is IPv6 cannot be ingested until the planned follow-on increment; such an event is rejected at the boundary.
* In a dual-stack production network, IPv4-only ingestion would not represent the full traffic profile. This is acceptable for the initial release and is the motivation for the documented increment path below.

### Increment Path

IPv4-only is the first step, not the end state. The planned follow-on adds IPv6:

* **Validation:** broaden the `client_ip` constraint to accept IPv6 as well as IPv4 (or validate the address with a dedicated address type).
* **Persistence:** no migration required — the `events.client_ip` column is already `INET`, which stores IPv4 and IPv6 transparently.
* **Enrichment:** geolocation and IP-reputation providers generally support IPv6 lookups; impossible-travel reasons over latitude/longitude and is independent of address family. The work is concentrated at the validation layer and in confirming each provider's IPv6 coverage, not in the core algorithms.

Because the database and the distance math are already address-family-agnostic, the increment is bounded and additive.

## Pros and Cons of the Options

### IPv4-only for the initial release

* Good, because one address family is supported completely and validated consistently end to end.
* Good, because boundary validation is simple and unambiguous, rejecting malformed input at ingestion.
* Good, because the first increment ships without partial-support caveats.
* Good, because the persistence layer (`INET`) and the impossible-travel math are already family-agnostic, so the follow-on is additive.
* Bad, because IPv6-sourced events are rejected until the follow-on increment.

### IPv4 + IPv6 from the outset

* Good, because it covers the full address space of a real dual-stack network immediately.
* Bad, because it spreads IPv6 handling across validation and three enrichers before any of it is exercised, widening the first increment for coverage the demo does not require.
* Bad, because it increases the surface that must be validated and tested before the first release is trustworthy.

### Accept any string, no address validation

* Good, because it imposes no constraint at ingestion.
* Bad, because malformed addresses propagate to the enrichers and fail there, far from where the bad value entered.
* Bad, because it abandons the boundary-validation principle the rest of the pipeline relies on.
* Bad, because the stored data loses the guarantee that `client_ip` is a usable address.

## More Information

The decision is enforced at a single point: the `client_ip` field on the shared login-event base model, whose pattern accepts only well-formed IPv4 addresses (each octet `0`–`255`, no leading-zero forms). Because all services validate inbound events against this shared model, the constraint applies uniformly across the pipeline without per-service enforcement.

When IPv6 support is taken up, this ADR should be superseded or amended rather than silently widened, so the move from one address family to two remains a documented, deliberate step.
