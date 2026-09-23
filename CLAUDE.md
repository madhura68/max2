# CLAUDE.md — max2

Host-repo voor de Ubuntu-machine `max2`. Het lopende werk is de tweede host van de Forgejo-Runner-tweemachinepool; de repo is breder bedoeld als plek voor alles wat op deze machine draait.

## Scrum4Me-product

- **Naam:** max2
- **product_id:** `cmsx8wyex0000hk7rx1428yyl`
- **Code:** `SYSTEM`
- **Omschrijving in Scrum4Me:** "Max2 ubuntu systeem"
- **Definition of Done:** nog niet geregistreerd in Scrum4Me (veld is leeg, gecontroleerd 2026-08-31). Tot JP er een vastlegt geldt voor het runnerpool-werk §9 "Definitie van een stabiele pool" uit het migratieontwerp in de `scrum4me-server`-repo: zeven aaneengesloten dagen waarin alle daar genoemde criteria groen zijn.
- **Lopend werk:** Forgejo Runner tweemachinepool. `max2` wordt als eerste uitgerold en afzonderlijk bewezen (stap D en E) vóórdat `scrum4me-server` wordt genormaliseerd, zodat een configuratiefout nooit de enige werkende runner uitschakelt. Het ontwerp heeft GO (delta-review R12, ronde 3); het uitvoerbare implementatieplan bestaat nog niet.

- **Verify:** deze repo bevat nog geen code. De verificatiecommando's worden vastgelegd in stap B van het migratieontwerp, samen met de bundel zelf.

<!-- BEGIN scrum4me-agent-workflow v1 -->
## Scrum4Me-methodiek en MCP-queue

Volgt de globale Scrum4Me-methodiek (`~/.claude/rules/scrum4me-methodiek.md` voor Claude; de "Scrum4Me-methodiek"-sectie in `~/.codex/AGENTS.md` voor Codex). Niet-triviaal werk: plan → Sprint/PBI/Story/Taak via de `scrum4me` MCP → `update_task_status` per laag → docs in de DB. Volg de bestaande goedkeuring en hardstop na materialisatie; voor alleen documentatie/instructies geldt de doc-only-uitzondering.

**Context.** Lees `product_id` uit het Scrum4Me-productblok in de repo-`CLAUDE.md`/`AGENTS.md`. Ontbreekt het, werk normaal zonder een product-ID te raden.
`mcp__scrum4me__get_context({ product_id })` → product, alle `active_sprints` en `agent_guide`. Kies de sprint binnen de actuele opdracht; lees `get_sprint_context({ sprint_id })` voor stories/taken en voeg `task_id` alleen toe voor het volledige taakplan. Gebruik `get_ideas_context({ product_id })` alleen voor ideeën. Geef expliciet bekende `agent.runtime` en `agent.model_id` mee (CLAUDE/CODEX + exact model-ID); laat onbekende gegevens weg. Ontbreekt de guide, gebruik `get_agent_guide` met dezelfde agentinvoer. Context autoriseert geen volgende story.

**Queue gebruiken.** Volg de `s4m-queue`-skill bij queue-handelingen. Gebruik de `mcp__scrum4me__queue_*`-tools met je eigen identiteit; de CLI is fallback bij ontbrekende MCP-toegang of identiteit.
- Stuur een geautoriseerde opdracht/vraag met `queue_push({ to, type, body, ... })`: `task`, `info` of `review_request`. Voor `task`/`review_request`: `cwd` op de ontvangende host en `meta.task: { objective, verification, response_format }`; geef `meta.task.repo` expliciet mee als die niet uit `cwd` kan worden afgeleid.
- Koppel bestaand werk met het meest specifieke `task_id`, `story_id` of `sprint_id` als toolparameter. Gebruik echte IDs uit de context, geen zichtbare codes. De tool leidt `product_id` en bovenliggende IDs af naar `meta.work_item`; geef geen losse `product_id`-parameter aan `queue_push`. Zonder bestaand werkitem geen ID verzinnen.
- Bewaar `message_id`; lees antwoorden met `queue_wait_reply({ message_ids: [...] })`. Ontvang werk via `queue_next`, lees body én metadata en werk binnen `meta.task.cwd`. Rond af via `queue_done`/`queue_fail` met `message_id` en `claim_token`; sluit CLI-claims via de CLI af.

**Reviewdocumenten via metadata.** Voeg bij `review_request` de beoordeelde bronnen toe als `meta.review_documents: { version: 1, items: [...] }`, naast `meta.task`.
- Iedere referentie bevat `key`, `title`, `product_id` en `sha256` van de exacte documentinhoud. Gebruik `source: "product_doc"` met `doc_id` + `revision_id`, of `source: "git"` met relatief `.md`-`path` + volledige gepubliceerde `commit_sha`.
- Lees als reviewer de gekoppelde exacte revisie/commit en controleer de SHA-256; alleen de body of de nieuwste versie lezen volstaat niet. Ontbreekt de gepinde bron of wijkt de hash af, voer de review niet uit: meld de fout en rond een geclaimd verzoek af met `queue_fail`.
- Rapporteer tegen deze pins en antwoord via `queue_done`; het `reviewed`-antwoord blijft via `in_reply_to` gekoppeld aan de reviewdocumenten van het verzoek.
<!-- END scrum4me-agent-workflow v1 -->

