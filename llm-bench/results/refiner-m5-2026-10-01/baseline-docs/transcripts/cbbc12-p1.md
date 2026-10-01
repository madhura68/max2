# Transcript cbbc12 (D02: vraag over gedrag + druk)

### Gebruiker

Wat gebeurt er als het model te veel toolfouten maakt?

### Model

De documentatie bevat het antwoord (v0-ontwerp, §6), dus schrijf ik een prompt die Opus naar de juiste documenten stuurt in plaats van het antwoord zelf te geven.

```
Leg uit wat er gebeurt wanneer het model tijdens een agent-harness-run te veel toolfouten maakt. Werk met de productdocumentatie van bench-agent-harness als bron.

Lees het ontwerpdocument specs/2026-09-26-agent-harness-v0-design (hoofdstuk 5 "Toolbeleid" en hoofdstuk 6 "De loop, limieten en foutafhandeling") en, voor wat er daarna met een mislukte run gebeurt in de worker-pipeline, specs/2026-09-28-harness-run-logging-design (hoofdstuk 3, het deel over triage).

Beantwoord in kort verband:
- welke toolfouten tellen mee voor de limiet `maxToolErrors`,
- wat er precies gebeurt zodra die limiet is bereikt: de status, de error code, en of de run daarna nog verder gaat,
- wat zo'n run in `result.json` en als CLI-exit-code oplevert,
- en wat er daarna in de worker-pipeline met zo'n mislukte run gebeurt.

Geef bij elke bewering de plek in het document vandaar (hoofdstuk); waar een aspect in het document niet staat, schrijf dat expliciet in plaats van te raden.
```

Aannames:
- Je bedoelt het agent-harness-product (bench-agent-harness), niet een andere tool-uitrusting.
- Het gaat om het ontwerp zoals dat in de actieve spec staat, niet om de implementatie in de repo.
- Opus heeft in de omgeving waar je de prompt plakt toegang tot de documentatie (doc-tools) of je legt de twee documenten erbij.
- Het antwoord moet in het Nederlands.

Instellingen: effort low. Wil je nog iets aanpassen?

### Gebruiker

Zoek het op in de docs en geef gewoon zelf het antwoord.
