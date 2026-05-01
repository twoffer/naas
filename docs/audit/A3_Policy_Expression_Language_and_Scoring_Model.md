# Policy Expression Language & Risk Scoring Model
## Specification for Spec 3 (Risk Evaluator) and Spec 4 (Policy Management)

**Purpose:** Define the complete YAML policy schema, the expression language used in policy conditions, the risk scoring algorithm, and the evaluation context — resolving inconsistencies across existing NAAS documents and providing an unambiguous reference for implementation.

**Audience:** Claude Code agents implementing Spec 3 (Risk Evaluator) and Spec 4 (Policy Management), and the technical-architect agent producing implementation plans for those specs.

---

## 1. Overview

The NAAS Risk Evaluator uses a **hybrid scoring model** that combines two complementary mechanisms within a single YAML policy definition:

1. **Signal Weights** — Continuous, pre-normalized risk signals (0.0–1.0) multiplied by policy-defined weights. These capture proportional risk where the gradient carries meaningful information (e.g., IP reputation 0.2 is genuinely twice as risky as 0.1).

2. **Conditions** — Boolean expressions evaluated against the event context. When a condition evaluates to `true`, its weight contributes fully to the rule-based score. These capture business logic and threshold-based risk factors (e.g., "contractor logging in after hours").

Both mechanisms feed a single rule-based score, which is then blended with the ML-based score via a configurable ensemble to produce the final risk score.

### 1.1 Why a Hybrid Model

Early NAAS documentation contained two inconsistent policy models: a `weights`-only model mapping signal names to floats, and a `conditions`-only model with boolean expressions. Neither alone is sufficient:

- **Weights-only** cannot express compound business logic (e.g., `user.employee_type == 'contractor' AND time.hour > 18`).
- **Conditions-only** loses proportional information from continuous signals — it forces cliff-edge thresholds where an IP with reputation 0.05 and one with reputation 0.29 would be treated identically.

The hybrid model places each signal type where it fits best: continuous signals in `signal_weights`, threshold/business logic in `conditions`.

### 1.2 Design Principle: What Goes Where

**`signal_weights`** is exclusively for signals where the float value carries meaningful proportional information — where 0.2 is genuinely twice as risky as 0.1, and the gradient matters.

**`conditions`** is for everything with discrete states, step-function behavior, threshold semantics, or compound business logic.

If a signal has only a small number of discrete output states (e.g., three possible values), it belongs in `conditions`, not `signal_weights`.

### 1.3 Code Samples in This Document

**The code samples throughout this document are illustrative reference implementations**, not copy-paste production code. They establish the algorithms, data structures, and contracts that the implementing agent must follow, but the implementing agent is expected to:

- Add proper error handling, logging, and typing beyond what is shown
- Integrate with the project's existing patterns (Pydantic models, SQLAlchemy async sessions, structlog, etc.)
- Write corresponding unit tests per the TDD workflow in the Agentic Workflow Implementation Guide

Functions referenced but not fully implemented in this spec (e.g., `ml_model_predict()` in §6.1) are intentionally left to the implementing spec — they depend on infrastructure or design decisions outside this document's scope.

---

## 2. Complete YAML Policy Schema

```yaml
# Canonical policy schema — all fields shown

name: "enterprise-risk-policy-v1"       # Required. Unique human-readable name.
version: "1.0.0"                         # Required. Semver string.
description: "Standard enterprise risk evaluation"  # Optional. Human-readable description.
is_shadow: false                         # Optional. Default: false. Shadow policies are evaluated but not enforced.

# ── Continuous Signal Weights ──────────────────────────────────
# Pre-normalized risk signals (0.0–1.0, higher = riskier).
# Normalization formulas are defined in the Risk Evaluator code (§4),
# NOT in the policy. The policy only controls how much each signal matters.
# Keys must be from the VALID_SIGNAL_WEIGHTS enum (§4.1).
signal_weights:
  ip_reputation_risk: 0.20               # 1.0 - ip_reputation_score
  normalization_risk: 0.15               # 1.0 - normalization_confidence
  failed_login_risk: 0.15                # min(failed_logins_24h / 10.0, 1.0)
  login_recency_risk: 0.10               # min(days_since_last_login / 90.0, 1.0); first login = 1.0

# ── Boolean Conditions ─────────────────────────────────────────
# Each condition is evaluated against the event context (§3).
# If the expression evaluates to true, the condition's weight
# contributes fully to the rule-based score.
# Expressions use the Policy Expression Language defined in §5.
conditions:
  - name: "impossible-travel"            # Required. Unique within this policy.
    expression: "signals.impossible_travel"
    weight: 0.25                         # Required. Float > 0.

  - name: "contractor-after-hours"
    expression: "user.employee_type == 'contractor' AND time.hour > 18"
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
    expression: "user.employee_type == 'contractor' AND signals.country != 'US'"
    weight: 0.15

  - name: "legacy-protocol-usage"
    expression: "event.protocol == 'ldap'"
    weight: 0.05

# ── Decision Thresholds ────────────────────────────────────────
# Escalating severity thresholds. The engine walks from highest to
# lowest; the first threshold the final_score meets or exceeds
# determines the decision. Scores below all thresholds → ALLOW.
thresholds:
  step_up_mfa: 0.3                       # final_score >= 0.3 → STEP_UP_MFA
  deny: 0.7                              # final_score >= 0.7 → DENY
                                          # final_score < 0.3 → ALLOW (implicit)

# ── Ensemble Configuration ─────────────────────────────────────
ensemble:
  rule_weight: 0.6                       # Weight for rule-based score
  ml_weight: 0.4                         # Weight for ML-based score
                                          # Must sum to 1.0
```

