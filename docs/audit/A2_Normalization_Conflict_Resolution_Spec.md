# Identity Normalization: Conflict Resolution & Confidence Scoring
## Specification for Spec 2 — Identity Normalization Service

**Purpose:** Define the conflict resolution algorithm, attribute authority configuration, and confidence scoring model for the NAAS Identity Normalization Service.

**Audience:** Claude Code agents implementing Spec 2, and the technical-architect agent producing the Spec 2 implementation plan.

---

## 1. Overview

The Identity Normalization Service receives login events tagged with one of three protocols (OIDC, SAML, LDAP). Each protocol adapter extracts raw attributes from the protocol-specific payload. The normalization engine then:

1. **Maps** protocol-specific attribute names to the unified schema
2. **Normalizes** attribute values (e.g., `"eng"` → `"Engineering"`, `"E"` → `"FTE"`)
3. **Resolves conflicts** when multiple sources provide different values for the same attribute
4. **Calculates confidence** based on source agreement and authority weights
5. **Produces** a `NormalizedAttributes` object with the resolved values and an overall `normalization_confidence` score

The confidence score feeds downstream into the Risk Evaluator as a normalization-quality signal: lower confidence (sources disagree) contributes to higher risk scores.

---

## 2. Attribute Mapping: Protocol → Unified Schema

Each protocol adapter extracts raw attributes and maps them to the unified schema fields. This mapping is deterministic — no conflict resolution needed at this stage.

### 2.1 Mapping Table

| Unified Field   | OIDC Claim      | SAML Assertion Attr | LDAP Attribute     | Type                                     |
| --------------- | --------------- | ------------------- | ------------------ | ---------------------------------------- |
| `display_name`  | `name`          | `displayName`       | `cn`               | `str`                                    |
| `primary_email` | `email`         | `email`             | `mail`             | `str`                                    |
| `department`    | `department`    | `dept`              | `departmentNumber` | `str` (normalized)                       |
| `employee_type` | `employee_type` | `employeeType`      | `employeeType`     | `Literal["FTE", "contractor", "vendor"]` |
| `groups`        | `groups` (list) | `groups` (list)     | `memberOf` (list)  | `list[str]` (merge strategy: union)      |

### 2.2 Value Normalization Rules

Before conflict resolution, raw attribute values are normalized to canonical forms.

**Department Normalization:**

A lookup table maps common abbreviations and variations to canonical department names:

```python
DEPARTMENT_CANONICAL = {
    # Engineering variations
    "eng": "Engineering",
    "engineering": "Engineering",
    "software engineering": "Engineering",
    "r&d": "Engineering",
    "product development": "Engineering",
    # Finance variations
    "fin": "Finance",
    "finance": "Finance",
    "accounting": "Finance",
    # HR variations
    "hr": "Human Resources",
    "human resources": "Human Resources",
    "people ops": "Human Resources",
    # IT variations
    "it": "Information Technology",
    "information technology": "Information Technology",
    "infra": "Information Technology",
    # Sales variations
    "sales": "Sales",
    "revenue": "Sales",
    # Marketing variations
    "mktg": "Marketing",
    "marketing": "Marketing",
}
```

Normalization is case-insensitive. If a value doesn't match any lookup entry, it is stored as-is (title-cased) with a reduced confidence penalty (see §4.3).

**Employee Type Normalization:**

```python
EMPLOYEE_TYPE_CANONICAL = {
    # FTE variations
    "fte": "FTE",
    "e": "FTE",
    "employee": "FTE",
    "full-time": "FTE",
    "full time": "FTE",
    "regular": "FTE",
    # Contractor variations
    "contractor": "contractor",
    "c": "contractor",
    "contract": "contractor",
    "contingent": "contractor",
    "temp": "contractor",
    # Vendor variations
    "vendor": "vendor",
    "v": "vendor",
    "external": "vendor",
    "partner": "vendor",
    "third-party": "vendor",
}
```

Normalization is case-insensitive. Unrecognized values log a warning and default to `None` (unmapped), with a confidence penalty.

---

## 3. Attribute Authority Configuration

### 3.1 Configuration Schema

Attribute authority is defined in a YAML configuration file loaded by the normalization service at startup and cached. Each attribute specifies which sources are authoritative and with what weight.

