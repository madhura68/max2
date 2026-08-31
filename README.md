# max2

Host-repo voor `max2`, de tweede host van de Forgejo-Runner-tweemachinepool.

## Wat hier staat

| Pad | Inhoud |
|---|---|
| `hosts/max2/` | Host-overlay: `runner-config.yml` zonder secrets, preflight-uitkomsten, inventarisatie (volgt) |
| `evidence/` | Metingen, testbewijs en maintenance-records van deze host (volgt) |

## Wat hier bewust NIET staat

De gedeelde runnerbundel (`compose.yaml`, `labels.txt`, `scripts/`, de
cyclecontroller) staat **uitsluitend** in de `scrum4me-server`-repo. Die is de
canonieke bron. `max2` rolt uit vanaf een gepinde commit-SHA daaruit; de bundel
wordt hier niet gekopieerd, omdat twee kopieën twee bronnen van waarheid zijn en
het ontwerp byte-identieke bundels op beide hosts eist.

Ontwerp en runbook: `docs/forgejo-runner-pool/` in de `scrum4me-server`-repo.

## Harde regels

- Secrets staan nooit in deze repo. Het runnertoken leeft alleen als
  `/opt/forgejo-runner/credentials/forgejo-token` op de host, mode `0600`.
- Deze host heeft een eigen runnerrecord, UUID en token; die worden nooit gedeeld
  met of gekopieerd van `scrum4me-server`.
