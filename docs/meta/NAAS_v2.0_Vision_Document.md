# NAAS v2.0: Master Vision Document
## Normalized Adaptive Access System

**Project Vision:** Enterprise-grade IAM modernization platform that provides unified, risk-based access control across heterogeneous identity systems

**Version:** 2.0  
**Document Date:** November 24, 2025  
**Status:** Design Finalized, Ready for Implementation  
**Target Timeline:** 8-10 weeks (64-100 hours total effort)

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [The Problem We Solve](#the-problem-we-solve)
3. [NAAS Solution Architecture](#naas-solution-architecture)
4. [Design Narrative: The IAM Modernization Bridge](#design-narrative-the-iam-modernization-bridge)
5. [Core Capabilities](#core-capabilities)
6. [Key Design Decisions](#key-design-decisions)
7. [Success Criteria](#success-criteria)
8. [Differentiators](#differentiators)

---

## Executive Summary

### What is NAAS?

**NAAS (Normalized Adaptive Access System)** is an IAM modernization platform designed to solve a critical enterprise problem: **how to provide unified, risk-based access control when your identity infrastructure spans multiple generations of protocols.**

Most large enterprises are stuck in "identity hell":
- Legacy LDAP directories from the late 1990s (can't remove them—too many dependencies)
- SAML-based SSO systems from acquisitions (different attribute schemas)
- Modern OIDC providers for new applications (but only 30% of systems support it)
- **No unified way to assess risk across all of them**

NAAS bridges this gap by:
1. **Normalizing** heterogeneous identity attributes from LDAP, SAML, and OIDC into a unified schema
2. **Applying** consistent, adaptive risk-based access control across all protocols
3. **Enabling** safe migration through shadow mode policy testing and gradual rollout
4. **Providing** real-time visibility into cross-protocol authentication flows

### Project Positioning

**Tagline:** "Normalize once. Secure everywhere."

**Target Audience:** Senior/Staff IAM Engineers at enterprises undergoing identity modernization

**Portfolio Purpose:** Demonstrate 20+ years of IAM expertise, production-grade distributed systems thinking, and the ability to bridge legacy and modern enterprise infrastructure

---

## The Problem We Solve

### The Enterprise Identity Crisis

Large organizations face an impossible choice:

**Option A: Rip and Replace**
- Migrate everything to modern OIDC
- Cost: $5-50M, 2-5 years
- Risk: Extremely high (break 100+ integrated systems)
- Reality: Most enterprises can't do this

**Option B: Accept Heterogeneity**
- Keep LDAP, SAML, and OIDC running in parallel
- Cost: Lower upfront
- Risk: No unified security posture
- Reality: This is what actually happens

**The Real Problem:**

When you have multiple identity protocols, you get:
- **Inconsistent security policies** (LDAP users get different treatment than OIDC users)
- **Attribute schema chaos** (LDAP's `cn` vs SAML's `displayName` vs OIDC's `name`)
- **No unified risk assessment** (can't correlate suspicious activity across protocols)
- **Migration paralysis** (can't test new policies without production risk)

### Why Existing Solutions Fall Short

**Single-Protocol IAM Systems (Auth0, Okta, Keycloak):**
- ✅ Great at modern OIDC
- ❌ Don't normalize across protocols
- ❌ Assume you're on a single identity system

**Security Analytics Platforms (Splunk, Elastic):**
- ✅ Can aggregate logs from multiple sources
- ❌ Don't understand IAM protocol semantics
- ❌ No real-time access control

**Legacy IAM (SiteMinder, Access Manager):**
- ✅ Handle multiple protocols
- ❌ 20-year-old architecture
- ❌ No modern risk-based access control

**NAAS fills the gap**: Modern architecture + Multi-protocol normalization + Adaptive risk control

---

## NAAS Solution Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         NAAS Platform                            │
│         Normalized Adaptive Access System v2.0                   │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│   Keycloak   │      │   OpenLDAP   │      │ SAML Provider│
│    (OIDC)    │      │   (Legacy)   │      │   (Legacy)   │
│              │      │              │      │              │
│ Modern IdP   │      │  Legacy Dir  │      │  Acq. SSO    │
└──────────────┘      └──────────────┘      └──────────────┘
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────────────┐
        │      Identity Normalization Layer           │
        │  ┌────────────────────────────────────────┐ │
        │  │ Protocol Adapters:                     │ │
        │  │  • OIDC Adapter   (JWT claims)        │ │
        │  │  • SAML Adapter   (assertions)        │ │
        │  │  • LDAP Adapter   (directory queries) │ │
        │  └────────────────────────────────────────┘ │
        │  ┌────────────────────────────────────────┐ │
        │  │ Attribute Normalization:               │ │
        │  │  • Schema mapping (cn → display_name)  │ │
        │  │  • Conflict resolution (multi-source)  │ │
        │  │  • Enrichment (HR, risk signals)      │ │
        │  └────────────────────────────────────────┘ │
        └─────────────────────────────────────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────────────┐
        │         Risk Evaluation Pipeline            │
        │  ┌────────────────────────────────────────┐ │
        │  │ Signal Enrichment:                     │ │
        │  │  • IP reputation                       │ │
        │  │  • Geolocation                         │ │
        │  │  • Device fingerprinting               │ │
        │  │  • Impossible travel detection         │ │
        │  │  • Failed login tracking               │ │
        │  └────────────────────────────────────────┘ │
        │  ┌────────────────────────────────────────┐ │
        │  │ Policy Engine:                         │ │
        │  │  • YAML-based declarative policies     │ │
        │  │  • Expression evaluation (AND/OR/NOT)  │ │
        │  │  • Shadow mode support                 │ │
        │  │  • Gradual rollout (feature flags)     │ │
        │  └────────────────────────────────────────┘ │
        │  ┌────────────────────────────────────────┐ │
        │  │ Risk Scoring:                          │ │
        │  │  • Rule-based scoring                  │ │
        │  │  • ML ensemble (Random Forest)         │ │
        │  │  • Configurable thresholds             │ │
        │  └────────────────────────────────────────┘ │
        └─────────────────────────────────────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────────────┐
        │          Access Decision Engine             │
        │                                             │
        │  Risk Score → Decision:                     │
        │   • < 0.3  → ALLOW                         │
        │   • 0.3-0.7 → STEP_UP_MFA                  │
        │   • > 0.7  → DENY                          │
        └─────────────────────────────────────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────────────┐
        │    Real-Time Dashboard & Monitoring         │
        │                                             │
        │  • Protocol flow visualization              │
        │  • Live event stream                        │
        │  • Policy management                        │
        │  • Shadow mode comparison                   │
        │  • Analytics & reporting                    │
        └─────────────────────────────────────────────┘
```

### Core Components

**1. Identity Normalization Layer**
- Protocol-specific adapters (OIDC, SAML, LDAP)
- Unified identity schema
- Attribute conflict resolution
- Multi-source enrichment

**2. Risk Evaluation Pipeline**
- Signal enrichment (IP, geo, device, behavioral)
- YAML-based policy engine
- Rule-based + ML ensemble scoring
- Shadow mode evaluation

**3. Access Decision Engine**
- Threshold-based decisions (allow/MFA/deny)
- Real-time evaluation (<500ms)
- Audit logging

**4. Dashboard & Visualization**
- Protocol flow visualization
- Live event monitoring
- Policy management UI
- Shadow mode comparison tools

**5. Testing & Simulation**
- Persona simulator (office worker, road warrior, attacker)
- Manual, auto, and historical bulk generation
- Multi-protocol event generation

---

## Design Narrative: The IAM Modernization Bridge

### The Story NAAS Tells

**Act 1: The Problem** (30 seconds)
> "You're a Fortune 500 company with 20 years of identity infrastructure. You have LDAP from 1999 that you can't remove. SAML from that acquisition in 2015. Modern OIDC for 30% of your apps. How do you secure all of them consistently? You can't. That's the problem NAAS solves."

**Act 2: The Normalization** (60 seconds)
> "NAAS acts as a bridge. Watch: here's a login via Keycloak OIDC. NAAS doesn't just normalize the OIDC token — it cross-references the user against the LDAP directory. OIDC says department is 'Product,' but LDAP — synced from HR — says 'Engineering.' NAAS resolves the conflict using configured authority weights and produces a confidence score. Same unified schema, regardless of source, with full provenance tracking."

**Act 3: The Unified Security** (60 seconds)
> "Now that identities are normalized, we can apply consistent risk assessment. IP reputation, geolocation, impossible travel detection—all evaluated the same way regardless of whether you came from LDAP, SAML, or OIDC. One security policy. Every protocol."

**Act 4: The Safe Migration** (60 seconds)
> "But you can't just deploy new policies in production. Watch this: I've got policy v2.4 running in shadow mode on 5% of traffic. See? It would change 8% of decisions. Let's investigate why before rolling out. This is how you migrate safely from legacy to modern without breaking production."

**Act 5: The Architecture** (90 seconds)
> "Let me show you the normalization layer code. Here's the LDAP adapter handling schema variations—Active Directory vs OpenLDAP. Here's attribute conflict resolution—when LDAP and SAML disagree about department. This is the hard part. This is what 20 years of IAM experience looks like."

**Total Demo:** 4-5 minutes of cohesive storytelling

### Dashboard UX Structure (5-Act Navigation)

The dashboard structure reinforces the narrative:

**Tab 1: Identity Sources**
- Shows Keycloak (OIDC), OpenLDAP (LDAP), SAML status
- Connection health, event counts, last sync
- **Message:** "We support multiple protocols"

**Tab 2: Normalization**
- Attribute mapping tables (raw → normalized)
- Conflict resolution rules
- Success rates, unmapped attributes
- **Message:** "We unify heterogeneous identities"

**Tab 3: Risk Engine**
- Active policy configuration
- Decision distribution (allow/MFA/deny)
- Risk score trends over time
- **Message:** "We assess risk consistently"

**Tab 4: Migration Tools**
- Shadow mode controls
- Policy comparison (active vs shadow)
- Rollout percentage controls
- Feature flag management
- **Message:** "We enable safe migration"

**Tab 5: Live Activity**
- Real-time event stream
- Protocol flow visualization (THE killer visual feature)
- Alert notifications
- **Message:** "We provide visibility"

**Floating Simulator Panel** (accessible from any tab)
- Manual event generation
- Auto-generation (background activity)
- Historical bulk generation
- **Purpose:** Testing and demonstration

---

## Core Capabilities

### 1. Multi-Protocol Identity Support

**Supported Protocols:**
- ✅ **OIDC** (OpenID Connect): Via Keycloak
- ✅ **SAML 2.0**: Simulator-generated events with SAML-convention attributes, processed by production-ready adapter (no live SAML IdP required — see SYSTEM_ARCHITECTURE.md §3)
- ✅ **LDAP v3**: Via OpenLDAP

**Key Features:**
- Protocol-specific adapters handle extraction
- Attribute schema mapping (handle variations)
- Cross-protocol LDAP enrichment (OIDC/SAML events enriched with directory data)
- Conflict resolution (multi-source attributes with per-attribute confidence scoring)
- Provenance tracking (which system provided what)

**Example Normalization:**

```yaml
# LDAP User
raw_attributes:
  cn: "Alice Smith"
  mail: "alice@corp.com"
  department: "eng"
  employeeType: "E"

# SAML User  
raw_attributes:
  displayName: "Bob Jones"
  email: "bob@corp.com"
  dept: "Engineering"
  employeeType: "Employee"

# OIDC User
raw_attributes:
  name: "Charlie Brown"
  email: "charlie@corp.com"
  department: "Engineering"
  employee_type: "FTE"

# All Normalize To:
normalized_identity:
  display_name: "Alice Smith" | "Bob Jones" | "Charlie Brown"
  primary_email: "alice@corp.com" | "bob@corp.com" | "charlie@corp.com"
  department: "Engineering"
  employee_type: "FTE"
  source_protocol: "ldap" | "saml" | "oidc"
```

### 2. Intelligent Risk Assessment

**Signal Enrichment:**
- IP reputation (multi-provider with fallback)
- Geolocation (city, country, coordinates)
- Device fingerprinting (User-Agent parsing)
- Impossible travel detection (Haversine distance)
- Failed login tracking (24-hour window)
- Login recency calculation (days since last successful login for this user)

**Policy Engine:**
- YAML-based declarative policies
- Expression evaluation (AND, OR, NOT, comparisons)
- Configurable signal weights
- Multiple policies with versioning
- Shadow mode evaluation (test without enforcement)

**Example Policy:**

```yaml
policy:
  name: "contractor-evening-restriction"
  version: "2.1.0"
  enabled: true

  # Continuous signal weights (pre-normalized by Risk Evaluator)
  signal_weights:
    ip_reputation_risk: 0.20
    normalization_risk: 0.15
    failed_login_risk: 0.15
    login_recency_risk: 0.10

  # Boolean conditions (expression language)
  conditions:
    - name: "time-restriction"
      expression: "user.employee_type == 'contractor' AND time.hour > 18"
      weight: 0.15

    - name: "vpn-requirement"
      expression: "NOT device.on_corporate_network AND NOT device.vpn_connected"
      weight: 0.20

    - name: "impossible-travel"
      expression: "signals.impossible_travel"
      weight: 0.25

  thresholds:
    step_up_mfa: 0.3
    deny: 0.7
```

**Scoring:**
- Hybrid rule-based: Signal weights (continuous, proportional) + Conditions (boolean, binary contribution)
- ML-based: Random Forest ensemble
- Combined: Configurable blend (default: 60% rules, 40% ML)
- Rule-based score clamped to [0.0, 1.0]

### 3. Safe Migration & Rollout

**Shadow Mode:**
- Evaluate new policy without enforcement
- Compare decisions (active vs shadow)
- Detect divergence rates
- Investigate differences before rollout

**Feature Flags:**
- Gradual rollout (5% → 25% → 50% → 100%)
- User allowlist/blocklist
- Cohort-based targeting
- Automatic rollback on failure

**Policy Versioning:**
- Every change creates new version
- Side-by-side comparison
- Rollback to previous version
- A/B testing support

### 4. Real-Time Visibility

**Protocol Flow Visualization:**
- Visual representation of events flowing through system
- Protocol-specific paths (OIDC=blue, SAML=green, LDAP=orange)
- Normalization step highlighted
- Real-time updates via WebSocket

**Live Event Stream:**
- All login attempts displayed in real-time
- Color-coded by decision (green=allow, yellow=MFA, red=deny)
- Expandable details (raw attributes, normalized attributes, signals, scores)
- Filterable by protocol, source, decision

**Analytics:**
- Time-series charts (event volume, risk score trends)
- Decision distribution (allow/MFA/deny percentages)
- Geographic heatmaps
- User risk profiles

### 5. Testing & Simulation

**Persona Types:**
- **Office Worker**: Regular 9-5 patterns, consistent location
- **Road Warrior**: Frequent travel, multiple locations
- **Attacker**: VPN usage, credential stuffing, impossible travel

**Generation Modes:**

**Manual:**
- Select protocol, persona, count
- Generate on-demand
- Immediate feedback

**Auto (Background):**
- Configurable rate (5-30 events/min)
- Protocol mix percentages
- Runs continuously in background
- Creates "live system" feel

**Historical Bulk:**
- Generate 100-5000 backdated events
- Populate analytics dashboards
- No alert generation (is_historical=true)

---

## Key Design Decisions

### Decision 1: Keycloak (Not Mock IDP)

**Rationale:**
- Shows integration with real enterprise systems (not toy implementation)
- Keycloak widely used in enterprises
- Strengthens "modern vs legacy" contrast
- Production-ready OIDC flow

**Time Investment:** 10-12 hours (vs 8-10 for mock)
**Value:** Higher credibility, realistic integration demonstration

### Decision 2: YAML Policies (Not Full CEL)

**Rationale:**
- CEL learning curve: 25-35 hours (too expensive for timeline)
- YAML + simple expressions: 16-20 hours
- Still declarative, still impressive
- Can document "production would use CEL" in design rationale

**Trade-off Accepted:** Slightly less sophisticated, but demonstrates policy thinking without excessive complexity

### Decision 3: Multi-Protocol Support (OIDC + SAML + LDAP)

**Rationale:**
- Core differentiator—leverages 20 years of IAM expertise
- Most candidates can't do this
- Directly addresses enterprise pain point
- Showcases protocol knowledge and integration skills

**Implementation Strategy:**
- OIDC: Real user login via Keycloak
- SAML/LDAP: Simulator-generated (architectural complexity identical)
- All protocols flow through same normalization layer

### Decision 4: Python (Not Java/Spring)

**Rationale:**
- Faster development (Python for IAM integration is standard)
- Better ML ecosystem (scikit-learn)
- Async/await performance (FastAPI)
- Modern IAM companies use Python (Okta, Auth0, Dropbox)

**Mitigation:** Elevate Python to enterprise-grade:
- Strict typing (Pydantic, mypy)
- Hexagonal architecture
- 12-factor configuration
- Comprehensive API documentation

### Decision 5: React + Templates (Not Custom Frontend)

**Rationale:**
- Frontend comfort level: 1/5
- Minimize custom frontend work (use shadcn/ui or Ant Design)
- Focus effort on backend/IAM complexity
- Template-driven development: 12-16 hours vs 25+ custom

**One Killer Visual:** Protocol Flow Visualization (highest impact per hour invested)

### Decision 6: Floating Simulator Panel (Not Separate Tab)

**Rationale:**
- Preserves 5-tab narrative structure
- Always accessible (any tab)
- Can run auto-mode in background while demoing
- Clear separation: production UI vs testing tools

---

## Success Criteria

### Functional Requirements

**Must Have (P0):**
- ✅ Multi-protocol support (OIDC, SAML, LDAP)
- ✅ Identity normalization layer
- ✅ YAML-based policy engine
- ✅ Risk scoring (rule-based + ML ensemble)
- ✅ Access decisions (allow/MFA/deny)
- ✅ Shadow mode evaluation
- ✅ Real-time dashboard with Protocol Flow Visualization
- ✅ Persona simulator (manual + auto + historical)

**Should Have (P1):**
- ✅ Feature flags for gradual rollout
- ✅ Distributed tracing (OpenTelemetry)
- ✅ Comprehensive metrics (Prometheus)
- ✅ Alert notifications
- ✅ Policy versioning

**Nice to Have (P2):**
- ⚪ Advanced ML monitoring (model drift detection)
- ⚪ Automated model retraining
- ⚪ Real-time risk heatmap
- ⚪ Policy diff viewer

### Performance Requirements

- Event ingestion: < 10ms
- Signal enrichment: < 200ms
- Risk evaluation: < 50ms
- End-to-end pipeline: < 500ms
- WebSocket latency: < 100ms
- Dashboard initial load: < 2 seconds

### Quality Requirements

- 40-50% code coverage (unit tests for critical paths)
- Integration tests for event pipeline
- Docker Compose setup works on first try
- Structured logging with correlation IDs
- Prometheus metrics for all services
- Comprehensive documentation (README, architecture docs, ADRs)

### Portfolio Impact Requirements

**The system must demonstrate:**
- ✅ Deep IAM expertise (multi-protocol normalization)
- ✅ Senior engineering thinking (shadow mode, feature flags, observability)
- ✅ Production-ready patterns (circuit breakers, graceful degradation)
- ✅ Legacy integration skills (LDAP adapter, schema variations)
- ✅ Modern architecture (microservices, event-driven, async)

---

## Differentiators

### What Makes NAAS Unique

**1. Multi-Protocol IAM Integration**
- Most portfolio projects: Single protocol (usually OIDC)
- NAAS: OIDC + SAML + LDAP with normalization
- **Why it matters:** This is the actual enterprise problem

**2. Identity Normalization as First-Class Feature**
- Most projects: Assume uniform identity schema
- NAAS: Explicit handling of schema variations, conflict resolution
- **Why it matters:** Shows real-world systems thinking

**3. Safe Migration Tools (Shadow Mode)**
- Most projects: Deploy and hope
- NAAS: Test policies without risk, gradual rollout
- **Why it matters:** Demonstrates production operations maturity

**4. Legacy System Integration**
- Most projects: Greenfield only
- NAAS: Bridges legacy (LDAP/SAML) and modern (OIDC)
- **Why it matters:** Leverages your 20 years of experience uniquely

**5. Cohesive Narrative**
- Most projects: "Here are my features"
- NAAS: "Here's the enterprise problem and my solution"
- **Why it matters:** Shows you understand business context, not just code

### What NAAS Proves About You

**To hiring managers, NAAS demonstrates:**

✅ **Deep IAM Expertise**: Multi-protocol support, normalization, attribute mapping  
✅ **Senior Engineering Judgment**: Shadow mode, feature flags, graceful degradation  
✅ **Production Thinking**: Observability, metrics, alert design  
✅ **Legacy Integration Skills**: LDAP adapters, schema handling  
✅ **Modern Architecture**: Microservices, event-driven, async patterns  
✅ **Independent Execution**: End-to-end system from vision to implementation  
✅ **Communication Skills**: Clear documentation, cohesive narrative  

**The unspoken message:** "I can architect and build production-grade IAM systems that bridge legacy and modern infrastructure—the exact problem your company has."

---

## Constraints & Timeline

**Available Resources:**
- Timeline: 8-10 weeks
- Effort: 8-10 hours per week
- Total: 64-100 hours

**Hard Constraints:**
- Deployment cost: ≤ $25/month
- Tech comfort levels guide prioritization
- Must showcase IAM expertise above all else

**Scope Management:**
- Clear P0/P1/P2 prioritization
- Built-in timeline buffers
- Fallback options for risky components
- Early validation of critical dependencies (Keycloak in Week 1)

---

## Next Steps

This vision document establishes **what** NAAS is and **why** it matters.

Companion documents define **how** to build it:

1. **Enhancement Roadmap** - Prioritized features with hour estimates
2. **Tech Stack Specification** - Complete technology choices with rationale
3. **Implementation Guide** - Week-by-week execution plan

**Time to build.**

---

*"Normalize once. Secure everywhere."*

**— NAAS: The bridge between your identity past and your identity future**
