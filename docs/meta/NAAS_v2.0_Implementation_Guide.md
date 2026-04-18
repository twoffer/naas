# NAAS v2.0: Implementation Guide
## Week-by-Week Execution Plan

**Document Date:** February 10, 2026 (Updated)  
**Timeline:** 10 weeks, 8-10 hours/week  
**Status:** Ready to build

---

## Table of Contents

1. [Getting Started](#getting-started)
2. [Week-by-Week Guide](#week-by-week-guide)
3. [Critical Path Components](#critical-path-components)
4. [Common Pitfalls & Solutions](#common-pitfalls--solutions)
5. [Testing Strategy](#testing-strategy)
6. [Demo Preparation](#demo-preparation)
7. [Portfolio Presentation](#portfolio-presentation)

---

## Getting Started

### Prerequisites

**Required Software:**
- Docker Desktop (or Docker Engine + Docker Compose)
- Python 3.12+ (with pip)
- Node.js 18+ (with npm)
- Git
- Code editor (VS Code recommended)

**Optional But Helpful:**
- PostgreSQL client (pgAdmin, DBeaver, or psql CLI)
- Redis client (RedisInsight or redis-cli)
- Postman or HTTPie (API testing)

**Recommended VS Code Extensions:**
- Python (Microsoft)
- Pylance
- Black Formatter
- ESLint
- Prettier
- Docker
- PostgreSQL

---

### Project Initialization

**Week 0 (Pre-Work, 2-3 hours):**

```bash
# Create project directory
mkdir naas
cd naas

# Initialize Git repository
git init
echo "# NAAS - Normalized Adaptive Access System" > README.md
git add README.md
git commit -m "Initial commit"

# Create project structure
mkdir -p services/{event-ingestion,signal-enrichment,risk-evaluator,policy-management,alert-service,api-gateway,persona-simulator}
mkdir -p infrastructure/{postgres,redis,keycloak,openldap,prometheus,grafana}
mkdir -p dashboard
mkdir -p docs/{adr,guides,api}

# Create .gitignore
cat > .gitignore << EOF
__pycache__/
*.pyc
.env
.env.local
node_modules/
dist/
build/
*.log
.DS_Store
.vscode/
*.db
*.sqlite
EOF

# Create docker-compose.yml skeleton
cat > docker-compose.yml << EOF
version: '3.8'

services:
  # Infrastructure services will go here
  
networks:
  naas-network:
    driver: bridge

volumes:
  postgres-data:
  redis-data:
  keycloak-data:
  ldap-data:
  prometheus-data:
  grafana-data:
EOF
```

---

## Week-by-Week Guide

### Week 1: Foundation & Keycloak (8-10 hours)

**Goal:** Infrastructure running, Keycloak authentication working

**Monday-Tuesday (4-5 hours): Infrastructure Setup**

**Step 1: PostgreSQL & Redis (1.5 hours)**

```yaml
# docker-compose.yml
services:
  postgres:
    image: postgres:17-alpine
    container_name: naas-postgres
    environment:
      POSTGRES_USER: naas
      POSTGRES_PASSWORD: naas_dev_password
      POSTGRES_DB: naas
    ports:
      - "5432:5432"
    volumes:
      - postgres-data:/var/lib/postgresql/data
      - ./infrastructure/postgres/init.sql:/docker-entrypoint-initdb.d/init.sql
    networks:
      - naas-network
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U naas"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7.4-alpine
    container_name: naas-redis
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    networks:
      - naas-network
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
```

**Create Initial Schema:**

```sql
-- infrastructure/postgres/init.sql
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) NOT NULL,
    display_name VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id VARCHAR(255) UNIQUE NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    protocol VARCHAR(10) NOT NULL,
    client_ip INET NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    source VARCHAR(20) DEFAULT 'user',
    is_synthetic BOOLEAN DEFAULT FALSE,
    is_historical BOOLEAN DEFAULT FALSE,
    raw_attributes JSONB,
    normalized_attributes JSONB,
    enriched_signals JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_events_user_id ON events(user_id);
CREATE INDEX idx_events_timestamp ON events(timestamp DESC);
CREATE INDEX idx_events_protocol ON events(protocol);

CREATE TABLE IF NOT EXISTS policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_id VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    version VARCHAR(50) NOT NULL,
    is_active BOOLEAN DEFAULT FALSE,
    policy_yaml TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS risk_assessments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID REFERENCES events(id),
    policy_id UUID REFERENCES policies(id),
    rule_based_score FLOAT,
    ml_based_score FLOAT,
    final_score FLOAT NOT NULL,
    decision VARCHAR(20) NOT NULL,
    contributing_factors JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_risk_assessments_event_id ON risk_assessments(event_id);
CREATE INDEX idx_risk_assessments_decision ON risk_assessments(decision);
```

**Test Infrastructure:**

```bash
# Start services
docker-compose up -d postgres redis

# Verify PostgreSQL
docker exec -it naas-postgres psql -U naas -d naas -c "\dt"

# Verify Redis
docker exec -it naas-redis redis-cli ping
# Should return: PONG
```

**Step 2: Keycloak Setup (2.5 hours)**

```yaml
# docker-compose.yml (add to services)
  keycloak:
    image: quay.io/keycloak/keycloak:26.0
    container_name: naas-keycloak
    environment:
      KEYCLOAK_ADMIN: admin
      KEYCLOAK_ADMIN_PASSWORD: admin
      KC_DB: postgres
      KC_DB_URL: jdbc:postgresql://postgres:5432/keycloak
      KC_DB_USERNAME: naas
      KC_DB_PASSWORD: naas_dev_password
      KC_HOSTNAME: localhost
      KC_HOSTNAME_PORT: 8080
      KC_HTTP_ENABLED: true
      KC_HOSTNAME_STRICT_HTTPS: false
    command: start-dev
    ports:
      - "8080:8080"
    depends_on:
      postgres:
        condition: service_healthy
    networks:
      - naas-network
```

**Start Keycloak:**

```bash
docker-compose up -d keycloak

# Wait for Keycloak to start (takes 1-2 minutes)
# Watch logs: docker-compose logs -f keycloak
```

**Wednesday-Thursday (4-5 hours): Keycloak Configuration**

**Access Keycloak Admin Console:**
- Open browser: http://localhost:8080
- Login: admin / admin

**Create Realm:**
1. Click "Create Realm"
2. Name: `naas-demo`
3. Click "Create"

**Create Client:**
1. Go to Clients → Create Client
2. Client ID: `naas-dashboard`
3. Client Protocol: `openid-connect`
4. Root URL: `http://localhost:3000`
5. Valid Redirect URIs: `http://localhost:3000/*`
6. Web Origins: `http://localhost:3000`
7. Access Type: `public` (no client secret needed for SPA)

**Create Test Users:**
1. Go to Users → Add User
2. Create users: alice, bob, charlie (see test data specification)
3. Set temporary passwords, mark as non-temporary

---

### Week 2: Event Ingestion Service (8-10 hours)

**Goal:** First Python service running, accepting events

**Service Template (use for all services):**

```python
# services/event-ingestion/app/main.py
from fastapi import FastAPI
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    yield
    # Shutdown

app = FastAPI(lifespan=lifespan)

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "event-ingestion"}
```

---

### Week 3-4: Identity Normalization (Critical Path)

See SYSTEM_ARCHITECTURE.md for full specification of the normalization layer.

---

### Week 5: Signal Enrichment

See SYSTEM_ARCHITECTURE.md for enrichment patterns and external API integration.

---

### Week 6: Risk Evaluator + Policy Engine

See SYSTEM_ARCHITECTURE.md for policy evaluation logic and scoring algorithm.

---

### Week 7: Alert Service + API Gateway

See SYSTEM_ARCHITECTURE.md for alert generation rules and routing logic.

---

### Week 8: Dashboard Foundation

**React 19 + TypeScript + Vite 6 Setup:**

```bash
cd dashboard
npm create vite@latest . -- --template react-ts
npm install
npm install @tanstack/react-query reactflow recharts
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss init -p
```

---

### Week 9: Dashboard Features

Implement the 5-tab dashboard structure with React Flow visualization.

---

### Week 10: Polish & Demo

Final integration, testing, and demo preparation.

---

## Testing Strategy

### Unit Tests

**Example Test:**
```python
# tests/unit/test_ldap_adapter.py
import pytest
from services.identity_normalization.adapters.ldap import LDAPAdapter

def test_ldap_normalization():
    adapter = LDAPAdapter()
    raw = {
        'cn': 'Alice Smith',
        'mail': 'alice@corp.com',
        'departmentNumber': 'Engineering',
        'employeeType': 'FTE'
    }
    normalized = adapter.normalize(raw)
    
    assert normalized['display_name'] == 'Alice Smith'
    assert normalized['primary_email'] == 'alice@corp.com'
    assert normalized['department'] == 'Engineering'
    assert normalized['employee_type'] == 'FTE'
    assert normalized['source_protocol'] == 'ldap'
```

### Integration Tests

**Key Flows to Test:**
- End-to-end event pipeline (ingestion → enrichment → evaluation)
- OIDC authentication flow
- Policy evaluation with different signal combinations

**Example:**
```python
# tests/integration/test_event_pipeline.py
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_event_pipeline():
    async with AsyncClient(base_url="http://localhost:8000") as client:
        # 1. Ingest event
        response = await client.post("/events/ingest", json={
            "user_id": "alice@corp.com",
            "client_ip": "203.0.113.42",
            "protocol": "oidc",
            "timestamp": "2025-11-24T10:00:00Z"
        })
        assert response.status_code == 202
        event_id = response.json()["event_id"]
        
        # 2. Wait for processing (poll)
        import asyncio
        await asyncio.sleep(2)
        
        # 3. Check risk assessment was created
        response = await client.get(f"/assessments/{event_id}")
        assert response.status_code == 200
        assessment = response.json()
        assert "final_score" in assessment
        assert "decision" in assessment
```

---

## Demo Preparation

### Demo Script (4-5 Minutes)

**Act 1: The Problem (30 seconds)**
> "I'm going to show you NAAS - a system that solves a specific enterprise problem. You're a Fortune 500 company with 20 years of identity infrastructure. You have LDAP from 1999, SAML from acquisitions, modern OIDC for new apps. How do you secure all of them consistently with one access control policy? You can't. That's what NAAS solves."

**Act 2: Multi-Protocol Normalization (90 seconds)**
> [Open dashboard, Identity Sources tab]  
> "Here are my three identity sources: Keycloak for OIDC, OpenLDAP for legacy directory, and SAML.  
> [Click login]  
> Watch: I'm authenticating via Keycloak OIDC. See the Protocol Flow Visualization? OIDC path lights up — and notice the secondary LDAP lookup. NAAS cross-references my OIDC token against the LDAP directory automatically.  
> [Open Normalization tab]  
> Here's the key: OIDC says my department is 'Product,' but LDAP — synced from HR — says 'Engineering.' See the conflict resolution? LDAP wins because it has higher authority weight for department. Confidence score: 0.72 with a disagreement penalty. That confidence feeds directly into risk assessment.  
> [Open simulator, generate LDAP events]  
> Now let me generate some legacy LDAP activity. These skip enrichment — the directory data is already in the login payload. Same unified output, different path."

**Act 3: Unified Risk Assessment (60 seconds)**
> [Navigate to Risk Engine tab]  
> "Now that identities are normalized, I apply the same risk assessment regardless of protocol. IP reputation, geolocation, impossible travel detection - same evaluation for everyone.  
> [Show policy configuration]  
> Here's my policy in YAML. Declarative rules with expression evaluation. Notice: it doesn't care about protocol. It operates on the normalized schema."

**Act 4: Safe Migration (60 seconds)**
> [Navigate to Migration Tools tab]  
> "But you can't just deploy new policies in production. Watch:  
> [Enable shadow mode]  
> I've enabled shadow mode for policy v2.4. It's evaluating 5% of traffic but not enforcing - just logging what it would have decided.  
> [Show comparison metrics]  
> See? It would change 8% of decisions. Let me investigate why before rolling out to 100%.  
> This is how you migrate safely from legacy to modern without breaking production."

**Act 5: The Code (60 seconds)**
> [Screen share: code editor]  
> "Let me show you the normalization layer code. Here's the LDAP adapter...  
> [Scroll through ldap_adapter.py]  
> Notice: it handles Active Directory vs OpenLDAP schema variations. Here's the attribute mapping logic...  
> [Show normalize() function]  
> This is the hard part - dealing with real-world heterogeneity. Twenty years of IAM experience distilled into production-ready code."

**Wrap-Up (30 seconds)**
> "That's NAAS. It bridges legacy and modern identity systems, normalizes heterogeneous protocols, and enables safe migration through shadow mode evaluation. The kind of system that takes enterprise IAM expertise to build. Questions?"

### Rehearsal Checklist

**Before Demo:**
- [ ] Docker Compose up (all services green)
- [ ] Keycloak has test users (alice, bob, charlie)
- [ ] OpenLDAP has test data
- [ ] Dashboard loads without errors
- [ ] Simulator generates events successfully
- [ ] Protocol Flow Viz animates properly

**During Demo:**
- [ ] Close unnecessary browser tabs/apps
- [ ] Full screen browser (hide bookmarks bar)
- [ ] Turn off notifications
- [ ] Have backup plan if live demo fails (video recording)

**Rehearse 3-4 Times:**
- First rehearsal: Just get through it (identify problems)
- Second rehearsal: Fix problems, smooth transitions
- Third rehearsal: Add polish, check timing
- Fourth rehearsal: Nail it, build confidence

---

## Portfolio Presentation

### GitHub Repository Structure

```
naas/
├── README.md                    # Hero README (problem, solution, architecture)
├── docs/
│   ├── architecture/
│   │   ├── system-overview.md
│   │   ├── identity-normalization.md   # Your masterpiece doc
│   │   └── policy-system.md
│   ├── adr/                    # Architectural Decision Records
│   │   ├── 001-why-python.md
│   │   ├── 002-redis-vs-kafka.md
│   │   └── 003-keycloak-vs-mock.md
│   ├── guides/
│   │   ├── quick-start.md
│   │   ├── development-guide.md
│   │   └── deployment-guide.md
│   └── api/
│       └── openapi.yaml
├── services/                   # Microservices
├── dashboard/                  # React frontend
├── infrastructure/             # Docker configs
├── docker-compose.yml          # One command to run everything
└── .github/
    └── workflows/
        └── ci.yml             # Optional: GitHub Actions
```

### README.md Structure

```markdown
# NAAS - Normalized Adaptive Access System

**Tagline:** Unified access control for heterogeneous identity systems

[Architecture Diagram - Visual showing OIDC/SAML/LDAP → Normalization → Risk Engine]

## The Problem

[3-4 sentences describing enterprise identity crisis]

## The Solution

[3-4 sentences describing how NAAS solves it]

## Key Features

- ✅ Multi-Protocol Support (OIDC, SAML, LDAP)
- ✅ Identity Normalization Layer
- ✅ Declarative Policy Engine (YAML)
- ✅ Shadow Mode Evaluation
- ✅ Real-Time Monitoring Dashboard

## Quick Start

\`\`\`bash
git clone https://github.com/yourusername/naas
cd naas
docker-compose up
# Dashboard: http://localhost:3000
# Login: alice / password123
\`\`\`

## Architecture

[Link to docs/architecture/system-overview.md]

## Demo Video

[Link to YouTube demo video - optional but impressive]

## Documentation

- [Identity Normalization Deep Dive](docs/architecture/identity-normalization.md)
- [Policy System Design](docs/architecture/policy-system.md)
- [Architectural Decisions](docs/adr/)

## Tech Stack

Backend: Python 3.12+ + FastAPI 0.115+ + PostgreSQL 17 + Redis 7.4  
Frontend: React 19 + TypeScript + TanStack Query  
Infrastructure: Docker Compose + Keycloak 26 + OpenLDAP

## Why This Project?

This project demonstrates:
- Deep IAM expertise (multi-protocol normalization)
- Production-grade architecture (shadow mode, observability)
- Legacy integration skills (LDAP, SAML)
- Modern development practices (microservices, event-driven)

Built as a portfolio project showcasing 20+ years of IAM and distributed systems experience.
```

---

## Final Checklist

### Week 10: Before Declaring "Done"

**Functionality:**
- [ ] OIDC login works end-to-end
- [ ] LDAP adapter normalizes attributes correctly
- [ ] SAML adapter normalizes attributes correctly
- [ ] Policy engine evaluates YAML policies
- [ ] Risk scores calculated correctly
- [ ] Dashboard loads without errors
- [ ] Protocol Flow Viz displays real-time events
- [ ] Simulator generates events (all 3 modes)
- [ ] Shadow mode comparison works

**Documentation:**
- [ ] README.md complete with quick start
- [ ] Architecture diagram(s) in docs/
- [ ] Identity normalization deep-dive doc written
- [ ] 2-3 ADRs documenting key decisions
- [ ] docker-compose up works on fresh machine

**Demo Readiness:**
- [ ] Demo script written
- [ ] Rehearsed 3-4 times
- [ ] All test accounts working (alice, bob, charlie)
- [ ] No console errors during demo flow
- [ ] Backup video recording (in case live demo fails)

**Portfolio Presentation:**
- [ ] GitHub repository public
- [ ] Professional README
- [ ] License file (MIT recommended)
- [ ] Clean commit history (squash if messy)
- [ ] Optional: Deploy to cloud for remote demos

---

## Success Definition

**You've succeeded when:**

✅ You can run `docker-compose up` and demonstrate:
- Multi-protocol identity normalization (OIDC + LDAP + SAML)
- Unified risk-based access control
- Shadow mode policy testing
- Protocol Flow Visualization

✅ Someone reviewing your GitHub repo can:
- Understand the problem you're solving
- Appreciate the architectural complexity
- Run the system locally
- Read your technical deep-dive docs

✅ You can confidently discuss:
- Why you chose Python over Java
- Why Redis Streams over Kafka
- How identity normalization works
- Trade-offs you made (documented in ADRs)

**If you have this, NAAS is portfolio-ready.**

---

*"Perfect is the enemy of done. Ship it. Iterate later."*

**— Now go build NAAS. You have the plan. You have the skills. Time to execute.**
