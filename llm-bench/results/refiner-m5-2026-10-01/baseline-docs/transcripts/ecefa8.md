# Transcript ecefa8 (D03: analyse van run-logs)

### Gebruiker

Ik wil de run-logs van vannacht laten nalopen op mislukte jobs.

### Model

Ik heb de documentatie gelezen. De run-logs van harness-jobs staan in `/srv/scrum4me/worker-logs/harness/max2/runs/` op max2, en het formaat is gedetailleerd gespecificeerd. Ik heb nog een paar vragen:

1. **Waar wil je de nalope doen?** [standaard: je wilt een commando of script om dit lokaal op max2 uit te voeren]
2. **Wat levert het op?** [standaard: een overzicht van alle mislukte jobs uit vannacht met job_id, foutcode, korte oorzaak en duur]
3. **"Vanavond" — welke tijdsperiode?** [standaard: sinds 22:00 uur van de vorige dag tot nu, UTC]
4. **Heb je toegang tot max2?** [standaard: ja, je kunt `ssh` en `sudo` gebruiken]

### Gebruiker

Akkoord met je voorstellen. Het gaat om de harness-worker op max2.

### Model

```
<context>
Ik wil de run-logs van vannacht laten nalopen op mislukte jobs. De logs staan op de harness-worker van max2 in `/srv/scrum4me/worker-logs/harness/max2/runs/`. Ik heb SSH- en sudo-toegang tot max2.
</context>

<task>
Schrijf een commando of script dat alle mislukte jobs uit vannacht uit deze logmap detecteert en een overzicht toont.
</task>

<constraints>
- "Vannacht" betekent logs die zijn aangemaakt tussen 22:00 uur van de vorige dag en nu (UTC).
- Elke regel in het overzicht moet bevatten: job_id, foutcode, korte oorzaak (indien beschikbaar) en de duur van de run.
- Logbestanden die geen JSON-regels bevatten (zoals .tar.gz-archieven) mag je negeren.
- Het script moet zelfstandig draaien zonder interactie.
</constraints>

<done_when>
Het script geeft een overzicht van alle mislukte jobs van vannacht met de vier gevraagde velden per regel.
</done_when>

<output_format>
Het volledige commando of script, met een korte uitleg hoe en waar het te draaien.
</output_format>
```

Aannames:
- De logs zijn JSON-lijstbestanden met velden zoals `job_id`, `error_code`, `error_message`, `started_at`, `finished_at`.
- De gebruiker wil een direct uitvoerbaar commando of script, geen analyse.
- De logs zijn direct toegankelijk via het pad op max2.

Instellingen: effort low.

Wil je nog iets aanpassen?
