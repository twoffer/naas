# A3 Document Change Manifest
## Exact Updates Required for Existing NAAS Project Documents

**Purpose:** This document lists the specific sections to update in existing project documents to integrate the Policy Expression Language and Hybrid Risk Scoring Model design decisions from A3.

**Context:** The A3 design resolves inconsistencies across NAAS documents regarding the policy schema and risk scoring algorithm. Two previously inconsistent models (weights-only and conditions-only) are unified into a single hybrid model. A new enrichment signal (`days_since_last_login`) is added. The seed policy must be replaced.

---

## 1. SYSTEM_ARCHITECTURE.md

### 1a. Update §4 (Signal Enrichment Service) — currently lines ~109–121

**Replace** the enrichers list with:

```markdown
### 4. Signal Enrichment Service
- **Port:** 8003
- **Role:** Augment normalized events with risk signals. I/O-heavy (external APIs, DB queries).
- **Consumes:** Redis Stream `normalized_events` (consumer group: `enrichment_workers`)
- **Publishes to:** Redis Stream `enriched_events`
- **Enrichers (run in parallel):**
  - **IP Reputation:** Multi-provider with fallback (AbuseIPDB → IPQualityScore → mock). Cached 24h in Redis.
  - **Geolocation:** MaxMind GeoLite2 local DB. IP → city/country/lat/lon. Cached 7d in Redis.
  - **Device Fingerprinting:** User-Agent parsing → browser, OS, device type. Track known devices per user.
  - **Impossible Travel:** Haversine distance between consecutive logins. Flag if required speed > 1800 km/h.
  - **Failed Login Tracking:** Count failed attempts in past 24h from PostgreSQL.
  - **Login Recency:** Days since user's last successful login. `NULL` for first-ever logins. Simple PostgreSQL `MAX(timestamp)` query.
- **Updates:** PostgreSQL `events.enriched_signals` (JSONB)
```

**What changed:** Removed "Time-of-Day Risk" enricher (time is handled as boolean conditions in policy, not as a continuous enrichment signal). Added "Login Recency" enricher.

### 1b. Update §5 (Policy Management Service) — currently lines ~123–129

**Replace with:**

```markdown
### 5. Policy Management Service
- **Port:** 8004
- **Role:** CRUD for YAML-based declarative risk policies. Policy validation (including expression parsing). Policy versioning. Only one active policy at a time.
- **Endpoints:** `GET/POST/PUT/DELETE /policies`, `POST /policies/{id}/activate`
- **Policy format:** YAML with hybrid scoring model — `signal_weights` (continuous pre-normalized signals) + `conditions` (boolean expressions using AND/OR/NOT/IN, comparisons). Decision thresholds and ensemble configuration. See `A3_Policy_Expression_Language_and_Scoring_Model.md` for full schema and validation rules.
- **Expression validation:** All condition expressions are parsed and validated at policy creation time using the safe `ast`-based evaluator. Invalid expressions are rejected with descriptive error messages.
- **Signal weight validation:** `signal_weights` keys must be from the closed `VALID_SIGNAL_WEIGHTS` enum: `ip_reputation_risk`, `normalization_risk`, `failed_login_risk`, `login_recency_risk`.
- **Caching:** Active policy cached in Redis (60s TTL).
- **Shadow mode support:** Policies can be flagged as shadow — evaluated but not enforced (results logged for comparison).
```

### 1c. Update §6 (Risk Evaluator Service) — currently lines ~131–146

**Replace with:**

