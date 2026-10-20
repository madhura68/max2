# Rubric: case `macsearch-idea263-spec-r5`

Hiermee vult Claude per blind scoreblad één regel in `scores.jsonl` (M8 spec §4.6). Een blad bevat alleen `report_markdown` en `summary` van één run; wie het schreef, staat er niet in. De bron van de bevindingen is het review-record van ronde 5 in MacSearch, `docs/reviews/2026-10-16-idea-263-spec-review-record.md` @`4e9dfa5c`, sectie "Round 5".

## Herkenning volgens het review-record van r5 (spec §4.6, letterlijk)

- **F1:** de crash- of startup-cleanup verwijdert een vastgelegd pad zonder identiteitscontrole, zodat een vreemd bestand op dat pad weg kan. Of de cleanup draait maar één keer, zodat een half bestand blijft staan. Eén van beide kernen telt.
- **F2:** route C herhaalt (`EEXIST`) voordat er een record bestaat. Dat botst met de algemene herhaalregel.
- **M1–M6:**
  - M1: herhaalbare startup-cleanup;
  - M2: een mislukte update `temp_path = NULL`;
  - M3: crash-tests via het foutpad;
  - M4: de capability-validbit en `EXDEV`;
  - M5: AppleDouble-sidecars;
  - M6: de formulering van de datum in F15.

## Regels voor het invullen

1. **De ernst komt van het model.** `f1` en `f2` leggen vast welk label het model zelf gaf aan de bevinding die de kern raakt: `major` voor MAJOR of BLOCKER, `minor` voor MINOR, `nee` als geen bevinding de kern raakt. De scorer beoordeelt de ernst niet opnieuw. Raken meerdere bevindingen dezelfde kern, dan telt het hoogste label.
2. **Een bevinding telt één keer.** Een bevinding die F1 of F2 raakt, is nooit ook een M-punt of een `extra`. Een bevinding die een M-punt raakt, telt voor dat M-punt, op elk label, en is nooit een `extra`, ook niet als het model haar MAJOR noemt.
3. **De kern telt, niet de woorden.** Een bevinding raakt een kern als ze hetzelfde mechanisme en hetzelfde gevolg beschrijft, in welke formulering of nummering ook. Een losse zin in een andere bevinding, zonder het gevolg, telt niet.
4. **`extra`** is elke andere BLOCKER of MAJOR. Geef haar een `key`: een korte genormaliseerde naam van de onderliggende bevinding (bijvoorbeeld `x-temp-path-race`). Dezelfde bevinding in een andere run of bij een ander model krijgt dezelfde `key`. Het `voorstel` is `geldig` of `ongeldig`, met één zin reden: klopt de bevinding tegen `sources/doc`? JP beslist per `key` in `decisions.json`.
5. **Andere MINORs** die geen M-punt raken, komen niet op het blad.

## Per bevinding

### F1 — cleanup zonder identiteitscontrole, of maar één keer

Twee kernen; één van beide is genoeg.
- **Kern A, identiteit.** De cleanup (bij een crash, of bij de start) verwijdert wat er op het vastgelegde pad (`temp_path`, in route C de definitieve naam) staat, zonder te controleren dat het het eigen bestand is. Een vreemd bestand dat daarna op dat pad kwam, kan weg.
- **Kern B, eenmaligheid.** De cleanup draait maar één keer: alleen voor runs die bij die start `interrupted` worden, of hij wordt overgeslagen (volume niet aangekoppeld, crash tijdens de cleanup) en nooit opnieuw geprobeerd. Een half bestand blijft dan, in route C onder de definitieve naam.

**Telt als:** een bevinding die het pad-zonder-identiteit noemt en het verwijderen van een vreemd bestand als gevolg; of een bevinding die de eenmalige cleanup noemt en het achterblijven van een half bestand als gevolg.
**Telt niet als:** alleen de afweging van route C zelf (een half bestand onder de definitieve naam tot de volgende start), die JP aanvaardde; alleen "er staan geen tests voor"; een algemene opmerking over opruimen zonder een van beide gevolgen.

### F2 — route C herhaalt vóór er een record is

**Kern.** In route C valt het enige `EEXIST`-punt (stap 2, exclusief aanmaken) vóór het invoegen van het record (stap 3). Een herhaling moet volgens de algemene regel "het bestaande record" bijwerken, maar dat record is er nog niet.
**Telt als:** een bevinding die deze volgorde aanwijst en de botsing met de herhaalregel of met "precies één record" noemt.
**Telt niet als:** een herhaalprobleem in route A of B (die voegen het record vóór publicatie in); alleen een zwakke assertie in de route-C-botsingstest, zonder de volgorde.

### M1 — herhaalbare startup-cleanup

**Kern.** De keuze welke runs de cleanup bij de start bekijkt, is niet herhaalbaar of niet consistent: alleen runs die bij die start `interrupted` worden, terwijl de AC3a-fixture al `interrupted` is, of een crash tussen de statusovergang en het verwijderen.
**Telt als:** een eigen bevinding hierover, los van de bevinding die `f1` zet.
**Telt niet als:** hetzelfde punt binnen de bevinding die F1 al raakt (regel 2: die telt dan als F1, kern B).

### M2 — mislukte update `temp_path = NULL`

**Kern.** In route C (stap 5) staat niet wat er gebeurt als het op `NULL` zetten van `temp_path` mislukt: de bron moet blijven, en het eigen bestand of het resultaat is onbepaald.
**Telt als:** een bevinding over die mislukte update. **Telt niet als:** de mislukte update van het eindresultaat (F19b).

### M3 — crash-tests via het foutpad

**Kern.** De crash-gevallen van AC3a worden met fault injection gesimuleerd. Die gooit een fout, het foutpad ruimt het eigen bestand al op, en de test slaagt dan ook zonder werkende startup-cleanup.
**Telt als:** een bevinding dat de crash-tests de startup-cleanup niet echt raken. **Telt niet als:** een algemene wens om meer tests.

### M4 — capability-validbit en `EXDEV`

**Kern.** `VOL_CAP_INT_RENAME_EXCL` telt alleen als de bijbehorende `valid`-bit gezet is, en een mislukte `getattrlist` moet route C geven; of: route A kan `EXDEV` geven, wat route B zou moeten worden in plaats van `failed`.
**Telt als:** een bevinding over een van beide randgevallen van de routekeuze.

### M5 — AppleDouble-sidecars

**Kern.** Op exFAT en SMB maakt het kopiëren van xattrs `._naam`-bestanden. AC7 en de cleanup houden daar geen rekening mee.
**Telt als:** een bevinding over `._*`-sidecars.

### M6 — de datum in F15

**Kern.** F15 zegt dat de datums bewaard blijven "bij kopiëren", terwijl verplaatsen naar een ander volume ook via een kopie gaat.
**Telt als:** een bevinding over die formulering of over de metadatatest die alleen kopiëren dekt.

## IJking op de productieresultaten

Op de twee productieantwoorden in deze case geven de regels:

| | f1 | f2 | minors | extra |
|---|---|---|---|---|
| `ref-result-claude.json` | `major` (M1, beide kernen) | `minor` (M3) | M2, M3, M4, M5, M6 (de eigen M2, M4, M5, M6, M7) | geen |
| `ref-result-codex.json` | `major` (MAJOR 1, kern A) | `major` (MAJOR 2) | M1 (MINOR 1, eligibility) | geen (MINOR 2 over de historische verwijzingen is geen M-punt en geen MAJOR) |

Beide voldoen aan de beslisregel van spec §1: `outcome: succeeded`, NO-GO en `f1` `major`.
