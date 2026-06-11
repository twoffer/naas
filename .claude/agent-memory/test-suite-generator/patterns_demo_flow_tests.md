---
name: patterns-demo-flow-tests
description: Patterns for testing demo CLI flow functions (submit/poll/verify/render/cleanup) with injectable seams and synthetic NormalizedAttributes fixtures built from real field names.
metadata:
  type: feedback
---

# Demo Flow Test Patterns

## File placement
`tests/demo/test_demo_flow.py` — alongside existing `test_demo_normalization.py`.
Do NOT modify the scaffold test file when adding flow tests; add a new module.

## Demo module import pattern
Use `importlib.util.spec_from_file_location` with a unique module name
(`"demo_normalization_flow"` not `"demo_normalization"`) to avoid collision with
the existing demo_module fixture in `test_demo_normalization.py`.

## Real NormalizedAttributes field names (confirmed from models.py + resolution.py)
- Top-level: `display_name`, `primary_email`, `department`, `employee_type`, `groups`,
  `source_protocol`, `normalization_confidence`, `resolution_details`, `enrichment`
- `resolution_details` is `Dict[str, ResolutionDetail]` — discriminated by `resolution` field
- Discriminator values: `"single_source"`, `"unanimous"`, `"priority"`, `"list_merge"`
- `SingleSourceResolution`: `resolution`, `resolved_value`, `confidence`, `sources`
- `UnanimousResolution`: `resolution`, `resolved_value`, `confidence`, `sources`
- `PriorityResolution`: `resolution`, `resolved_value`, `confidence`, `winner_source`,
  `conflicting_values`, `penalty_applied`
- `ListMergeResolution`: `resolution`, `resolved_value`, `confidence`, `strategy`,
  `total_unique_groups`, `sources` (added ec7a42f — contributing protocols; all
  multi-element `sources` lists across variants are sorted alphabetically and
  exact-match assertable)
- `EnrichmentApplied`: `applied=True`, `source="ldap"`, `cache_hit: bool`
- `EnrichmentSkipped`: `applied=False`, `skip_reason: EnrichmentSkipReason`

## Injectable seams to define for implementer
All flow functions that do I/O need an injectable seam so tests run offline:

- `submit_scenes(scenes, ingest_url, args, *, http_client=None)` — accepts mock httpx client
- `render_results(scenes, results, verification, *, console=None, pace=0.0, step=False)` —
  accepts Rich Console; pace/step kwargs added in b6d7a81 (pacing runs between rendered
  scene panels, not between submissions)
- `cleanup_events(event_ids, db_dsn, *, db_execute=None)` — accepts a callable for DB execute
- `poll_results` uses psycopg directly; test via patching psycopg module or injecting cursor

## SQL query constants
Module must define:
- `POLL_QUERY = "SELECT id, protocol, normalized_attributes FROM events WHERE id = ANY(%(ids)s)"`
- `CLEANUP_QUERY = "DELETE FROM events WHERE id = ANY(%(ids)s)"`

## confidence_style helper
The implementer must expose `confidence_style(value: float) -> str` as a module-level callable.
Thresholds: >= 0.80 → "green", 0.50–0.79 → amber/yellow, < 0.50 → "red".
Test boundary values: 0.80, 0.79, 0.50, 0.49.

## poll_results DB row format
`poll_results` returns `list[dict]` where each dict has keys:
`{"id": str, "protocol": str, "normalized_attributes": dict}`
Wrap synthetic NormalizedAttributes with `.model_dump(mode="json")` before passing as normalized_attributes.

## Scene index alignment (SCENES list 0-indexed)
- Index 0: frank/oidc (Scene 1) — single source, no enrichment
- Index 1: frank/saml (Scene 2) — single source, no enrichment
- Index 2: grace/ldap (Scene 3) — ldap_event skip_reason
- Index 3: mallory/saml (Scene 4) — unmapped dept retained, unknown employee_type → None
- Index 4: alice/oidc (Scene 5) — enrichment applied, unanimous scalars
- Index 5: diana/oidc (Scene 6) — enrichment applied, priority conflicts; since b6d7a81
  the token omits vpn-users (back-population showcase: merged groups strict superset of
  token groups, 1/3 corroborated, groups list_merge confidence 0.80 < Scene 5's 0.90)

## Confidence ordering contract (verified against config weights)
- C(4) < C(2) < C(1) < C(3): mallory < frank/saml < frank/oidc < grace/ldap
- C(5) > C(1): enriched alice > unenriched frank
- C(6) < C(5): diana priority conflicts < alice unanimous

## Weight values from config/normalization.yaml
- display_name:  ldap=0.85, saml=0.75, oidc=0.70  priority=[oidc,saml,ldap]
- primary_email: oidc=0.95, saml=0.75, ldap=0.65  priority=[oidc,saml,ldap]
- department:    ldap=0.90, oidc=0.70, saml=0.50  priority=[ldap,oidc,saml]
- employee_type: ldap=0.95, saml=0.80, oidc=0.60  priority=[ldap,saml,oidc]
- groups:        merge_strategy=union

## main() --keep flag tests pass before flow is implemented
`test_cleanup_events_not_called_when_keep_flag_set` and `test_cleanup_events_called_when_keep_not_set`
pass immediately because `main()` orchestration IS already implemented in the skeleton
(the `if not args.keep: cleanup_events(...)` branch). These are valid passing tests —
they test existing `main()` code with all flow functions patched. Do NOT rewrite them
to fail; 51/53 failing with 2 correctly-passing is the right TDD state.

## Rich Console capture pattern
```python
from rich.console import Console
buf = io.StringIO()
con = Console(file=buf, force_terminal=False, width=200)
func(console=con)
output = buf.getvalue().lower()
```
Use `force_terminal=False` to disable Rich markup escaping in plain string comparison.
