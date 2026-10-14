# dev-docker — bediening (IDEA-258)

Dev-Docker op `max2` voor de Mac: een aparte rootless Docker-engine onder gebruiker `devdock` (user-slice met `MemoryMax`), met één
`dev-postgres` op `192.168.0.158:55432`, bereikbaar via `docker --context max2-dev`. Ontwerp: [SPEC.md](SPEC.md), plan: [PLAN.md](PLAN.md).
De productie-engine van `max2` (rootful, `/var/run/docker.sock`) wordt niet aangeraakt.

## Bestanden

| Pad | Rol |
|---|---|
| `host/bootstrap.sh` | root: preflight met headroomgate, pakketten, `devdock`, subid, slice-drop-in, firewall-units, linger, ufw |
| `host/dev-docker-firewall.sh`, `host/systemd/dev-docker-firewall.{service,timer}` | root: keten `dev-docker-in` en de sprong op `INPUT`-positie 1 (LAN-grens) |
| `host/install-user.sh` | `devdock` via SSH-login: rootless engine, context, `.env`, compose, user-units, images |
| `host/compose.yml`, `host/init/` | `dev-postgres` (digest-gepind), rol `dev`, `pg_hba.conf`, register `devmeta.databases` |
| `host/prune.sh`, `host/pull-images.sh`, `host/images.txt` | wekelijks opruimen (`--dry-run`, `--selftest`), standaardimages |
| `host/recovery-test.sh`, `host/proof-checks.sh`, `host/sampler.sh` | proefscripts: afgedwongen herstel, root-leescontroles met `SUMMARY`, 5 s-sampler |
| `secretscan.sh` | per bewijscommit: scant de gestagede blobs op wachtwoord- en URL-patronen |

## Uitrol (kort; de exacte regels staan in PLAN.md taak 2)

1. Root-scripts naar `~/dd-run/` op max2 (niet naar het wereld-schrijfbare `/tmp`): `scp -r bootstrap.sh dev-docker-firewall.sh systemd <sleutel>.pub max2:dd-run/`.
2. `ssh -t max2 "sudo bash ~/dd-run/bootstrap.sh --preflight-only --pubkey-file … --floor-gib 12.0 --series '<GiB>:<bron>'"`, daarna zonder `--preflight-only`.
3. Mac: alias `max2-dev` in `~/.ssh/config`; `rsync -a --delete dev-docker/host/ max2-dev:dev-docker-src/ && ssh max2-dev bash dev-docker-src/install-user.sh`.
4. Mac: `docker context create max2-dev --docker host=ssh://max2-dev`; controle `docker --context max2-dev info --format '{{.Name}} {{.SecurityOptions}}'`.
5. Beide bootstrap- en install-scripts zijn idempotent; een tweede run meldt alleen `SAME`.

## Gebruik

De skill `max2-docker` (s4m-queue-repo, `scripts/max2-docker`) is de enige bedoelde route: `db create|run|url|drop|list|keep`, `cleanup --dry-run`, `status`.
`db run <naam> -- <testcommando>` zet `DATABASE_URL` en de `PG*`-variabelen alleen in de omgeving van het kindproces; het wachtwoord staat nooit in argv.

## Rollback

Volledig omkeerbaar zonder productie te raken, in deze volgorde: als devdock `docker compose down` in `~/dev-docker` en `systemctl --user disable --now dev-postgres.service dev-docker-prune.timer docker`; als root `loginctl disable-linger devdock`, `loginctl terminate-user devdock` (of `systemctl stop user@<uid>.service`; `userdel` weigert anders vanwege lopende processen), ufw-regel verwijderen (`ufw delete` op het regelnummer of de comment), `systemctl disable --now dev-docker-firewall.timer dev-docker-firewall.service`, de sprong verwijderen (`iptables -D INPUT -m comment --comment dev-docker -j dev-docker-in`, herhalen tot `-D` faalt: na de herstelproef kunnen er tijdelijk twee hebben bestaan en `-X` weigert op een keten die nog in gebruik is), de keten legen en verwijderen (`iptables -F dev-docker-in && iptables -X dev-docker-in`), een eventueel restant van de herstelproef verwijderen (`iptables -D INPUT -s 192.0.2.254/32 -m comment --comment dd-recovery-test -j DROP`, herhalen tot `-D` faalt), de unitbestanden en `/usr/local/sbin/dev-docker-firewall.sh` verwijderen, `userdel -r devdock`, subid-regels verwijderen, en **daarna pas** de slice-drop-in verwijderen plus één afsluitende `daemon-reload`. De pakketten `uidmap` en `slirp4netns` blijven staan (onschadelijk; vermelden in het bewijs). Op de Mac de context en de alias verwijderen. Docker Desktop wordt pas in fase 4 verwijderd; tot dan is terugvallen `docker context use desktop-linux` plus Desktop starten.
