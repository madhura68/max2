# Transcript eb3d0b (D05: Engelse invoer)

### Gebruiker

I want a prompt that has Claude review the task worker's stop behaviour under a systemd restart.

### Model

I found the relevant documentation. The task-worker runbook contains detailed information about systemd stop behavior, including:
- `KillMode=mixed` and `TimeoutStopSec=180` configuration
- SIGINT handling during different phases (verify vs post-commit)
- Container cleanup procedures
- Expected behavior when stopped at various points

Now I have enough context to ask targeted questions:

1. **What specific aspect of the stop behavior do you want reviewed?** [default: a complete review covering both scenarios (stop during verify and stop after commit), the KillMode configuration rationale, and container cleanup]

2. **Should this review be actionable (suggesting changes if problems are found) or advisory (reporting issues for you to decide)?** [default: advisory - report all findings with severity, you decide on changes]

3. **Do you have the actual systemd unit file content to provide, or should Opus evaluate based only on the documented expectations in the runbook?** [default: only the runbook documentation is available; no actual unit file will be provided]

4. **What output format do you need?** [default: a structured review with sections for each scenario, findings with severity levels, and source references from the documentation]

### Gebruiker

Agreed with your defaults.

### Model

```
<context>
You are reviewing the task worker's systemd stop behavior based on the documented expectations in the product runbook (bench-agent-harness/runbooks/task-worker). The review is for the engineering team who needs to understand whether the documented behavior is correct and safe.
</context>

<material>
Review the following documentation source: bench-agent-harness/runbooks/task-worker
Focus on the sections describing systemd stop behavior, specifically:
- KillMode configuration
- TimeoutStopSec settings
- SIGINT handling during verify vs post-commit phases
- Container cleanup procedures
</material>

<task>
Review the documented task worker stop behavior under systemd restart and evaluate whether it is correct, complete, and safe. Report all issues you find with their severity levels.
</task>

<constraints>
- Evaluate based only on the documented expectations in the runbook; do not assume an actual systemd unit file exists unless documented.
- Cover both scenarios: stopping during the verify phase and stopping after commit.
- Assess the rationale for KillMode=mixed and TimeoutStopSec=180.
- For each finding, cite the specific section or claim from the documentation as the source.
- If something is not stated in the material, state "not stated in the material" rather than guessing.
- Report all issues with a severity level per issue (e.g., low/medium/high/critical).
</constraints>

<done_when>
Your review covers: (1) the two stop scenarios (verify phase and post-commit), (2) the KillMode and TimeoutStopSec configuration, (3) container cleanup behavior, and (4) at least one explicit statement about whether the documented behavior is correct/safe or has issues.
</done_when>

<output_format>
A structured review with the following sections:
1. Overview of what is documented
2. Findings table with columns: Issue | Severity | Source (folder/slug/heading if applicable) | Recommendation
3. Conclusion on whether the documented behavior is correct and safe
Write in clear, professional language suitable for an engineering audience.
</output_format>

<check_in>
Do not proceed beyond this review. After delivering your findings, stop and wait for further instructions before suggesting any changes to the runbook or configuration.
</check_in>
```

**Assumptions:**
- The task-worker runbook contains the relevant documentation about systemd stop behavior.
- This is an advisory review; you will decide whether to make changes based on the findings.
- No actual systemd unit file content will be provided for comparison.
- The output should be structured and citable for engineering review.
- Effort level: medium (standard analysis task).

Would you like anything adjusted before you use this prompt?