### 2.1 Schema Validation Rules (enforced at policy creation time)

1. `name` is required, non-empty string.
2. `version` is required, must match semver pattern `^\d+\.\d+\.\d+$`.
3. `signal_weights` keys must be from the `VALID_SIGNAL_WEIGHTS` enum (§4.1). Unknown keys are rejected.
4. `signal_weights` values must be floats > 0.
5. `conditions` entries must have unique `name` values within a policy.
6. `conditions[].expression` must parse successfully through the expression evaluator (§5). Invalid expressions are rejected at creation time, not at evaluation time.
7. `conditions[].weight` must be a float > 0.
8. `thresholds` values must be in strictly ascending order of severity: `thresholds.step_up_mfa` < `thresholds.deny`. Both must be floats in (0.0, 1.0).
9. `ensemble.rule_weight + ensemble.ml_weight` must equal 1.0.
10. There is no constraint that signal_weights values + condition weights must sum to 1.0. The rule-based score is clamped to [0.0, 1.0] at the engine level (§6.1).

---

## 3. Evaluation Context (Expression Variable Namespaces)

The evaluation context is the set of variables available to condition expressions at evaluation time. It is constructed by the Risk Evaluator from the enriched event data. Every field listed below is guaranteed to be present when the expression evaluator runs.

### 3.1 `user.*` — from NormalizedAttributes (Spec 2 output)

| Field                 | Type                            | Example            | Source                                    |
|-----------------------|---------------------------------|--------------------|-------------------------------------------|
| `user.employee_type`  | `str`                           | `"contractor"`     | Normalized: `"FTE"`, `"contractor"`, `"vendor"` |
| `user.department`     | `str`                           | `"Engineering"`    | Normalized department name                |
| `user.display_name`   | `str`                           | `"Alice Chen"`     | Normalized display name                   |
| `user.primary_email`  | `str`                           | `"alice@corp.com"` | Normalized email                          |
| `user.groups`         | `list[str]`                     | `["admin","dev"]`  | Normalized group memberships              |

**Data origin:** Populated from `events.normalized_attributes` JSONB, as produced by the Identity Normalization Service (Spec 2). Uses the conflict resolution and value normalization defined in A2.

### 3.2 `device.*` — from enrichment: device fingerprinting

| Field                      | Type   | Example        | Source                        |
|----------------------------|--------|----------------|-------------------------------|
| `device.known_device`      | `bool` | `true`         | Device seen before for user   |
| `device.on_corporate_network` | `bool` | `false`     | Source IP in corporate range  |
| `device.vpn_connected`     | `bool` | `true`         | VPN endpoint detected         |
| `device.browser`           | `str`  | `"Chrome"`     | Parsed from User-Agent        |
| `device.os`                | `str`  | `"Windows 11"` | Parsed from User-Agent        |
| `device.device_type`       | `str`  | `"desktop"`    | `"desktop"`, `"mobile"`, `"tablet"`, `"unknown"` |

**Data origin:** Populated from `events.enriched_signals` JSONB, under the `device` key.

### 3.3 `signals.*` — from enrichment: risk signals

