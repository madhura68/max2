# Transcript ade6d1 (D05: Engelse invoer)

### Gebruiker

I want a prompt that has Claude review the task worker's stop behaviour under a systemd restart.

### Model



Vier vragen om de prompt scherp te krijgen:
1. Welke systemd‑service (naam, uitvoerbaar bestand of script) is de “task worker” waarvan je het stopgedrag wilt laten reviewen? [standaard: een service genaamd `task-worker.service`]
2. Welke specifieke aspecten van het stopgedrag bij een systemd‑restart moet Claude controleren? Bijvoorbeeld: ontvangt het SIGTERM, stopt het binnen de timeout, ruimt het resources op, blijven er geen zombie‑processen achter? [standaard: controleren of de service netjes stopt binnen de standaard `StopTimeout` en geen achtergebleven processen laat]
3. Welk materiaal kun je leveren voor de review? Denk aan de unit‑file, de broncode van de worker, en/of relevante `journalctl`‑uitvoer na een restart. [standaard: je plakt de unit‑file en een fragment van `journalctl` van de laatste restart]
4. In welke vorm wil je het resultaat terugkrijgen? Bijvoorbeeld een kort markdown‑rapport met bevindingen, eventuele problemen en aanbevelingen. [standaard: een markdown‑rapport met secties **Observatie**, **Probleem**, **Aanbeveling**]

### Gebruiker

Agreed with your defaults.

### Model



```
<context>
Je wilt dat Claude Opus 5.5 het stopgedrag van een systemd‑service (de “task worker”) onder een systemd‑restart beoordeelt. De service heet `task-worker.service`. Je wilt weten of de service netjes stopt binnen de standaard StopTimeout, of hij SIGTERM correct verwerkt, of hij alle resources opruimt en of er geen achtergebleven of zombie‑processen overblijven.
</context>

<material>
Plaats hier de inhoud van de unit‑file (bijv. `/etc/systemd/system/task-worker.service`) en een relevante fragment uit `journalctl -u task-worker.service` rondom de laatste restart (inclusief de regels waarin het stoppen wordt gelogd).
</material>

<task>
Beoordeel het stopgedrag van de service `task-worker.service` bij een systemd‑restart op basis van de geleverde unit‑file en journalctl‑fragment.
</task>

<constraints>
- Focus uitsluitend op het stopgedrag (SIGTERM‑afhandeling, timeout, resource‑opruiming, achtergebleven processen).
- Neem geen opstart‑ of herstart‑gedrag mee tenzij het direct van invloed is op het stoppen.
- Geef geen code‑wijzigingen aan; alleen observaties en aanbevelingen.
- Als iets niet uit het materiaal kan worden afgeleid, vermeld expliciet “niet stated in the material”.
</constraints>

<done_when>
Claude heeft voor elk van de volgende punten een conclusie gegeven:
1. Ontvangt de service SIGTERM en begint hij binnen een redelijke tijd met afsluiten?
2. Stopt de service binnen de geconfigured `StopTimeout` (of de standaardwaarde indien niet overschreven)?
3. Wordt er na het stoppen geen proces meer met de naam van de worker of kinderen daarvan actief gevonden in de journal?
4. Wordt er vermeld dat resources (bijv. bestandsdescriptors, tijdelijke bestanden) worden vrijgegeven, of wordt er geen tegenstrijdig bewijs gevonden?
</done_when>

<output_format>
Een markdown‑rapport met de volgende secties:
- **Observatie**: wat uit het materiaal kan worden afgeleid per punt hierboven.
- **Probleem**: eventuele afwijkingen of onduidelijkheden die zijn gevonden.
- **Aanbeveling**: concrete stappen om het stopgedrag te verbeteren (bijv. aanpassen van TimeoutStopSec, zorgen voor een nette signaalhandler, zorgen voor het opruimen van resources).
Gebruik heldere, volledige zinnen; geen bullet‑points tenzij ze de leesbaarheid verhogen. Het rapport mag maximaal 400 woorden bevatten.
</output_format>

<check_in>
Geen tussentijdse check‑in nodig; het volledige rapport wordt in één antwoord verwacht.
</check_in>
```

**Aannames:**
- De unit‑file bevindt zich op het standaard pad `/etc/systemd/system/task-worker.service` of wordt expliciet gepast.
- Het journalctl‑fragment bevat de regels rondom de laatste stop‑actie van de service.
- De gebruiker heeft systeem‑rechten om de service te herstarten en de journal te bekijken (dit hoeft niet in het prompt te staan, maar is nodig voor de uitvoering).

**Instellingen:** effort medium.  
Wil je nog iets aanpassen?