```yaml
# config/normalization.yaml

# Default authority weights applied when an attribute has no explicit config
defaults:
  source_weights:
    ldap: 0.7
    saml: 0.6
    oidc: 0.8

# Per-attribute authority overrides
attributes:
  display_name:
    priority: [ldap, saml, oidc]
    weights:
      ldap: 0.90
      saml: 0.70
      oidc: 0.60
    rationale: "LDAP synced from HR system (Workday); most authoritative for legal name"

  primary_email:
    priority: [oidc, saml, ldap]
    weights:
      oidc: 0.95
      saml: 0.75
      ldap: 0.65
    rationale: "OIDC has most current email from recent SSO migration"

  department:
    priority: [ldap, oidc, saml]
    weights:
      ldap: 0.90
      oidc: 0.70
      saml: 0.50
    rationale: "LDAP synced nightly from HR; OIDC updated on login; SAML from acquisition may be stale"

  employee_type:
    priority: [ldap, saml, oidc]
    weights:
      ldap: 0.95
      saml: 0.80
      oidc: 0.60
    rationale: "HR system (LDAP) is authoritative for employment classification"

  groups:
    merge_strategy: union
    rationale: "Groups from all sources are valid; user may have roles in each system"
```

### 3.2 Configuration Semantics

- **`priority`**: Ordered list of sources. When sources disagree, the highest-priority source with a value wins.
- **`weights`**: Float 0.0–1.0 per source. Represents trust in that source's data quality for this attribute. Used in confidence calculation.
- **`merge_strategy`** (list attributes only): `union` (combine all values), `intersection` (only values present in all sources), or `priority` (use highest-priority source's list). Default: `union`.
- **`rationale`**: Human-readable explanation. Displayed in the Normalization dashboard tab and included in documentation. Not used by the algorithm.
- **`defaults`**: Applied to any attribute not explicitly listed. Ensures the system handles unexpected attributes gracefully.

### 3.3 Configuration Loading

The configuration file is loaded once at service startup. It is NOT hot-reloaded — a service restart is required to pick up changes. This is acceptable for a demo project; production would use a config management system with hot-reload.

The configuration is validated at startup using a Pydantic model. Invalid configuration prevents service startup with a clear error message.

---

## 4. Conflict Resolution Algorithm

### 4.1 Single-Source Events (No Conflict Possible)

Most events arrive from a single protocol. In this case, there is no conflict to resolve. The normalization process is:

1. Extract raw attributes using the protocol adapter
2. Map to unified schema using the mapping table (§2.1)
3. Apply value normalization (§2.2)
4. Set confidence = source weight for the event's protocol (from §3.1 config)
5. Store the protocol as `source_protocol`

This is the common case and should be fast (<10ms).

### 4.2 Multi-Source Conflict Resolution

Multi-source conflicts occur when the normalization service has access to attribute data from more than one protocol for the same user. This happens when:

- The event's raw_attributes contain cross-referenced data (e.g., an OIDC login event that also carries LDAP-sourced claims via Keycloak's user federation)
- The service queries a secondary source to enrich the primary event's data (e.g., OIDC event triggers an LDAP lookup for additional attributes)
- Historical data from a different protocol source exists for this user in the database

**Resolution Algorithm (per attribute):**

```
function resolve_attribute(attribute_name, source_values, authority_config):
    """
    source_values: dict of {protocol: raw_value} — e.g., {"oidc": "alice@new.com", "ldap": "alice@old.com"}
    authority_config: the per-attribute config from §3.1
    returns: (resolved_value, confidence, resolution_metadata)
    """

    # Step 1: Normalize all values
    normalized = {}
    for protocol, raw_value in source_values.items():
        normalized[protocol] = apply_value_normalization(attribute_name, raw_value)

    # Step 2: Check for agreement
    unique_values = set(normalized.values()) - {None}

    if len(unique_values) == 0:
        # No source has a value for this attribute
        return (None, 0.0, {"resolution": "no_data"})

    if len(unique_values) == 1:
        # All sources agree (after normalization)
        agreed_value = unique_values.pop()
        max_weight = max(
            authority_config.weights[p]
            for p in normalized
            if normalized[p] == agreed_value
        )
        return (agreed_value, max_weight, {"resolution": "unanimous", "sources": list(normalized.keys())})

    # Step 3: Sources disagree — use priority to resolve
    for protocol in authority_config.priority:
        if protocol in normalized and normalized[protocol] is not None:
            winner_value = normalized[protocol]
            winner_weight = authority_config.weights[protocol]
            # Apply disagreement penalty
            confidence = winner_weight * 0.8
            return (
                winner_value,
                confidence,
                {
                    "resolution": "priority",
                    "winner_source": protocol,
                    "conflicting_values": {p: v for p, v in normalized.items() if v != winner_value},
                    "penalty_applied": True
                }
            )

    # Step 4: Fallback — no priority source has a value (shouldn't happen with correct config)
    first_available = next((p for p in normalized if normalized[p] is not None), None)
    if first_available:
        return (
            normalized[first_available],
            authority_config.weights.get(first_available, 0.5) * 0.5,
            {"resolution": "fallback", "source": first_available}
        )

    return (None, 0.0, {"resolution": "no_data"})
```

