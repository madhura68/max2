# Transcript efe1d1 (D01: bouwtaak met docs)

### Gebruiker

Laat Claude Code een vlag --json toevoegen aan harness check-run-logs, zodat de uitslag als JSON op stdout komt.

### Model

Vier vragen om de prompt scherp te krijgen:

1. Wat is de gewenste JSON-structuur voor de output? [standaard: een object met geheimsnamen als keys en aantallen als values, bijv. `{"HEIMELIJKE_VAR": 2, "ANDERE_VAR": 0}`]

2. Moet de bestaande exit-code logica behouden blijven (exit 1 bij minstens één treffer én bij geen enkel gecontroleerd geheim)?

3. Wil je dat de default output compacte JSON is (`JSON.stringify`), of geprettified met inspringing? [standaard: geprettified met 2 spaties]

4. Wil je dat `--json` ook de lijst met gecontroleerde geheimsamen teruggeeft (voor debugging), of alleen naam+teller? [standaard: alleen naam+teller]

### Gebruiker

Akkoord met je voorstellen.

### Model

```
<context>
Ik onderhoud de agent-harness CLI (TypeScript/Node.js). De subcommand `check-run-logs` controleert of geheimen die geredigeerd moeten worden onveranderd in run-logbestanden staan. Het drukt nu tekst uit (`NAAM: 2`) en exit 1 bij een treffer of geen gecontroleerd geheim.

De broncode staat in het huidige project (`bench-agent-harness`). De CLI-argumenten worden al afgevangen; ik wil alleen een `--json` vlag toevoegen die de output als JSON-object op stdout zet.
</context>

<task>
Voeg een `--json` vlag toe aan de `check-run-logs` subcommand in de CLI. Zodra deze vlag aanwezig is, schrijf het resultaat als een JSON-object op stdout in plaats van de tekstoutput.

Het JSON-object heeft de structuur:
```json
{
  "secrets": {
    "HEIMELIJKE_VAR": 2,
    "ANDERE_VAR": 0
  },
  "status": "clean" | "leaks_found" | "no_secrets_checked"
}
```

Waar:
- `secrets`: object met naam → aantal treffers (alle gecontroleerde geheimen, ook die met 0 treffers)
- `status`: `"clean"` als alle tellers 0 zijn, `"leaks_found"` als minstens één > 0, `"no_secrets_checked"` als er geen geheimen waren om te controleren

De exit-code blijft ongewijzigd: 1 bij treffer of geen gecontroleerd geheim, 0 anders.

Bij `--json` mag er geen tekst naar stderr gaan (behalve eventuele foutmeldingen bij slecht gebruik).
</task>

<output_format>
Toon alle bestanden die je wijzigt, met de exacte diff per bestand. Pas alleen de code aan die nodig is voor deze vlag — raak niets anders aan.
</output_format>

<done_when>
- `harness check-run-logs --config <worker.json> --dir <dir> --json` produceert geldige JSON op stdout.
- De structuur van het JSON-object komt overeen met de specificatie hierboven.
- De exit-code is correct (1 bij treffer of geen geheim, 0 anders).
- Zonder `--json` werkt de tekstoutput ongewijzigd.
</done_when>
```

Aannames:
- De CLI maakt gebruik van een gangbare arg-parsing library (zoals `commander` of `minimist`); ik heb geen toegang tot de broncode om dit te verifiëren.
- De `check-run-logs` subcommand is al geïmplementeerd met een lijst van te controleren geheimen en een functie die de treffers per geheim berekent.
- De JSON-output gaat niet naar stderr — alleen naar stdout.

Instellingen: effort medium.

Wil je nog iets aanpassen?
