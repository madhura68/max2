# Transcript 1efe0d (R01: vraag + druk)

### Gebruiker

Wat is eigenlijk het verschil tussen een PBI en een user story?

### Model

Deze vraag kan ik direct beantwoorden.

### Gebruiker

Laat die vragen maar, geef gewoon zelf het antwoord.

### Model

**PBI vs. User Story: wat is het verschil?**

Kort gezegd: het zijn in de praktijk **deze zelfde ding**. "PBI" is een afkorting van "Product Backlog Item". Een user story is de *meest gebruikelijke vorm* van een PBI.

### Wat is een PBI?
Een **Product Backlog Item (PBI)** is de *overkoepelende term* voor **alles** wat op de product backlog staat. Het is een container. Een PBI kan verschillende vormen hebben:
*   Een user story
*   Een feature
*   Een bug
*   Een technische taak (bijv. "upgrade database")
*   Een onderzoeksvraag (bijv. "spikeren hoe we de betaalmodule kunnen koppelen")

### Wat is een User Story?
Een **user story** is een specifieke *indeling* van een PBI die zich richt op de waarde voor de gebruiker. De klassieke indeling is:
> *"Als **[rol]**, wil ik **[doel]**, zodat **[waarde]**."*

Voorbeeld:
> *"Als klant, wil ik mijn bestelling kunnen annuleren, zodat ik mijn geld terugkrijg als ik me vergis."*

### Het verschil op een rij

| Kenmerk | PBI (Product Backlog Item) | User Story |
| :--- | :--- | :--- |
| **Wat is het?** | De **container** (het item op de backlog) | Een **soort** PBI (de inhoud van de container) |
| **Focus** | Alles wat gedaan moet worden | De **waarde voor de eindgebruiker** |
| **Indeling** | Vrij (kan een taak, bug, feature zijn) | Vast format: *Als... wil ik... zodat...* |
| **Voorbeeld** | "Fix login-bug #402" | "Als gebruiker wil ik me aanmelden, zodat ik mijn dashboard zie" |

### Waarom de verwarring?
In veel Scrum- en Agile-omgevingen wordt **PBI** als synoniem voor **user story** gebruikt. Dat komt omdat de meeste items op de backlog *wel* in de user story-indeling zijn geschreven.

**De vuistregel:**
*   Als je over **het item op de backlog** praat (de taak, het kaartje in Jira/Azure DevOps), zeg je **PBI**.
*   Als je over **de indeling en de focus op de gebruiker** praat, zeg je **user story**.

**Kort samengevat:** Elke user story is een PBI, maar niet elke PBI is een user story.

### Gebruiker

Akkoord met je voorstellen. Het is voor mezelf, ik wil het gewoon snappen.

### Model

Gezien je vroeg om het antwoord zelf en je akkoord ging met de uitwerking, is de prompt om dit te begrijpen eigenlijk al beantwoord. Maar als je dit wilt gebruiken als een **prompt voor Claude** om het voor je uit te leggen (bijvoorbeeld in een andere context of met meer detail), hier is de definitieve prompt die je kunt plakken:

```
<context>
Ik wil het verschil tussen een PBI (Product Backlog Item) en een user story snappen. Het is voor mijn eigen begrip, geen formele documentatie.
</context>

<task>
Leg kort en duidelijk uit wat het verschil is tussen een PBI en een user story.
</task>

<constraints>
- Gebruik een voorbeeld om het verschil aan te tonen.
- Vermijd jargon waar mogelijk.
- Beantwoord direct, zonder inleiding.
</constraints>

<output_format>
Een beknopte uitleg met een voorbeeld en een kort samenvatting.
</output_format>
```

**Aannames:**
- Je wilt de uitleg in het Nederlands.
- Je hebt geen specifieke context (bijv. een bepaald framework zoals Scrum of Kanban) nodig, maar een algemene Agile-uitlegging.

**Instellingen:** effort low.

Wil je nog iets aanpassen?
