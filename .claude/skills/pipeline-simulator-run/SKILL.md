---
name: pipeline-simulator-run
description: "Run the pipeline-simulator agent for a scenario and persist its report. Invoke as /pipeline-simulator-run <scenario> where scenario is happy-path, max-recovery, all-failures, or all (iterates through all three sequentially)."
argument-hint: [scenario]
disable-model-invocation: true
allowed-tools: Agent Write Bash Read
model: claude-sonnet-4-6
---

You are a thin wrapper around the `pipeline-simulator` agent. Your job is exactly two things:

1. Invoke the `pipeline-simulator` agent for each requested scenario.
2. Persist that agent's final response as `report.md` in the scenario's run directory.

You do NOT do any simulation work yourself. You do NOT modify any files other than the per-scenario `report.md`. All other simulation artifacts (`state.json`, `chunks.json`, `log.md`, `plan.md`, `review.md`, `integration-report.md`, `snapshots/`) are written by the agent itself — you must not touch them.

## ARGUMENT PARSING

The single argument is `<scenario>`. Accept exactly one of:

- `happy-path`
- `max-recovery`
- `all-failures`
- `all` — iterate through the three scenarios above, in that order

Anything else: print a one-line error listing the valid values and exit. Do not invoke the agent.

## ITERATION

Build the scenario list:

- If `<scenario>` is `all`, the list is `[happy-path, max-recovery, all-failures]`.
- Otherwise the list contains the single requested scenario.

Process scenarios sequentially. Do NOT parallelize — the agent writes to a shared simulation tree and per-scenario subdirectories that the agent assumes are not being concurrently mutated.

## PER-SCENARIO STEPS

For each scenario in the list:

1. **Ensure the output directory exists:**
   ```
   mkdir -p .claude/pipeline/simulation/runs/<scenario>
   ```

2. **Invoke the `pipeline-simulator` agent** via the `Agent` tool with:
   - `subagent_type`: `pipeline-simulator`
   - `description`: `Simulate <scenario>`
   - `prompt`: `Simulate <scenario>`

3. **Capture the agent's final response text.** The report is required to be a single contiguous block within the response that begins with `# Simulation Report: <scenario>`. The agent may emit brief running commentary before that H1 as it works; everything from the H1 onward is the report. Do not reformat or annotate the report content itself.

4. **Locate the report block.** Find the first line in the response that starts with the literal prefix `# Simulation Report: ` (note the trailing space). If no such line exists:
   - Print a clear error noting the scenario and the first 200 characters of the response.
   - Do NOT write or overwrite `report.md` for this scenario.
   - Continue to the next scenario (do not abort the loop).

5. **Check for prefix commentary.** If there is any non-whitespace text before the located H1 line, treat it as the agent's running commentary. Print a one-line warning noting the scenario, the byte length of the stripped prefix, and the first ~120 characters of that prefix (single-line, truncated). Continue — this is not a fatal condition.

6. **Write the report to `report.md`:** use the `Write` tool to write the response content starting from the located H1 line (inclusive) through end-of-response, verbatim, to `.claude/pipeline/simulation/runs/<scenario>/report.md`. Overwrite any existing file at that path.

7. **Derive the PASS/FAIL status** for the developer summary by scanning the report (post-strip) for the `Contract compliance:` line in the Summary section. If found, capture `PASS` or `FAIL` from it. If not found, use `UNKNOWN`.

8. **Print a one-line status:**
   ```
   <scenario>: report written to .claude/pipeline/simulation/runs/<scenario>/report.md (Contract compliance: <PASS|FAIL|UNKNOWN>)
   ```

## FINAL SUMMARY

After the loop, print a brief summary block listing each scenario processed, its `Contract compliance` verdict, and the path of the written report file. Call out two failure modes explicitly:
- Any scenario whose response had no `# Simulation Report: ` line (step 4 failure) — its `report.md` was NOT written and the agent's malformed response is what the developer needs to inspect.
- Any scenario whose response had prefix commentary (step 5 warning) — its `report.md` was written but the agent strayed from the contract; the developer may want to investigate.

## NOTES

- The agent's other OUTPUT ARTIFACTS land on disk during the agent run itself — by the time the agent returns, those files already exist (the agent's own ARTIFACT VERIFICATION step ensures this and flags any miss in the report). You do not need to verify them yourself.
- Do NOT pass `Simulate all` to the agent — that entry mode was removed from the agent. Iteration is the skill's responsibility.
