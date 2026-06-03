# 1. Use Python as the Primary Backend Language

* Status: accepted
* Date: 2026-02-10
* Deciders: Tony

## Context and Problem Statement

NAAS is a multi-service IAM platform that needs to bridge legacy (LDAP, SAML) and modern (OIDC) identity protocols, perform real-time risk evaluation including ML inference, and process an event pipeline with mostly I/O-bound work (database queries, external API calls for IP reputation and geolocation, Redis stream reads). It must be implementable by a solo developer within a constrained timeline while still demonstrating production-grade engineering practices.

What primary backend language should the services be written in?

## Decision Drivers

* Strength of the IAM library ecosystem (OIDC, SAML, LDAP clients and servers)
* Quality of ML tooling for the Risk Evaluator's Random Forest model
* Async I/O performance, since the event pipeline is I/O-bound rather than CPU-bound
* Solo-developer velocity — the project must ship within a constrained timeline
* "Enterprise credibility" perception, since the project is intended to demonstrate enterprise-grade sensibilities

## Considered Options

* Python 3.12+ (with FastAPI, SQLAlchemy 2.0, Pydantic 2)
* Java 21 (with Spring Boot)
* Go (with Gin or Echo)
* Node.js / TypeScript (with NestJS or Fastify)

## Decision Outcome

Chosen option: **Python 3.12+**, because it offers the strongest combined IAM and ML ecosystem, async I/O performance sufficient for the projected throughput, and 2–3x the development velocity of Java for a solo developer — while modern Python frameworks (FastAPI) and patterns (hexagonal architecture, strict typing) address the "enterprise credibility" concern that motivated considering Java in the first place.

### Positive Consequences

* Faster iteration speed for a solo developer working under a deadline.
* First-class ML integration via scikit-learn for the Risk Evaluator, with no FFI or service boundary required.
* Mature, well-documented IAM libraries (`python-ldap`, `python3-saml`, `authlib`) that align with how production IAM systems at companies like Okta, Auth0, Dropbox, and Instagram are built.
* FastAPI's async model gives I/O throughput competitive with Go for I/O-bound workloads, which is what NAAS actually does.

### Negative Consequences

* Slower raw CPU performance than Java or Go. Mitigated by NAAS being I/O-bound, not CPU-bound.
* Risk of being perceived as "not enterprise enough" by reviewers who associate enterprise IAM with the JVM. Mitigated by:
  * Strict typing throughout (Pydantic models, mypy enforcement)
  * Hexagonal architecture for testability and clear service boundaries
  * Production patterns: structured logging, Prometheus metrics, comprehensive error handling
  * The existence of this very ADR — choosing Python deliberately, with documented tradeoffs, rather than reflexively

## Pros and Cons of the Options

### Python 3.12+

* Good, because it has the strongest IAM library ecosystem of the four options
* Good, because scikit-learn integration removes a service boundary the Risk Evaluator would otherwise need
* Good, because FastAPI + async/await delivers I/O performance comparable to Go for the workload profile NAAS has
* Good, because development velocity is materially higher than Java for a solo developer
* Good, because Pydantic 2 + mypy provide stronger compile-time safety than vanilla dynamic Python
* Bad, because raw CPU performance trails compiled languages
* Bad, because some reviewers carry an implicit "enterprise = JVM" prior

### Java 21 (Spring Boot)

* Good, because it carries unambiguous "enterprise" signal
* Good, because the JVM ecosystem has mature SAML and OIDC libraries (Keycloak itself is Java)
* Bad, because Spring Boot's ceremony cost is high for a solo developer on a deadline
* Bad, because integrating ML requires either a separate Python service or a heavier ONNX/DJL approach
* Bad, because Java's async story (Project Loom is recent; reactive frameworks have learning curves) is more complex than Python's `async def`

### Go

* Good, because raw concurrency performance exceeds the other options
* Good, because static binaries simplify deployment
* Bad, because the IAM library ecosystem is thinner than Python's or Java's
* Bad, because ML integration is awkward — typically requires calling out to Python anyway
* Bad, because struct-tag-based serialization and verbose error handling slow solo development

### Node.js / TypeScript

* Good, because it shares typing with the React 19 frontend, reducing context-switching cost
* Good, because async-first by default
* Bad, because the IAM library ecosystem is the weakest of the four
* Bad, because ML integration is significantly worse than Python's
* Bad, because the runtime's single-threaded model is awkward for CPU-bound risk scoring even if NAAS is mostly I/O-bound

## More Information

This decision is foundational. Subsequent ADRs (FastAPI, SQLAlchemy 2.0 async, Pydantic 2, scikit-learn, Python `ast`-based policy expression evaluation) all assume Python as the host language and would need to be revisited if this decision were ever reversed.