```markdown
### 6. Risk Evaluator Service
- **Port:** 8005
- **Role:** Calculate risk scores and make access decisions. The "brain."
- **Consumes:** Redis Stream `enriched_events` (consumer group: `evaluator_workers`)
- **Publishes to:** Redis Pub/Sub channel `decisions`
- **Hybrid scoring model:**
  - **Signal weights:** Pre-normalizes continuous enrichment signals to [0.0, 1.0] risk values using hardcoded formulas (`ip_reputation_risk`, `normalization_risk`, `failed_login_risk`, `login_recency_risk`). Multiplies each by its policy-defined weight.
  - **Conditions:** Evaluates boolean expressions against the event context (5 namespaces: `user`, `device`, `signals`, `time`, `event`). Each triggered condition contributes its weight.
  - **Rule-based score:** `clamp(signal_score + condition_score, 0.0, 1.0)`
  - **ML-based:** Random Forest classifier (scikit-learn, joblib serialized). Predicts probability of malicious.
  - **Ensemble:** `final_score = (rule_score × rule_weight) + (ml_score × ml_weight)`. Default: 60/40.
- **Decision thresholds (configurable per policy, escalating severity):**
  - `< 0.3` → ALLOW (implicit — below all thresholds)
  - `≥ 0.3` → STEP_UP_MFA
  - `≥ 0.7` → DENY
- **Expression evaluator:** Python `ast`-based safe evaluator. Whitelist of allowed AST node types. Expressions preprocessed from uppercase (AND/OR/NOT/IN) to lowercase Python syntax. See `A3_Policy_Expression_Language_and_Scoring_Model.md` for full expression language spec.
- **Contributing factors:** Every scoring decision records which signals and conditions contributed, stored in `risk_assessments.contributing_factors` JSONB for dashboard explainability.
- **Shadow mode:** If shadow policy exists, evaluate with both active and shadow, log comparison.
- **Writes to:** PostgreSQL `risk_assessments` table
- **Fail-safe:** On error, returns score 1.0 (DENY).
```

---

## 2. SPEC_0_Project_Scaffold_and_Shared_Foundation.md

### 2a. Replace seed policy — currently lines ~235–264

**Replace** the entire seed data section with:

```sql
-- ============================================================
-- SEED DATA: Default policy
-- ============================================================
INSERT INTO policies (policy_id, name, version, is_active, is_shadow, policy_yaml) VALUES (
    'default-v1',
    'Default Risk Policy',
    '1.0.0',
    TRUE,
    FALSE,
    '
name: Default Risk Policy
version: "1.0.0"
description: Baseline risk evaluation policy for NAAS demo
is_shadow: false

signal_weights:
  ip_reputation_risk: 0.20
  normalization_risk: 0.15
  failed_login_risk: 0.15
  login_recency_risk: 0.10

conditions:
  - name: "impossible-travel"
    expression: "signals.impossible_travel"
    weight: 0.25
  - name: "contractor-after-hours"
    expression: "user.employee_type == ''contractor'' AND time.hour > 18"
    weight: 0.15
  - name: "unknown-device-off-network"
    expression: "NOT device.known_device AND NOT device.on_corporate_network"
    weight: 0.20
  - name: "known-device-off-network"
    expression: "device.known_device AND NOT device.on_corporate_network"
    weight: 0.05
  - name: "weekend-login"
    expression: "time.day_of_week >= 5"
    weight: 0.05
  - name: "foreign-contractor"
    expression: "user.employee_type == ''contractor'' AND signals.country != ''US''"
    weight: 0.15
  - name: "legacy-protocol-usage"
    expression: "event.protocol == ''ldap''"
    weight: 0.05
  - name: "dormant-account-login"
    expression: "signals.days_since_last_login > 90"
    weight: 0.10

thresholds:
  step_up_mfa: 0.3
  deny: 0.7

ensemble:
  rule_weight: 0.6
  ml_weight: 0.4
'
) ON CONFLICT (policy_id) DO NOTHING;
```

**⚠️ SQL string escaping:** Single quotes inside the YAML string literals must be escaped as `''` (doubled) in the SQL INSERT statement. The expression `user.employee_type == 'contractor'` becomes `user.employee_type == ''contractor''` inside the SQL string. This is standard PostgreSQL string escaping.

