# Transcript accf7e (R06: review zonder bestand)

### Gebruiker

Kun je mijn docker-compose op security laten reviewen?

### Model

Vier vragen om de prompt scherp te krijgen:

1. Zal je de docker-compose.yaml hier plakken, of staat hij in een repo die Claude Code kan lezen? [standaard: ik plak het bestand hier]
2. Draait deze stack in productie (met publiek bereikbare services), of is het lokaal/interne dev? [standaard: productie, enkele services zijn extern bereikbaar]
3. Welke services draaien erin, en zijn er speciale zorgen? [standaard: geen specifieke zorgen; bekijk alles: image tags, secrets, privileges, network exposure, volume mounts, healthchecks, resource limits]
4. Gewenste vorm van het resultaat? [standaard: lijst van bevindingen per service met ernst (hoog/middel/laag), concrete aanbevolen fix per bevinding, en een kort overzicht bovenaan]

### Gebruiker

Akkoord met je voorstellen. Het is een compose-bestand voor een paar containers op mijn thuisserver.

### Model

```
<context>
Ik draai een klein aantal containers op mijn thuisserver met Docker Compose. De stack is voor persoonlijk gebruik, maar sommige services zijn bereikbaar vanaf het lokale netwerk. Ik wil weten of er security-issues zitten die ik moet oplossen voordat ik er langer op vertrouw.
</context>

<material>
[docker-compose.yaml hier plakken]
</material>

<task>
Review dit docker-compose-bestand op security en lever per bevinding de ernst (hoog, middel of laag), waarom het een risico is in deze setup, en een concrete aanpassing van de compose-configuratie die het oplost.
</task>

<constraints>
- Beoordeel alleen wat uit het compose-bestand zelf blijkt; als iets afhangt van bestanden of settings die niet meegeleverd zijn (bijvoorbeeld .env, secrets, hostconfiguratie), noem dat expliciet als "niet beoordeeld" in plaats van te gokken.
- Houd rekening met de context: thuisserver, geen publiek internetbereik tenzij expliciet via ports naar 0.0.0.0 of een proxy, persoonlijk gebruik.
- Check minimaal: image tags (floating vs pinned), hardcoded secrets of credentials, use_of_privileges/root-containers, exposed ports en welke interfaces ze luisteren op, network configuratie (default bridge vs gescheiden netwerken), volume mounts (host-paths, read-only waar mogelijk), resource limits, healthchecks, restart policies, en environment variables die gevoelige data lekken.
- Rapporteer alle bevindingen, ook lage risico's; filter niet zelf op ernst.
</constraints>

<done_when>
Elke service in het compose-bestand is beoordeeld. Elke bevinding heeft een ernst-label, een korte uitleg van het risico en een concrete fix. Bevindingen over zaken die niet uit het bestand blijken staan apart onder "niet beoordeeld".
</done_when>

<output_format>
Bovenin een kort overzicht van maximaal vijf zinnen: totaal aantal bevindingen per ernst en de meest urgente actie. Daaronder een lijst van bevindingen, elk met: service-naam, ernst, probleem, aanbevolen fix (met code-snippet van de aangepaste compose-regel waar relevant). Afsluitend een sectie "niet beoordeeld" met wat nodig is om die punten alsnog te checken.
</output_format>
```

Aannames:
- Je plakt het compose-bestand in de chat of voegt het toe; Claude Code heeft hier geen repo-toegang nodig.
- Er is geen aparte .env of secrets-file meegestuurd; die worden dus gemarkeerd als niet beoordeeld.
- "Thuisserver" betekent geen publiek internetbereik tenzij je dat zelf hebt geconfigureerd via port-mapping naar 0.0.0.0 of een reverse proxy; dat neem ik als basis voor de risicobeoordeling.
- Je wilt de fixes in de vorm van aangepaste compose-regels, niet als volledig herbouwd bestand.

Instellingen: effort medium. Plak het compose-bestand bij je volgende bericht zodat ik het eventueel nog kan verwerken in de prompt, of plak het direct in de prompt waar het `[docker-compose.yaml hier plakken]` staat.

Wil je nog iets aanpassen?
