# 5. Use a Hybrid Policy Scoring Model with a Safe `ast`-Based Expression Evaluator

* Status: accepted
* Date: 2026-05-01
* Deciders: Tony

## Context and Problem Statement

The Risk Evaluator scores access events against a configurable policy. Policy authors need to express two fundamentally different kinds of risk inputs:

1. **Continuous signals** — IP reputation, normalization confidence, recent failed-login counts, login-recency. These are floats in `[0.0, 1.0]` whose contribution to the score should scale proportionally with their value.
2. **Discrete conditions** — "this user is a contractor logging in after 18:00", "this device is unknown and off the corporate network", "impossible travel was detected". These are boolean predicates that either fire or don't.

Earlier iterations of NAAS oscillated between two incompatible designs: a weights-only schema that handled signals well but expressed boolean rules awkwardly (or not at all), and a conditions-only schema that handled rules well but reduced continuous signals to threshold-bucketed booleans, losing precision. Neither model alone serves real IAM policy authoring.

In addition, however policy expressions are evaluated, the evaluator must be safe by construction — policies are loaded from a YAML configuration file editable through an API and must never permit arbitrary code execution.

## Decision Drivers

* Faithful representation of both continuous and discrete risk inputs without forcing one into the shape of the other
* Safety: the expression evaluator must be unable to execute arbitrary Python or perform I/O
* Authoring ergonomics: policies are written in YAML and read by humans
* Validation at policy-creation time, not at first evaluation
* Operational simplicity for a solo developer — no dependency on a heavy external policy-engine runtime
* Future extensibility: the language must be expandable without breaking existing policies

## Considered Options

* Hybrid YAML schema with `signal_weights` (continuous) + `conditions` (boolean expressions), evaluated by a custom Python `ast`-based safe evaluator
* Full CEL (Common Expression Language) via `cel-python`
* Open Policy Agent (OPA) with policies in Rego
* Weights-only schema (continuous signals only)
* Conditions-only schema (boolean rules only)
* A custom DSL with a hand-written parser (e.g., via `lark` or `pyparsing`)
* `eval()` against a restricted globals/locals dict

## Decision Outcome

Chosen option: **Hybrid YAML schema with `signal_weights` + `conditions`, evaluated by a Python `ast`-based safe evaluator.** The two halves of the schema model the two kinds of risk inputs natively, without forcing either into the other's shape. The `ast`-based evaluator parses each condition expression once at policy-creation time, walks the resulting tree against an explicit allowlist of node types, and evaluates with no I/O, no function calls, no attribute assignment, and no subscript access. The expression language supports `AND`, `OR`, `NOT`, `IN`, comparison operators, and dotted attribute access across five fixed namespaces (`user`, `device`, `signals`, `time`, `event`).

The rule-based score is the sum of `signal × weight` contributions plus the sum of `weight` contributions for each condition that evaluates to true, clamped to `[0.0, 1.0]`. This is then blended with the ML model's score (default 60% rules, 40% ML) to produce the final risk score, which is compared against escalating thresholds (`step_up_mfa`, `deny`).

### Positive Consequences

* Continuous signals contribute proportionally; boolean conditions contribute as step functions. Each input shape is respected.
* Policy validation happens at creation time. Invalid expressions are rejected with descriptive errors before they can ever be evaluated against an event.
* The evaluator has no external runtime dependency — it is pure Python using the standard library `ast` module.
* Safety is enforced by construction: only AST node types on the explicit allowlist execute. There is no need to sandbox a general-purpose interpreter.
* The five-namespace evaluation context (`user.*`, `device.*`, `signals.*`, `time.*`, `event.*`) makes policies readable and self-documenting.
* Adding new operators or namespaces is a localized change to the evaluator and the validator.

### Negative Consequences

