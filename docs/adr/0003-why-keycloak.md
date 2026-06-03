# 3. Use Keycloak as the OIDC Identity Provider for demo purposes

* Status: accepted
* Date: 2026-02-10
* Deciders: Tony

## Context and Problem Statement

NAAS demonstrates unified access control across heterogeneous identity protocols. The OIDC arm of that demonstration requires a real OIDC provider that NAAS can authenticate against and pull tokens from. The provider must be self-hostable for demonstration purposes, must support enough of the OIDC spec to make the integration realistic, and must not consume the project's modest budget.

What OIDC IdP should NAAS use for demo purposes?

## Decision Drivers

* Realism of the OIDC integration — toy implementations undermine the narrative
* Strength of the "modern protocol vs legacy LDAP" contrast NAAS is trying to draw
* Setup complexity and time cost for a solo developer
* Cost: must be free or fit within a very modest economic allowance
* Risk of the IdP setup blocking other work if it proves harder than expected

## Considered Options

* Keycloak 26+ (self-hosted, open source)
* A bespoke Mock IDP (FastAPI service that simulates OIDC endpoints)
* Auth0 / Okta (managed cloud IdPs, free dev tiers)
* Authentik (self-hosted, open source, lighter than Keycloak)
* Ory Hydra (self-hosted OIDC server, no UI included)

## Decision Outcome

Chosen option: **Keycloak 26+**, because it is the production IdP that real enterprises actually deploy, and using it (rather than simulating it) makes the integration story credible. Though building a mock OIDC provider carries meaningful credibility of its own, integrating with the same IdP that a Fortune 500 deploys supports a more potent narrative.

A fallback to a Mock IDP is permitted if Keycloak setup exceeds a modest time budget, to prevent IdP setup from blocking pipeline implementation.

### Positive Consequences

* Real OIDC flows — authorization code with PKCE, refresh tokens, JWKS rotation, discovery document — exercised against an IdP that behaves like production.
* Stronger "modern vs legacy" contrast in the demo narrative: real Keycloak on the OIDC side, real OpenLDAP on the legacy side.
* Demonstrates integration competence, not implementation competence — which is the more valuable senior-level signal in IAM.
* Keycloak's MCP integration documentation creates a low-friction path for potential future Claude-mediated administration scenarios.

### Negative Consequences

* Setup is more involved than a Mock IDP — realm configuration, client registration, user provisioning. Estimated +2 to +4 hours over a Mock IDP.
* Keycloak's resource footprint (a JVM container) is heavier than a Python mock. Acceptable in the local Docker Compose context.
* Keycloak's UI and admin model are opinionated; some flows that would be trivial in a mock require navigating Keycloak's abstractions.

### Fallback Plan

If Keycloak setup exceeds 6 hours, fall back to a Mock IDP implemented as a FastAPI service exposing the OIDC discovery document, JWKS endpoint, and authorization/token endpoints. The fallback is acceptable but inferior — invoking it should be treated as a schedule-driven concession, not a preference.

## Pros and Cons of the Options

### Keycloak 26+

* Good, because it is what enterprises actually run
* Good, because it provides the strongest "real integration" signal in the application
* Good, because all OIDC features are present without simulation
* Bad, because setup takes longer than a mock
* Bad, because debugging integration issues sometimes requires understanding Keycloak's internals

### Mock IDP

* Good, because setup is fast and fully under the developer's control
* Good, because it can be tailored exactly to NAAS's needs
* Bad, because the narrative is materially weaker — "I integrated with my own mock" is only marginally better than saying "I wrote unit tests"
* Bad, because it tempts the implementer to skip realistic edge cases (token expiry, JWKS rotation, error responses)

### Auth0 / Okta (managed)

* Good, because production-grade and zero-setup
* Good, because they are real products real enterprises deploy
* Bad, because they require external account creation and tie any demonstrations to a third-party SaaS
* Bad, because reviewers cannot run the demonstration locally without provisioning their own tenant
* Bad, because the demonstration cannot run fully offline — a constraint the NAAS project values

### Authentik

* Good, because self-hostable and modern
* Good, because lighter resource footprint than Keycloak
* Bad, because brand recognition is meaningfully lower than Keycloak's
* Bad, because the team (solo developer) has no prior operational experience

### Ory Hydra

* Good, because purpose-built OIDC server with strong spec compliance
* Bad, because it has no built-in user management UI — would require a separate component
* Bad, because the additional integration work negates the simplicity benefit

## More Information

The "fallback if blocked" clause is a deliberate hedge: effective engineering judgment includes knowing when to abandon a preferred approach to avoid schedule risk. Documenting the fallback explicitly, with a numeric trigger, prevents both over-investment in Keycloak setup and reflexive abandonment at the first friction.
