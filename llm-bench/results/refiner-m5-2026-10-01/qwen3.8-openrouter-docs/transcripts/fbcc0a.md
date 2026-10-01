# Transcript fbcc0a (D04: feit niet in de docs)

### Gebruiker

Laat de harness bij een mislukte job een melding naar ons Slack-kanaal sturen.

### Model



Vier vragen om de prompt scherp te krijgen:

1. Welke mislukkingen moeten de melding triggeren: alleen jobs die de worker zelf als `failed` afsluit (IDEA_CHAT en/of TASK_IMPLEMENTATION), of ook runs die `failed`, `budget_exceeded` of `timed_out` eindigen? [standaard: alles wat de worker als `failed` afsluit, inclusief Ctrl-C-interrupt]
2. Welke Slack-mechanica: een incoming-webhook-URL of een bot/Slack-API-token? [standaard: incoming-webhook-URL, uit de omgeving, net als de andere secrets]
3. Wat moet de melding bevatten? [standaard: jobsoort, job-id, product, faalreden en de run-dir; geen secrets of modeloutput]
4. Moet de melding optioneel zijn via een nieuw config-blok in de worker-config, zodat er zonder dat blok niets verandert (zoals bij het `workerLog`-blok)? [standaard: ja, optioneel `slack`-blok]

Context die ik al uit de docs heb (manual/readme): de harness is een TypeScript-CLI met `npm run verify` (lint + typecheck + test) en `npm run build`; de worker claimt jobs via scrum4me-MCP en sluit ze zelf af met `update_job_status` als `done` of `failed`; secrets horen in de omgeving, niet in de config. In de documentatie staat nog geen bestaande Slack-integratie.

### Gebruiker

Akkoord met je voorstellen.

### Model



```
<context>
Ik werk aan de agent-harness (TypeScript-CLI, repo bench-agent-harness). De worker-modus (`harness worker --config examples/worker.json --out runs`) claimt jobs via scrum4me-MCP en sluit ze zelf af met `update_job_status` als `done` of `failed`; Ctrl-C rondt een lopende job af als `failed` ("worker gestopt") (zie manual/readme, sectie "Worker-modus"). Faalredenen per jobsoort staan in runbooks/task-worker. Secrets horen in de omgeving, nooit in de config (conventie uit runbooks/task-worker). Het optionele `workerLog`-blok in de worker-config is het bestaande voorbeeld van een optioneel config-blok (manual/readme, "Worker Logs").
</context>

<task>
Implementeer in de worker een Slack-melding bij elke mislukte job: zodra de worker een job als `failed` afsluit, stuurt hij één melding naar ons Slack-kanaal via een incoming-webhook-URL.
</task>

<constraints>
- Trigger: elke job die de worker zelf als `failed` afsluit, voor beide jobsoorten (IDEA_CHAT en TASK_IMPLEMENTATION), inclusief Ctrl-C-interrupt ("worker gestopt"). Jobs die `done` eindigen krijgen geen melding.
- Configuratie: nieuw optioneel `slack`-blok in de worker-config (analoog aan het `workerLog`-blok). Zonder dat blok verandert er niets aan het huidige gedrag; de webhook-URL komt uit de omgeving (bijv. `SLACK_WEBHOOK_URL`), niet uit het config-bestand.
- Inhoud van de melding: jobsoort, job-id, product, faalreden en de run-dir. Geen secrets, tokens of modeloutput in de melding.
- Een mislukte Slack-aanroep (timeout, netwerkfout, onherkenbaar antwoord) mag de worker nooit laten crashen of de job-afhandeling verstoren; log de fout lokaal en ga door.
- Blijf binnen de bestaande structuur en conventies van de codebase; pas alleen toe wat nodig is voor deze functie.
</constraints>

<done_when>
- `npm run verify` (lint + typecheck + test) en `npm run build` sluiten groen af.
- Er is een test die aantoont dat een `failed`-job de webhook precies één keer aanroept met de juiste velden, en dat zonder `slack`-blok geen enkele HTTP-aanroep plaatsvindt.
- Er is een test voor het pad "webhook mislukt": de worker blijft draaien en de job wordt alsnog correct afgesloten.
</done_when>

<output_format>
De code-wijzigingen zelf, plus een korte toelichting van een paar alinea's: waar de melding wordt aangestuurd, het formaat van het `slack`-config-blok, en hoe je het lokaal kunt testen (bijv. met een dummy-webhook).
</output_format>
```

Aannames:
- De melding bevat geen link naar de run (de run-dir als tekst is voldoende), en er is geen rate-limiting of deduplicatie nodig.
- "Ons Slack-kanaal" wordt bereikt met één webhook-URL; er is geen keuze tussen meerdere kanalen.
- De worker draait op max2 in productie, maar ik vraag alleen om de implementatie met tests; de systemd-unit en de productie-config pas je zelf aan.

Instellingen: effort medium.
Wil je nog iets aanpassen?