### 4.3 Groups Merge Strategy

Groups (list-type attributes) use a different resolution approach:

```
function resolve_groups(source_values, authority_config):
    """
    source_values: dict of {protocol: list[str]}
    returns: (merged_groups, confidence, resolution_metadata)
    """
    strategy = authority_config.get("merge_strategy", "union")

    all_groups = {}  # group_name -> set of sources that have it
    for protocol, groups in source_values.items():
        for group in (groups or []):
            all_groups.setdefault(group, set()).add(protocol)

    if strategy == "union":
        merged = sorted(all_groups.keys())
    elif strategy == "intersection":
        total_sources = len(source_values)
        merged = sorted(g for g, sources in all_groups.items() if len(sources) == total_sources)
    elif strategy == "priority":
        for protocol in authority_config.priority:
            if protocol in source_values and source_values[protocol]:
                merged = sorted(source_values[protocol])
                break
        else:
            merged = []

    # Confidence for groups: proportion of groups that appear in multiple sources
    if not merged:
        confidence = 0.0
    elif len(source_values) == 1:
        confidence = list(authority_config.weights.values())[0] if authority_config.weights else 0.7
    else:
        multi_source_ratio = sum(1 for g in merged if len(all_groups.get(g, set())) > 1) / len(merged)
        confidence = 0.7 + (0.3 * multi_source_ratio)  # 0.7 base, up to 1.0 if all groups multi-sourced

    return (merged, confidence, {"strategy": strategy, "total_unique_groups": len(merged)})
```

---

## 5. Overall Normalization Confidence

The `normalization_confidence` field on `NormalizedAttributes` is the **weighted average** of per-attribute confidences, where weights reflect attribute importance to downstream risk evaluation.

### 5.1 Attribute Importance Weights

```python
ATTRIBUTE_IMPORTANCE = {
    "display_name": 0.15,
    "primary_email": 0.25,
    "department": 0.20,
    "employee_type": 0.25,
    "groups": 0.15,
}
# Weights sum to 1.0
```

Rationale: `primary_email` and `employee_type` are most critical for risk decisions (email for identity correlation, employee_type for policy conditions like contractor restrictions). `department` affects policy evaluation. `display_name` and `groups` are important but less directly tied to access decisions.

### 5.2 Overall Confidence Calculation

```
function calculate_overall_confidence(per_attribute_confidences):
    """
    per_attribute_confidences: dict of {attribute_name: float}
    returns: float (0.0 - 1.0)
    """
    total = 0.0
    for attr, importance in ATTRIBUTE_IMPORTANCE.items():
        attr_confidence = per_attribute_confidences.get(attr, 0.0)
        total += attr_confidence * importance

    # Clamp to [0.0, 1.0]
    return max(0.0, min(1.0, total))
```

### 5.3 Confidence Interpretation Guide

| Confidence Range | Meaning                                      | Dashboard Color | Risk Impact          |
|------------------|----------------------------------------------|-----------------|----------------------|
| 0.90 – 1.00     | High: All sources agree, authoritative source | Green           | No additional risk   |
| 0.70 – 0.89     | Moderate: Minor disagreements or single source| Yellow          | Low additional risk  |
| 0.50 – 0.69     | Low: Significant disagreements resolved by priority | Orange    | Moderate risk signal |
| 0.00 – 0.49     | Very Low: Major conflicts or missing data     | Red             | High risk signal     |

---

## 6. Integration with Risk Evaluator

The `normalization_confidence` score is passed through the pipeline as part of the enriched event data and is available to the Risk Evaluator as a signal.

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

