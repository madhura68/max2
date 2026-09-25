def reclaimable(messages, now, cli_timeout=4 * 3600, mcp_timeout=300):
    out = []
    for m in messages:
        if m.get("status") != "claimed":
            continue
        via = m.get("claimed_via")
        claimed_at = m["claimed_at"]
        if via == "mcp":
            renewed = m.get("lease_renewed_at")
            last = claimed_at if renewed is None else max(claimed_at, renewed)
            if now - last > mcp_timeout:
                out.append(m)
        elif via == "cli":
            if now - claimed_at > cli_timeout:
                out.append(m)
    return [m["id"] for m in sorted(out, key=lambda m: (m["claimed_at"], m["id"]))]
