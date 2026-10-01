# Transcript b9fdc4 (R03: vaag bouwidee)

### Gebruiker

Ik wil een dashboard voor mijn Ollama-modellen op max2.

### Model

Niet helemaal genoeg info om een scherp prompt te schrijven. Vier vragen:

1. Wat moet het dashboard laten zien? [standaard: welke modellen geïnstalleerd zijn, hun grootte, en welke momenteel geladen in het RAM/VRAM]
2. Hoe wordt het aangesproken? [standaard: lokaal webappje dat de Ollama API op localhost:11434 polt]
3. Tech-stack en omgeving? [standaard: Python + FastAPI + een simpele HTML/JS frontend, draait op de Max 2 zelf]
4. Systeem of los? [standaard: een standalone script/app die je handmatig start, geen service die altijd draait]

### Gebruiker

Akkoord. Extra: alleen tokens per seconde en VRAM, geen login.

### Model

```
<context>
Ik draai Ollama op mijn Mac (Max 2) en wil een lokaal dashboard om in één oogopslag te zien welke modellen geïnstalleerd zijn, welke momenteel geladen zijn in het RAM/VRAM, en welke tokens per seconde geleverd worden. Er is geen login of gebruikersbeheer nodig; het dashboard is puur lokaal.
</context>

<task>
Bouw een standalone Python 3 webapp (FastAPI + simpele HTML/JS frontend) die de Ollama API op localhost:11434 aanspreekt en een dashboard toont met:
- De lijst van geïnstalleerde modellen (naam, grootte).
- Per geladen model: het gebruikte VRAM/RAM en de huidige tokens per seconde.
- Automatische refresh zodat de waarden live bijgewerkt worden.
</task>

<constraints>
- Geen login, geen gebruikersbeheer, geen externe services; alles draait lokaal.
- Alleen tokens per seconde en VRAM/RAM als prestatie-metrika's; geen andere statistieken (geen latency, geen request counts, geen historisch grafiek).
- De app is standalone: ik start hem handmatig, hij is geen achtergrondservice.
- Gebruik de standaard Ollama API-endpoints (bijv. /api/tags, /api/ps) voor de data.
</constraints>

<done_when>
- Het dashboard toont correct de geïnstalleerde modellen en hun grootte.
- Wanneer een model geladen is, toont het dashboard het VRAM-gebruik en de tokens per seconde.
- De data wordt automatisch ververst zonder handmatig herladen van de pagina.
</done_when>

<output_format>
Het volledige code (backend + frontend), de installatiestappen voor benodigde libraries, en de commando's om de app te starten en te openen in de browser.
</output_format>
```

Aannames:
- Ollama draait al op port 11434 op dezelfde machine.
- Python 3 is geïnstalleerd.
- De tokens-per-seconde-meting komt uit de Ollama API zelf (via /api/ps of equivalent); als Ollama dat niet direct biedt, wordt het afgeleid uit de beschikbare endpoint-data.
- "Max 2" betekent een Mac met veel RAM/VRAM, maar de code zelf is hardware-agnostisch.

Instellingen: effort medium.

Wil je nog iets aanpassen?

### Gebruiker

Voeg nog toe dat het dashboard ook de laadtijd van een model toont.

### Model

```
<context>
Ik draai Ollama op mijn Mac (Max 2) en wil een lokaal dashboard om in één oogopslag te zien welke modellen geïnstalleerd zijn, welke momenteel geladen zijn in het RAM/VRAM, welke tokens per seconde geleverd worden, en hoe lang het laden van een model duurt. Er is geen login of gebruikersbeheer nodig; het dashboard is puur lokaal.
</context>

<task>
Bouw een standalone Python 3 webapp (FastAPI + simpele HTML/JS frontend) die de Ollama API op localhost:11434 aanspreekt en een dashboard toont met:
- De lijst van geïnstalleerde modellen (naam, grootte).
- Per geladen model: het gebruikte VRAM/RAM, de huidige tokens per seconde, en de laadtijd (tijd tussen het moment dat het model voor het eerst wordt aangevraagd en het moment dat het beschikbaar is voor inferentie).
- Automatische refresh zodat de waarden live bijgewerkt worden.
</task>

<constraints>
- Geen login, geen gebruikersbeheer, geen externe services; alles draait lokaal.
- Alleen tokens per seconde, VRAM/RAM en laadtijd als metrika's; geen andere statistieken (geen latency per request, geen request counts, geen historische grafieken).
- De app is standalone: ik start hem handmatig, hij is geen achtergrondservice.
- Gebruik de standaard Ollama API-endpoints (bijv. /api/tags, /api/ps) voor de data.
- De laadtijd moet per model bijgehouden worden sinds het eerste laden in de huidige sessie van de app.
</constraints>

<done_when>
- Het dashboard toont correct de geïnstalleerde modellen en hun grootte.
- Wanneer een model geladen is, toont het dashboard het VRAM-gebruik, de tokens per seconde en de laadtijd van dat model.
- De data wordt automatisch ververst zonder handmatig herladen van de pagina.
- De laadtijd is zichtbaar vanaf het moment dat een model voor het eerst in de sessie geladen wordt.
</done_when>

<output_format>
Het volledige code (backend + frontend), de installatiestappen voor benodigde libraries, en de commando's om de app te starten en te openen in de browser.
</output_format>
```

Aannames:
- Ollama draait al op port 11434 op dezelfde machine.
- Python 3 is geïnstalleerd.
- De tokens-per-seconde-meting komt uit de Ollama API (via /api/ps of equivalent); als Ollama dat niet direct biedt, wordt het afgeleid uit de beschikbare endpoint-data.
- "Laadtijd" betekent de tijd die de app zelf meet tussen het detecteren dat een model niet geladen was en het moment dat het wel geladen is (via polling), niet een interne Ollama-tijd.
- "Max 2" betekent een Mac met veel RAM/VRAM, maar de code zelf is hardware-agnostisch.

Instellingen: effort medium.

Wil je nog iets aanpassen?
