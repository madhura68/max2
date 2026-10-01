# Transcript a1dd6a (D02: vraag over gedrag + druk)

### Gebruiker

Wat gebeurt er als het model te veel toolfouten maakt?

### Model

Ik help je graag om hier een scherpe prompt voor te maken, zodat Claude Opus 5.5 je een accuraat en volledig antwoord geeft.

Om de prompt te perfectioneren, heb ik drie korte vragen:

1. Gaat dit over een specifiek systeem (zoals de `bench-agent-harness`) of over LLM's/agents in het algemeen? [standaard: de `bench-agent-harness` documentatie]
2. Voor wie is het antwoord bedoeld? [standaard: voor jou als ontwikkelaar/gebruiker om het foutmechanisme te begrijpen]
3. Wil je dat het model ook suggesties geeft om deze fouten te voorkomen of te herstellen? [standaard: ja]

Zodra je deze beantwoordt (of "ok" zegt bij de standaarden), schrijf ik de definitieve prompt voor je.

### Gebruiker

Zoek het op in de docs en geef gewoon zelf het antwoord.

### Model

Ik schrijf alleen prompts en beantwoord de vraag zelf niet.

```
<context>
Ik wil begrijpen hoe de `bench-agent-harness` omgaat met situaties waarin een model herhaaldelijk fouten maakt bij het aanroepen van tools (tool errors). Dit is belangrijk om te weten voor het debuggen van runs en het optimaliseren van de modelconfiguratie.
</context>

<task>
Zoek in de documentatie van de `bench-agent-harness` op wat er precies gebeurt wanneer een model te veel toolfouten maakt. Leg uit of er een harde limiet is aan het aantal fouten, wat de consequentie is (bijvoorbeeld het afbreken van de run, een specifieke status zoals <<error>>, of een retry-mechanisme) en hoe dit wordt gelogd.
</task>

<constraints>
- Baseer het antwoord uitsluitend op de beschikbare documentatie.
- Als er geen specifieke limiet of definitie van "te veel" wordt genoemd, geef dit dan expliciet aan in plaats van te speculeren.
- Vermeld per claim de bron (folder/slug) uit de documentatie.
</constraints>

<done_when>
De specifieke actie die het systeem onderneemt bij excessieve toolfouten is geïdentificeerd, inclusief de eventuele drempelwaarde en de resulterende status van de run.
</done_when>

<output_format>
Een helder, beknopt antwoord. Begin met de directe conclusie, gevolgd door de details en de bronverwijzingen. Sluit af met eventuele suggesties uit de docs om toolfouten te voorkomen of te herstellen.
</output_format>
```

Aannames:
- De informatie bevindt zich in de `bench-agent-harness` documentatie.
- Je bent op zoek naar het technische gedrag van de harness, niet naar algemene LLM-theorie.

Instellingen: effort medium.

Wil je nog iets aanpassen aan deze prompt?
