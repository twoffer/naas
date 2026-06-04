# Architectural Decision Records

This directory captures the significant architectural decisions made on NAAS, in the [MADR (Markdown Any Decision Record)](https://adr.github.io/madr/) format. Each ADR records the context for a decision, the options considered, the decision itself, and the consequences — both positive and negative.

## Why ADRs?

Architectural decisions tend to fade from memory faster than the systems that embody them. Six months after a decision is made, the question "why did we use X instead of Y?" is usually easier to ask than to answer. ADRs solve this by capturing the *reasoning* alongside the decision, so that future maintainers — including the original author — can understand not just *what* was decided but *why*, and on what assumptions the decision rested.

A decision documented in an ADR can be:
- **Revisited** when circumstances change, by reading the original drivers and checking whether they still hold.
- **Defended** to reviewers, who can see the alternatives that were considered.
- **Superseded** by a later ADR that explicitly references it, preserving the decision history.

## Conventions

- Files are named `NNNN-short-slug.md`, where `NNNN` is a zero-padded sequential number.
- Numbers are never reused. If a decision is reversed, a new ADR supersedes the old one; the old one stays in place with its status updated.
- Each ADR is self-contained: it should be readable without reference to other documents in the repository.
- ADRs use one of the following statuses:
  - **proposed** — under discussion, not yet adopted
  - **accepted** — adopted and in effect
  - **deprecated** — no longer recommended but not formally superseded
  - **superseded by ADR-NNNN** — replaced by a later ADR (link the replacement)
  - **rejected** — considered and explicitly declined

## When to Write an ADR

Write an ADR when a decision:
- Is non-trivial to reverse
- Has plausible alternatives that were considered and declined
- Establishes a pattern that other parts of the system will follow
- Resolves a tension between competing concerns (cost vs. capability, simplicity vs. flexibility, etc.)

Do not write an ADR for:
- Routine choices with no real alternative (e.g., "we use Git")
- Implementation details that do not constrain future work
- Decisions whose rationale is fully captured by a relevant industry standard

## Index

| #    | Title                                                                                                                                  | Status   | Date       |
|------|----------------------------------------------------------------------------------------------------------------------------------------|----------|------------|
| 0001 | [Use Python as the Primary Backend Language](0001-why-python.md)                                                                       | accepted | 2026-02-10 |
| 0002 | [Use Redis Streams as the Event Pipeline Message Broker](0002-why-redis-streams.md)                                                    | accepted | 2026-02-10 |
| 0003 | [Use Keycloak as the OIDC Identity Provider for the Demo](0003-why-keycloak.md)                                                        | accepted | 2026-02-10 |
| 0004 | [Use a Transparent LLM Backend for the Persona Simulator](0004-transparent-llm-integration.md)                                         | accepted | 2026-02-10 |
| 0005 | [Use a Hybrid Policy Scoring Model with a Safe `ast`-Based Expression Evaluator](0005-hybrid-policy-scoring-model.md)                  | accepted | 2026-05-01 |
| 0006 | [Resolve Identity Attribute Conflicts via Per-Attribute Authority Weights with Confidence Scoring](0006-per-attribute-normalization-authority.md) | accepted | 2026-05-01 |
| 0007 | [Train the ML Risk Model on Parameterized Distribution Profiles with Labels Independent of the Rule Engine](0007-independent-ml-training-labels.md) | accepted | 2026-05-01 |
| 0008 | [Enrich OIDC and SAML Events via Live OpenLDAP Lookup, Correlated by a Unified-Schema Key](0008-cross-protocol-ldap-enrichment.md)     | accepted | 2026-05-01 |
| 0009 | [Use Hexagonal Architecture for Service Internals](0009-hexagonal-service-architecture.md)                                             | accepted | 2026-05-01 |
| 0010 | [Accept Only IPv4 Addresses for Login-Event `client_ip` in the Initial Release](0010-ipv4-only-client-ip.md)                           | accepted | 2026-06-03 |

## Template

A blank MADR template is available at [https://adr.github.io/madr/](https://adr.github.io/madr/). When adding a new ADR, copy an existing one as a starting point and update the front matter, content, and index.