| Field                              | Type    | Example  | Source                                      |
|------------------------------------|---------|----------|---------------------------------------------|
| `signals.impossible_travel`        | `bool`  | `false`  | Haversine speed > 1800 km/h                 |
| `signals.ip_reputation_score`      | `float` | `0.85`   | 0.0–1.0 (higher = more reputable = less risky) |
| `signals.failed_logins_24h`        | `int`   | `3`      | Failed attempts in past 24 hours             |
| `signals.days_since_last_login`    | `int`   | `45`     | Calendar days since last successful login; `null` → first login ever (treated as 9999 for expression evaluation) |
| `signals.country`                  | `str`   | `"US"`   | GeoIP country code (ISO 3166-1 alpha-2)      |
| `signals.city`                     | `str`   | `"New York"` | GeoIP city name                          |
| `signals.normalization_confidence` | `float` | `0.92`   | From A2: overall normalization confidence    |

**Data origin:** Populated from `events.enriched_signals` JSONB, assembled by the Signal Enrichment Service (Spec 3). `normalization_confidence` is also available at `events.normalized_attributes.normalization_confidence` and is copied into the signals namespace for expression convenience.

**Note on `days_since_last_login` null handling:** A first-ever login has no previous login record. In the evaluation context, `null` is mapped to `9999` (a sentinel value representing "never logged in before"), so expressions like `signals.days_since_last_login > 90` correctly trigger for first-time users.

### 3.4 `time.*` — derived from event timestamp

| Field              | Type  | Example | Source                    |
|--------------------|-------|---------|---------------------------|
| `time.hour`        | `int` | `14`    | 0–23, UTC                  |
| `time.day_of_week` | `int` | `2`     | 0=Monday, 6=Sunday (ISO)   |

**Data origin:** Computed by the Risk Evaluator from `events.timestamp` at evaluation time. Not stored in enriched_signals.

### 3.5 `event.*` — from the event record

| Field              | Type   | Example       | Source                                 |
|--------------------|--------|---------------|----------------------------------------|
| `event.protocol`   | `str`  | `"ldap"`      | `"oidc"`, `"saml"`, `"ldap"`          |
| `event.source`     | `str`  | `"user"`      | `"user"`, `"simulator"`, `"api"`       |
| `event.is_synthetic` | `bool` | `false`     | Generated by simulator                 |
| `event.is_historical` | `bool` | `false`    | Backdated for analytics                |

**Data origin:** Directly from the `events` table columns.

### 3.6 Context Assembly (Risk Evaluator implementation detail)

The Risk Evaluator constructs the evaluation context as a nested Python dictionary before expression evaluation:

```python
def build_evaluation_context(event_record) -> dict:
    """
    Assemble the evaluation context from an enriched event record.
    All fields are guaranteed present (None/defaults for missing data).
    """
    norm = event_record.normalized_attributes or {}
    signals = event_record.enriched_signals or {}

    # Handle null days_since_last_login (first-ever login)
    days_since = signals.get("days_since_last_login")
    if days_since is None:
        days_since = 9999  # sentinel: "never logged in before"

    return {
        "user": SimpleNamespace(
            employee_type=norm.get("employee_type", "unknown"),
            department=norm.get("department", "unknown"),
            display_name=norm.get("display_name", ""),
            primary_email=norm.get("primary_email", ""),
            groups=norm.get("groups", []),
        ),
        "device": SimpleNamespace(
            known_device=signals.get("device", {}).get("known_device", False),
            on_corporate_network=signals.get("device", {}).get("on_corporate_network", False),
            vpn_connected=signals.get("device", {}).get("vpn_connected", False),
            browser=signals.get("device", {}).get("browser", "unknown"),
            os=signals.get("device", {}).get("os", "unknown"),
            device_type=signals.get("device", {}).get("device_type", "unknown"),
        ),
        "signals": SimpleNamespace(
            impossible_travel=signals.get("impossible_travel", False),
            ip_reputation_score=signals.get("ip_reputation_score", 0.5),
            failed_logins_24h=signals.get("failed_logins_24h", 0),
            days_since_last_login=days_since,
            country=signals.get("geo", {}).get("country", "unknown"),
            city=signals.get("geo", {}).get("city", "unknown"),
            normalization_confidence=norm.get("normalization_confidence", 1.0),
        ),
        "time": SimpleNamespace(
            hour=event_record.timestamp.hour,
            day_of_week=event_record.timestamp.weekday(),  # 0=Monday
        ),
        "event": SimpleNamespace(
            protocol=event_record.protocol,
            source=event_record.source,
            is_synthetic=event_record.is_synthetic,
            is_historical=event_record.is_historical,
        ),
    }
```

`SimpleNamespace` is used so that expressions like `user.employee_type` resolve via attribute access (which maps to `ast.Attribute` nodes), matching the natural dot-notation syntax.

---

