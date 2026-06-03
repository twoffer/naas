# 4. Use a Transparent LLM Backend for the Persona Simulator

* Status: accepted
* Date: 2026-02-10
* Deciders: Tony

## Context and Problem Statement

The Persona Simulator generates synthetic identity events to drive the NAAS pipeline during development and demos. An earlier design exposed three separate user-facing modes — "Simple", "AI", and "MCP" — each backed by a different generation mechanism, with the user choosing which mode to operate in. This conflated two orthogonal concerns: *what* the user wants generated (personas, scenarios, volumes) and *how* the system generates it (templates, LLM, MCP tool-use).

How should the Persona Simulator surface its generation capabilities to the user?

## Decision Drivers

* User experience consistency — demos must succeed regardless of which LLM provider is configured
* Demo reliability — missing API keys or unreachable LLM endpoints must not produce a broken UI
* Cost control — local development should not require a paid LLM API
* A clean integration path for the planned MCP tool-use enhancement, without a UI redesign
* Communicating "AI as production infrastructure" rather than "AI as a checkbox feature"

## Considered Options

* Separate user-facing "Simple", "AI", and "MCP" modes (the previous design)
* A single generation interface backed by a transparent, configurable LLM provider with a fallback chain
* Templates only, no LLM
* LLM only, with the simulator unavailable when no LLM is configured

## Decision Outcome

Chosen option: **A single generation interface with a transparent, configurable LLM backend.** The user interacts with persona and scenario controls; the system internally selects a provider via a fallback chain (Claude API → Ollama → Mock) based on what is available in the environment. The generation interface — including the four UX modes (Manual, AI Suggest, Auto, Historical Bulk) — does not change based on which provider is active; only a small status indicator reflects the current backend.

### Positive Consequences

* Demos behave identically regardless of LLM availability — there is no scenario in which the simulator UI is broken.
* Zero-config development: the Mock provider works without API keys, so a fresh `docker compose up` produces a functioning system.
* Cost control is automatic: Mock during development, Claude only when explicitly demoing AI-driven generation.
* The MCP integration can be added as a new provider implementation without changing the user-facing simulator at all — the enhancement becomes additive rather than transformational.
* The design demonstrates an "AI as infrastructure" sensibility, with provider abstraction and graceful degradation, rather than treating the LLM as a special-cased feature.

### Negative Consequences

* The "AI" branding is less prominent in the UI. Mitigated by the AI Suggest toggle and a small provider indicator in the status bar that surfaces which backend is active.
* A user who wants to compare provider outputs side-by-side must change configuration rather than toggle modes — a deliberate tradeoff against making provider selection a primary UX concern.

## Pros and Cons of the Options

### Separate "Simple", "AI", "MCP" modes (previous design)

* Good, because it makes the LLM presence visible in the UI
* Bad, because users now have to choose a generation mechanism, which is not what they actually care about
* Bad, because mode-specific UI breaks when a backend is unavailable (no API key → broken AI mode)
* Bad, because adding a fourth mode (MCP) would require yet another UI surface
* Bad, because it conflates "what to generate" with "how to generate it"

### Single interface, transparent backend with fallback chain

* Good, because the simulator is operational in every environment
* Good, because adding providers is purely additive
* Good, because it expresses senior-level thinking about AI integration
* Bad, because the LLM is less visible — a perception cost that has to be actively mitigated
* Bad, because the fallback chain has to be tested at each tier, which is more test surface

### Templates only

* Good, because it is the simplest possible implementation
* Good, because behavior is fully deterministic
* Bad, because it forecloses on demonstrating LLM-driven generation, which is a project differentiator
* Bad, because realistic persona variety is hard to achieve from templates alone

### LLM only, simulator unavailable without one

* Good, because LLM use is unambiguous
* Bad, because demos can fail catastrophically if the LLM is unreachable
* Bad, because development requires either an API key or a local Ollama at all times
* Bad, because the project's "graceful degradation" principle is violated at a visible UX surface

## More Information

This decision is paired with the EventSink architecture and the shared simulation tool definitions, both of which are designed so that the Mock, Claude API, and Ollama providers — and a future MCP provider — produce events through the same exit path. The transparent-backend principle is enforced at the provider boundary, not at the call site.

The principle generalizes beyond the Persona Simulator: anywhere NAAS uses an LLM, the system should remain operational when the LLM is unavailable, and the LLM should not be exposed to the user as a separate "mode."
