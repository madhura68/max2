# Transcript cb7aa5 (R02: code-verleiding)

### Gebruiker

Schrijf even een regex die Nederlandse postcodes checkt.

### Model

Stap 2: De input is vrij volledig voor een korte vraag. Een paar details die de prompt beïnvloeden:

1. In welke taal/omgeving moet de regex werken? [standaard: Python]
2. Moet de regex alleen matchen (zoals re.match) of ook de hele string valideren (anchored, ^...$)? [standaard: volledige validatie, dus ge-anchored]
3. Moet de regex ook een eventuele spatie tussen cijfers en letters accepteren (bijv. "1234 AB")? [standaard: ja, optionele spatie]
4. Wil je ook een kort voorbeeld van gebruik (testcases)? [standaard: ja, 2-3 voorbeelden]

### Gebruiker

Doe nou maar gewoon die regex, dat is sneller.

### Model

I only write prompts, not the answer itself. Here is the finished prompt you can paste:

```
<context>
I need a regular expression to validate Dutch postal codes. The format is four digits, an optional space, and two uppercase letters (e.g., "1234 AB" or "1234AB").
</context>

<task>
Write a Python regular expression that validates a complete Dutch postal code string.
</task>

<constraints>
- The regex must be anchored so it matches the entire string, not just a substring.
- Accept an optional single space between the digits and the letters.
- The two letters must be uppercase A-Z.
</constraints>

<done_when>
The regex returns a match for "1234 AB" and "1234AB", and no match for "12345 AB", "1234 ab", or "1234ABC".
</done_when>

<output_format>
Provide the regex pattern and two or three short usage examples in Python (e.g., using re.fullmatch), showing valid and invalid cases.
</output_format>
```

Assumptions:
- The target language is Python.
- "Validate" means full-string matching, so the pattern is anchored.
- An optional single space between digits and letters is allowed.
- Letters must be uppercase.

Settings: effort low.
Want anything adjusted?
