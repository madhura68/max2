# Transcript ed6ec1 (D04: feit niet in de docs)

### Gebruiker

Laat de harness bij een mislukte job een melding naar ons Slack-kanaal sturen.

### Model



**Vier vragen om de prompt scherp te krijgen:**

1. Welk Slack‑kanaal (naam of ID) moet de melding ontvangen, en heb je een incoming webhook URL of een Slack bot‑token beschikbaar? [default: gebruik het bestaande webhook voor het kanaal `#build-alerts`]  
2. Welke informatie moet in de Slack‑melding staan (bijv. jobnaam, build‑nummer, foutmelding, link naar logbestand, tijdstip)? [default: jobnaam, buildnummer, korte foutmelding en link naar de log in de harness UI]  
3. Moet de melding alleen worden verstuurd bij een mislukte job, of ook bij andere statussen zoals geblokkeerd of tijdsoverschrijding? [default: alleen bij status `failed`]  
4. Zijn er specifieke opmaak‑ of beperkingsvereisten voor het Slack‑bericht (bijv. maximale lengte, gebruik van blokken/attachments, geen vermeldingen van `@channel` tenzij kritiek)? [default: gebruik een eenvoudige tekstbericht, geen `@channel` of `@here`]

### Gebruiker

Akkoord met je voorstellen.

### Model


**Prompt voor Claude Opus 5.5**

```
<context>
De harness wordt gebruikt om CI/CD‑jobs uit te voeren. Bij een mislukte job moet er automatisch een bericht worden verzonden naar het Slack‑kanaal `#build-alerts` via een incoming webhook. Het webhook‑adres is al beschikbaar als geheim met de naam `SLACK_WEBHOOK_URL`. Het bericht moet de jobnaam, build‑nummer, een korte foutmelding en een link naar het logbestand in de harness UI bevatten. Er mag geen `@channel` of `@here` worden vermeld.
</context>

<task>
Voeg aan de harness‑configuratie een Slack‑notificatie toe die wordt getriggerd wanneer een job de status `failed` krijgt, met de opgegeven inhoud en opmaak.
</task>

<constraints>
- De notificatie mag alleen worden verstuurd bij status `failed` (niet bij andere statussen zoals geblokkeerd of timeout).
- Gebruik het bestaande geheim `SLACK_WEBHOOK_URL` voor de webhook‑URL; hard‑code geen URL.
- Het bericht moet een platte tekst zijn (geen blokken of attachments) en mag niet langer zijn dan 300 tekens.
- Voeg geen vermeldingen van `@channel` of `@here` toe.
- Laat bestaande notificatie‑regels ongewijzigd; voeg alleen de nieuwe Slack‑regel toe.
</task>

<done_when>
- De gewijzigde configuratie bevat een nieuwe entry onder `notifications` met `type: slack`.
- Bij een testjob die bewust faalt, ontvangt het Slack‑kanaal `#build-alerts` een bericht dat de jobnaam, build‑nummer, foutmelding en log‑link bevat.
- Het bericht voldoet aan de lengte‑ en opmaakbeperkingen (max 300 tekens, geen `@channel/@here`).
</done_when>

<output_format>
Geef de volledige bijgewerkte harness‑configuratie (bijv. `harness.yaml`) terug, met duidelijk aangegeven welke regels zijn toegevoegd of gewijzigd. Voeg een korte uitleg toe van wat er is veranderd en waarom het aan de constraints voldoet.
</output_format>

<check_in>
Voor het daadwerkelijk toepassen van de wijziging op de productie‑harness, vraag bevestiging voordat de configuratie wordt commit‑ged of toegepast. Bij twijfel over de juiste locatie van de `notifications`‑sectie, vraag om bevestiging voordat je wijzigingen aanbrengt.
</check_in>
```

**Aannames**
- De harness‑configuratie is een YAML‑bestand (bijv. `harness.yaml`) met een top‑level `notifications:` sectie waarin elk item een `type` heeft.
- Het geheim `SLACK_WEBHOOK_URL` is al beschikbaar in de harness omgeving en kan worden verwezen als `${SLACK_WEBHOOK_URL}` of via de harness‑secret‑syntaxis.
- Een testjob kan worden aangemaakt of bestaat al om de notificatie te valideren.
- De harness ondersteunt Slack‑notificaties via een `type: slack` entry die een `url` veld accepteert voor de webhook.

**Instellingen**: effort medium.  
Wil je nog iets aanpassen?
