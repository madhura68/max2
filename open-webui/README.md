# Open WebUI on max2

Browser chat for the local Ollama models at **https://ollama.jp-visser.nl** (PBI-6). Same
isolation pattern as `../deepseek-harness`.

## Request path

```
browser → 154 edge Caddy (LE cert) → LAN https://192.168.0.158 (tls internal, when2watch trust pool)
        → max2 Caddy: only remote_ip 192.168.0.154, basic_auth user jp
        → 172.18.0.1:3082 owui-web-bridge (socat; firewall: only scrum4me-caddy's IP)
        → open-webui container 172.30.81.10:8080 (network owui-internal, no internet, no LAN)
        → 172.30.81.1:11434 owui-ollama-bridge (socat) → Ollama 127.0.0.1:11434
```

**One login.** After `basic_auth`, Caddy sets a fixed `X-Webui-Email: jp@jp-visser.nl` and
Open WebUI trusts it (`WEBUI_AUTH_TRUSTED_EMAIL_HEADER`); `jp` is the first user and admin.
Open WebUI's own API calls send `Authorization: Bearer <jwt>`, which replaces the browser's
Basic credentials, so Caddy lets Bearer requests through **without** basic_auth and **strips**
the identity headers on that route. Open WebUI then checks the JWT. A JWT can only be obtained
behind basic_auth, because signup and the password form are off (`ENABLE_SIGNUP=false`,
`ENABLE_LOGIN_FORM=false`). Keep all three settings together: changing one opens a hole.

## Files

| File | What |
|---|---|
| `docker-compose.yml` | own compose project `open-webui`, pinned image, network `owui-internal` / `br-owui` 172.30.81.0/24 |
| `.env` | `WEBUI_SECRET_KEY` (0600, not in git; losing it logs everyone out) |
| `host/owui-ollama-bridge.service` | 172.30.81.1:11434 → 127.0.0.1:11434 |
| `host/owui-web-bridge.service` | 172.18.0.1:3082 → 172.30.81.10:8080 |
| `host/owui-firewall.sh` + `.service` + `.timer` | br-owui may only reach 11434; 3082 only from the current Caddy IP (re-applied every 2 min) |
| `host/install.sh` | installs and enables the host units (sudo) |

The Caddy blocks are not in this repo: `/srv/scrum4me/caddy/Caddyfile` on max2 (`ollama.jp-visser.nl`)
and on 154 (edge). Edit them in place (same inode) and `caddy reload`.

## Operations

```bash
docker compose -f ~/Development/max2/open-webui/docker-compose.yml up -d     # start / apply changes
sudo bash ~/Development/max2/open-webui/host/install.sh                        # after the network exists
docker logs -f open-webui
```

- **Models:** pull, pick or delete them in the UI (Admin → Settings → Models) or with `ollama pull` on
  max2. Downloads run through Ollama on the host; the container itself has no internet.
- **Upgrade:** change the image tag, `docker compose pull && docker compose up -d`.
- **Password change:** in your own terminal (needs a TTY) `docker exec -it scrum4me-caddy caddy hash-password`,
  replace the hash in the max2 Caddyfile, reload.
- **Documents/RAG:** `OFFLINE_MODE` means Open WebUI cannot download its local embedding model, so file
  uploads for RAG will not work until an embedding source is configured.