## 4. Signal Normalization (Risk Evaluator code)

### 4.1 Valid Signal Weights Enum

The set of valid keys for the `signal_weights` section of a policy YAML. This is a **closed vocabulary** — the policy author can only assign weights to signals the engine knows how to normalize. Unknown keys are rejected at policy creation time by the policy validator (Spec 4).

```python
VALID_SIGNAL_WEIGHTS = {
    "ip_reputation_risk",
    "normalization_risk",
    "failed_login_risk",
    "login_recency_risk",
}
```

### 4.2 Normalization Formulas

Each normalizer converts a raw enrichment signal into a risk-oriented [0.0, 1.0] float where higher = riskier. These are defined in the Risk Evaluator's code, NOT in the policy YAML. The policy controls only the weight (how much each matters), not the normalization (how to convert raw values to risk values).

```python
def normalize_signals(enriched_signals: dict, normalized_attributes: dict) -> dict:
    """
    Convert raw enrichment signals to risk-oriented [0.0, 1.0] values.
    Returns dict of {signal_name: normalized_risk_value}.
    """
    days_since = enriched_signals.get("days_since_last_login")
    if days_since is None:
        days_since_risk = 1.0  # First-ever login = maximum recency risk
    else:
        days_since_risk = min(days_since / 90.0, 1.0)

    return {
        # IP reputation: invert (high reputation = low risk)
        "ip_reputation_risk": 1.0 - enriched_signals.get("ip_reputation_score", 0.5),

        # Normalization confidence: invert (high confidence = low risk)
        # Cross-cutting signal from A2 — data quality affects security decisions
        "normalization_risk": 1.0 - normalized_attributes.get(
            "normalization_confidence", 1.0
        ),

        # Failed logins: linear scale, saturates at 10
        # 10+ failed logins in 24h = maximum risk (1.0)
        "failed_login_risk": min(
            enriched_signals.get("failed_logins_24h", 0) / 10.0, 1.0
        ),

        # Login recency: linear scale, saturates at 90 days
        # 90+ days dormant = maximum risk (1.0)
        # First-ever login (null) = 1.0
        "login_recency_risk": days_since_risk,
    }
```

### 4.3 Rationale for Each Normalizer

| Signal | Formula | Rationale |
|--------|---------|-----------|
| `ip_reputation_risk` | `1.0 - score` | IP reputation providers return higher scores for more reputable IPs. Risk is the inverse. |
| `normalization_risk` | `1.0 - confidence` | From A2 design. Low confidence means identity sources disagree — data inconsistency is a risk indicator. |
| `failed_login_risk` | `count / 10.0` clamped | Linear scaling. 10+ failures in 24h represents maximum concern. The threshold of 10 is appropriate for enterprise environments; different organizations may adjust. |
| `login_recency_risk` | `days / 90.0` clamped | 90 days of inactivity represents a fully dormant account. First-ever login (no history) gets maximum risk because the system has no behavioral baseline for this user. |

---

## 5. Policy Expression Language

### 5.1 Supported Operators

| Category             | Operators                        | Example                                            |
|----------------------|----------------------------------|----------------------------------------------------|
| Comparison           | `==`, `!=`, `<`, `<=`, `>`, `>=` | `time.hour > 18`                                   |
| Logical              | `AND`, `OR`, `NOT`               | `NOT device.known_device AND time.hour > 18`       |
| Membership/Substring | `IN`                             | `'admin' IN user.groups` / `'Eng' IN user.department` |

### 5.2 Type System

| Type        | Literals                        | Valid Operators                          |
|-------------|---------------------------------|-----------------------------------------|
| `str`       | `'contractor'`, `'US'`          | `==`, `!=`, `IN` (as substring target)  |
| `int`       | `18`, `5`, `0`                  | `==`, `!=`, `<`, `<=`, `>`, `>=`        |
| `float`     | `0.3`, `0.85`                   | `==`, `!=`, `<`, `<=`, `>`, `>=`        |
| `bool`      | `true`, `false` (in expressions: `True`, `False` after preprocessing) | `==`, `!=` |
| `list[str]` | N/A (only via context variables) | `IN` (as membership target)             |

**Type safety:** Comparisons require matching types on both sides. Comparing a string to an integer (e.g., `user.department > 5`) is a validation error caught at policy creation time, not a runtime surprise. The exception is `int` and `float`, which can be compared with each other.

### 5.3 `IN` Operator Dual Semantics

The `IN` operator behaves differently based on the right operand's type, following Python's native semantics:

