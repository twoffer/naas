# NAAS v2.0: Enhancement Roadmap
## Prioritized Implementation Plan

**Document Date:** November 24, 2025  
**Timeline:** 8-10 weeks, 8-10 hours/week (64-100 total hours)  
**Status:** Ready for execution

---

## Table of Contents

1. [Roadmap Overview](#roadmap-overview)
2. [Priority Definitions](#priority-definitions)
3. [Phase-by-Phase Breakdown](#phase-by-phase-breakdown)
4. [Detailed Enhancement List](#detailed-enhancement-list)
5. [Risk Mitigation Strategies](#risk-mitigation-strategies)
6. [Week-by-Week Schedule](#week-by-week-schedule)

---

## Roadmap Overview

### Total Scope: 88-112 Hours (Trimmed to Fit Budget)

| Phase | Duration | Hours | Deliverables |
|-------|----------|-------|--------------|
| **Phase 1: Foundation** | Weeks 1-2 | 18-22 | Keycloak, core pipeline, basic OIDC flow |
| **Phase 2: Multi-Protocol** | Weeks 3-5 | 24-30 | LDAP + SAML adapters, normalization layer |
| **Phase 3: Policy System** | Weeks 5-6 | 16-20 | YAML policies, expression evaluation |
| **Phase 4: Visual Wow** | Weeks 6-7 | 12-16 | Dashboard with Protocol Flow Viz |
| **Phase 5: Migration Tools** | Week 7-8 | 10-12 | Shadow mode, feature flags |
| **Phase 6: Polish** | Weeks 8-10 | 10-14 | Documentation, testing, demo prep |
| **TOTAL** | 10 weeks | **90-114** | **MVP + Stretch goals** |

### Budget Management

**Target:** 64-100 hours  
**Estimated:** 90-114 hours  
**Gap:** Need to trim 10-20 hours

**Trimming Strategy:**
- Phase 3 (Policy): Simplify to 12-16 hours (from 16-20)
- Phase 4 (Visual): Use more templates, reduce to 10-14 hours (from 12-16)
- Phase 6 (Polish): Focus on essentials, 8-12 hours (from 10-14)

**Trimmed Total: 76-98 hours** ✅ Fits budget

---

## Priority Definitions

### P0: Must Have (Core MVP)
Critical features that demonstrate the core value proposition. Without these, NAAS doesn't fulfill its purpose.

**Criteria:**
- Essential to the "IAM Modernization Bridge" narrative
- Demonstrates unique expertise (multi-protocol IAM)
- Required for coherent demo

### P1: Should Have (Strong Enhancement)
Important features that significantly strengthen the project but aren't strictly necessary for core functionality.

**Criteria:**
- Demonstrates production-grade thinking
- Adds polish and credibility
- Reasonable effort-to-impact ratio

### P2: Nice to Have (Stretch Goals)
Features that would be impressive but are optional given time constraints.

**Criteria:**
- Lower priority than P0/P1
- Can be documented as "future enhancements"
- Higher effort or lower impact

---

## Phase-by-Phase Breakdown

### Phase 1: Foundation & Keycloak (Weeks 1-2, 18-22 hours)

**Objective:** Get core infrastructure running with Keycloak authentication

**Deliverables:**
- ✅ Docker Compose orchestration (all services)
- ✅ PostgreSQL schema initialization
- ✅ Redis configuration (Streams + Pub/Sub)
- ✅ Keycloak setup and configuration
- ✅ Event ingestion service (REST API)
- ✅ Basic enrichment pipeline (Redis Streams)
- ✅ Simple risk evaluation (rule-based only)
- ✅ Dashboard with Keycloak OAuth flow

**Hour Breakdown:**
| Task | Hours | Priority |
|------|-------|----------|
| Docker Compose + infrastructure | 4-5 | P0 |
| Keycloak setup + realm config | 6-8 | P0 |
| Event ingestion service | 3-4 | P0 |
| Basic enrichment (IP, geo) | 3-4 | P0 |
| Simple risk evaluator | 2-3 | P0 |
| Dashboard auth integration | 3-4 | P0 |
| **SUBTOTAL** | **21-28** | |

**Trimming:** Reduce to 18-22 hours
- Use existing Docker Compose examples (save 1-2 hours)
- Minimal Keycloak customization initially (save 2-3 hours)
- Defer complex enrichment to Phase 2 (save 1-2 hours)

**Critical Milestone:** Keycloak authentication working by end of Week 1

**Validation Checkpoint (End of Week 1):**
- Can I log in via Keycloak? ✅/❌
- If YES: Continue with Keycloak
- If NO (>6 hours spent, still broken): Fall back to Mock IDP

---

### Phase 2: Multi-Protocol IAM (Weeks 3-5, 24-30 hours)

**Objective:** Build the identity normalization layer that makes NAAS unique

**Deliverables:**
- ✅ LDAP adapter + OpenLDAP container
- ✅ SAML adapter (assertion parsing)
- ✅ Identity normalization service
- ✅ Attribute conflict resolution
- ✅ Multi-source enrichment
- ✅ Protocol-specific metadata tracking

**Hour Breakdown:**
| Task | Hours | Priority |
|------|-------|----------|
| OpenLDAP setup + test data | 2-3 | P0 |
| LDAP adapter implementation | 6-8 | P0 |
| SAML adapter implementation | 6-8 | P0 |
| Normalization service core | 4-5 | P0 |
| Attribute mapping engine | 3-4 | P0 |
| Conflict resolution logic | 2-3 | P0 |
| Testing + debugging | 3-4 | P0 |
| **SUBTOTAL** | **26-35** | |

**Trimming:** Reduce to 24-30 hours
- SAML adapter: Basic implementation only (save 2-3 hours)
- Conflict resolution: Simple "last write wins" initially (save 1-2 hours)

**Key Feature: LDAP Adapter Depth (Option 2)**

**Includes:**
- Multiple schema support (Active Directory vs OpenLDAP)
- Attribute variations (cn vs commonName)
- Connection handling
- Error cases documentation

**Why This Phase Is Critical:**
This is your unique differentiator. Most candidates can't build this. Invest the time here.

**Demo Impact:**
By end of this phase, you can show:
- OIDC login (Keycloak)
- LDAP query (OpenLDAP)
- SAML event (simulated)
- All three normalize to same schema

---

### Phase 3: Policy System v2.0 (Weeks 5-6, 16-20 hours)

**Objective:** Build declarative YAML-based policy engine

**Deliverables:**
- ✅ YAML policy schema definition
- ✅ Policy parser and validator
- ✅ Safe expression evaluator (Python ast-based)
- ✅ Hybrid scoring model (signal weights + boolean conditions)
- ✅ Policy versioning
- ✅ Policy caching (Redis)
- ✅ Policy CRUD API

**Hour Breakdown:**

| Task                                                    | Hours     | Priority |
| ------------------------------------------------------- | --------- | -------- |
| YAML schema design                                      | 2-3       | P0       |
| Parser + validator                                      | 4-5       | P0       |
| Expression evaluator (ast-based safe eval + validation) | 5-6       | P0       |
| Signal normalization formulas (4 continuous signals)    | 1-2       | P0       |
| Policy versioning                                       | 2-3       | P1       |
| REST API (CRUD)                                         | 3-4       | P0       |
| Testing                                                 | 2-3       | P0       |
| **SUBTOTAL**                                            | **18-24** |          |

**Trimming:** Reduce to 12-16 hours
- Simpler expression evaluation (use Python eval with safe namespace)
- Defer advanced versioning features
- Basic CRUD only (no complex validation initially)

**Why Not Full CEL:**
CEL learning curve: 25-35 hours (too expensive)
YAML + expressions: 12-16 hours
Still demonstrates policy thinking, faster delivery

**Documentation Note:**
Create `docs/why-not-full-cel.md` explaining trade-off (shows senior decision-making)

---

### Phase 4: Visual Wow Factor (Weeks 6-7, 12-16 hours)

**Objective:** Build impressive Protocol Flow Visualization and polished dashboard

**Deliverables:**
- ✅ Dashboard template (shadcn/ui or Ant Design)
- ✅ 5-tab structure (Identity Sources, Normalization, Risk Engine, Migration Tools, Live Activity)
- ✅ Protocol Flow Visualization (THE killer visual)
- ✅ Live event stream (WebSocket)
- ✅ Basic charts (Recharts)
- ✅ Floating simulator panel

**Hour Breakdown:**
| Task | Hours | Priority |
|------|-------|----------|
| Template setup + customization | 3-4 | P0 |
| 5-tab structure implementation | 2-3 | P0 |
| Protocol Flow Visualization | 5-6 | P0 |
| WebSocket live updates | 2-3 | P0 |
| Simulator panel UI | 2-3 | P0 |
| Charts + analytics views | 2-3 | P1 |
| **SUBTOTAL** | **16-22** | |

**Trimming:** Reduce to 10-14 hours
- Use template dashboards heavily (minimal customization)
- Protocol Flow Viz: Use React Flow library (don't build from scratch)
- Defer some analytics charts to Phase 6

**Protocol Flow Visualization Details:**

**Technology:** React Flow (https://reactflow.dev/)
- Pre-built node/edge components
- Auto-layout algorithms
- Drag-and-drop optional (not needed)
- Good documentation

**Visual Design:**
```
[LDAP] ──┐
         ├──> [Normalize] ──> [Risk Engine] ──> [Decision: ALLOW]
[SAML] ──┤
         │
[OIDC] ──┘
```

**Real-Time Updates:**
- WebSocket receives events
- Update node colors (protocol lights up)
- Animate flow through pipeline
- Show decision outcome

**Estimated Effort:** 5-6 hours with React Flow library

---

### Phase 5: Migration Tools (Weeks 7-8, 10-12 hours)

**Objective:** Add shadow mode and feature flags for safe rollout

**Deliverables:**
- ✅ Shadow mode evaluation (dual policy execution)
- ✅ Policy comparison metrics
- ✅ Feature flag system (Redis-backed)
- ✅ Gradual rollout controls (percentage slider)
- ✅ Dashboard UI for shadow mode

**Hour Breakdown:**
| Task | Hours | Priority |
|------|-------|----------|
| Shadow mode evaluation logic | 3-4 | P1 |
| Policy comparison metrics | 2-3 | P1 |
| Feature flag system | 3-4 | P1 |
| Dashboard UI (shadow mode tab) | 2-3 | P1 |
| **SUBTOTAL** | **10-14** | |

**Trimming:** Keep at 10-12 hours (already lean)

**Why This Phase Matters:**
Demonstrates production operations thinking. Shows you understand deployment risk.

**Demo Value:**
> "Watch: I enable shadow mode for policy v2.4. See? 12% of decisions would change. Let's investigate before rolling out."

This moment impresses hiring managers.

---

### Phase 6: Polish & Documentation (Weeks 8-10, 10-14 hours)

**Objective:** Professional presentation and comprehensive documentation

**Deliverables:**
- ✅ README.md (quick start, architecture diagram)
- ✅ docs/identity-normalization-architecture.md (your masterpiece doc)
- ✅ docs/policy-system-design.md
- ✅ docs/why-not-full-cel.md (trade-off analysis)
- ✅ docs/production-deployment-guide.md
- ✅ Architecture Decision Records (ADRs)
- ✅ Unit tests for critical paths (40-50% coverage)
- ✅ Integration tests (event pipeline)
- ✅ Demo script (written)
- ✅ Video recording (optional)

**Hour Breakdown:**
| Task | Hours | Priority |
|------|-------|----------|
| README + architecture docs | 3-4 | P0 |
| Technical deep-dive docs | 3-4 | P0 |
| ADRs (3-4 decisions) | 2-3 | P1 |
| Unit tests | 3-4 | P1 |
| Integration tests | 2-3 | P1 |
| Demo script writing | 1-2 | P0 |
| **SUBTOTAL** | **14-20** | |

**Trimming:** Reduce to 8-12 hours
- Focus on README and 1-2 technical docs
- 2-3 ADRs (not 4-5)
- Tests for critical paths only (not 50% coverage, maybe 30-40%)

**Critical Documents:**

**1. README.md** (1 hour)
- Hero section with tagline
- Problem statement (identity hell)
- Architecture diagram
- Quick start (docker-compose up)
- Demo instructions

**2. docs/identity-normalization-architecture.md** (2-3 hours)
- Your masterpiece technical document
- Shows LDAP/SAML/OIDC normalization in detail
- Code examples
- Schema mapping tables
- This is what gets you hired

**3. docs/adr/001-why-python.md** (30 min)
- Architectural Decision Record
- Shows senior thinking: "I chose Python because..."

**4. Demo Script** (1 hour)
- Written script (4-5 minute narrative)
- Screenshots/talking points
- Rehearse this 3-4 times

---

## Detailed Enhancement List

### P0: Must Have (Core MVP)

| # | Enhancement | Hours | Phase | Value |
|---|-------------|-------|-------|-------|
| 1 | Keycloak OIDC integration | 6-8 | 1 | Core auth |
| 2 | Event ingestion service | 3-4 | 1 | Foundation |
| 3 | LDAP adapter + normalization | 8-10 | 2 | Differentiator |
| 4 | SAML adapter + normalization | 6-8 | 2 | Differentiator |
| 5 | Identity normalization service | 6-8 | 2 | Differentiator |
| 6 | YAML policy engine | 12-16 | 3 | Core logic |
| 7 | Risk evaluation pipeline | 4-5 | 3 | Core logic |
| 8 | Protocol Flow Visualization | 5-6 | 4 | Demo killer |
| 9 | 5-tab dashboard structure | 4-6 | 4 | Narrative |
| 10 | Persona simulator (3 modes) | 4-5 | 4 | Testing |
| 11 | README + architecture docs | 3-4 | 6 | Portfolio |

**P0 SUBTOTAL: 61-80 hours**

### P1: Should Have (Strong Enhancements)

| # | Enhancement | Hours | Phase | Value |
|---|-------------|-------|-------|-------|
| 12 | Shadow mode evaluation | 3-4 | 5 | Production thinking |
| 13 | Feature flags system | 3-4 | 5 | Safe rollout |
| 14 | Policy versioning | 2-3 | 3 | Governance |
| 15 | OpenTelemetry tracing | 2-3 | 6 | Observability |
| 16 | Prometheus metrics (detailed) | 2-3 | 6 | Monitoring |
| 17 | Integration tests | 2-3 | 6 | Quality |
| 18 | ADRs (3 documents) | 2-3 | 6 | Senior thinking |

**P1 SUBTOTAL: 16-23 hours**

### P2: Nice to Have (Stretch Goals)

| # | Enhancement | Hours | Phase | Value |
|---|-------------|-------|-------|-------|
| 19 | ML model monitoring | 4-6 | - | MLOps depth |
| 20 | Model explainability (SHAP) | 3-4 | - | ML depth |
| 21 | Real-time risk heatmap | 4-5 | - | Visual wow |
| 22 | Policy diff viewer | 3-4 | - | Migration UX |
| 23 | Automated rollback | 3-4 | - | Production ops |
| 24 | Attack simulation mode | 3-4 | - | Demo feature |

**P2 SUBTOTAL: 20-27 hours** (defer most of these)

---

## Risk Mitigation Strategies

### Risk 1: Keycloak Setup Takes Too Long

**Risk:** Keycloak configuration has unexpected complexity (>6 hours)

**Mitigation:**
- **Checkpoint:** End of Week 1, max 6 hours spent
- **Fallback:** Switch to Mock IDP (lose ~2 hours of Keycloak work)
- **Decision Maker:** You (no need to ask permission)

**Likelihood:** Low (Keycloak well-documented, Docker images stable)

---

### Risk 2: Frontend Takes Longer Than Expected

**Risk:** React/frontend work exceeds estimates (frontend comfort: 1/5)

**Mitigation:**
- **Prevention:** Use templates heavily (shadcn/ui, Ant Design)
- **Fallback 1:** Reduce Protocol Flow Viz complexity (simpler visual)
- **Fallback 2:** Defer some analytics charts to "future enhancements"
- **Buffer:** Phase 4 has 2-4 hour buffer already

**Likelihood:** Medium (frontend is weak area)

---

### Risk 3: Phase 2 (Multi-Protocol) Complexity

**Risk:** LDAP/SAML adapters more complex than estimated

**Mitigation:**
- **Leverage:** You're 4/5 on IAM protocols (this is your strength)
- **Strategy:** Start with simplest case, iterate
- **Fallback:** SAML adapter can be more basic (still demonstrates concept)
- **Non-negotiable:** This phase is the differentiator—invest time here

**Likelihood:** Low (this is your expertise area)

---

### Risk 4: Scope Creep

**Risk:** Adding features beyond plan during implementation

**Mitigation:**
- **Discipline:** Strict P0/P1/P2 adherence
- **Defer List:** Maintain "future enhancements" doc for P2 items
- **Weekly Check:** End of each week, review hours spent vs plan
- **Buffer:** 10-hour buffer built into timeline

**Likelihood:** Medium (common issue in projects)

---

## Week-by-Week Schedule

### Week 1: Foundation & Keycloak Validation (8-10 hours)

**Monday-Tuesday (4-5 hours):**
- Docker Compose infrastructure setup
- PostgreSQL + Redis configuration
- Keycloak container + basic realm setup

**Wednesday-Thursday (4-5 hours):**
- Keycloak realm configuration (users, clients, scopes)
- Test authentication flow
- **CHECKPOINT:** Can I log in via Keycloak? ✅/❌

**Deliverable:** Infrastructure running, Keycloak auth working

---

### Week 2: Core Pipeline (8-10 hours)

**Monday-Wednesday (5-6 hours):**
- Event ingestion service (REST API)
- PostgreSQL schema + models
- Redis Streams setup

**Thursday-Friday (3-4 hours):**
- Basic enrichment service (IP, geo)
- Simple risk evaluator (rule-based)
- Dashboard OAuth integration with Keycloak

**Deliverable:** End-to-end OIDC login flow working

---

### Week 3: LDAP Adapter (8-10 hours)

**Monday-Tuesday (4-5 hours):**
- OpenLDAP container setup
- Test data (users, attributes)
- LDAP connection library integration

**Wednesday-Friday (4-5 hours):**
- LDAP adapter implementation
- Attribute extraction
- Schema mapping (LDAP → normalized)

**Deliverable:** LDAP events flow through normalization

---

### Week 4: SAML Adapter (8-10 hours)

**Monday-Tuesday (4-5 hours):**
- SAML assertion parser
- Attribute extraction
- Schema mapping (SAML → normalized)

**Wednesday-Friday (4-5 hours):**
- Identity normalization service core
- Attribute conflict resolution
- Multi-protocol testing (OIDC + LDAP + SAML)

**Deliverable:** All three protocols normalize to same schema

---

### Week 5: Policy Engine Start (8-10 hours)

**Monday-Wednesday (5-6 hours):**
- YAML policy schema design
- Policy parser and validator
- Basic expression evaluator

**Thursday-Friday (3-4 hours):**
- Policy CRUD API
- Policy caching (Redis)
- Simple policy testing

**Deliverable:** Policies can be created and evaluated

---

### Week 6: Policy Engine Complete + Dashboard Start (8-10 hours)

**Monday-Tuesday (3-4 hours):**
- Policy versioning
- Complete expression evaluation
- Integration with risk evaluator

**Wednesday-Friday (5-6 hours):**
- Dashboard template setup (shadcn/ui or Ant Design)
- 5-tab structure implementation
- Basic styling

**Deliverable:** Policy system complete, dashboard structure ready

---

### Week 7: Visual Wow (8-10 hours)

**Monday-Wednesday (6-7 hours):**
- Protocol Flow Visualization (React Flow)
- WebSocket live updates
- Real-time event stream

**Thursday-Friday (2-3 hours):**
- Floating simulator panel UI
- Manual mode implementation

**Deliverable:** Protocol Flow Viz working, impressive demo visual

---

### Week 8: Migration Tools (8-10 hours)

**Monday-Wednesday (5-6 hours):**
- Shadow mode evaluation logic
- Policy comparison metrics
- Feature flag system (Redis-backed)

**Thursday-Friday (3-4 hours):**
- Dashboard UI (shadow mode tab)
- Gradual rollout controls
- Testing

**Deliverable:** Shadow mode working, can demo safe rollout

---

### Week 9: Polish & Testing (8-10 hours)

**Monday-Tuesday (4-5 hours):**
- Unit tests (critical paths)
- Integration tests (event pipeline)
- Bug fixes

**Wednesday-Friday (4-5 hours):**
- README.md
- Architecture documentation
- ADRs (2-3 decisions)

**Deliverable:** Tests passing, documentation complete

---

### Week 10: Final Polish & Demo Prep (8-10 hours)

**Monday-Wednesday (5-6 hours):**
- Technical deep-dive doc (identity normalization)
- Demo script writing
- Rehearse demo (3-4 times)

**Thursday-Friday (3-4 hours):**
- Final bug fixes
- Docker Compose refinement
- Video recording (optional)

**Deliverable:** Portfolio-ready, demo-ready system

---

## Monitoring Progress

### Weekly Check-In Questions

**End of Each Week:**
1. ✅ Did I complete the planned deliverables?
2. ⏱️ How many hours did I actually spend?
3. 📊 Am I on track with the budget (cumulative)?
4. 🚧 Any blockers or risks identified?
5. 📝 Do I need to adjust next week's plan?

### Cumulative Hour Tracking

| Week | Planned | Actual | Cumulative | Budget Remaining |
|------|---------|--------|------------|------------------|
| 1 | 8-10 | ___ | ___ | 90-100 |
| 2 | 8-10 | ___ | ___ | 80-90 |
| 3 | 8-10 | ___ | ___ | 70-80 |
| 4 | 8-10 | ___ | ___ | 60-70 |
| 5 | 8-10 | ___ | ___ | 50-60 |
| 6 | 8-10 | ___ | ___ | 40-50 |
| 7 | 8-10 | ___ | ___ | 30-40 |
| 8 | 8-10 | ___ | ___ | 20-30 |
| 9 | 8-10 | ___ | ___ | 10-20 |
| 10 | 8-10 | ___ | ___ | 0-10 |

**Red Flag:** If cumulative exceeds 50 hours by Week 5, reassess P1/P2 scope

---

## Flexibility & Adaptation

### If Ahead of Schedule

**By 5+ hours in Week 5:**
- Add P1 features earlier (e.g., OpenTelemetry tracing)
- Increase test coverage (40% → 50%)
- Add one P2 feature (e.g., policy diff viewer)

### If Behind Schedule

**By 5+ hours in Week 5:**
- Defer P1 features (shadow mode, feature flags)
- Reduce test coverage (40% → 30%)
- Simplify Protocol Flow Viz (text-based instead of visual)

### Critical Path

**These phases CANNOT be cut:**
- Phase 1: Foundation (need infrastructure)
- Phase 2: Multi-Protocol (core differentiator)
- Phase 3: Policy Engine (core logic)
- Phase 6: Documentation (portfolio presentation)

**These phases CAN be reduced:**
- Phase 4: Visual (can simplify)
- Phase 5: Migration Tools (can defer to "future work")

---

## Success Metrics

### Minimum Viable Portfolio (MVP)

**By Week 10, must have:**
- ✅ Multi-protocol normalization (OIDC + LDAP + SAML)
- ✅ YAML policy engine
- ✅ Risk evaluation pipeline
- ✅ Basic dashboard with live updates
- ✅ Persona simulator
- ✅ README + architecture docs
- ✅ Working Docker Compose setup

**If you have this, NAAS is portfolio-ready.**

### Stretch Goal (Ideal)

**If time permits:**
- ✅ Everything in MVP
- ✅ Protocol Flow Visualization (impressive visual)
- ✅ Shadow mode evaluation
- ✅ Feature flags
- ✅ Comprehensive documentation (ADRs, technical deep-dives)
- ✅ 40-50% test coverage

**If you have this, NAAS is exceptional.**

---

## Final Thoughts

**This roadmap is a guide, not a contract.**

Reality will differ from plan. That's okay. The key is:
1. **Protect Phase 2** (multi-protocol is your differentiator)
2. **Track hours weekly** (catch overruns early)
3. **Be willing to cut P1/P2** (better to finish strong than half-done features)
4. **Document trade-offs** (shows senior thinking)

**Most importantly:**

**Done is better than perfect.** A complete, working NAAS with P0 features beats an incomplete NAAS with P0+P1+P2 features.

Ship it. Then iterate.

---

*"The enemy of good is perfect. The enemy of done is scope creep."*

**— Build NAAS. Demonstrate expertise. Get hired.**
