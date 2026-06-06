# 11. Carry the Full Event Record as the Payload on Every Pipeline Stream

* Status: accepted
* Date: 2026-06-04
* Deciders: Tony

## Context and Problem Statement

NAAS moves each login event through a chain of Redis Streams — `login_events` → `normalized_events` → `enriched_events` — where each pipeline stage consumes the previous stream, does its work, updates the canonical row in the PostgreSQL `events` table, and publishes to the next stream for the following stage.

ADR-0002 established Redis Streams as the transport and PostgreSQL as the system of record, but it did not pin down the *granularity* of a stream message. Two shapes are possible, and the choice is a cross-cutting contract that every consuming service inherits:

1. **A full event record** — the complete serialized event (all original fields plus whatever the publishing stage has added so far), keyed by `id`.
2. **A minimal notification** — just the correlation key (`{"id": ...}`), with each consumer re-reading the authoritative row from PostgreSQL.

The Event Ingestion service (the first stage) already publishes the full `LoginEventRecord` to `login_events`. The question is whether the rest of the pipeline should follow that pattern or adopt minimal notifications, and the answer should be a single principle applied uniformly rather than a per-stream judgement call.

## Decision Drivers

* A uniform message shape across all stages keeps consumers mechanical and avoids per-stream special-casing.
* PostgreSQL must remain the system of record (ADR-0002); the stream must not become a competing source of truth.
* The per-stage outputs written to `events` (`normalized_attributes`, `enriched_signals`) are each written exactly once by their owning stage and never mutated afterward.
* Downstream stages should retain the option to re-read the authoritative row when they want the freshest copy, without being *forced* to on every message.
* The pipeline runs at demo scale (~10 events/sec, streams capped at 10 000 entries), so message size is not a binding constraint.

## Considered Options

* **Full event record on every stream** (chosen): each stage publishes the complete serialized event, with its own contribution populated, keyed by `id`.
* **Minimal correlation-key notification**: each stage publishes `{"id": ...}`; consumers re-read the row from PostgreSQL.
* **Bespoke per-stream payloads**: each stream carries a hand-tailored schema containing only the fields the next stage needs.

## Decision Outcome

Chosen option: **full event record on every stream.** Every pipeline stage publishes the complete event — the shared `LoginEventRecord` serialized with `mode="json"`, carrying `id` as the correlation key and the system-of-record primary key — using the shared stream-publish helper. The stage's own output (`normalized_attributes` for normalization, `enriched_signals` for enrichment) is populated on the record before publishing.

This is consistent with ADR-0002: PostgreSQL remains the system of record. The full-record payload is a transport convenience and an explicitly accepted second copy of the stage's just-written output — never a replacement for the database row. Because the per-stage outputs are write-once in the database, the stream-borne copy cannot drift from the authoritative row in any way that matters under the current design.

### Positive Consequences

* One message shape across the whole pipeline. Every consumer parses the single `data` field as JSON and validates it with `LoginEventRecord` identically, regardless of stage. New stages inherit the pattern with no schema decision to make.
* The full record is a superset: because it carries `id`, a consumer that wants the absolutely-freshest copy of any field can still re-read the authoritative row — the choice is preserved, not removed.
* No mandatory database read sits on the consumer hot path; a stage can act on the payload directly.
* The first-stage pattern (`login_events`) repeats unchanged downstream, so the planning and implementation work for each new stage is uniform rather than novel.

### Negative Consequences

* The stream holds a second copy of the stage's output. This is tolerable only because those outputs are write-once in the database; if a future feature ever mutates an already-written `normalized_attributes` or `enriched_signals`, a replayed or still-pending stream message could disagree with the database row. See *Conditions for Revisiting* below.
* Each stage re-ships fields the next stage does not need — for example, `normalized_events` re-carries `raw_attributes`, which is normalization's *input* and of no interest to enrichment. This is accepted as the price of reusing the one canonical model instead of minting and maintaining bespoke per-stream schemas.
* Messages are larger than a minimal key. Immaterial at the project's scale and stream cap, but noted.

### Conditions for Revisiting

This decision rests on the assumption that each stage's output is written once and never modified. If any post-ingestion stage gains the ability to mutate a previously-written `normalized_attributes` or `enriched_signals` value — for example a re-normalization, correction, or back-fill feature — the write-once assumption no longer holds, and a stream-borne copy could go stale relative to the database. At that point this ADR should be amended or superseded (with a move toward minimal notifications for the affected stream) rather than silently retained.

## Pros and Cons of the Options

### Full event record on every stream

* Good, because the message shape is uniform across the pipeline and every consumer validates it the same way.
* Good, because the payload is a superset — `id` is present, so a consumer can still re-read the authoritative row when it wants to.
* Good, because no database read is forced onto the consumer hot path.
* Good, because it matches the existing `login_events` pattern, so each new stage is mechanical rather than novel.
* Bad, because it places a second, transport-resident copy of the stage's output alongside the system-of-record row (benign only while those outputs are write-once).
* Bad, because it re-ships fields the next stage does not consume.

### Minimal correlation-key notification

* Good, because the database row is the single, unambiguous source of truth — no second copy can ever drift.
* Good, because messages are as small as possible.
* Bad, because it forces every consumer to perform a database read for every message, even when the payload would have sufficed.
* Bad, because it breaks symmetry with the established `login_events` payload, splitting the pipeline into two message conventions.
* Bad, because it adds a moving part (the mandatory read) to every stage's hot path.

### Bespoke per-stream payloads

* Good, because each message carries exactly the fields its consumer needs and nothing more.
* Bad, because it introduces N message schemas to define, version, and test instead of one.
* Bad, because every new consumer requires a fresh schema decision, and the per-stream schemas tend to drift from the shared model over time.
* Bad, because it is the highest-maintenance option for the least benefit at this scale.

## More Information

The transport envelope is unchanged from ADR-0002: the shared stream-publish helper wraps the JSON payload as a single stream field named `data`, and consumers read it with `json.loads(message["data"])` before validating against `LoginEventRecord`. The `id` (a UUID) is both the correlation key carried on every stream and the primary key of the `events` row, so a consumer can always locate the authoritative record from a message.

This principle governs `login_events`, `normalized_events`, and `enriched_events` alike. It does not apply to the Redis Pub/Sub channels (`decisions`, `alerts`), which carry their own purpose-built message models (`RiskDecision`, `AlertMessage`) and are broadcast notifications rather than pipeline hand-offs.