**What changed:** The old weights-only policy schema (`weights: { ip_reputation: 0.20, device_risk: 0.15, ... }`) is replaced with the hybrid schema (`signal_weights` + `conditions`). Thresholds now use escalating severity keys (`step_up_mfa: 0.3`, `deny: 0.7`) instead of the old `allow`/`deny` pair — ALLOW is implicit below all thresholds. Signal names are updated to the canonical `VALID_SIGNAL_WEIGHTS` enum (`ip_reputation_risk` not `ip_reputation`, etc.). `device_risk` and `time_of_day` removed from signal weights (they are now handled via boolean conditions). `impossible_travel` moved from signal weights to a boolean condition. Eight conditions included to demonstrate the full range of the expression language (multiple namespaces, all comparison operators, logical operators). This expanded seed policy serves as a first-boot showcase on the Risk Engine dashboard tab.

---

## 3. A2_Normalization_Conflict_Resolution_Spec.md

### 3a. Update §6.1 (How the Risk Evaluator Uses Confidence) — currently lines ~357–385

**Replace** section 6.1 with:

```markdown
### 6.1 How the Risk Evaluator Uses Confidence

The Risk Evaluator treats `normalization_confidence` as one of four continuous risk signals in its hybrid scoring model. It is pre-normalized to a risk value and included in the `signal_weights` section of the policy YAML.

**Signal normalization (in Risk Evaluator code):**

```python
"normalization_risk": 1.0 - event.normalization_confidence  # Invert: low confidence = high risk
```

**Policy YAML (signal weight controlled by policy author):**

```yaml
signal_weights:
  ip_reputation_risk: 0.20
  normalization_risk: 0.15
  failed_login_risk: 0.15
  login_recency_risk: 0.10
```

Additionally, `normalization_confidence` is available in the expression evaluation context as `signals.normalization_confidence`, enabling boolean conditions like:

```yaml
conditions:
  - name: "very-low-normalization-confidence"
    expression: "signals.normalization_confidence < 0.5"
    weight: 0.20
```

This creates a feedback loop: when identity sources disagree about a user's attributes, the system treats that user's login attempts with higher scrutiny. This is a realistic enterprise security posture — data inconsistency across identity systems is itself a risk indicator.

See `A3_Policy_Expression_Language_and_Scoring_Model.md` for the complete hybrid scoring model, expression language spec, and signal normalization formulas.
```

### 3b. Update §6.2 (Impact on Default Policy) — currently lines ~387–389

**Replace with:**

```markdown
### 6.2 Impact on Default Policy

The default seed policy in `init.sql` (Spec 0) uses the hybrid policy schema defined in A3. The `normalization_risk` signal weight is included at weight 0.15. See the A3 Document Change Manifest for the exact seed policy YAML.
```

---

## 4. NAAS_System_Decomposition_Guide.md

### 4a. Update Spec 3 description — currently in the Spec 3 section

In the **Enrichment Service** bullet list within Spec 3, **add** after "Time-of-day risk assessment":

```markdown
  - Login recency calculation (days since last successful login for this user)
```

And **remove** "Time-of-day risk assessment" (time is handled via policy conditions, not enrichment).

In the **Risk Evaluator Service** bullet list, **replace** the scoring bullets with:

```markdown
  - Hybrid scoring: signal weights (4 continuous pre-normalized signals) + conditions (boolean expression evaluation)
  - Expression evaluator (Python ast-based, safe evaluation with AST node whitelist)
  - Evaluation context assembly (5 namespaces: user, device, signals, time, event)
  - Signal normalization (ip_reputation_risk, normalization_risk, failed_login_risk, login_recency_risk)
  - ML scoring (Random Forest, joblib model loading)
  - Ensemble calculation (configurable rule/ML blend)
  - Decision thresholds (escalating severity: step_up_mfa/deny, allow implicit below all thresholds)
  - Contributing factors logging (signals + conditions breakdown for dashboard explainability)
  - Shadow mode dual evaluation (if shadow policy exists)
```

### 4b. Update Spec 4 description — currently in the Spec 4 section

