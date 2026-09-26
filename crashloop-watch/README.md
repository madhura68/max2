# crashloop-watch

Mails within ~10 minutes when a container on max2 crash-loops. Written after ISS-11: on
2026-09-21 a worker rollout (scrum4me-docker #84, DB-role preflight) met a still-elevated
DB role, all three agent containers looped for ~2.5 days, and only the once-a-day health
report noticed it.

- `crashloop-watch.sh` runs as `janpeter` from `crashloop-watch.timer` (every 10 min).
- Alarm when a running container is `restarting`, its `RestartCount` rose by
  `THRESHOLD` (3) or more since the previous run, or it is `unhealthy`.
- One mail per incident, a reminder every 6 h while it lasts, and a mail on recovery.
  State: `~/.local/state/crashloop-watch/state.tsv`.
- Stopped containers are ignored, so parked stacks (video-editor) and one-shots stay quiet.
- Mail uses the health-report route: `MAIL_FROM`/`MAIL_TO` from
  `/opt/server-health/conf/config.env` and `~/.msmtprc`.

```bash
./test.sh        # offline: fake docker, captured mail, 7 scenarios
./install.sh     # /usr/local/bin/crashloop-watch + units, enables the timer
journalctl -u crashloop-watch --since today
```
