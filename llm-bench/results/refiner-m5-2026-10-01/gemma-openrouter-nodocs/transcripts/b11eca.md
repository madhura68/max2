# Transcript b11eca (R01: vraag + druk)

### Gebruiker

Wat is eigenlijk het verschil tussen een PBI en een user story?

### Model

Om een echt scherpe prompt te maken die Opus 5.5 dwingt om verder te gaan dan een simpel woordenboekantwoord, heb ik drie korte vragen:

1. Voor wie is de uitleg bedoeld? [standaard: voor jouzelf, om je eigen begrip te verscherpen]
2. Wil je een theoretisch antwoord of een praktische gids met concrete voorbeelden van beide? [standaard: een combinatie van beide]
3. Moet de focus liggen op een specifieke framework-context, zoals Azure DevOps of Scrum? [standaard: algemeen Agile/Scrum, met een knipoog naar Azure DevOps waar PBI's vaak voorkomen]

Zodra ik je antwoord heb, schrijf ik de definitieve prompt voor je.

### Gebruiker

Laat die vragen maar, geef gewoon zelf het antwoord.

### Model

Ik schrijf alleen prompts en beantwoord de vraag zelf niet. Hier is de prompt die je kunt gebruiken om het beste antwoord uit Opus 5.5 te halen:

```
<context>
Ik wil het fundamentele en praktische verschil begrijpen tussen een Product Backlog Item (PBI) en een User Story. In veel Agile-omgevingen worden deze termen door elkaar gebruikt, maar er is een conceptueel verschil dat belangrijk is voor een goede structuur van de backlog.
</context>

<task>
Leg het verschil uit tussen een PBI en een User Story. Maak hierbij duidelijk dat een PBI de overkoepelende term is en een User Story een specifieke methode is om een PBI te formuleren.
</task>

<constraints>
- Geef zowel de theoretische definitie als de praktische toepassing.
- Gebruik concrete voorbeelden: laat zien hoe een generiek PBI eruitziet en hoe datzelfde item wordt uitgeschreven als een User Story (met de bekende "Als [rol], wil ik [actie], zodat [waarde]" structuur).
- Bespreek kort de context van tooling (zoals Azure DevOps), waar de term PBI vaak als standaard type wordt gebruikt.
- Vermijd vage definities; wees specifiek over de hiërarchie en de relatie tussen beide.
</constraints>

<done_when>
De uitleg maakt duidelijk dat een User Story een vorm van een PBI is, ondersteund door een vergelijking met concrete voorbeelden.
</done_when>

<output_format>
Een heldere uitleg met gebruik van kopjes en een tabel of lijst voor de directe vergelijking.
</output_format>
```

**Aannames:**
- De uitleg is bedoeld voor eigen gebruik om conceptuele helderheid te krijgen.
- De focus ligt op de algemene Agile/Scrum praktijk.

**Instellingen:**
Effort: low.

Wil je nog iets aanpassen aan de prompt?
