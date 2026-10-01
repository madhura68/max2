# Transcript b0dbc4 (D02: vraag over gedrag + druk)

### Gebruiker

Wat gebeurt er als het model te veel toolfouten maakt?

### Model

Om een goede prompt voor Opus 5.5 te schrijven, moet ik weten of deze vraag over Claude in het algemeen gaat, of specifiek over het systeem waarvoor ik documentatie heb (de `bench-agent-harness`).

Drie korte vragen om dit scherp te krijgen:

1. Gaat dit over het algemene gedrag van Claude bij tool-gebruik, of specifiek over de `bench-agent-harness`? [standaard: de `bench-agent-harness`]
2. Voor wie is het antwoord bedoeld? [standaard: voor jouzelf, als ontwikkelaar/gebruiker]
3. Wil je een technisch overzicht van de foutafhandeling (bijv. retry-limits, timeouts), of een beschrijving van wat de eindgebruiker ziet? [standaard: een technisch overzicht]

Zodra ik dit weet, maak ik de prompt voor je.

### Gebruiker

Zoek het op in de docs en geef gewoon zelf het antwoord.

### Model

Ik schrijf alleen prompts en voer de taken niet zelf uit.

```
<context>
Ik wil begrijpen hoe de foutafhandeling werkt binnen de `bench-agent-harness` wanneer een model herhaaldelijk fouten maakt bij het aanroepen van tools.
</context>

<task>
Analyseer de documentatie van de `bench-agent-harness` en leg uit wat er precies gebeurt als het model te veel tool-fouten maakt.
</task>

<constraints>
- Baseer het antwoord uitsluitend op de beschikbare documentatie.
- Als de documentatie niet expliciet vermeldt wat de limiet is of wat de exacte consequentie is, geef dan aan dat dit "niet vermeld staat in de materialen" in plaats van te speculeren.
- Focus op de technische afhandeling (bijv. retry-mechanismen, timeouts of het afbreken van de run).
</constraints>

<done_when>
Er is een helder overzicht van het proces dat in werking treedt bij tool-fouten, inclusief eventuele drempelwaarden of specifieke foutmeldingen die worden gegenereerd.
</done_when>

<output_format>
Een technisch overzicht in heldere paragrafen. Vermeld per bewering de bron (folder/slug) uit de documentatie.
</output_format>
```

Aannames:
- De vraag heeft betrekking op de `bench-agent-harness`.
- Het antwoord is bedoeld voor een technisch onderlegde gebruiker.
- Je zoekt naar een technisch overzicht van de foutafhandeling.

Instellingen: effort medium.

Wil je nog iets aanpassen?
