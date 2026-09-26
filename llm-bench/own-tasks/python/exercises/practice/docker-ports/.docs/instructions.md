# Docker ports

Our worker containers get host ports from a range that shifts on every redeploy, so tooling must
read the real ports from `docker ps` instead of trusting documentation.

Implement `published_ports(ps_output, prefix)`.

`ps_output` is the text printed by `docker ps --format '{{.Names}}\t{{.Ports}}'`: one container
per line, name and ports separated by a single tab. The ports column is a comma-separated list
(`", "`) of entries such as:

- `0.0.0.0:18082->8080/tcp` — published host port 18082
- `[::]:18082->8080/tcp` — the same port on IPv6 (count it once)
- `127.0.0.1:3001->3000/tcp` — published on one address
- `0.0.0.0:18080-18081->8080-8081/tcp` — a range: host ports 18080 and 18081
- `8080/tcp` — exposed but **not** published: ignore
- `0.0.0.0:5353->5353/udp` — UDP: include it too; ports are numbers regardless of protocol

The ports column may be empty (the line then ends right after the tab, or has no tab at all).
Blank lines must be ignored.

Return a dict mapping every container whose name starts with `prefix` to a **sorted list of
unique host ports (ints)**. Containers matching the prefix without published ports map to `[]`.
Containers not matching the prefix are left out.