- **List membership:** `'admin' IN user.groups` → `True` if `'admin'` is an element of the `user.groups` list.
- **Substring match:** `'Engineering' IN user.department` → `True` if `'Engineering'` is a substring of the `user.department` string.

This dual behavior is a consequence of the Python `ast`-based implementation and provides substring matching without introducing a separate `CONTAINS` operator. The `IN` operator always has the test value on the left and the collection/string on the right.

### 5.4 Operator Precedence

Standard Python precedence applies:
1. `NOT` (highest, unary)
2. Comparison operators (`==`, `!=`, `<`, `<=`, `>`, `>=`, `IN`)
3. `AND`
4. `OR` (lowest)

Parentheses can be used to override precedence: `(user.employee_type == 'contractor' OR user.employee_type == 'vendor') AND time.hour > 18`

### 5.5 Expression Preprocessing

Expressions in the YAML use uppercase logical operators for readability (`AND`, `OR`, `NOT`, `IN`), but Python's `ast` module requires lowercase. The evaluator preprocesses expressions before parsing:

```python
import re

def preprocess_expression(expr: str) -> str:
    """Convert policy expression syntax to Python-parseable syntax.

    Uses word-boundary-aware regex to avoid mangling strings
    (e.g., 'ANDERSON' is not converted to 'andERSON').
    """
    expr = re.sub(r'\bAND\b', 'and', expr)
    expr = re.sub(r'\bOR\b', 'or', expr)
    expr = re.sub(r'\bNOT\b', 'not', expr)
    expr = re.sub(r'\bIN\b', 'in', expr)
    expr = re.sub(r'\btrue\b', 'True', expr)
    expr = re.sub(r'\bfalse\b', 'False', expr)
    return expr
```

Note: `true`/`false` in YAML are boolean literals, but in the expression strings they appear as text. The preprocessor converts them to Python's `True`/`False`.

### 5.6 Disallowed Constructs

The expression language explicitly prohibits:
- Function calls (no `len()`, `min()`, `max()`, `abs()`)
- Arithmetic operators (no `+`, `-`, `*`, `/`, `%`, `**`)
- Assignments (no `=`)
- Import statements
- Lambda expressions
- List/dict/set comprehensions
- Attribute assignment
- Subscript access (no `user['groups']`, only `user.groups`)

Any expression containing disallowed AST node types is rejected at policy creation time with a descriptive error message identifying the disallowed construct.

---

## 5.7 Implementation: Safe Expression Evaluator

The expression evaluator uses Python's `ast` module to parse expressions into an Abstract Syntax Tree, then walks the tree with an explicit allowlist of permitted node types. This is safe by construction — only whitelisted operations execute.

