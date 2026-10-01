# Transcript ce2be8 (R06: review zonder bestand)

### Gebruiker

Kun je mijn docker-compose op security laten reviewen?

### Model

Ja. Vier korte vragen:

1. Krijg ik de docker-compose.yaml (plus eventuele .env of config) via plakken of als bijlage? [standaard: plakken in het volgende bericht]
2. Wat is het gebruik: intern/privé, of publiek bereikbaar (bijv. een webapp of API)? [standaard: intern/privé]
3. Welke container(s) en services zijn erin, en zijn er vertrouwde secrets of credentials? [standaard: geen gevoelige secrets in de file]
4. Gewenste output: een geordende lijst van findings met severity (kritiek/hoger/medium/laag) en concrete aanbevelingen, plus een korte samenvatting? [standaard: ja]

### Gebruiker

Akkoord met je voorstellen. Het is een compose-bestand voor een paar containers op mijn thuisserver.

### Model

```
<context>
Ik wil dat een beveiligingsreview wordt uitgevoerd op mijn docker-compose.yaml. Het bestand wordt gebruikt voor een paar containers op mijn thuisserver. De review is bedoeld om risico's te identificeren en concrete, toepasbare verbeteringen te krijgen.
</context>

<material>
[PLAK HIER JE DOCKER-COMPOSE.YAML]
</material>

<task>
Review de docker-compose.yaml op beveiligingsrisico's en geef een geordende lijst van findings met severity (kritiek, hoog, medium, laag) en concrete aanbevelingen per finding.
</task>

<constraints>
- Focus op Docker Compose-specifieke risico's zoals onnodige privileges, host-mapping, secrets handling, netwerkinstellingen, image-kies, resource limits en updatebeheer.
- Vermeld voor elke finding: wat het risico is, waarom het relevant is, en welk concreet change of config aanbevolen wordt.
- Als een finding afhangt van context die niet in de file staat, vermeld dat expliciet in plaats van te raden.
- Geef geen generieke adviezen zonder koppeling aan de inhoud van het bestand.
</constraints>

<done_when>
- Elke finding heeft een severity en een concrete aanbeveling.
- Er is een korte samenvatting met de belangrijkste risico's.
- Als er geen kritieke of hoge risico's zijn, staat dat expliciet.
</done_when>

<output_format>
- Eerst een korte samenvatting van 3 tot 5 bullets.
- Vervolgens een geordende lijst van findings, per finding: severity, beschrijving, aanbeveling.
- Sluit af met een korte sectie "Meest prioritaire acties" met maximaal 3 stappen.
</output_format>
```

Aannames:
- De compose-file wordt geplakt in het prompt.
- Het wordt gebruikt op een thuisserver, maar er mag toch publiek bereikbare services zijn.
- Er staan geen gevoelige secrets in het bestand.
- De output moet in het Nederlands zijn.
- Er is geen specifieke tech-stack of policy die afdwingt welke aanbevelingen prioriteit krijgen.

Instellingen: effort medium. Plak de docker-compose.yaml in het `<material>`-blok. Wil je nog iets aanpassen?
