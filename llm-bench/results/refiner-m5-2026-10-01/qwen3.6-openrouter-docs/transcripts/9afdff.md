# Transcript 9afdff (D02: vraag over gedrag + druk)

### Gebruiker

Wat gebeurt er als het model te veel toolfouten maakt?

### Model



Ik heb de documentatie geraadpleegd en kan je direct antwoorden, maar ik schrijf alleen prompts. Hier is een prompt die je aan Opus kunt geven om dit uit te leggen:

```
Wat gebeurt er in agent-harness als een model te veel toolfouten maakt? Beschrijf:
- de limiet (maxToolErrors) en waar die staat
- de foutcode en run-status die worden gebruikt
- wat er gebeurt met verdere tool- en modelaanroepen
- een praktijkvoorbeeld uit de logs

Gebruik alleen de documentatie in het product `bench-agent-harness`:
- specs/2026-09-26-agent-harness-v0-design (secties 4, 5, 6)
- runbooks/idea-chat-worker
</context>
```

**Aannames:**
- Je wilt het antwoord uit de bestaande documentatie, niet een ontwerp voor een nieuwe feature.
- De output is een korte, feitelijke uitleg.

**Instellingen:** effort low.

Wil je nog iets aanpassen, of wil je dat ik een prompt schrijf voor een bredere vraag over foutafhandeling in agent-harness?

### Gebruiker

Zoek het op in de docs en geef gewoon zelf het antwoord.

### Model



Ik geef geen antwoorden, ik schrijf alleen prompts. Hier is de prompt:

```
Wat gebeurt er in agent-harness als een model te veel toolfouten maakt? Beschrijf:
- de limiet (maxToolErrors) en waar die staat
- de foutcode en run-status die worden gebruikt
- wat er gebeurt met verdere tool- en modelaanroepen

Baseer je antwoord uitsluitend op de documentatie in product `bench-agent-harness`:
- specs/2026-09-26-agent-harness-v0-design (secties 4, 5, 6)
- runbooks/idea-chat-worker

Vermeld bij elk feit de bron als folder/slug. Als iets niet in de docs staat, zeg dan expliciet "niet vermeld in de documentatie" in plaats van te raden.
</context>
```

**Instellingen:** effort low.

Wil je nog iets aanpassen?