### 6.2 Impact on Default Policy

The default seed policy in `init.sql` (Spec 0) uses the hybrid policy schema defined in A3. The `normalization_risk` signal weight is included at weight 0.15. See the A3 Document Change Manifest for the exact seed policy YAML.

---

## 7. Normalization Output: NormalizedAttributes Model

The full normalization output is formalized as the `NormalizedAttributes` Pydantic model in `shared/naas_shared/models.py` (defined in Spec 0). The model uses discriminated unions for the polymorphic `resolution_details` and `enrichment` substructures, providing a typed contract between the normalization service (writer) and downstream consumers (the Risk Evaluator and the Spec 6 dashboard's Normalization tab). The §7.1 example below shows the JSON shape produced by serializing this model.

### 7.1 What Gets Stored

The `events.normalized_attributes` JSONB column stores the full normalization output:

```json
{
  "display_name": "Alice Smith",
  "primary_email": "alice@corp.com",
  "department": "Engineering",
  "employee_type": "FTE",
  "groups": ["engineering", "admin", "vpn-users"],
  "source_protocol": "oidc",
  "normalization_confidence": 0.87,
  "enrichment": {
    "applied": true,
    "source": "ldap",
    "cache_hit": false
  },
  "resolution_details": {
    "display_name": {
      "resolution": "unanimous",
      "resolved_value": "Alice Smith",
      "confidence": 0.90,
      "sources": ["oidc", "ldap"]
    },
    "primary_email": {
      "resolution": "unanimous",
      "resolved_value": "alice@corp.com",
      "confidence": 0.95,
      "sources": ["oidc", "ldap"]
    },
    "department": {
      "resolution": "priority",
      "resolved_value": "Engineering",
      "confidence": 0.72,
      "winner_source": "ldap",
      "conflicting_values": {"oidc": "Product"},
      "penalty_applied": true
    },
    "employee_type": {
      "resolution": "unanimous",
      "resolved_value": "FTE",
      "confidence": 0.95,
      "sources": ["oidc", "ldap"]
    },
    "groups": {
      "resolution": "list_merge",
      "resolved_value": ["engineering", "admin", "vpn-users"],
      "confidence": 0.85,
      "strategy": "union",
      "total_unique_groups": 3
    }
  }
}
```

The `resolution_details` object is essential for the Normalization dashboard tab — it powers the attribute mapping visualization, showing which source won for each attribute and why.

---

## 8. Edge Cases

### 8.1 Missing Attributes

If a protocol adapter cannot extract a value for an attribute (e.g., SAML assertion doesn't include department), that source is simply absent from the resolution. Single-source resolution applies. If NO source provides a value, the attribute is `None` with confidence `0.0`.

### 8.2 First-Time User

On first login, only one protocol source is available. All attributes come from that single source, confidence equals the source weight for each attribute. This is the common case and is fast.

### 8.3 Value Normalization Failure

If a raw value cannot be normalized (e.g., `employeeType: "XYZ"` matches nothing in the lookup), the value is stored as-is with a 0.2 confidence penalty applied to that attribute. A structured log warning is emitted:

```python
logger.warning(
    "unmapped_attribute_value",
    attribute="employee_type",
    raw_value="XYZ",
    protocol="ldap",
    user_id=event.user_id
)
```

### 8.4 Configuration Missing for Attribute

If the authority configuration has no entry for a specific attribute, the `defaults` section is used. If even defaults are missing (configuration error), global fallback weights of `{ldap: 0.7, saml: 0.6, oidc: 0.8}` are hardcoded as a last resort.

---

## 9. What This Spec Does NOT Cover

- **Cross-event correlation.** This spec resolves attributes within a single event's available data. It does not aggregate attribute history across multiple events to build a "best known" user profile. That would be a P2 enhancement (user identity graph).
- **Attribute change detection.** If Alice's department changes from "Engineering" to "Sales" between logins, this spec does not flag that as anomalous. Change detection would be a Signal Enrichment responsibility.
- **Custom attribute mappings.** The mapping table (§2.1) is hardcoded. A production system would make it configurable. For the MVP, the fixed mapping is sufficient.
- **Real-time configuration updates.** The authority configuration is loaded at startup. Hot-reload is not implemented.

---

*End of Normalization Conflict Resolution Specification.*
