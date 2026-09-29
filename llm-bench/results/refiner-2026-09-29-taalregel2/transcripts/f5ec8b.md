# Transcript f5ec8b (R10: Engels)

### Gebruiker

I need a prompt to get Claude to help me write a cover letter for a data engineer job.

### Model

Laten we je prompt verfijnen. Geef me een paar details zodat de prompt echt aansluit bij jouw situatie.

1. Welke specifieke ervaring of vaardigheden wil je benadrukken? [standaard: ervaring met grote datasets en Python/SQL]
2. Voor welke vacature of bedrijf schrijf je deze? [standaard: een algemene data engineer rol bij een techbedrijf]
3. Wat is je huidige rol of achtergrond? [standaard: data analyst met 3 jaar ervaring]
4. Welke toon wil je? [standaard: professioneel maar toegankelijk, niet te formeel]

### Gebruiker

Go with your suggestions. Extra: the job is at a mid-size logistics company; I have 4 years of Python and Airflow experience.

### Model

De onderstaande prompt is klaar om te kopiëren. Ik heb aangenomen dat je ook ervaring hebt met cloud-platformen (AWS/GCP/Azure) en SQL, aangezien dit standaard is voor een Data Engineer met jouw profiel. Mocht dit niet kloppen, pas dan de `<material>` sectie aan.

```prompt
<context>
Ik solliciteer op de functie van Data Engineer bij een middelgroot logistiek bedrijf. Mijn achtergrond is 4 jaar ervaring met Python en Airflow. Het bedrijf is actief in de logistiek, wat betekent dat ze waarschijnlijk te maken hebben met real-time data, supply chain optimalisatie en schaalbare pipelines. Ik wil mijn technische expertise koppelen aan de specifieke uitdagingen in deze sector.
</context>

<material>
Hieronder vind je mijn relevante werkervaring en vaardigheden. Gebruik deze informatie om een overtuigende cover letter te schrijven.

[FILL IN: Voeg hier je CV, een samenvatting van je werkervaring, of specifieke projecten toe die relevant zijn voor de rol. Bijvoorbeeld: "Bij mijn vorige werk heb ik Airflow DAGs geoptimaliseerd...", "Ik heb ervaring met AWS S3 en Redshift..."]
</material>

<task>
Schrijf een overtuigende en gepersonaliseerde cover letter voor de functie van Data Engineer bij een middelgroot logistiek bedrijf.
</task>

<constraints>
- Benadruk mijn 4 jaar ervaring met Python en Airflow.
- Leg uit hoe mijn technische achtergrond waarde toevoegt aan de logistieke sector (bijv. door efficiëntie, betrouwbare dataflows of schaalbaarheid).
- Houd de toon professioneel maar toegankelijk; vermijd te formeel of 'gekke' jargon.
- Maak de letter specifiek genoeg voor een middelgroot bedrijf (focus op impact en veelzijdigheid, niet alleen op enterprise-schaal).
</constraints>

<output_format>
De cover letter zelf, direct te gebruiken. Geen inleiding of uitleg aan mijn kant.
</output_format>
```

**Aannames:**
- Je hebt ook basiskennis van SQL en een cloud-provider (AWS/GCP/Azure), wat standaard is voor deze rol.
- De "middelgrote" omvang impliceert dat je ook met brede taken te maken krijgt, in tegenstelling tot een zeer gespecialiseerde rol in een startup of enterprise.
- De focus ligt op de combinatie van technische skills (Airflow/Python) met de domeinkennis van logistiek.

**Instellingen:**
- Effort: **medium** (voldoende voor tekstgeneratie, geen complexe redenering nodig).

Wil je nog iets aanpassen? Bijvoorbeeld de toon verander naar meer 'startup-achtig' of specifiekere tools toevoegen?
