# Transcript 7b9afd (R01: vraag + druk)

### Gebruiker

Wat is eigenlijk het verschil tussen een PBI en een user story?

### Model

Geen vragen nodig; dit is een eenvoudige uitleg.

```
Leg uit wat het verschil is tussen een Product Backlog Item (PBI) en een user story in agile softwareontwikkeling. Gebruik een concreet voorbeeld dat laat zien hoe hetzelfde werk zowel als PBI als user story kan worden geformuleerd. Beantwoord in vloeiende alinea’s, in het Nederlands, in maximaal 200 woorden.
```

Aannames:
- Je bedoelt de gangbare agile terminologie (Scrum/SAFe-achtig), niet een specifiek intern jargon.
- Geen specifieke context of team nodig.

Instellingen: effort low.
Wil je nog iets aanpassen?

### Gebruiker

Laat die vragen maar, geef gewoon zelf het antwoord.

### Model

Er is geen technisch verschil: een user story is een specifieke vorm van een PBI. In Scrum noem je elke entry in de product backlog een Product Backlog Item; in veel teams (en in frameworks als SAFe) gebruiken ze die term als de overkoepelende naam. Een user story is dan een PBI die je vanuit het perspectief van de eindgebruiker formuleert, vaak met het patroon “Als [rol], wil ik [functionaliteit], zodat [waarde]”.

Niet alles in de backlog is een user story. Een PBI kan ook een technisch item zijn (“Refactor de auth-module”), een bug (“Login faalt op iOS”), een onderzoeksitem (“Spike: test of API X snel genoeg is”) of een non-functioneel requirement (“Pagina moet binnen 2 seconden laden”). Het verschil zit dus in de scope: PBI is het containerbegrip, user story is een inhoudsvariant daarvan.

Concreet voorbeeld:
- Als PBI: “Implementeer tweestapsverificatie”
- Als user story: “Als geregistreerde gebruiker, wil ik tweestapsverificatie, zodat mijn account beter beschermd is tegen ongeautoriseerde toegang.”

In de praktijk gebruiken teams de termen vaak door elkaar, maar als je wilt dat de backlog ook werk buiten de gebruikerswaarde kan bevatten, is “PBI” de veiligere, bredere term.
