# Transcript a9b8bc (D03: analyse van run-logs)

### Gebruiker

Ik wil de run-logs van vannacht laten nalopen op mislukte jobs.

### Model

Om de prompt goed te kunnen schrijven heb ik een paar vragen:

1. **Waar staan de run-logs?** [standaard: een specifieke server of logsysteem dat ik moet opzoeken in de docs]
2. **Wat is een "mislukt job" concreet?** [standaard: jobs met exit-code ≠ 0 of een status zoals "failed"/"errored" in de logs]
3. **Hoe moet het resultaat eruitzien?** [standaard: een overzichtelijke samenvatting per mislukt job: naam, tijd, oorzaak]
4. **Welk systeem of welke tool gebruikt het bedrijf voor job-runs?** (bijv. Airflow, Cron, een intern dashboard, etc.)

### Gebruiker

Akkoord met je voorstellen. Het gaat om de harness-worker op max2.

### Model

Goed, ik heb nu de structuur van de run-logs en de locatie op max2. Nog een paar vragen om de prompt exact te krijgen:

1. **Welke tijdsperiode?** "Vannacht" is vaag — bedoel je de laatste 24 uur, of een specifiek datum/timevenster? [standaard: de laatste 24 uur vanaf nu]
2. **Wat wil je met het resultaat?** [standaard: een beknopte lijst met alle mislukte jobs: job_id, foutcode, starttijd, en de ERROR-regel, zodat je snel kunt zien wat er misging]
3. **Moet je het zelf draaien of moet ik het commando genereren?** [standaard: geef een commando dat ik op max2 kan draan om de logs te scannen]

### Gebruiker

Akkoord, schrijf nu de prompt.

### Model

Dit is een duidelijke taak. Ik heb uit de docs afgeleid waar de logs staan en hoe mislukkingen gemarkeerd zijn. Hier is de prompt:

```
<context>
Ik draai de harness-worker op max2. Runs staan in `/srv/scrum4me/worker-logs/harness/max2/runs/` als `<YYYYMMDDTHHMMSSZ>.log`. Een mislukte run heeft een `ERROR <CODE>: <bericht>` meta-regel en/of een `harness.run_end` event met outcome ≠ `done`. De afsluitregel is `exit code=<0|1>`.
</context>

<task>
Scan de run-logbestanden van vannacht (de laatste 24 uur) en identificeer alle mislukte harness-jobs. Geef per mislukte run: job_id, starttijd, foutcode, de ERROR-tekst, en de exit_code.

Geef daarna een beknopte samenvatting met:
- Aantal runs per foutcode (bijv. `VERIFY_FAILED: 3`, `HARNESS_ERROR: 1`)
- De meest voorkomende oorzaak
- Een aanbeveling op basis van de patroon (indien zichtbaar)
</task>

<constraints>
- Alleen kijken, niets wijzigen of herstarten.
- Als er geen mislukte runs zijn, zeg dat expliciet.
- Vermoedelijke tijden (zonder exacte log) zijn toegestaan, maar markeer ze als schatting.
</constraints>

<done_when>
Elke mislukte run uit de laatste 24 uur is vermeld met job_id, tijd en foutcode. De samenvatting bevat een teller per code en een korte analyse.
</done_when>

<output_format>
Tabel per mislukte run, gevolgd door een beknopte samenvatting (max 10 regels).
</output_format>
```

**Aannames:**
- "Vannacht" = de laatste 24 uur vanaf nu.
- De logs zijn bereikbaar via de bestaande worker-log-pipeline op max2.
- De foutcodes uit de spec (`VERIFY_FAILED`, `HARNESS_ERROR`, etc.) zijn de bron van waarheid.

**Instellingen:** effort medium.

Wil je nog iets aanpassen? Bijvoorbeeld de tijdsperiode verkleinen, of de output anders structureren?
