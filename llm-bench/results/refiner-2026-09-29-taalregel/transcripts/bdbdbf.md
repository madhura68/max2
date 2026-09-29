# Transcript bdbdbf (R07: onderzoek)

### Gebruiker

Zoek uit welke NAS het beste is voor backups thuis.

### Model

Dit is een research-opdracht. Om de prompt scherp te krijgen, stel ik eerst een paar vragen:

1. Hoeveel data moet er bij een backup (ongeveer, en groeit het)? [standaard: ~2–5 TB, groeit traag]
2. Wat is de max budget? [standaard: €300–500 excl. schijven]
3. Backup van welke apparaten (laptops, desktops, telefoons, cameras) en is synchrone of asynchrone backup goed genoeg? [standaard: 2–3 PC's/laptops, asynchroon]
4. Moet er ook een NAS-schijf in zitten of heb je al schijven / wil je ook media-streaming? [standaard: NAS zonder schijven + 2x 4TB, geen streaming]

### Gebruiker

Akkoord. Extra: budget maximaal 600 euro, 4 schijven.

### Model

```
<context>
Ik zoek een NAS voor thuisbackups. Ik heb 2–3 PC's/laptops die ik asynchroon wil back uppen. Ik verwacht 2–5 TB data die traag groeit. Ik heb een budget van maximaal €600 inclusief 4 schijven, dus de NAS zelf mag minder kosten. Ik wil geen media-streaming, alleen betrouwbaar back uppen.
</context>

<task>
Bepaal welke NAS het beste is voor deze thuisbackups. Geef een top 3 met een duidelijke aanrader, en leg kort uit waarom die keuze past bij mijn situatie.
</task>

<constraints>
- Budget: maximaal €600 totaal, inclusief 4 schijven.
- Gebruik actuele prijzen (2024/2025) en geef de bron per prijs.
- Focus op betrouwbaarheid, eenvoudige backupsoftware, RAID/protectie en stilte/verbruik.
- Vermeld expliciet of de backup met een gratis ingebouwde tool (bijv. Hyper Backup, Time Machine, rsync) kan.
- Geen media-streaming-functies als selectiecriterium.
</constraints>

<done_when>
- Top 3 met prijs per model (NAS + 4 schijven) en bron.
- Eén aanrader met 3–5 redenen.
- Per model: aantal schijven, RAM, CPU, besturingssysteem, RAID-opties, geluid/verbruik (indien bekend), en of gratis backup mogelijk is.
- Als een specificatie of prijs niet in de bron staat: schrijf "niet vermeld", niet raden.
</done_when>

<output_format>
Nederlands. Structuur:
1. Aanrader (1 model, 3–5 redenen)
2. Top 3 tabel: model | NAS-prijs | 4-schijven-prijs | totaal | besturingssysteem | RAM | RAID | gratis backup | bron
3. Kort: waarom de overige 2 ook overwegenswaardig zijn (1–2 zinnen per model)
4. Bronnenlijst
</output_format>
```

Aannames:
- "4 schijven" betekent 4 schijven in de NAS (dus een 4-bay NAS), niet 4 schijven totaal in het budget.
- Budget €600 is totaal (NAS + schijven).
- Geen eisen aan netwerk (1GbE is voldoende), geen 10GbE.
- Backup is asynchroon (geen real-time replicatie nodig).
- Geen 10GbE of enterprise-eisen; consumenten-NAS is de scope.

Instellingen: effort medium.
Wil je nog iets aanpassen?
