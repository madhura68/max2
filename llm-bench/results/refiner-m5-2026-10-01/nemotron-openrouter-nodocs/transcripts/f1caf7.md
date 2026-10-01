# Transcript f1caf7 (R06: review zonder bestand)

### Gebruiker

Kun je mijn docker-compose op security laten reviewen?

### Model

Vier vragen om de prompt scherp te krijgen:
1. Welke versie van Docker Compose gebruik je, en welke services staan erin? [standaard: nieuwste versie, een paar services zoals webapp en database]
2. Moet ik alleen de docker-compose.yml bekijken, of ook gerelateerde bestanden zoals Dockerfiles of .env? [standaard: alleen de docker-compose.yml]
3. Welke specifieke security-aspecten wil je laten checken? Bijvoorbeeld: gebruik van root, poorten blootstellen, geheimen beheren, netwerkinstellingen? [standaard: algemene best practices voor container security]
4. Hoe wil je het review ontvangen? Als lijst met bevindingen, of ook met concrete suggesties voor verbetering? [standaard: lijst met bevindingen en suggesties]

Beantwoord met bijvoorbeeld: "1 ok, versie 3.8 met webapp en db. 2 ook Dockerfiles meenemen. 3 focus op root-gebruik en geheimen. 4 lijst met bevindingen en fixes."  
Of zeg "ok" bij een vraag om de standaard te gebruiken.

### Gebruiker

Akkoord met je voorstellen. Het is een compose-bestand voor een paar containers op mijn thuisserver.

### Model

Drie vragen om de prompt scherp te krijgen:
1. Welke services staan er ongeveer in je docker-compose.yml? Bijvoorbeeld: webapp, database, cache, monitoring? [standaard: een paar basisservices zoals webapp en database]
2. Moet ik ook de Dockerfiles van deze services meenemen in de review, of alleen de docker-compose.yml? [standaard: alleen de docker-compose.yml]
3. Welke output-formaat wil je voor het review? Een korte samenvatting, of een gedetailleerde lijst met bevindingen per service en actiepunten? [standaard: gedetailleerde lijst met bevindingen en concrete verbeteringsuggesties per service]

Beantwoord met bijvoorbeeld: "1 webapp, db, redis. 2 alleen compose-file. 3 gedetailleerde lijst."  
Of zeg "ok" bij een vraag om de standaard te gebruiken.  
Na drie ronden, of zodra de essentiële punten helder zijn, schrijf ik de finale prompt.

### Gebruiker

Akkoord met je voorstellen.

### Model

```
<context>
Je hebt een docker-compose.yml voor een thuisserver met een paar containers (bijvoorbeeld webapp, database, redis). Je wilt een security-review van dit bestand om basisbeveiligingsrisico's te identificeren en te verhelpen.
</context>

<material>
[Plak hier de volledige inhoud van je docker-compose.yml]
</material>

<task>
Voer een security-review uit op de geleverde docker-compose.yml. Identificeer mogelijke beveiligingsproblemen en geef concrete verbeteringsuggesties.
</task>

<constraints>
- Focus op veelvoorkomende container-beveiligingsaspecten: gebruik van non-root gebruikers, blootstellen van poorten, beheren van geheimen (environment variabelen, secrets), netwerkinstellingen, en privileges.
- Bekijk alleen de docker-compose.yml; ga niet uit van of veronderstel inhoud van Dockerfiles of andere bestanden tenzij expliciet vermeld in de compose-file.
- Geen uitspraken doen over de interne werking of security van de containers zelf (bijvoorbeeld applicatie-level vulnerabilities).
</task>

<done_when>
Elke service in de compose-file is nagekeken op de genoemde security-aspecten, en voor elke bevinding is een duidelijke omschrijving en een concrete suggestie voor verbetering gegeven.
</done_when>

<output_format>
Een lijst met bevindingen, gestructureerd per service. Voor elke bevinding:
- Service naam
- Beschrijving van het potentieel beveiligingsprobleem
- Concrete suggestie voor verbetering (bijvoorbeeld: voeg een gebruiker toe, wijzig een poort, gebruik secrets)
Gebruik heldere, zakelijke taal in het Nederlands. Geen inleidende of afsluitende alinea's; begin direct met de lijst.
</output_format>
```
Aannames:
- De docker-compose.yml gebruikt een recente versie (3.8 of hoger).
- De services zijn gebaseerd op standaard publieke afbeeldingen (bijv. uit Docker Hub) waarvan de basisbekendheid voldoende is om algemene security-praktijken toe te passen.
Instellingen: effort medium.  
Wil je nog iets aanpassen?
