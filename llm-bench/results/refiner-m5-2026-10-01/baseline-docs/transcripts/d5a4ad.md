# Transcript d5a4ad (D05: Engelse invoer)

### Gebruiker

I want a prompt that has Claude review the task worker's stop behaviour under a systemd restart.

### Model

I found the relevant material in the product docs (runbooks/task-worker covers the SIGINT stop path, `KillMode=mixed`, `TimeoutStopSec=180`, the exit-1 → systemd-restart → cleanup-on-start cycle, and the live stop-test scenarios). Four quick questions to sharpen the prompt:

1. What exactly should the review cover — just the code (SIGINT handling in `src/cli.ts` / `src/worker/task-impl.ts`), just the systemd unit, or both the stop path and the restart/cleanup cycle? [default: both — the stop path and what happens when systemd restarts the worker]
2. Where will this prompt run — Claude Code with access to the repo (and possibly the unit file)? [default: yes, Claude Code in the agent-harness repo]
3. What should the review be judged against — the documented expected behaviour in the runbook, or also general correctness? [default: judged against runbooks/task-worker (SIGINT scenarios, `KillMode=mixed`, `TimeoutStopSec=180`), plus general correctness of the stop/restart logic]
4. What should the deliverable be — a findings report only, or also concrete fix proposals? [default: a findings report with a severity per issue, plus a short proposed fix per finding, but no code changes made]

### Gebruiker

Agreed with your defaults.

### Model

Here's the finished prompt:

```
<context>
I maintain the agent-harness task worker (TypeScript, Node 24), which runs as the systemd service `agent-harness-worker` on the host max2. The worker spawns an MCP child process over stdio, drives Docker containers for prepare/verify, and on failure may exit 1 so systemd restarts it (`Restart=always`), with cleanup of leftover `harness-*` containers happening at startup.

The expected stop behaviour is documented in the product doc runbooks/task-worker (headings "SIGINT tijdens een taak", "Systemd-stopgedrag voor Taak 13 (setup)", "Opruimen", "Live stoptest voor Taak 13"). The key expectations to review against:
- A SIGINT before the host commit (step 5 of the task loop) must abort the running step, kill the running container, end the job as failed with reason "worker gestopt", and perform no git operation.
- A SIGINT after the commit must let the remaining green path (verify_task_against_plan, done) finish before exiting.
- The systemd drop-in /etc/systemd/system/agent-harness-worker.service.d/m3.conf sets KillMode=mixed (SIGINT only to the main process; SIGKILL to the rest of the control group only after the main process exits) and TimeoutStopSec=180. The MCP child has no SIGINT handler, so the harness itself must close the MCP connection in cmdWorker's finally block (src/cli.ts, via connectStdioClient in src/tools/registry.ts) as a second, independent guarantee.
- If a container cannot be confirmed stopped during a job, the worker exits 1; systemd restarts it; the startup cleanup (runWorker: docker rm -f plus a confirming docker ps) must then resolve it, and task jobs must refuse with "achtergebleven harness-container niet aantoonbaar opgeruimd; geen taak uitgevoerd" until that is certain.
</context>

<material>
Review these sources, read them fully before drawing conclusions:
- src/cli.ts (cmdWorker: signal handling, finally block, MCP close)
- src/worker/task-impl.ts (task loop, stop/failure paths, container kill, git-administration scan)
- src/tools/registry.ts (connectStdioClient / transport close)
- __tests__/cli-worker.test.ts (MCP close before return)
- Any other file the stop or startup-cleanup path touches (e.g. the runWorker startup cleanup, docker kill/ps helpers).
The systemd unit file itself lives on max2, not in the repo; treat the documented values (KillMode=mixed, TimeoutStopSec=180, Restart=always, KillSignal=2) from runbooks/task-worker as the given.
</material>

<task>
Review the task worker's stop behaviour under a systemd restart. Trace the full lifecycle: SIGINT received -> abort path -> container kill -> job failure -> process exit -> systemd restart -> startup cleanup -> next job claim. Judge the code against the expected behaviour listed above and against general correctness (signal races, async gaps, missing awaits, unhandled rejection on the abort path, cleanup uncertainty).
</task>

<constraints>
- Review only: do not modify any files, do not run the service or Docker.
- Report every issue you find, each with a severity (critical / major / minor), the file and line, and a one-paragraph explanation of the failure scenario it enables.
- Do not guess at behaviour you cannot verify from the code. If a point depends on something not visible in the repo (for example the exact unit file on max2), say "not verifiable from the code" instead of assuming.
- If the code matches the expected behaviour, say so explicitly per expectation rather than only listing problems.
</constraints>

<done_when>
Each of the four expectations in the context is mapped to the specific code that implements it (file + line), or flagged as missing or divergent. Every finding has a severity and a location. The SIGINT-before-commit and SIGINT-after-commit paths are each traced end to end.
</done_when>

<output_format>
A report in English, in flowing prose with short section headings: (1) how each expected behaviour is implemented, (2) findings ordered by severity, (3) a short list of concrete fix proposals — one per finding, no code changes made.
</output_format>
```

Assumptions:
- The prompt runs in Claude Code with access to the agent-harness repo, so Opus can read the listed files directly.
- The systemd unit file is not in the repo (it lives on max2), so the documented unit values are stated as given rather than asked to be read.
- The review is judged against the runbook's expected behaviour plus general correctness, and the report is written in English even though the source docs are Dutch.
- The review covers both the stop path and the restart/cleanup-on-start cycle, as agreed.
- No code changes are part of the task; fix proposals stay at the description level.

Settings: effort medium (use high if the review turns up subtle async races you want deeply explored).
Would you like any adjustments?
