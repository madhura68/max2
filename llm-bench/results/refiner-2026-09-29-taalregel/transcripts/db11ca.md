# Transcript db11ca (R07: onderzoek)

### Gebruiker

Zoek uit welke NAS het beste is voor backups thuis.

### Model

Om een advies op maat te geven, heb ik een paar details nodig:

1. Hoe groot is de huidige en verwachte dataomvang (in TB) en welke bestaande opslagoplossingen wil je vervangen of integreren?
2. Wat is je budget inclusief de benodigde harde schijven en eventuele extra hardware (bijv. voor caching of ups)?
3. Zijn er specifieke technische vereisten zoals maximale snelheid, ondersteuning voor ZFS, of de voorkeur voor een specifiek besturingssysteem (bijv. TrueNAS, Unraid, Synology DSM)?
4. Voor wie is het advies bedoeld: voor je eigen gebruik (gebruiksgemak prioriteit) of voor een klein bedrijf (betrouwbaarheid en support prioriteit)?

Geef deze details op, of laat de standaardaannames (onderaan) staan.

### Gebruiker

Akkoord. Extra: budget maximaal 600 euro, 4 schijven.

### Model

Drie korte vragen om de prompt definitief te maken:

1. Welk besturingssysteem of merk heb je voorkeur? [standaard: Synology (vanwege gebruiksgemak) of TrueNAS (vanwege ZFS/betrouwbaarheid)?]
2. Gaat het voornamelijk om lokale backups van je eigen pc's, of ook om cloud-synchronisatie/replicatie naar andere locaties? [standaard: lokale netwerkbackups met optie voor cloud]
3. Welke data-grootte rijk je nu aan, en hoeveel groeit het per jaar? [standaard: beginnend bij 10 TB, groei van 2-4 TB/jaar]

Zodra je deze bevestigt (of "ok" zegt), lever ik de complete prompt.

### Gebruiker

Akkoord met je voorstellen.

### Model

Hier is de kant-en-klare prompt.

```prompt
<context>
Ik zoek een NAS-oplossing voor thuisgebruik om backups van mijn pc's te organiseren.
Mijn huidige situatie: ik begin met ongeveer 10 TB aan data, met een groei van 2-4 TB per jaar.
Mijn budget is maximaal 600 euro, inclusief de behuizing (chassis), moederboard, CPU en 4 harde schijven.
</context>

<task>
Bekijk de huidige markt en stel de beste NAS-configuratie voor die past binnen het budget en de capaciteitsbehoeften.
Overweeg zowel kant-en-klare oplossingen (zoals Synology of QNAP) als custom builds (met TrueNAS of Unraid), maar weeg de installatiecomplexiteit mee in je advies.
</task>

<constraints>
- Het totaalbedrag van de onderdelen of de kant-en-klare NAS mag de 600 euro niet overschrijden.
- Kies 2.5-inch of 3.5-inch schijven die passen bij de behuizing en het budget.
- Leg uit waarom je voor de voorgestelde configuratie kiest, specifiek gericht op betrouwbaarheid en gebruiksgemak voor thuisgebruik.
- Vermeld eventuele beperkingen van de gekozen oplossing (bijv. geen ZFS, beperkte upgrade-opties, of lange levertijden).
</constraints>

<done_when>
Ik heb een concreet advies voor één hoofdaanbeveling (en één alternatief als dat relevant is), inclusief een gedetailleerde componentenlijst of modelnummer, de geschatte totale kosten, en een korte motivering voor de keuze op basis van backups.
</done_when>

<output_format>
Een gestructureerd overzicht met duidelijke koppen: 'Aanbevolen Configuratie', 'Componentenlijst en Kosten', 'Motivatie en Backup-strategie', en 'Alternatief'. Gebruik een professionele, neutrale toon.
</output_format>
```

**Aannames:**
- De 600 euro is een harde grens voor alles (hardware + schijven).
- "Thuisgebruik" impliceert dat gebruiksgemak en stilte belangrijk zijn, maar dat betrouwbare backup-functies (zoals snapshots of replicatie) prioriteit hebben.
- Ik ga uit van een standaard huishoudelijk netwerk (Gigabit Ethernet).

**Instellingen:**
- **Effort:** Medium. Dit is een vergelijkende analyse die actuele kennis vereist, maar geen diepe technische simulatie.
- **Attachties:** Geen nodig, tenzij je specifieke schijvenmodellen al hebt uitgekozen.

Wil je nog iets aan de toon of de focus (bijv. meer nadruk op cloud-integratie of juist op lokale snelheid) aanpassen?
