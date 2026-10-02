# Transcript 6abd7f (D05: Engelse invoer)

### Gebruiker

I want a prompt that has Claude review the task worker's stop behaviour under a systemd restart.

### Model

The documentation gives me what I need to scope this well — the runbook `runbooks/task-worker` documents the exact stop behaviour under systemd (SIGINT handling, `KillMode=mixed`, `TimeoutStopSec=180`, the exit-1 + restart + cleanup path, and the two live stop-test scenarios). Four questions to sharpen the prompt:

1. Where will this prompt run? [default: Claude Code, checked out in the agent-harness repo, with file access]
2. What exactly should be reviewed: only the stop/shutdown code paths (signal handling, systemd unit drop-in, MCP close in `finally`), or also the restart side (the startup cleanup of leftover `harness-*` containers in `runWorker`)? [default: both — stop and restart, since they form one behaviour]
3. Should the runbook's documented behaviour be the reference standard the code is judged against? [default: yes — deviations between code and `runbooks/task-worker` are findings]
4. Should Opus only report, or may it also propose fixes? [default: report only, each issue with severity; no code changes]

### Gebruiker

Agreed with your defaults.

### Model

All defaults confirmed — here's the finished prompt, scoped from the runbook `runbooks/task-worker` (headings "Opruimen" and the failure-reasons table), which documents the exact expected stop behaviour.

```
<context>
I'm reviewing the agent-harness task worker (harness worker with a task block, running under systemd on max2). I want to know that its stop behaviour under a systemd restart is implemented as documented, before I trust it in production. Review this as a reliability reviewer: you only report, you do not change any code.

The documented reference behaviour is the runbook runbooks/task-worker (headings "Opruimen" and the failure-reasons table; full text at scrum4me-doc://product/bench-agent-harness/runbooks/task-worker if you have access). The expected behaviours, distilled from that runbook:

1. SIGINT arriving before the host git commit (task step 5): the running step is interrupted, any running harness container is killed, the job is closed as failed with the literal reason "worker gestopt", and no git operation touches the worktree.
2. SIGINT arriving after the commit: the green path still runs to completion — verify_task_against_plan, done, and (only on a confirmed push) update_task_status review — with no new model run.
3. A container that cannot be verified as stopped (failed docker kill, or docker ps still shows it): the job is closed (or left, on a lost heartbeat) and the worker exits with code 1 so systemd restarts it (Restart=always).
4. On every startup, runWorker removes all leftover harness-* containers (docker rm -f, then a confirming docker ps) before the first job starts; while that cleanup stays uncertain, subsequent task jobs are refused with the literal reason "achtergebleven harness-container niet aantoonbaar opgeruimd; geen taak uitgevoerd".
5. The systemd unit sets KillMode=mixed (SIGINT only to the main process; SIGKILL to the rest of the control group only after it exits) and TimeoutStopSec=180.
6. Independently of systemd, the harness closes its stdio-MCP child itself: cmdWorker (src/cli.ts) runs await conn?.close() in a finally, where conn comes from connectStdioClient (src/tools/registry.ts), on both the clean path and the SIGINT-abort path.
</context>

<task>
Review the task worker's stop behaviour under a systemd restart: both the stop side (signal handling through to process exit) and the restart side (startup cleanup of leftover harness-* containers). Judge the code against the six expected behaviours above and report every issue you find, each with a severity (critical, major, minor or note), the file and line, and a suggested fix.
</task>

<material>
Start from these files, and follow the code wherever the stop path leads (locate runWorker and the signal handlers yourself):
- src/cli.ts — cmdWorker, the finally that closes the MCP connection
- src/tools/registry.ts — connectStdioClient
- src/worker/task-impl.ts — SIGINT handling and the failure paths (the literal failure reasons in the code are in Dutch)
- the systemd unit file or drop-in for the worker, if it exists in this repo (KillMode=mixed, TimeoutStopSec=180, Restart=always)
- __tests__/cli-worker.test.ts — the test "closes the MCP connection itself before returning"
</material>

<constraints>
- Report only: do not modify any file, do not run the worker or docker commands.
- Do not review the model loop, the verify gate or the dispatch logic; only the stop/restart behaviour chain.
- The production unit runs on max2 and may not live in this repo; if the unit file or drop-in is absent here, say so explicitly instead of assuming it matches.
- Where the code and the runbook disagree, the runbook is the reference: report the code as a deviation.
</constraints>

<done_when>
- Every code path in the stop chain is traced: signal receipt, step interruption, container kill, job closure, MCP connection close, process exit code.
- Each of the six expected behaviours above is checked and marked matches / deviates / not found in code, with the deciding file and line.
- Every finding has a severity, a location and a suggested fix, and findings are ordered by severity.
- The test coverage for the MCP close is assessed: does the test actually pin the behaviour described in expected behaviour 6?
</done_when>

<output_format>
A review report in English, in this order:
1. A verdict in two or three sentences.
2. Findings, most severe first, each as a short entry: severity — file:line — what is wrong — suggested fix.
3. A checklist of the six expected behaviours, each marked matches / deviates / not found in code with the deciding location.
4. A short section on what could not be verified from this repo (for example the unit file on max2).
</output_format>
```

Assumptions:
- The repo checkout you run this in is current and matches what runs on max2.
- The runbook text is in Dutch; I translated the expected behaviours into English and kept the literal (Dutch) failure-reason strings verbatim, since those are the exact code strings.
- The systemd unit file may or may not live in the repo; the prompt tells Opus to flag its absence instead of assuming.
- "Report only" includes suggested fixes in the report, but no edits to files.
- The six reference behaviours are inlined so the prompt works even if Opus can't reach the doc tool; the doc URI is included as a pointer for the full text.

Settings: effort medium. Nothing to attach — Claude Code has file access in the repo checkout.

Want anything adjusted?
