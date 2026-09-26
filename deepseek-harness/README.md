# DeepSeek Harness op max2

DeepSeek Harness (`dsh` 0.1.5-rc.3) in een geïsoleerde container, met de lokale Qwen-modellen via
Ollama, publiek op `https://deepseek.jp-visser.nl`. Scrum4Me max2 PBI-2; runbook:
ProductDoc `RUNBOOKS/deepseek-harness`.

## Pad van een verzoek

```
browser ─https→ 154 edge-Caddy (Let's Encrypt)
        ─https (LAN 192.168.0.158, Caddy local CA, when2watch-root.crt)→ max2 scrum4me-caddy
            alleen remote_ip 192.168.0.154 (anders 403) · basic_auth jp · token uit de log gefilterd
        ─http→ 172.18.0.1:3080  dsh-web-bridge (socat; firewall: alleen het IP van scrum4me-caddy)
        ─→ 172.30.80.10:3081    socat in de container
        ─→ 127.0.0.1:3080       dsh web (eigen per-proces token → cookie, 30 dagen)
dsh ─→ 172.30.80.1:11434 dsh-ollama-bridge (socat) ─→ 127.0.0.1:11434 Ollama
```

## Bestanden

| Pad | Wat |
|---|---|
| `Dockerfile`, `package.json`, `package-lock.json`, `entrypoint.sh` | image `dsh:0.1.5-rc.3`, alle 585 npm-pakketten vastgepind |
| `docker-compose.yml` | project `deepseek-harness`, container `dsh`, intern netwerk `dsh-internal` (`br-dsh`, 172.30.80.0/24), volumes `dsh-data` (`/data` = `DSH_HOME`) en `dsh-workspace` |
| `host/` | `dsh-firewall.sh` (+ `.service`/`.timer`, elke 2 min), `dsh-ollama-bridge.service`, `dsh-web-bridge.service`, `install.sh` |
| `config/cordis.patch.yml`, `config/apply.sh` | Ollama-route en standaardmodel in het `web`-profiel |

Buiten deze repo (hostconfig): het `deepseek.jp-visser.nl`-blok in `/srv/scrum4me/caddy/Caddyfile`
op max2 én op 154 (geen van beide in versiebeheer).

## Gebruik

- Token na elke start van dsh: `docker logs dsh 2>&1 | grep -o 'token=[^ ]*' | tail -1`, dan
  `https://deepseek.jp-visser.nl/?token=<waarde>` openen en inloggen als `jp`.
- Web-sessies starten read-only; zet de sandboxmodus in de UI op workspace-write om bestanden te laten schrijven.
- Commando's van de agent draaien in Landlock (bwrap werkt niet in een container zonder extra rechten).

## Beheer

```bash
docker compose -f docker-compose.yml up -d --build   # (her)bouwen en starten
sudo host/install.sh                                  # host-units en firewall installeren/verversen
config/apply.sh                                       # profielpatch naar de container
```

Isolatie opnieuw meten: zie het runbook (container → alleen Ollama; 172.18.0.1:3080 alleen vanuit Caddy).

## Bewuste keuzes

- dsh weigert `--host 0.0.0.0` omdat de UI geen login heeft. Hier luistert dsh op loopback en zet
  een socat in de container het door naar het container-IP; bereikbaar is dat alleen via de
  web-bridge, die de firewall alleen voor `scrum4me-caddy` openzet, achter `basic_auth`.
- `OLLAMA_API_KEY=ollama` in de compose is geen geheim: Ollama heeft geen auth, maar de pi-ai-route
  weigert een route zonder sleutel.
- Geen internet voor de agent (geen webzoeken of npm-plugins) — bewuste v1-keuze.