In the **Policy Management Service** bullet list, **replace**:

```markdown
  - Expression evaluation engine (AND/OR/NOT, comparisons)
```

**with:**

```markdown
  - Expression validation engine (parse and validate condition expressions at policy creation time using ast-based safe evaluator; reject invalid expressions with descriptive errors)
  - signal_weights key validation against VALID_SIGNAL_WEIGHTS enum (ip_reputation_risk, normalization_risk, failed_login_risk, login_recency_risk)
  - YAML schema validation (Pydantic model: required fields, type checks, threshold ordering, ensemble weight sum)
```

Note: The expression *evaluation* engine runs in the Risk Evaluator (Spec 3). The Policy Management Service (Spec 4) only *validates* expressions at policy creation time. This is a deliberate separation of concerns.

---

## 5. NAAS_v2.0_Vision_Document.md

### 5a. Update the Policy Engine example — in the "Intelligent Risk Assessment" section

**Replace** the example policy YAML block with:

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

### 5b. Update the Scoring description — same section, after the YAML example

**Replace** the scoring bullets with:

```markdown
**Scoring:**
- Hybrid rule-based: Signal weights (continuous, proportional) + Conditions (boolean, binary contribution)
- ML-based: Random Forest ensemble
- Combined: Configurable blend (default: 60% rules, 40% ML)
- Rule-based score clamped to [0.0, 1.0]
```

---

## 6. NAAS_v2.0_Enhancement_Roadmap.md

### 6a. Update Phase 3 description — in the "Phase 3: Policy System v2.0" section

In the **Deliverables** list, **add:**

```markdown
- ✅ Hybrid scoring model (signal weights + boolean conditions)
- ✅ Safe expression evaluator (Python ast-based)
```

In the **Hour Breakdown**, **replace** "Expression evaluator | 5-6 | P0" with:

```markdown
| Expression evaluator (ast-based safe eval + validation) | 5-6 | P0 |
| Signal normalization formulas (4 continuous signals) | 1-2 | P0 |
```

---

## 7. CLAUDE.md

### 7a. Update Event Pipeline description

In the "Event Pipeline" section, no changes needed — the pipeline flow is correct as-is.

### 7b. Add policy model note to Key Conventions (if a Key Conventions section exists or is added)

**Add:**

```markdown
- **Policy Model:** Hybrid scoring — `signal_weights` (4 continuous signals: ip_reputation_risk, normalization_risk, failed_login_risk, login_recency_risk) + `conditions` (boolean expressions evaluated by Python ast-based safe evaluator). Expression language supports AND/OR/NOT/IN operators across 5 namespaces (user, device, signals, time, event). See `A3_Policy_Expression_Language_and_Scoring_Model.md`.
```

---

## 8. NAAS_v2.0_Tech_Stack.md

### 8a. No ADR changes required

The existing ADR-002 (Why YAML Policies, Not Full CEL) remains valid and accurately describes the decision. The hybrid model with `ast`-based evaluation is the implementation of the "YAML + simple expressions" approach referenced in that ADR. No updates needed.

---

## Summary of Changes

| Document | Sections Changed | Nature of Change |
|----------|-----------------|------------------|
| SYSTEM_ARCHITECTURE.md | §4, §5, §6 | Replace enrichment list, policy mgmt description, risk evaluator description |
| SPEC_0 | Seed policy INSERT | Replace weights-only schema with hybrid schema |
| A2 Spec | §6.1, §6.2 | Update risk evaluator integration to reference hybrid model |
| System Decomposition Guide | Spec 3, Spec 4 | Update scope bullets for scoring model and validation |
| Vision Document | Policy example, scoring description | Update YAML example and scoring bullets |
| Enhancement Roadmap | Phase 3 | Add hybrid model deliverables |
| CLAUDE.md | Key conventions | Add policy model note |
| Tech Stack | None | No changes needed |

---

*End of A3 Change Manifest.*