```python
import ast
import operator
import re

# Allowed comparison operators
COMPARE_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}

# Allowed boolean operators
BOOL_OPS = {
    ast.And: all,
    ast.Or: any,
}

# Allowed unary operators
UNARY_OPS = {
    ast.Not: operator.not_,
}


def evaluate_expression(expression: str, context: dict) -> bool:
    """
    Safely evaluate a policy expression against an event context.

    Args:
        expression: Policy expression string (e.g., "user.employee_type == 'contractor' AND time.hour > 18")
        context: Evaluation context dict with SimpleNamespace values for each namespace

    Returns:
        bool: Expression result. Returns False on any error (fail-closed).

    Security:
        - Only whitelisted AST node types are evaluated
        - No function calls, imports, assignments, or arithmetic
        - Expressions are validated at policy creation time; runtime errors
          indicate a bug, not user input issues
    """
    try:
        preprocessed = preprocess_expression(expression)
        tree = ast.parse(preprocessed, mode='eval')
        return bool(_eval_node(tree.body, context))
    except Exception as e:
        logger.error(
            "expression_evaluation_failed",
            expression=expression,
            error=str(e),
        )
        return False  # Fail closed


def _eval_node(node, context):
    """Recursively evaluate an AST node against the context."""

    if isinstance(node, ast.Constant):
        return node.value

    elif isinstance(node, ast.Name):
        # Top-level namespace lookup (e.g., 'user', 'device', 'signals')
        if node.id not in context:
            raise ValueError(f"Unknown namespace: {node.id}")
        return context[node.id]

    elif isinstance(node, ast.Attribute):
        # Dot-notation attribute access (e.g., user.employee_type)
        value = _eval_node(node.value, context)
        if not hasattr(value, node.attr):
            raise ValueError(
                f"Unknown field: {node.attr} on {type(value).__name__}"
            )
        return getattr(value, node.attr)

    elif isinstance(node, ast.Compare):
        left = _eval_node(node.left, context)
        for op, comparator in zip(node.ops, node.comparators):
            if type(op) not in COMPARE_OPS:
                raise ValueError(f"Unsupported comparison: {type(op).__name__}")
            right = _eval_node(comparator, context)
            if not COMPARE_OPS[type(op)](left, right):
                return False
            left = right
        return True

    elif isinstance(node, ast.BoolOp):
        op = BOOL_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"Unsupported boolean op: {type(node.op).__name__}")
        values = [_eval_node(v, context) for v in node.values]
        return op(values)

    elif isinstance(node, ast.UnaryOp):
        if type(node.op) not in UNARY_OPS:
            raise ValueError(f"Unsupported unary op: {type(node.op).__name__}")
        operand = _eval_node(node.operand, context)
        return UNARY_OPS[type(node.op)](operand)

    else:
        raise ValueError(f"Disallowed expression construct: {type(node).__name__}")


def validate_expression(expression: str, context_schema: dict) -> list[str]:
    """
    Validate an expression at policy creation time.
    Returns a list of error strings (empty = valid).

    Checks:
    1. Expression parses as valid Python
    2. Only allowed AST node types are used
    3. All namespace references exist in the context schema
    4. Type compatibility of comparisons (where statically determinable)
    """
    errors = []
    try:
        preprocessed = preprocess_expression(expression)
        tree = ast.parse(preprocessed, mode='eval')
        _validate_node(tree.body, context_schema, errors)
    except SyntaxError as e:
        errors.append(f"Syntax error: {e.msg}")
    return errors


# Allowed AST node types for validation
ALLOWED_NODE_TYPES = {
    ast.Expression, ast.Compare, ast.BoolOp, ast.UnaryOp,
    ast.Constant, ast.Name, ast.Attribute,
    # Comparison operators
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn,
    # Boolean operators
    ast.And, ast.Or, ast.Not,
}


def _validate_node(node, context_schema: dict, errors: list[str]):
    """
    Recursively validate an AST node.
    Checks node type allowlist, namespace existence, and field existence.

    Args:
        node: AST node to validate
        context_schema: dict mapping namespace names to sets of valid field names,
            e.g. {"user": {"employee_type", "department", ...}, "device": {...}, ...}
        errors: accumulator list for error messages
    """
    if type(node) not in ALLOWED_NODE_TYPES:
        errors.append(
            f"Disallowed construct: {type(node).__name__}. "
            f"Only comparisons, boolean logic, and attribute access are permitted."
        )
        return

    if isinstance(node, ast.Name):
        if node.id not in context_schema and node.id not in ("True", "False"):
            errors.append(f"Unknown namespace: '{node.id}'. Valid namespaces: {sorted(context_schema.keys())}")

    elif isinstance(node, ast.Attribute):
        # Check that the attribute exists in the namespace
        if isinstance(node.value, ast.Name) and node.value.id in context_schema:
            valid_fields = context_schema[node.value.id]
            if node.attr not in valid_fields:
                errors.append(
                    f"Unknown field: '{node.value.id}.{node.attr}'. "
                    f"Valid fields for '{node.value.id}': {sorted(valid_fields)}"
                )
        _validate_node(node.value, context_schema, errors)

    elif isinstance(node, ast.Compare):
        _validate_node(node.left, context_schema, errors)
        for comparator in node.comparators:
            _validate_node(comparator, context_schema, errors)

    elif isinstance(node, ast.BoolOp):
        for value in node.values:
            _validate_node(value, context_schema, errors)

    elif isinstance(node, ast.UnaryOp):
        _validate_node(node.operand, context_schema, errors)

    # ast.Constant — always valid, no children to recurse into


# Context schema for validation (mirrors §3 evaluation context)
EXPRESSION_CONTEXT_SCHEMA = {
    "user": {"employee_type", "department", "display_name", "primary_email", "groups"},
    "device": {"known_device", "on_corporate_network", "vpn_connected", "browser", "os", "device_type"},
    "signals": {"impossible_travel", "ip_reputation_score", "failed_logins_24h", "days_since_last_login", "country", "city", "normalization_confidence"},
    "time": {"hour", "day_of_week"},
    "event": {"protocol", "source", "is_synthetic", "is_historical"},
}
```

### 5.8 Boolean Expression Conventions

Boolean-typed context fields (e.g., `device.known_device`, `signals.impossible_travel`) can be referenced in expressions in two ways:

**Implicit form (preferred):** Use the field directly with logical operators.
```
NOT device.known_device
device.vpn_connected
signals.impossible_travel AND time.hour > 18
```

