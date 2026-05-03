# 9. Use Hexagonal Architecture for Service Internals

* Status: accepted
* Date: 2026-05-01
* Deciders: Tony

## Context and Problem Statement

NAAS is a collection of Python microservices, each with multiple external dependencies: HTTP/REST APIs, Redis Streams (consumer groups, pub/sub, caching), PostgreSQL (via SQLAlchemy async), LDAP (via `python-ldap`), external HTTP APIs (IP reputation providers, the Claude API), and pluggable LLM providers with a fallback chain. Each service must be independently testable — including without these dependencies being available — and must permit dependency swapping for development, testing, and configurable runtime behavior.

A consistent internal structure is needed across services so that a developer (or an agent) reading any one of them can navigate the codebase without re-orienting to a new pattern. Without an explicit decision, each service's internal structure becomes ad hoc, which makes the codebase harder to reason about as a whole and harder to test consistently.

This ADR is partly retroactive: hexagonal architecture has been mentioned in passing in earlier design documents as a "production pattern" applied to NAAS, but never formally adopted with documented alternatives. This ADR formalizes the choice.

## Decision Drivers

* Testability of business logic in isolation from external dependencies
* Substitutability of external dependencies (e.g., real Claude API vs. mock provider) without conditional logic at call sites
* Consistency across services — the same person or agent should be able to navigate any service after learning the pattern once
* Solo-developer maintainability — the pattern must not impose ceremony cost disproportionate to the project's size
* Compatibility with FastAPI, SQLAlchemy 2.0 async, and the broader Python ecosystem

## Considered Options

* **Hexagonal architecture (ports and adapters)** (chosen): business logic in the core; ports define interfaces the core requires; adapters implement those interfaces against concrete external systems
* **Layered (N-tier) architecture**: presentation → service → data, with each layer depending on the one below
* **Clean architecture**: concentric layers with strict inward-only dependency rule; entities at the center, frameworks at the periphery
* **Anemic domain / transaction script**: data classes plus procedural service functions; no domain layer
* **No prescribed pattern**: each service organized however its author prefers

## Decision Outcome

Chosen option: **Hexagonal architecture (ports and adapters).** Each service is structured around a core that contains the business logic for that service. The core defines ports — abstract interfaces — for the operations it needs from the outside world (e.g., `EventRepository`, `LLMProvider`, `LDAPClient`, `RiskPolicyStore`). Adapters implement those ports against concrete technologies (PostgreSQL for `EventRepository`, Claude API or Ollama or Mock for `LLMProvider`, `python-ldap` for `LDAPClient`).

The core depends only on ports, never on adapters or external libraries. Adapters depend on the core's port definitions but the core knows nothing about which adapter is wired in at runtime. Wiring happens at service startup in a composition root.

### Positive Consequences

* Business logic is testable without spinning up PostgreSQL, Redis, LDAP, or external APIs. Tests substitute in-memory or fake adapters at the port boundary.
* The transparent LLM backend (Mock → Ollama → Claude fallback) is a natural expression of the pattern: each provider is an adapter behind a single `LLMProvider` port. Adding the planned MCP provider becomes a new adapter, not a refactor.
* Per-attribute conflict resolution in the Identity Normalization Service operates on protocol-adapter outputs through a uniform interface; swapping an OIDC adapter implementation does not perturb the conflict-resolution algorithm.
* Agents implementing or modifying a service can rely on a consistent pattern across the codebase.
* The strict typing posture established by Pydantic and mypy reinforces the port boundaries: ports are typed protocols, and violations are caught at static-analysis time.

### Negative Consequences

* The pattern carries some indirection cost. A change that touches both the core's expectations and an adapter's behavior requires modifying two places. Acceptable for the testability and substitutability gains.
* For services with little business logic (the Alert Service is on the order of 100 lines of meaningful code), the ports-and-adapters scaffolding is disproportionate. Pragmatic deviation is permitted: trivial services can collapse the structure as long as the public surface still goes through ports for testability.
* Newcomers to hexagonal need a moment to orient. Mitigated by consistent naming conventions across services and by the fact that, for a developer with IAM and microservices background, the pattern is broadly familiar.

## Pros and Cons of the Options

### Hexagonal architecture

* Good, because business logic is fully isolated from external dependencies for testing
* Good, because dependency substitution (real / mock / alternate provider) is a first-class capability
* Good, because the pattern reinforces the existing strict-typing posture
* Good, because it gives the codebase a consistent navigation model
* Bad, because it introduces ceremony for very small services
* Bad, because it requires a moment of orientation for those new to the pattern

### Layered (N-tier) architecture

* Good, because it is the most familiar pattern in mainstream backend engineering
* Good, because the structure is intuitive at first glance
* Bad, because dependencies flow downward rather than inward, which makes substitution at the data layer awkward
* Bad, because business logic in the service layer typically ends up coupled to the data layer's specific types
* Bad, because testability is weaker — testing the service layer typically requires either the real data layer or a mocking framework rather than a clean substitution at a port boundary

### Clean architecture

* Good, because it shares hexagonal's testability and substitutability benefits
* Good, because the inward-only dependency rule is rigorous
* Bad, because the additional concentric layers (entities, use cases, interface adapters, frameworks) are more structure than NAAS needs at its scale
* Bad, because the discipline-to-payoff ratio is unfavorable for a solo project — most of the additional rigor is amortized over teams larger than one
* Neutral, because it is essentially a stricter variant of hexagonal; the choice between them is largely a matter of how much ceremony is appropriate

### Anemic domain / transaction script

* Good, because it is the lowest-ceremony option — data classes plus functions
* Bad, because business logic ends up scattered across procedural functions with implicit dependencies on global state or framework objects
* Bad, because testability is poor — every test typically requires the real database or extensive mocking
* Bad, because it does not express the substitution requirement (multiple LLM providers, multiple risk-signal sources) cleanly

### No prescribed pattern

* Good, because each service can use whatever fits its specific shape
* Bad, because navigating the codebase requires re-orienting in every service
* Bad, because cross-cutting concerns (logging, metrics, error handling) end up implemented inconsistently
* Bad, because agents implementing or modifying services have no shared structure to rely on

## More Information

In practice, "ports and adapters" in NAAS looks like:

* A `core/` package per service containing the domain logic, port protocols (typed via `typing.Protocol`), and pure data types (Pydantic models for inputs/outputs)
* An `adapters/` package per service containing concrete implementations: `adapters/postgres/`, `adapters/redis/`, `adapters/llm/claude.py`, `adapters/llm/ollama.py`, `adapters/llm/mock.py`, etc.
* A composition root (typically the FastAPI app factory or a service entry-point script) that wires concrete adapters into the core based on configuration

The pragmatic deviation clause is important: the Alert Service does not need a full hexagonal structure to be testable — its small surface can be tested directly. The pattern is a default, not a mandate. Where it adds value (Identity Normalization with multiple adapters, Persona Simulator with provider fallback chain, Risk Evaluator with the rule/ML ensemble and pluggable signal sources), it is applied. Where it would only add ceremony, a flatter structure is acceptable.

This ADR was formalized after several services' designs had already implicitly adopted the pattern. Future ADRs that depend on this one — for example, the LLM provider fallback chain — assume hexagonal as the host pattern and would need adjustment if this decision were ever reversed.
