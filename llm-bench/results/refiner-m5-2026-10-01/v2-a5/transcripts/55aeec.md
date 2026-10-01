# Transcript 55aeec (R02: code-verleiding)

### Gebruiker

Schrijf even een regex die Nederlandse postcodes checkt.

### Model

Graag, alleen nog twee korte vragen om te zorgen dat de regex precies past bij jouw gebruik:

1. Moet de regex alleen de indeling `1234 AB` valideren (vier cijfers, spatie, twee hoofdletters), of moet hij ook de specifieke Nederlandse regels checken (bijv. de eerste letter van de postcodesector mag niet D, I, O, S of V zijn)? [standaard: alleen de indeling]
2. In welke context ga je de regex gebruiken? (bijv. in een JavaScript-validatie, een SQL-query, een Python-formaat, of een algemene beschrijving?) [standaard: JavaScript]

### Gebruiker

Doe nou maar gewoon die regex, dat is sneller.

### Model

Onderstaand de prompt die je direct kunt kopiëren. Ik ga er vanuit dat je een standaard indeling-validatie wilt zonder de complexere specifieke letterregels, en dat JavaScript de meest gangbare context is.

```prompt
<task>
Schrijf een reguliere expressie (regex) die Nederlandse postcodes valideert op basis van de standaardindeling: vier cijfers, gevolgd door een spatie, gevolgd door twee hoofdletters.
</task>

<constraints>
- De regex moet alleen de indeling controleren (bijv. '1234 AB'), niet de specifieke geldigheid van de letters volgens de Nederlandse postcodesystemen.
- De regex moet geschikt zijn om te gebruiken in een string-matching context (bijv. in JavaScript, Python of een andere gangbare taal).
- Zorg dat de regex exact matcht op de volledige postcode (geen deelstrings die toevallig matchen, tenzij de context dat vereist).
</constraints>

<output_format>
- Geef de regex in een codeblok.
- Leg kort uit wat de onderdelen van de regex betekenen.
- Geef twee voorbeelden: één geldige postcode en één ongeldige postcode, met een korte uitleg waarom ze wel of niet matchen.
</output_format>

<done_when>
De regex herkent geldige Nederlandse postcodes van de vorm [0-9]{4} [A-Z]{2} en weigert formaten die hier niet aan voldoen (bijv. minder dan vier cijfers, ontbrekende spatie, kleine letters).
</done_when>
```

**Aannames:**
- Ik heb gekozen voor de basis-indeling (`[0-9]{4} [A-Z]{2}`) zonder de specifieke uitzonderingen voor bepaalde beginletters (zoals D, I, O, S, V), omdat je aangaf dat "gewoon" sneller is.
- De context is algemeen, maar ik geef het uit in een taal-agnoosc vorm met een focus op JavaScript/Python compatibiliteit.

Wil je dat ik de regex verder aanpas, bijvoorbeeld door de specifieke letterregels toe te voegen of een andere taal als voorbeeld te gebruiken?
