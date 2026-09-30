# Transcript 8ced9f (R08: agenttaak)

### Gebruiker

Laat Claude Code mijn repo migreren van Jest naar Vitest.

### Model

Laat me helpen deze taak goed te definiëren. Ik heb een paar vragen nodig om de scope en aanpak vast te leggen.

1. Wat is de huidige omvang van de testcode? [standaard: het hele project, geschat op basis van bestandsgrootte/aantal testbestanden]
2. Wil je dat Claude Code dit automatisch doet (code aanpast, imports wijzigen) of alleen een gedetailleerd migratieplan en diffs oplevert? [standaard: automatisch uitvoeren via Claude Code]
3. Zijn er specifieke Jest-functies die in Vitest anders werken en waar extra aandacht voor nodig is? (bijv. mocking van `window`/`document`, timers, of specifieke matchers) [standaard: standaard migratie, maar wees alert op veelvoorkomende valkuilen]
4. Moet er ook een verificatiestap in zitten (bijv. `vitest run` uitvoeren) om te bevestigen dat de tests nog steeds doorlopen? [standaard: ja, voer `vitest run` uit na migratie en rapporteer of alle tests slagen]

Wil je nog iets toevoegen of aanpassen aan deze aannames?

### Gebruiker

Akkoord met je voorstellen. Het is een TypeScript-project met ongeveer 200 tests.

### Model

Bedankt voor de bevestiging. Hier is de definitieve prompt, geoptimaliseerd voor Claude Code.

```markdown
<context>
Ik heb een TypeScript-project met ongeveer 200 tests dat momenteel Jest als testrunner gebruikt. Ik wil dit migreren naar Vitest om van de moderne features en betere TypeScript-ondersteuning gebruik te maken.
</context>

<task>
Voer de volledige migratie van Jest naar Vitest uit in deze repository. Dit omvat:
1. Installatie van de benodigde `vitest` en `@vitest/ui` (en eventuele nodige polyfills zoals `happy-dom` of `jsdom` afhankelijk van de testsetup).
2. Aanpassing van de `package.json` (verwijder Jest-afhankelijkheden, voeg Vitest toe, pas het test-script aan).
3. Migratie van alle testbestanden:
   - Vervang `jest` imports door `vitest` (bijv. `describe`, `it`, `expect`, `mock`).
   - Pas de testsetup aan voor Vitest (bijv. globals, environment).
   - Vervang Jest-specifieke matchers of functies door hun Vitest-equivalenten waar nodig.
4. Verwijdering van onnodige Jest-configuratiebestanden (zoals `jest.config.js` of `jest.config.ts`) tenzij ze nodig blijven voor een hybride fase.
5. Uitvoeren van `vitest run` om te verifiëren dat alle tests nog steeds slagen.
</task>

<constraints>
- Behoud de testdekking en -logica; verander geen testcases zelf, alleen de implementatie die nodig is voor de overgang.
- Zorg voor goede TypeScript-typing in de nieuwe setup.
- Als er specifieke Jest-functies zijn die niet direct overzetbaar zijn (bijv. `jest.mock` vs `vi.mock`), gebruik dan de Vitest-standaardaanpak en leg kort uit waarom.
- Wees voorzichtig met globale staat; Vitest kan hier anders mee omgaan dan Jest.
</constraints>

<done_when>
- Alle 200 tests lopen succesvol via `vitest run`.
- De `package.json` is up-to-date met de juiste dependencies en scripts.
- Er zijn geen overgebleven Jest-specifieke imports of configuraties die niet meer nodig zijn.
</done_when>

<output_format>
Voer de codeaanpassingen direct uit in de repository. Rapporteer daarna kort:
1. Welke bestanden zijn aangepast of verwijderd.
2. Eventuele bekende verschillen in gedrag tussen Jest en Vitest in deze codebase.
3. De output van `vitest run` om te bevestigen dat alles slaagt.
</output_format>

<check_in>
Als er een specifieke test mislukt door een fundamenteel verschil in API (bijv. mock-strategie), stop dan en leg de situatie uit in plaats van te gokken.
</check_in>
```

Assumptions:
- Je wilt dat Claude Code de code direct aanpast en de tests uitvoert (niet alleen een plan).
- De tests gebruiken `jsdom` of `happy-dom` als environment; Claude Code zal dit detecteren en installeren.
- Er is geen speciale `jest.config` met complexe aliassen of transform-regels die handmatig moeten worden overgezet; Claude Code zal de standaard Vitest-configuratie gebruiken en daarop aanpassen indien nodig.

Instellingen: effort medium.

Wil je nog iets aanpassen?
