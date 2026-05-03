# 2. Use Redis Streams as the Event Pipeline Message Broker

* Status: accepted
* Date: 2026-02-10
* Deciders: Tony

## Context and Problem Statement

NAAS processes a pipeline of identity events: ingestion → normalization → enrichment → risk evaluation. The pipeline must support multiple consumer services running concurrently with at-least-once delivery semantics, ordered per-key processing, and the ability to replay events for debugging and demos. Projected throughput is approximately 10 events/sec at demo scale, with the design needing to accommodate growth without architectural rework.

What message broker should sit between the pipeline stages?

## Decision Drivers

* Operational simplicity for a solo developer running everything via Docker Compose
* Throughput sufficient for the demo (10 events/sec) with headroom for growth
* Consumer groups for parallel processing across replicas of a stage
* At-least-once delivery with explicit acknowledgement
* Infrastructure footprint — every additional container is additional surface area
* Existing tooling reuse: NAAS already uses Redis for caching and pub/sub

## Considered Options

* Redis Streams (Redis 7.4+)
* Apache Kafka
* RabbitMQ
* NATS JetStream
* In-process queue (e.g., `asyncio.Queue`)

## Decision Outcome

Chosen option: **Redis Streams**, because it provides consumer groups, at-least-once delivery, and replay semantics in a single container that NAAS is already running, at throughput two to three orders of magnitude above what the demo needs, with sub-millisecond latency. Kafka would deliver superior durability and throughput but at a setup and operational cost that is wildly disproportionate to the actual requirements.

### Positive Consequences

* Single-container broker — no Zookeeper, no separate cluster to operate.
* Consumer groups enable horizontal scaling within a pipeline stage when needed.
* Sub-millisecond latency keeps the end-to-end pipeline responsive.
* Reuses Redis infrastructure already in place for caching (60s TTL on LDAP enrichment lookups) and ephemeral state.
* Replay is straightforward — streams retain entries until trimmed, and `XREAD` from `0` replays from the beginning.

### Negative Consequences

* Less durable than Kafka in the catastrophic-failure case (Redis AOF is good but not equivalent to Kafka's replicated log). Mitigated by writing canonical event records to PostgreSQL — the stream is the transport, the database is the system of record.
* Redis Streams' consumer-group model has fewer battle-tested patterns documented than Kafka's. Mitigated by NAAS's modest scale and well-defined consumer topology.

### Scaling Path

This decision is not permanent and has a documented escalation path:

* 0–1,000 events/sec: Redis Streams (current design)
* 1,000–10,000 events/sec: Redis Cluster
* 10,000+ events/sec: Migrate to Kafka

The migration boundary is well above NAAS's projected scale, so this ADR is unlikely to need revisiting for the lifetime of the project. The point of documenting the path is to demonstrate that the choice is deliberate and bounded, not naive.

## Pros and Cons of the Options

### Redis Streams

* Good, because it adds zero new infrastructure components
* Good, because consumer groups + acknowledgement give correct semantics for a pipeline
* Good, because throughput exceeds requirements by 1,000x
* Good, because replay-from-zero is a one-liner
* Bad, because durability guarantees are weaker than Kafka's
* Bad, because the ecosystem of monitoring and management tooling is smaller

### Apache Kafka

* Good, because it is the industry-standard event log
* Good, because durability and replay semantics are best-in-class
* Good, because it would carry strong "enterprise streaming" signal in a portfolio
* Bad, because the operational footprint (brokers, controllers or Zookeeper, schema registry) is overwhelming for a solo demo project
* Bad, because the resource cost (multi-GB heap per broker) bumps against the project's cloud budget if deployed
* Bad, because designing for 10,000x the actual throughput is engineering for a problem that does not exist

### RabbitMQ

* Good, because it is well-understood and widely deployed
* Good, because routing flexibility (exchanges, topics) is excellent
* Bad, because it is a separate container with its own operational model
* Bad, because it is push-based by default, which fits NAAS's pull-based stage processing less naturally
* Bad, because replay is awkward — RabbitMQ is a queue, not a log

### NATS JetStream

* Good, because it is operationally simple, like Redis
* Good, because it has strong streaming semantics and replay
* Bad, because it adds a new infrastructure component when Redis is already present
* Bad, because the team (i.e., the solo developer) has no prior NATS operational experience

### In-process queue

* Good, because it has zero infrastructure cost
* Bad, because it forecloses on multi-service architecture — every stage would have to live in the same process
* Bad, because it eliminates the ability to demonstrate event-driven, horizontally-scalable design, which is itself a portfolio goal
* Bad, because crashes lose in-flight events

## More Information

The "stream is transport, database is system of record" principle is what makes the durability tradeoff acceptable. Every event is persisted to the PostgreSQL `events` table during the ingestion stage, before any downstream stage acknowledges it. Loss of the Redis stream itself is an inconvenience (some events would need to be replayed from PostgreSQL) but not a data loss event.
