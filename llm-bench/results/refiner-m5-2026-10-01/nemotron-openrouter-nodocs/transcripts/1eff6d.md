# Transcript 1eff6d (R02: code-verleiding)

### Gebruiker

Schrijf even een regex die Nederlandse postcodes checkt.

### Model

Vier vragen om de prompt scherp te krijgen:
1. Welke indeling moet de postcode hebben? [standaard: vier cijfers, spatie, twee hoofdletters (bijv. 1234 AB)]
2. Moet de spatie verplicht zijn of mag deze ook ontbreken? [standaard: spatie verplicht]
3. Welke letters zijn toegestaan in de tweelettercode? [standaard: alle hoofdletters A-Z, behalve SA, SD en SS]
4. Moet de regex alleen valideren (true/false) of ook de onderdelen vastleggen (groepen)? [standaard: alleen valideren]

Geef uw antwoord bijvoorbeeld als: "1 ok, 2 nee: spatie mag ontbreken, 3 ok, 4 groepen voor cijfers en letters". Daarna lever ik de prompt.

### Gebruiker

Doe nou maar gewoon die regex, dat is sneller.

### Model

Ik schrijf alleen prompts, dus hieronder staat de prompt voor Opus 5.5 die de gevraagde regex oplevert.

```
<context>
De gebruiker wil een reguliere expressie die een Nederlandse postcode valideert. De postcode moet worden gecontroleerd op juiste opmaak volgens de officiële Nederlandse indeling.
</context>

<task>
Geef een reguliere expressie (regex) die een Nederlandse postcode valideert volgens de standaardindeling: vier cijfers, een spatie, en twee hoofdletters, waarbij de tweelettercombinatie SA, SD en SS niet toegestaan is.
</task>

<constraints>
- De spatie tussen de cijfers en de letters is verplicht.
- Alleen hoofdletters A-Z zijn toegestaan in de tweelettercode, met uitzondering van SA, SD en SS.
- De regex moet een volledige match opleveren (van begin tot einde van de string).
- Geen capturing groups nodig; alleen een boolean match is vereist.
</constraints>

<done_when>
De regex komt overeen met geldige postcodes zoals 1234 AB, 9999 ZZ en komt niet overeen met ongelijke voorbeelden zoals 1234AAB, 1234 ABB, 1234 SA, 1234AB (zonder spatie) of 123-AB.
</task>

<output_format>
Alleen de reguliere expressie als platte tekst, zonder omlijsting of uitleg.
</output_format>
```

Aannames:
- De gebruiker wil de standaard Nederlandse postcodeindeling zoals gebruikt door PostNL.
- Hoofdletters zijn vereist; kleine letters worden niet geaccepteerd tenzij anders aangegeven.
- De regex wordt gebruikt in een context waarin volledige string matching nodig is (bijv. met ^ en $).

Instellingen: effort medium.  
Wil je nog iets aanpassen?