* The expression language is custom to NAAS, so policy authors cannot draw on prior CEL or Rego experience directly.
* The set of supported operators is intentionally small. Some expressions that would be one line in CEL (e.g., arithmetic, function calls, list comprehensions) cannot be expressed at all.
* The `ast`-based implementation is NAAS-maintained code, which means NAAS owns the safety properties. A bug in the allowlist could permit unintended operations. Mitigated by extensive unit testing of the allowlist boundary, including explicit negative tests for each prohibited construct.

## Pros and Cons of the Options

### Hybrid YAML schema with `ast`-based evaluator

* Good, because both continuous and discrete inputs are first-class
* Good, because it has zero external runtime dependencies
* Good, because safety is enforced by AST-node allowlisting rather than sandboxing
* Good, because validation runs at policy-creation time
* Bad, because the language is NAAS-specific and not portable
* Bad, because the safety boundary is owned by NAAS, not by a hardened library

### Full CEL via `cel-python`

* Good, because CEL is a standard language used in Kubernetes admission controllers, Envoy, and other production systems
* Good, because it is a hardened, externally-maintained safety boundary
* Good, because the language is more expressive
* Bad, because expressiveness is mostly unused — NAAS policies are simple
* Bad, because it adds a heavyweight dependency for what is, in practice, a handful of comparisons and boolean operations
* Bad, because integrating CEL doesn't solve the continuous-vs-boolean schema problem — we'd still need the `signal_weights` half on top

### Open Policy Agent (OPA) with Rego

* Good, because OPA is the most mature open-source policy engine
* Good, because Rego is purpose-built for policy
* Bad, because it requires running a separate OPA service or sidecar — a significant infrastructure addition for a solo-dev project
* Bad, because Rego has a steep learning curve relative to the complexity of NAAS policies
* Bad, because, like CEL, it doesn't address the hybrid signal/condition shape

### Weights-only schema

* Good, because it is the simplest possible model
* Good, because the math is a pure dot product
* Bad, because boolean concepts ("contractor after 18:00") have to be hand-encoded as upstream signals or shoehorned into thresholds
* Bad, because the upstream signal-engineering work that this requires is itself error-prone

### Conditions-only schema

* Good, because expressing rules feels natural to authors with backgrounds in firewall ACLs or RBAC policies
* Bad, because continuous signals get bucketed into thresholds, losing precision (e.g., `ip_reputation < 0.3 → +0.2`)
* Bad, because rule explosion is a real risk as the input space grows

### Custom DSL with hand-written parser

* Good, because total control over syntax and semantics
* Bad, because writing and maintaining a parser is non-trivial work for marginal benefit over the AST-based approach
* Bad, because every new operator means parser changes
* Bad, because the AST approach gets a parser for free (the Python parser) and only requires the validator to constrain what the parser produces

### `eval()` with restricted globals/locals

* Good, because it requires the least code
* Bad, because Python's `eval()` cannot be safely restricted in a general way — there are well-documented escape patterns through dunder attribute access, subclass walks, and similar
* Bad, because rejecting a request from a security-minded reviewer who sees `eval()` in the code is a hard sell, regardless of how careful the restrictions are

## More Information

Expressions in YAML use uppercase logical operators (`AND`, `OR`, `NOT`, `IN`) for readability; the evaluator preprocesses these to lowercase before parsing because Python's `ast` module requires the lowercase form. Word-boundary regex is used so that, for example, a string value of `"ANDERSON"` is not mangled to `"andERSON"`.

The five evaluation namespaces and their fields are defined as part of the policy specification — they are part of the contract between the Risk Evaluator and policy authors and cannot be extended ad-hoc by individual policies. Adding a new namespace or field requires a code change to the evaluation context construction, which gives the design a deliberate friction against scope creep.

The decision thresholds (`step_up_mfa`, `deny`) must be in strictly ascending order; ALLOW is implicit below the lowest threshold. This escalating-severity schema replaces an earlier `allow`/`deny` pair that could not express step-up authentication as an intermediate outcome.
