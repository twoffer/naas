# 6. Resolve Identity Attribute Conflicts via Per-Attribute Authority Weights with Confidence Scoring

* Status: accepted
* Date: 2026-05-01
* Deciders: Tony

## Context and Problem Statement

The Identity Normalization Service maps attributes from heterogeneous identity protocols (OIDC, SAML, LDAP) into a unified schema. When attribute data for the same user is available from more than one source — for example, an OIDC token claim plus an LDAP directory lookup — the sources may disagree. OIDC may report `department: "Product"`; LDAP, synced nightly from HR, may report `department: "Engineering"`.

A conflict-resolution algorithm is needed that produces:

1. A single resolved value for each attribute
2. A per-attribute confidence score reflecting how trustworthy that resolution is
3. An overall identity-level confidence score consumable by the Risk Evaluator

The "right" winner is not the same for every attribute. LDAP, sourced from HR, is typically authoritative for department and employment classification. OIDC, sourced from the SSO provider, is typically more current for email after a recent migration. SAML attributes from a legacy acquisition system may be stale across the board. A scheme that picks one global winner across all attributes will be wrong about half the time.

## Decision Drivers

* Resolution decisions must reflect real organizational data ownership, which varies by attribute
* Confidence must be quantifiable so that low-confidence normalization can drive higher risk scores rather than silently producing bad data
* The algorithm must be deterministic — the same inputs always produce the same resolved values and confidence
* Configuration must be human-readable and auditable
* The single-source case (one protocol, no conflicts possible) is the common case and must be fast
* List-valued attributes (groups) need different semantics than scalar attributes

## Considered Options

* **Per-attribute authority configuration with priority order and weights** (chosen): each attribute names a priority list of sources and a weight per source; conflicts resolve to the highest-priority source's value, confidence reflects agreement and authority weight
* **Global priority list across all attributes**: one ordered list of sources applied uniformly to every attribute (e.g., LDAP > OIDC > SAML for everything)
* **Most-recent-wins**: temporal ordering — whichever source observed the attribute most recently wins
* **First-source-wins**: lock in the first observed value and never update
* **Always-merge**: keep all observed values per attribute; defer resolution to the consumer
* **Manual resolution**: surface conflicts to an operator for human decision

## Decision Outcome

Chosen option: **Per-attribute authority configuration with priority order and weights.** A YAML configuration file (`config/normalization.yaml`) declares, for each attribute in the unified schema, an ordered priority list of sources and a numeric weight per source. The conflict-resolution algorithm operates per-attribute:

* If only one source has a value, use it; confidence is that source's weight.
* If multiple sources agree (after value normalization), use the agreed value; confidence is the maximum of the contributing source weights, optionally bonused for agreement.
* If multiple sources disagree, the highest-priority source's value wins; confidence is the winning source's weight, with a penalty applied for the disagreement.
* For list-valued attributes (groups), a configurable merge strategy applies — `union` by default — and confidence reflects the average authority of contributing sources.

Per-attribute confidences are aggregated (importance-weighted average) into an overall `normalization_confidence` score on the `NormalizedAttributes` output. The Risk Evaluator consumes this via the derived signal `normalization_risk = 1.0 - normalization_confidence`, so low-confidence normalization automatically raises the event's risk score.

### Positive Consequences

* Each attribute gets the resolution policy that fits its real-world data ownership.
* Confidence is exposed as a first-class signal feeding the Risk Engine, so normalization quality is observable and risk-relevant rather than silently absorbed.
* Configuration is human-readable, version-controllable, and includes a free-text `rationale` field per attribute that documents *why* the priority order is what it is — directly useful for the Normalization dashboard tab and for onboarding new operators.
* Per-attribute provenance (which source won, what the conflicting values were, what penalty applied) is captured in `resolution_details` and surfaced in the dashboard, making the normalization layer auditable rather than opaque.
* The single-source common case is a simple lookup — no algorithmic overhead.

### Negative Consequences

* Configuration complexity is higher than a global-priority approach. Mitigated by sane `defaults` that apply to any attribute without explicit configuration.
* Operators have to understand and maintain the authority configuration. Mitigated by the `rationale` field encouraging self-documentation.
* The algorithm has multiple resolution variants (unanimous, priority, single-source, list-merge), each of which must be tested. Acceptable cost for correctness.

## Pros and Cons of the Options

### Per-attribute authority with priority and weights

* Good, because the resolution policy matches the underlying data-ownership reality
* Good, because confidence is quantified and auditable
* Good, because configuration is readable and includes rationale
* Bad, because it requires more configuration than the global-priority approach

### Global priority list across all attributes

* Good, because configuration is minimal — one ordered list
* Bad, because it gets the wrong answer whenever the authoritative source for an attribute is not the globally-highest-priority source
* Bad, because it forces the operator to choose between, say, "LDAP wins everything" (wrong for email) or "OIDC wins everything" (wrong for department)

### Most-recent-wins

* Good, because it is fully deterministic and trivially simple
* Bad, because a stale source that happens to push an update most recently wins, regardless of correctness
* Bad, because it doesn't model trust — only timing
* Bad, because clock skew across systems makes "most recent" itself unreliable

### First-source-wins

* Good, because it is the simplest possible scheme
* Bad, because user attributes change over time and locking in the first observation is wrong by construction
* Bad, because it cannot accommodate updates from authoritative sources

### Always-merge (no resolution)

* Good, because no information is discarded
* Bad, because the consumer (Risk Evaluator, dashboard) now has to reason about conflicts itself, duplicating logic
* Bad, because the unified schema's purpose is to produce a single canonical view; deferring resolution undermines that purpose

### Manual resolution

* Good, because a human can apply context the algorithm cannot
* Bad, because it doesn't scale beyond a handful of conflicts per day
* Bad, because real-time risk evaluation cannot block on human input
* Bad, because it inverts the value proposition of automated normalization

## More Information

The configuration schema includes a `defaults` section with source weights applied to any attribute not explicitly listed. This means the system handles unexpected attributes gracefully without requiring exhaustive enumeration up front.

Value-normalization failures (e.g., an `employeeType` value that doesn't map to any of `FTE`, `contractor`, `vendor`) apply a fixed confidence penalty and emit a structured warning log. Unrecognized values are stored as-is rather than discarded, so the underlying data is not lost — but the lowered confidence reflects that the value was not understood.

The configuration is loaded once at service startup. Hot-reload is intentionally not supported in the current scope; configuration changes require a service restart. Production deployments would address this with a configuration management system, but the demo's restart cost is small enough to defer the work.

The `groups` attribute uses `union` as the default merge strategy because the natural semantics of group membership across systems is additive — a user with a group in LDAP and a different group in OIDC has both groups. `intersection` and `priority` strategies are configurable for cases where additive semantics are wrong.
