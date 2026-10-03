# Beoordeling criteria 4 en 5 — M7 Taak 8 (selectie van 12 benchmarktaken)

## Waarom

We kiezen 12 oude, afgeronde Scrum4Me-taken als benchmark voor een taalmodel. Het model krijgt per taak:
- de taaktekst: `task.title`, `task.description`, `task.implementation_plan`, en `story.title`, `story.description`,
  `story.acceptance_criteria`;
- de repo op `base_commit` (inclusief `docs/`), met tools om bestanden te lezen, te schrijven en tests te draaien.

Daarna worden de **verborgen tests** gedraaid tegen zijn werk. Dat zijn de testbestanden die `ref_commit` toevoegde of wijzigde.
`__tests__/` wordt daarvoor exact teruggezet naar `ref_commit`. Een taak is alleen een eerlijke meting als:

- **C4 — de verborgen tests toetsen alleen wat de taaktekst vastlegt** (namen, signaturen, gedrag), niet toevallige details van
  de oplossing van toen. Een redelijke implementatie die de tekst volgt, moet de tests kunnen halen.
  - **Nee** bij bijvoorbeeld:
    - exacte meldingen of strings die niet in de tekst staan;
    - een import van een bestand, export of helper die de tekst niet noemt (het model kan die naam niet weten);
    - interne details (aantal aanroepen, privé-toestand, volgorde) die de tekst niet beschrijft;
    - een uitvoerformaat dat niet is vastgelegd;
    - afhankelijkheid van bestanden buiten `__tests__/` die `ref_commit` toevoegt of wijzigt (fixtures, scripts);
    - gewijzigde bestaande tests die alleen bij de oude oplossing passen.
  - **Ok** als de imports en het geteste gedrag af te leiden zijn uit de tekst: Files/Interfaces in het plan, acceptatiecriteria
    van de story, beschreven gedrag.
  - Twijfel bij één of twee asserties tussen veel goede: zou een redelijke implementatie van de tekst daarop falen? Ja → nee.
- **C5 — het plan bevat niet de volledige implementatie.** Dat geldt voor het `implementation_plan` in de taak, en ook voor een
  plan van deze taak dat op `base_commit` al in de repo staat (agent-harness: `docs/plans/M*.md`; scrum4me-mcp:
  `docs/plans/*`, `docs/superpowers/plans/*`). Anders meet de taak overtikken.
  - **Nee** als een codeblok in een van die plannen het grootste deel van de `src/`-wijziging van `ref_commit` bevat
    (kopieerbare functiebodies).
  - **Ok** bij signaturen, interfaces, een klein fragment voor een kwetsbaar contract, en stappen in proza.

## Hoe

- Case-tekst (een regel per kandidaat, met `id`, `repo_url`, `base_commit`, `ref_commit`, `task`, `story`, `hidden_tests`,
  `lines`, `kind`):
  `python3 -c "import json; [print(json.dumps(c, ensure_ascii=False, indent=1)) for c in map(json.loads, open('/private/tmp/claude-501/-Users-janpetervisser-Development-Scrum4Me--claude-worktrees-heuristic-ishizaka-8d42c7/f774c898-2ed2-4aa4-aa08-b8148524ade3/scratchpad/m7-selectie/cases-kandidaten.jsonl')) if c['id']=='<ID>']"`
- Repo's, **alleen lezen**:
  - agent-harness: `/Users/janpetervisser/Development/agent-harness`
  - scrum4me-mcp: `/Users/janpetervisser/Development/scrum4me-mcp-stable`
- Toegestaan zijn alleen `git -C <repo> show|ls-tree|diff|log|grep`. **Nooit** checkout, switch, fetch, pull, reset, stash,
  worktree, of iets schrijven in de repo's. Geen netwerk.
  - Verborgen test op ref: `git -C <repo> show <ref>:<pad>`
  - De `src/`-wijziging: `git -C <repo> diff --no-renames <base> <ref> -- src`
  - Plannen op base: `git -C <repo> ls-tree -r --name-only <base> -- docs`, dan `git -C <repo> show <base>:<bestand>`. Zoek de
    sectie van deze taak op titel, "Taak N" of commitboodschap.
- Alles wat de tests importeren of aanroepen, toets je aan de tekst.

## Uitvoer

Schrijf naar het uitvoerbestand dat je opdracht noemt, per kandidaat:

```
### <ID> (<taakcode>, <ref 8 tekens>, <lines> regels, <kind>)
- C4: ok|nee — <één regel reden, met testbestand:regel als bewijs>
- C5: ok|nee — <één regel reden; noem de plannen die je bekeek>
- Opmerking: <wat --check-case of de bench kan breken: netwerk, git of timing in de tests, bestanden buiten src/__tests__ nodig, soort klopt niet> of "geen"
```

Antwoord daarna kort: een tabel `ID | C4 | C5 | opmerking` met elk één regel, en het pad van je uitvoerbestand.
Start geen subagents. Ruim alleen op wat je zelf maakte, op exact pad.
