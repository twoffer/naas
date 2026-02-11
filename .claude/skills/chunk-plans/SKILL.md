---
name: chunk-plans
description: Invokes the technical-architect subagent to create one or more chunked implementation plans for a given functional spec file
disable-model-invocation: true
context: fork
agent: technical-architect
argument-hint: [spec-file] [prereq-spec-file]
---

You are the technical-architect agent.

**IMPORTANT:** Follow all behavioral guidelines from `docs/AI-AGENT-PRINCIPLES.md`.

Your task is to create a chunked implementation plan for the specification in $ARGUMENTS[0]. This spec is the live source of truth for the implementation plan.

Spec document: $ARGUMENTS[0]
Prerequisites: Everything specified in $ARGUMENTS[1]

Requirements for chunking:
1. Each chunk must be completable by the feature-implementer in a single Claude Code session (~30-45 min of agent work, roughly 200-500 lines of new code).
2. Each chunk must have a standalone verification ("Done When") that proves it works WITHOUT requiring later chunks.
3. Chunks must be ordered so each builds on the previous.
4. The first chunk for any new service is always: scaffold (directory structure, Dockerfile, docker-compose.yml entry, FastAPI app skeleton with health endpoint, naas_shared imports verified).
5. The last chunk is always: integration smoke test (verify this spec's output connects to downstream consumers or can be manually tested end-to-end).

Output format:
- One markdown document per chunk
- Folder: `docs/implementation-plans/`
- Filename: "plan_[Base filename of $ARGUMENTS[0]]_chunk[N]" where [N] is the 0-based index ordering the chunks
- Each chunk document contains:
    - Scope (exactly which files)
    - Steps (numbered, with file paths and implementation details)
    - naas_shared imports needed
    - References to appropriate sections in the spec document where applicable (Do NOT rewrite the spec - the implementer MUST refer to the given spec document as the live source of truth)
    - Done When (concrete verification commands)
    - Next Chunk Preview (one sentence on what comes next with explicit instructions to the implementer NOT to proceed to the next chunk)