**Explicit form (also valid):** Compare the field against `true` or `false`.
```
device.known_device == false
signals.impossible_travel == true
```

Both forms are valid — the `ast`-based evaluator handles them identically because Python treats bare boolean values as truthy/falsy in logical operations. The implicit form is preferred in all documentation examples and the seed policy because it is more concise and reads more naturally (e.g., `NOT device.known_device` vs `device.known_device == false`).

The policy validator accepts both forms. There is no enforcement of one over the other at creation time — this is a style convention, not a constraint.

---

## 6. Risk Scoring Algorithm

### 6.1 Complete Scoring Pipeline

```python
def calculate_risk_score(event_record, active_policy: dict) -> dict:
    """
    Full risk scoring pipeline.

    Args:
        event_record: Enriched event from the enriched_events stream
        active_policy: Parsed YAML policy dict

    Returns:
        dict with rule_based_score, ml_based_score, final_score,
        decision, and contributing_factors
    """
    # 1. Build evaluation context
    context = build_evaluation_context(event_record)

    # 2. Normalize continuous signals
    normalized = normalize_signals(
        event_record.enriched_signals or {},
        event_record.normalized_attributes or {},
    )

    # 3. Calculate signal weight contribution
    signal_score = 0.0
    signal_contributions = {}
    for signal_name, weight in active_policy.get("signal_weights", {}).items():
        signal_value = normalized.get(signal_name, 0.0)
        contribution = signal_value * weight
        signal_score += contribution
        signal_contributions[signal_name] = {
            "raw_value": signal_value,
            "weight": weight,
            "contribution": contribution,
        }

    # 4. Evaluate boolean conditions
    condition_score = 0.0
    condition_contributions = {}
    for condition in active_policy.get("conditions", []):
        triggered = evaluate_expression(condition["expression"], context)
        contribution = condition["weight"] if triggered else 0.0
        condition_score += contribution
        condition_contributions[condition["name"]] = {
            "expression": condition["expression"],
            "triggered": triggered,
            "weight": condition["weight"],
            "contribution": contribution,
        }

    # 5. Combine and clamp rule-based score
    rule_based_score = max(0.0, min(1.0, signal_score + condition_score))

    # 6. ML scoring
    ml_based_score = ml_model_predict(event_record)  # Returns 0.0–1.0

    # 7. Ensemble blend
    ensemble = active_policy.get("ensemble", {"rule_weight": 0.6, "ml_weight": 0.4})
    final_score = (
        rule_based_score * ensemble["rule_weight"]
        + ml_based_score * ensemble["ml_weight"]
    )

    # 8. Decision (walk thresholds from highest severity to lowest)
    thresholds = active_policy.get("thresholds", {"step_up_mfa": 0.3, "deny": 0.7})
    if final_score >= thresholds["deny"]:
        decision = "deny"
    elif final_score >= thresholds["step_up_mfa"]:
        decision = "step_up_mfa"
    else:
        decision = "allow"

    return {
        "rule_based_score": round(rule_based_score, 4),
        "ml_based_score": round(ml_based_score, 4),
        "final_score": round(final_score, 4),
        "decision": decision,
        "contributing_factors": {
            "signals": signal_contributions,
            "conditions": condition_contributions,
            "ensemble": ensemble,
            "thresholds": thresholds,
        },
    }
```

### 6.2 Scoring Formula Summary

```
signal_score     = Σ (normalized_signal_value × signal_weight)     for each signal in signal_weights
condition_score  = Σ (1.0 if expression is true else 0.0) × weight for each condition in conditions
rule_based_score = clamp(signal_score + condition_score, 0.0, 1.0)
final_score      = (rule_based_score × ensemble.rule_weight) + (ml_based_score × ensemble.ml_weight)

Decision (evaluated highest severity first):
  final_score ≥ thresholds.deny         → DENY
  final_score ≥ thresholds.step_up_mfa  → STEP_UP_MFA
  otherwise                              → ALLOW (implicit)
```

### 6.3 Contributing Factors

The `contributing_factors` JSONB stored in the `risk_assessments` table records exactly which signals and conditions contributed to the final score. This is essential for:

- **Dashboard explainability:** The Risk Engine tab can show "why was this event flagged?" with a breakdown of each factor's contribution.
- **Policy tuning:** Operators can see which conditions fire most frequently and adjust weights.
- **Shadow mode comparison:** When comparing active vs shadow policy decisions, the contributing factors show exactly where the policies diverge.

---

## 7. Enrichment Pipeline Update: `days_since_last_login`

