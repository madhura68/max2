# Transcript dbf02e (D05: Engelse invoer)

### Gebruiker

I want a prompt that has Claude review the task worker's stop behaviour under a systemd restart.

### Model



The docs give me the expected stop behaviour (runbook `runbooks/task-worker`, sections "Opruimen" and "Systemd-stopgedrag voor Taak 13"), so the prompt can be grounded in that. Four questions before I write it:

1. Where will the review run? [default: Claude Code in a checkout of the agent-harness repo, read-only]
2. Static code review only, or should it also run the live stop test on max2 (`kill -INT` on the main PID, both scenarios: stop during verify, stop after commit)? [default: static review only; a live test on max2 only after explicit confirmation]
3. Scope: only the TASK_IMPLEMENTATION stop path (`src/worker/task-impl.ts`, `src/cli.ts`), or also the shared idea-chat stop path? [default: task path plus the shared `cmdWorker`/MCP-close code it relies on]
4. Output format? [default: a list of issues each with severity and file/line, plus a table: expected behaviour (per runbook) vs. what the code actually does, per stop scenario]

### Gebruiker

Agreed with your defaults.

### Model



```
<context>
I maintain the agent-harness product. Its task worker runs as a systemd service (`agent-harness-worker.service`) on a VPS, and it has a documented stop behaviour that I want verified against the actual code. The authoritative description of that behaviour is in the product documentation, folder `runbooks`, slug `task-worker` — read the sections "Opruimen" and "Systemd-stopgedrag voor Taak 13" before reviewing, and treat them as the specification.

The worker's stop path is the TASK_IMPLEMENTATION path in `src/worker/task-impl.ts` (its `runTaskImplementation` / `runWorker`), driven from `src/cli.ts` (`cmdWorker`), including the shared MCP client close and process-exit code those paths rely on.
</context>

<task>
Review the task worker's stop behaviour under a systemd restart, as a code reviewer. For every stop scenario in the runbook specification, trace the code path from receiving the stop signal to process exit, and report where the code matches, deviates from, or cannot be verified against the documented behaviour.
</task>

<constraints>
- Static review only: read the code and the runbook; do not run the service, do not connect to the VPS, and do not modify any file.
- If you want to run the live stop test on max2 (kill -INT on the main PID, stop during verify, stop after commit), stop and ask for my explicit confirmation first; do not run it on your own initiative.
- Do not review the idea-chat stop path unless it shares code with the task path; only include shared code the task path actually depends on.
- Do not fix anything; report only.
</constraints>

<done_when>
- Every stop scenario named in the runbook sections "Opruimen" and "Systemd-stopgedrag voor Taak 13" has a row in the comparison table: expected behaviour (quoted or paraphrased from the runbook) vs. what the code actually does, with file and line references.
- Every deviation or gap is listed as a separate issue with a severity (critical, major, minor) and a one-line explanation of the consequence.
- Anything the code cannot settle (e.g. systemd unit settings on the VPS, runtime state) is explicitly marked "not verifiable from the code", not guessed.
</done_when>

<output_format>
1. A table: scenario | expected (per runbook) | actual (per code, with file:line) | status (match / deviates / not verifiable).
2. The issue list, each with severity and file:line.
3. A short closing verdict in a few sentences: is the stop behaviour safe for systemd restart as documented?
</output_format>

<check_in>
Stop and ask before: running any live test on the VPS, and before making any change to the code.
</check_in>
```

Assumptions:
- The runbook's two sections are the complete specification of the stop behaviour; no other doc defines it.
- "Systemd restart" means the stop side (SIGINT/SIGTERM handling, clean exit), not the start side (Restart=, After=) — the unit file itself is on the VPS and out of scope, so unit-level settings are flagged as not verifiable.
- The repo checkout available to Claude Code is current with what runs on max2.
- The code lives at the paths named (`src/worker/task-impl.ts`, `src/cli.ts`); if the review finds the task path elsewhere, Opus should say so rather than guess.

Settings: effort medium. Make sure the product documentation (runbook `runbooks/task-worker`) and the repo checkout are available to the session — if the docs live in a separate tool, tell Opus how to read them.

Want me to adjust anything?
