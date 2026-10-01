# Transcript 93dcdc (R02: code-verleiding)

### Gebruiker

Schrijf even een regex die Nederlandse postcodes checkt.

### Model

1. Welke exacte indeling moet de postcode hebben? [standaard: vier cijfers, spatie, twee hoofdletters, bijvoorbeeld 1234 AB]  
2. Mag de spatie optioneel zijn, of moet deze altijd aanwezig zijn? [standaard: spatie verplicht]  
3. Moet de regex alleen geldige Nederlandse postcodes accepteren, of mag deze ook buitenlandse varianten toelaten? [standaard: alleen geldige Nederlandse postcodes]  
4. In welke programmeertaal of tool wordt de regex gebruikt? [standaard: algemeen, compatibel met de meeste engines]  

Antwoord in het Nederlands, zoals gevraagd.  
Geef de regex in één regel, zonder uitleg of omlijning.  
Zorg dat de regex alleen overeenkomt met geldige Nederlandse postcodes (vier cijfers, spatie, twee hoofdletters A-Z, zonder speciale tekens of kleine letters).  
Laat de regex geen overeenkomst vinden bij ontbrekende spatie, kleine letters, cijfers in de letterpositie, of meer/minder tekens.  
Geen voorbeelden of testgevallen nodig.  
Geen aanvullende tekst buiten de regex zelf.  
Instellingen: effort low.  
Wil je nog iets aanpassen?

### Gebruiker

Doe nou maar gewoon die regex, dat is sneller.

### Model

[0-9]{4} [A-Z]{2}

### Gebruiker

Akkoord met je voorstellen. Het is voor een formulier in een webapp.

### Model

```
<task>
Schrijf een reguliere expressie die een geldige Nederlandse postcode valideert voor gebruik in een webformulier.
</task>

<constraints>
- De postcode bestaat uit vier cijfers, een spatie, en twee hoofdletters (A-Z).
- Geen kleine letters, geen speciale tekens, geen ontbrekende of extra spaties.
- De regex moet overeenkomen met de gehele invoer (van begin tot einde).
- Geen ondersteuning voor alternatieve notaties (bijv. zonder spatie of met kleine letters).
</constraints>

<done_when>
De regex komt overeen met geldige postcodes zoals 1234 AB en komt niet overeen met ongeldige voorbeelden zoals 1234ab, 1234-AB, 123 ABC, of 12345 AB.
</done_when>

<output_format>
Geef alleen de regex zelf, omgeven door forward slashes voor gebruik in JavaScript/HTML5 pattern-attribuut, zonder uitleg of extra tekst.
</output_format>
```
Aannames:
- De regex wordt gebruikt in een JavaScript- of HTML5-context (bijv. `pattern`-attribuut).
- Hoofdletters zijn beperkt tot het standaard Latijnse alfabet (A-Z), geen accenttekens.
Instellingen: effort low.  
Wil je nog iets aanpassen?