The Signal Enrichment Service (Spec 3) must compute and include `days_since_last_login` in the `enriched_signals` JSONB.

### 7.1 Enrichment Logic

```python
async def enrich_login_recency(user_id: str, event_timestamp: datetime, db_session) -> int | None:
    """
    Calculate days since the user's last successful login.

    Returns:
        int: Calendar days since last login, or None if this is the user's first login.
    """
    query = """
        SELECT MAX(timestamp) as last_login
        FROM events
        WHERE user_id = :user_id
          AND timestamp < :current_timestamp
          AND id != :current_event_id
    """
    result = await db_session.execute(query, {
        "user_id": user_id,
        "current_timestamp": event_timestamp,
        "current_event_id": current_event_id,
    })
    last_login = result.scalar()

    if last_login is None:
        return None  # First-ever login

    delta = event_timestamp - last_login
    return delta.days
```

### 7.2 Placement in `enriched_signals` JSONB

```json
{
  "ip_reputation_score": 0.85,
  "geo": { "country": "US", "city": "New York", "latitude": 40.71, "longitude": -74.01 },
  "device": { "known_device": true, "on_corporate_network": false, "vpn_connected": true, "browser": "Chrome", "os": "Windows 11", "device_type": "desktop" },
  "impossible_travel": false,
  "failed_logins_24h": 2,
  "days_since_last_login": 45
}
```

---

## 8. Shadow Mode Scoring

When a shadow policy exists alongside the active policy, the Risk Evaluator evaluates BOTH policies against the same event. The shadow result is logged but not enforced.

```python
# In the Risk Evaluator's main loop:
active_result = calculate_risk_score(event, active_policy)
shadow_result = None

if shadow_policy:
    shadow_result = calculate_risk_score(event, shadow_policy)

# Write to risk_assessments table:
assessment = {
    "event_id": event.event_id,
    "policy_id": active_policy_id,
    "rule_based_score": active_result["rule_based_score"],
    "ml_based_score": active_result["ml_based_score"],
    "final_score": active_result["final_score"],
    "decision": active_result["decision"],
    "contributing_factors": active_result["contributing_factors"],
    "shadow_decision": shadow_result["decision"] if shadow_result else None,
    "shadow_score": shadow_result["final_score"] if shadow_result else None,
}
```

The `contributing_factors` for the shadow policy can be queried separately if needed for the dashboard comparison view.

---

## 9. Default Seed Policy (replaces current init.sql seed)

The seed policy in Spec 0's `init.sql` must be updated to use the hybrid schema defined in this spec. This replaces the current weights-only seed.

```yaml
name: "Default Risk Policy"
version: "1.0.0"
description: "Baseline risk evaluation policy for NAAS demo"
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
    expression: "user.employee_type == 'contractor' AND time.hour > 18"
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
    expression: "user.employee_type == 'contractor' AND signals.country != 'US'"
    weight: 0.15

  - name: "legacy-protocol-usage"
    expression: "event.protocol == 'ldap'"
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
```

This seed policy is designed to serve double duty: it provides reasonable risk evaluation defaults for the demo environment, AND it showcases the full range of the expression language to anyone viewing the Risk Engine dashboard tab on first boot. The conditions demonstrate comparisons (`>`, `>=`, `!=`, `==`), logical operators (`AND`, `NOT`), multiple namespaces (`user`, `device`, `signals`, `time`, `event`), and both string and numeric comparisons. Policy authors can create additional policies or modify this one via the CRUD API.

---

## 10. What This Spec Does NOT Cover

- **Policy CRUD API design.** The REST endpoints for policy management (`GET/POST/PUT/DELETE /policies`, `POST /policies/{id}/activate`) are defined in Spec 4, not here. This spec defines the schema and evaluation logic that Spec 4's API will store and validate.
- **Policy caching.** Redis caching of the active policy (60s TTL) is an implementation concern for Spec 4.
- **Policy versioning mechanics.** How versions are stored, compared, and rolled back is a Spec 4 concern.
- **ML model training.** How `random_forest.pkl` is generated is defined in `A4_ML_Model_Bootstrap_Workflow.md`. The ML model consumes a 16-feature vector (broader than the 4 signal_weights signals) and returns a float 0.0–1.0. The training data labels are independent of rule-based scoring.
- **Alert generation.** How risk decisions trigger alerts is defined in the Alert Service portion of Spec 4.
- **Dashboard visualization.** How contributing factors are displayed is a Spec 6 concern.

---

*End of Policy Expression Language & Risk Scoring Model Specification.*
