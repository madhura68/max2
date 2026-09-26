# Queue reclaim

Our message queue hands out work by *claiming* a message. A claim can die with its worker, so a
periodic sweep puts stuck messages back. Implement `reclaimable(messages, now, cli_timeout=4 * 3600, mcp_timeout=300)`.

Each message is a dict with:

- `id` (str)
- `status`: one of `"pending"`, `"claimed"`, `"done"`, `"failed"`, `"cancelled"`
- `claimed_via`: `"mcp"` or `"cli"` (only meaningful when `status == "claimed"`)
- `claimed_at` (epoch seconds, int) — when it was claimed
- `lease_renewed_at` (epoch seconds, int or `None`) — last lease heartbeat (MCP claims only)

Rules:

1. Only messages with `status == "claimed"` can be reclaimed.
2. An **MCP** claim is reclaimable when the most recent of `lease_renewed_at` and `claimed_at`
   is **strictly more** than `mcp_timeout` seconds before `now`. A missing (`None`) or absent
   `lease_renewed_at` counts as "never renewed".
3. A **CLI** claim is reclaimable when `claimed_at` is strictly more than `cli_timeout` seconds
   before `now`. CLI claims ignore `lease_renewed_at`.
4. A claimed message with any other or missing `claimed_via` is never reclaimed (unknown owner:
   leave it alone).
5. Return the ids ordered by `claimed_at` ascending (oldest first); ties are broken by `id`.
6. Do not modify the input.