## Rol van deze repo

Host-overlay. De gedeelde runnerbundel is canoniek in de `scrum4me-server`-repo en wordt hier **niet** gekopieerd: twee kopieën zijn twee bronnen van waarheid en maken de byte-identiek-eis onbewijsbaar. `max2` rolt uit vanaf een gepinde commit-SHA van die repo.

Deze host draait al productiewerk. Volgens IDEA-185 in Scrum4Me dragen hier onder meer de workers, video-editor, media-organizer, agent-codex en de ops-agent; die last is niet op de host geverifieerd en moet in stap A alsnog gemeten worden, omdat de headroomgate van §7.8 tegen de laagste `MemAvailable` **onder eigen productielast** rekent.

| Pad | Inhoud | Bestaat nu |
|---|---|---|
| `hosts/max2/` | `runner-config.yml` zonder secretwaarden, preflight-uitkomsten, hostinventarisatie | nee — ontstaat in stap D |
| `evidence/` | Metingen, testbewijs en maintenance-records van deze host | nee — ontstaat in stap A en E |

## Oriëntatie

| Bestand | Waarvoor |
|---|---|
| `docs/forgejo-runner-pool/migratieontwerp.md` in de **`scrum4me-server`-repo** | **Begin hier.** Het goedgekeurde ontwerp: doelarchitectuur, trustgate, cyclecontroller, migratievolgorde stap A–H, stabiliteitsdefinitie, monitoring en rollback |
| §5 van dat ontwerp | Wat per host uniek is: runnernaam `max2-forgejo-runner-02`, eigen UUID, eigen token, eigen DinD-volume |
| §7.8 van dat ontwerp | Resourcecaps en de preflightdrempels die op **deze** host moeten slagen voordat er iets wordt gemuteerd |
| Stap D, E en F in §8 | Uitrol van `max2`, het afzonderlijke bewijs en de pooltests |
| `docs/forgejo-runner-pool/reviews/` in die repo | Alle reviewrondes: R1–R10, delta-review R11 en delta-review R12 |

## Infra-issues melden

Deze repo hoort bij een **host-product**. De agent-guide van Scrum4Me is hierover bindend: loopt er op deze host iets mis dat niet bij één taak hoort — een service die omvalt, een claim die verdwijnt, een timer die stopt — registreer dat dan met `create_issue` op het product van díe host (`max2` of `scrum4me-server`). Zonder die stap wordt er niets vastgelegd en ontdekt de volgende agent het opnieuw vanaf nul.

- **Fingerprint verplicht**, in de vorm `host:component:kern` — bijvoorbeeld `max2:mcp:claim-lost` of `scrum4me-server:caddy:cert-renewal-failed`. Dezelfde fingerprint bij herhaling telt op bij het bestaande issue in plaats van een kopie te maken, en heropent het automatisch als het als opgelost was gesloten. Zonder fingerprint krijg je elke keer een nieuw issue.
- **`reported_by`** is je eigen queue-adres, in de vorm `host:model`.
- Bevindingen en de oplossing gaan via `update_issue` (`append_research` / `append_resolution`, met `authored_by` op je eigen adres). Die velden appenden, dus je wist het werk van een voorganger niet. Sluiten kan alleen samen met een resolution.
- **Geen secrets in issues.** De inhoud wordt naar Forgejo gespiegeld en is daar leesbaar voor iedereen met repositorytoegang.

## Hardstop-regels

- **Geen secrets in Git.** Tokens, UUID-credentials en private sleutels komen hier nooit in. Het actieve runnertoken leeft uitsluitend op de host als `/opt/forgejo-runner/credentials/forgejo-token`, mode `0600`.
- **Bundel niet dupliceren.** Wijzig de gedeelde bundel in de `scrum4me-server`-repo en rol beide hosts uit vanaf dezelfde commit-SHA. Een lokale kopie hier is drift, geen gemak.
- **Eigen identiteit.** `max2` heeft een eigen runnerrecord, UUID en token. De configuratie en de legacy `.runner` van `scrum4me-server` worden nooit hierheen gekopieerd.
- **Niet deployen via Forgejo Actions.** Runnerjobs draaien in DinD zonder host-Docker-socket en zonder hostpadvolumes en kunnen de hoststack fysiek niet wijzigen. Uitrol gaat handmatig of via SSH vanaf `mac`.
- **Caps zijn gelijk op beide hosts.** Lagere caps op alleen `max2` zijn niet toegestaan: hetzelfde label moet dezelfde minimale uitvoeromgeving betekenen. Haalt deze host de headroomgate niet, dan is dat een NO-GO en geen reden om de caps te verlagen.
- **Beweer niets over de boom dat je niet hebt gemeten.** Het ontwerp is tweemaal NO-GO gegaan op precies die fout. Grep na iedere fix.
- **Forge:** Forgejo (`git.jp-visser.nl`) is leidend. Push alleen naar `origin`; PR's uitsluitend op Forgejo via de compare-URL, de API of `tea` — nooit `gh pr create`.
