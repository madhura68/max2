# M7 Taak 11: schrijft llm-bench/results/task-bench-2026-10-03.md uit rapport-data.json, cases.jsonl en het grootboek.
# Gebruik (vanuit de max2-repo-root): python3 rapport.py
import json, math, os
from collections import Counter

RES = "llm-bench/results/task-bench-2026-10-03"
runs = json.load(open(f"{RES}/rapport-data.json"))
cases = [json.loads(l) for l in open("llm-bench/task_bench/cases.jsonl")]
ledger = [json.loads(l) for l in open(f"{RES}/vensters/ledger.jsonl")]
H, G = "qwen3.8-openrouter", "gsq-lokaal"
by = {(r["label"], r["case"]): r for r in runs}
klasse = lambda n: "klein" if n <= 80 else "middel" if n <= 200 else "groot"
usd = lambda x: "–" if x is None else f"${x:.4f}".replace(".", ",")
num = lambda n: f"{n:,}".replace(",", ".")
dec = lambda x: str(x).replace(".", ",")


def uitkomst(r):
    s = r["status"]
    if s == "limiet":
        return f"limiet ({r['turns']} beurten)"
    if s == "verborgen_tests_rood":
        return f"verborgen tests rood ({len(r['failing'])})"
    return s


def verdict(h, g):  # spec §1, gelijk aan task_bench/score.py
    if h < 9: row, base = 1, "gezakt"
    elif g >= 9: row, base = 2, "max2 volstaat"
    elif h - g >= 3: row, base = 3, "meerwaarde"
    else: return "onbeslist"
    b = h in (9, 8) or (row in (2, 3) and g in (9, 8)) or (row == 3 and h - g == 3)
    return "onbeslist" if b else base


h = sum(by[(H, c["id"])]["status"] == "geslaagd" for c in cases)
g = sum(by[(G, c["id"])]["status"] == "geslaagd" for c in cases)
tot = math.fsum(e["cost_usd"] or 0 for e in ledger)
nulls = sum(e["cost_usd"] is None for e in ledger)
hosted_runs = math.fsum(e["cost_usd"] or 0 for e in ledger if e["kind"] == "run" and e["label"] == H and not e["id"].startswith("AH-01-qwen3.8-openrouter-d6c19fec"))
proef = [e for e in ledger if e["id"] in ("AH-01-qwen3.8-openrouter-d6c19fec", "probe-qwen3.8-openrouter-20261003T081726Z")]
probe_gehost = [e for e in ledger if e["kind"] == "probe" and e["label"] == H and e not in proef]
mins = lambda lab: sum(by[(lab, c["id"])]["minutes"] for c in cases)

L = []
w = L.append
w("# Task-bench: Qwen 3.8 voor een 96 GB-machine op echt werk (M7, 2026-10-03)")
w("")
w("## Kort")
w("")
w(f"- **Oordeel: onbeslist.** Gehost (`qwen/qwen3.8-27b` in BF16, zoals hij op een Mac van 96 GB zou draaien) haalde **{h} van 12**,"
  f" `gsq-lokaal` op max2 ook **{g} van 12**. Gehost ligt op de grens (8), dus volgens spec §1 is het oordeel onbeslist, wat gsq ook haalt.")
w("- **JP koos op 2026-10-04: stoppen.** Volgens spec §1 betekent dat: geen meerwaarde aangetoond. Geen Mac voor dit doel.")
w("- Op deze 12 taken haalt max2 nu al wat de 27B op volle precisie haalt. De twee modellen verschillen op twee taken, één naar elke kant"
  " (AH-08 alleen gehost, AH-16 alleen gsq). Drie taken haalde geen van beide.")
w(f"- Geen benchfouten en geen herhaalde verzoeken. Kosten van heel M7: **{usd(tot)}** (budget $19,08). Gehost duurde {mins(H):.0f} min voor"
  f" de 12 runs, gsq {mins(G):.0f} min.")
w("")
w("## Opzet")
w("")
w("- **Echt werk:** 12 oude, afgeronde Scrum4Me-taken (`TASK_IMPLEMENTATION`), opnieuw uitgevoerd vanaf hun begincommit met de taaktekst"
  " zoals de productieworker die krijgt. Een run is **geslaagd** als de verify-gate van de repo groen is én de verborgen tests van de"
  " echte oplossing (`ref_commit`) slagen; daarvoor worden `__tests__/` en de runnerconfig exact teruggezet.")
w("- **Bench:** `harness task-bench` (agent-harness `24aa096`), dezelfde lus, tools, gate (`maxVerifyRepairs` 3) en limieten als `runTaskJob`"
  " (`maxTurns` 40, `maxOutputTokens` 80000, `maxWallSeconds` 2400, `maxToolErrors` 8, `contextTokens` 65536), zonder doc-tools.")
w("- **Modellen:** `qwen3.8-openrouter` = `qwen/qwen3.8-27b` via OpenRouter, alleen op een 16-bit-route (`quantizations: [bf16, fp16]`,"
  " `data_collection: deny`, `require_parameters`, `reasoning.effort: medium`), herhaling bij storingen aan; `gsq-lokaal` ="
  " `qwen3.8-gsq-rco:27b-iq3_s-text` op max2 (Ollama, 64k context, thinking aan), zoals de productieworker. Eén run per taak.")
w("- **Beslisregel (spec §1):** een model kan het werk aan bij minstens 9 van 12; meerwaarde vraagt bovendien minstens 3 meer dan gsq; een"
  " telling op de grens (9 of 8) of een verschil van precies 3 maakt het oordeel onbeslist.")
w("- Spec: `docs/specs/2026-10-02-task-bench-design.md` (rev 5) en plan `docs/plans/M7-task-bench.md` (rev 4 met uitvoeringsnotities) in agent-harness.")
w("")
w("## De takenset")
w("")
w("Bron-pin (origin/main, 2026-10-03): agent-harness `67377014`, scrum4me-mcp `a6b3fe0b`. Filter, koppeling, beoordeling van criteria 4/5 en"
  " het `--check-case`-bewijs per kandidaat staan in `task-bench-2026-10-03/selectie/` (voorstel.md, case-check/). JP keurde de set goed vóór"
  " increment 3; hij is bevroren in `llm-bench/task_bench/cases.jsonl`.")
w("")
w("| id | repo | taak | ref | regels | klasse | soort | verborgen tests |")
w("|---|---|---|---|---|---|---|---|")
for c in cases:
    repo = "agent-harness" if "agent-harness" in c["repo_url"] else "scrum4me-mcp"
    w(f"| {c['id']} | {repo} | {c['task']['code']} | `{c['ref_commit'][:8]}` | {c['lines']} | {klasse(c['lines'])} | {c['kind']} | "
      + ", ".join(f"`{t.removeprefix('__tests__/')}`" for t in c["hidden_tests"]) + " |")
w("")
w("Afwijkingen van spec §4.2 op JP's besluit (2026-10-03): 8 agent-harness + 4 scrum4me-mcp in plaats van 6 + 6; 2 kleine taken in plaats van 4;"
  " MC-19 (T-19) komt uit product Agent-harness (M3) in plaats van Scrum4Me; voor scrum4me-mcp is verbreed naar commits sinds 2026-05-01."
  " Reden: op het productierecept waren scrum4me-mcp-bases tussen 2026-08-12 en 2026-09-14 rood (ppe-tests zonder databasefixture),"
  " M20-bases (juli) rood op een job-config-pariteitstest, veel plannen bevatten de volledige code (criterium 5), en git-tests slagen niet"
  " in de container. Drie selectierondes `--check-case` (33 kandidaten) staan in `selectie/case-check/`.")
w("")
w("## Uitkomst per taak")
w("")
w(f"| Taak | {H} | {G} |")
w("|---|---|---|")
for c in cases:
    w(f"| {c['id']} ({c['task']['code']}) | {uitkomst(by[(H, c['id'])])} | {uitkomst(by[(G, c['id'])])} |")
w("")
w("**Redenen van falen.**")
w("")
w("- **Limiet:** elke limiet-run eindigde op `budget_exceeded` na 40 modelbeurten, zonder eindantwoord en zonder dat de gate rood was:"
  " AH-16 (alleen gehost), MC-11 en MC-31 (beide modellen). gsq haalde AH-16 wel, in 27 beurten (21,5 min).")
w("- **Verborgen tests rood** (de gate was groen; de falende tests uit `hidden-vitest.json`):")
for c in cases:
    for lab in (H, G):
        r = by[(lab, c["id"])]
        for f in r["failing"]:
            w(f"  - {c['id']}, {lab}: `{f['file']}` › {f['test']} — `{f['message']}`")
w("  - AH-17 faalt bij beide modellen op dezelfde test: de prompt moet `wijzigt niets` bevatten. Die woorden staan in de taaktekst, dus de test"
  " was eerlijk maar letterlijk (spec §6: JP beoordeelt). AH-08 bij gsq: `createPolicy` geeft bij lege argumenten een extra veld terug.")
w("")
w("## Tellingen en oordeel (spec §1)")
w("")
for lab in (H, G):
    cnt = Counter(by[(lab, c["id"])]["status"] for c in cases)
    w(f"- **{lab}:** geslaagd {cnt['geslaagd']}, verborgen_tests_rood {cnt['verborgen_tests_rood']}, verify_rood {cnt['verify_rood']},"
      f" limiet {cnt['limiet']}, geen_wijzigingen {cnt['geen_wijzigingen']}, benchfout {cnt['benchfout']}.")
w(f"- `verdict({h}, {g})` = **{verdict(h, g)}** (`task_bench/score.py`, zelfde uitkomst als deze regels). Gehost 8 valt in rij 1"
  " (gezakt, 8 of minder), maar 8 is de grens min één: daarmee is het oordeel onbeslist. Dat geldt voor elke gsq-telling.")
w("- **Betekenis voor de aankoop:** bij onbeslist kiest JP tussen meer taken en stoppen. JP koos stoppen: geen meerwaarde aangetoond, geen Mac"
  " voor dit doel. De gelijke stand (8 tegen 8, verschillen op twee taken) wijst dezelfde kant op: wat de 96 GB-klasse met dit model"
  " zou toevoegen, haalt max2 met gsq nu al.")
w("")
w("## Per run: tijd, beurten, toolfouten, kosten en aanbieders")
w("")
for lab in (H, G):
    w(f"**{lab}**")
    w("")
    w("| Taak | uitkomst | min | beurten | tools | toolfouten | in / uit (reasoning) tokens | kosten | aanbieders | herhalingen |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    for c in cases:
        r = by[(lab, c["id"])]
        prov = ", ".join(f"{k} ×{v}" for k, v in r["providers"].items()) or "–"
        w(f"| {c['id']} | {uitkomst(r)} | {dec(r['minutes'])} | {r['turns']} | {r['toolCalls']} | {r['toolErrors']} | {num(r['inputTokens'])} / "
          f"{num(r['outputTokens'])} ({'–' if r['reasoningTokens'] is None else num(r['reasoningTokens'])}) | {usd(r['costUsd'])} | {prov} | {len(r['retries'])} |")
    w("")
n_resp = sum(sum(by[(H, c["id"])]["providers"].values()) for c in cases)
w(f"Gehost kwam elke respons van DeepInfra in BF16 ({n_resp} antwoorden, plus 12 in de praktijkproef). gsq draait lokaal en meldt geen kosten en geen aparte reasoning-tokens.")
w("")
w("## Benchfouten, herhalingen en afgebroken runs")
w("")
w("Geen. Geen enkele run eindigde als benchfout, geen enkel verzoek werd herhaald (`retries` leeg in alle 25 runs), en geen run werd"
  " afgebroken: het vangnet van het nachtvenster bleef ongebruikt. Geen enkele run schreef in een submodule (controle op `write_file`/`edit_file`"
  " onder `vendor/` in elke `trace.jsonl`).")
w("")
w("## Kosten (grootboek)")
w("")
w("| post | bedrag |")
w("|---|---|")
w(f"| praktijkproef (probe + run AH-01) | {usd(math.fsum(e['cost_usd'] or 0 for e in proef))} |")
w(f"| probe gehost (Taak 9) | {usd(math.fsum(e['cost_usd'] or 0 for e in probe_gehost))} |")
w(f"| 12 gehoste runs (Taak 9) | {usd(hosted_runs)} |")
w(f"| gsq (probe + 12 runs) | $0 ({nulls} regels zonder bedrag) |")
w(f"| **totaal M7** | **{usd(tot)}** |")
w("")
w(f"Het totaal is gelijk aan de stijging van het verbruik van de OpenRouter-sleutel (0,9238 → 2,0985, gelezen zonder de sleutel te tonen)."
  " De spec schatte $0,54 per gehoste run; gemeten was het $0,013–$0,245, gemiddeld $0,09.")
w("")
w("## Endpointlijsten")
w("")
w("Bij het begin van beide gehoste vensters toonde de publieke endpointlijst van `qwen/qwen3.8-27b` 17 aanbieders, waarvan alleen DeepInfra"
  " (BF16) 16-bit met tools aanbiedt (Cerebras is FP16 maar zonder tools). Bestanden: `vensters/endpoints-proef.json` en"
  " `vensters/gehost/endpoints-qwen3.8-openrouter-20261003T121905Z.json`. De probes: proef reliable ($0,00078; a_plain via Cerebras, de rest"
  " DeepInfra), gehost reliable ($0,00077), gsq reliable.")
w("")
w("## Verschillen met productie en kanttekeningen")
w("")
w("- **Bewust anders dan productie (spec §4.1):** geen doc-tools (de bijzin in de systeemprompt en het blok `## Product` vallen weg), een"
  " eigen werkmap met de gitdir buiten de containermount, de verborgen toets na de run (schone installatie op een verse clone van"
  " `ref_commit`, dan `__tests__/` en runnerconfig terug), herhaling bij storingen alleen op de gehoste route, en een benchfout als"
  " de bench of de aanbieder faalt in plaats van een modelstatus.")
w("- **Kleine aantallen:** bij 12 taken scheelt één taak 8 procentpunt; daarom is 8 van 12 onbeslist en geen bewijs.")
w("- **Gehost ≠ lokaal op een Mac:** precisie vastgelegd op BF16, maar engine en template verschillen. Eén aanbieder (DeepInfra).")
w("- **Eén run per taak:** een steekproef; gehost is niet herhaalbaar.")
w("- **Verborgen tests kunnen streng zijn:** zie AH-17 hierboven.")
w("- **Selectie:** de set is anders samengesteld dan spec §4.2 voorschreef (zie De takenset); scrum4me-mcp telt 4 van de 12 taken.")
w("- **Bekende restpunten van de bench** (plan, uitvoeringsnotities): modelcode wordt in de verborgen toets niet geïsoleerd;"
  " `vite.config.*`/`vitest.workspace.*` worden niet teruggezet; de schone installatie komt na de betaalde run.")
w("- **Base met een bekende flake:** de bases van AH-01 en AH-02 bevatten de later gefixte search-flake in `task-tools.test.ts`. Die kan"
  " alleen de gate raken; beide modellen haalden beide taken.")
w("")
w("## Vensters en dienststand (spec §5, criterium 6)")
w("")
w("Alle vensters volgens de Vensterprocedure (M6) met de M7-punten: M4-stop fail-closed, containers volgens de dienststand gestopt, tmux"
  " met sessie-ID, eindvoorwaarde zonder `harness-`-containers, herstel. Vooraf was het telkens: worker `active`, `dsh` en `open-webui`"
  " draaiden, `tei-gpu` niet; na het herstel telkens gelijk.")
w("")
w("| venster | wanneer (CEST) | wat | dienststand voor → na |")
w("|---|---|---|---|")
w("| proef | 2026-10-03 10:12–10:37 | check-case AH-01, probe, run AH-01 (sleutel op tmpfs, daarna weg) | gelijk |")
w("| selectie 1 | 12:06–12:27 | 21 × check-case | gelijk |")
w("| selectie 2 | 12:28–12:34 | 3 × check-case | gelijk |")
w("| selectie 3 | 12:47–13:02 | 9 × check-case | gelijk |")
w("| gehost | 14:17–16:13 | Taak 9: endpointlijst, probe, 12 runs (sleutel op tmpfs, daarna weg; vangnet ongebruikt) | gelijk |")
w("| gsq | 22:00–00:19 (nacht) | Taak 10: probe, 12 runs; automatisch gestart vanaf de Mac, nazorg herstelde om 00:19 | gelijk |")
w("")
w("Het nachtvenster startte automatisch: een starter op de Mac (onder `caffeinate`) deed om 22:00 de controles en de M4-stop (max2 bereikt"
  " de database op scrum4me-srv niet), daarna draaiden run, nazorg (herstel direct na afloop) en vangnet (06:40) zelfstandig op max2."
  " Scripts en logs: `vensters/` en `vensters/mac/`.")
w("")
w("## Commits en versies")
w("")
w("- Bench: agent-harness `24aa096ee5f9` (merge PR #31), gebouwd in `~/Development/agent-harness-m7` op max2.")
w("- Driver en scorer: max2 `cb99e3db1952` (merge PR #30), clone `~/Development/max2-m7` op max2.")
w("- Worker-checkout: agent-harness `15c1e26e6d80`, vóór en na elk venster ongewijzigd; `/etc/agent-harness/worker.json` laatst gewijzigd"
  " 2026-09-29 (vóór M7), het `task`-blok was in elk venster gelijk aan `task_bench/task-config.json`.")
w("- `ollama --version`: 0.34.4.")
w("")
w("## Bestanden in `task-bench-2026-10-03/`")
w("")
w("- `selectie/`: bron-pin, voorstel met afvallers, `case-check.json` van alle 33 gecontroleerde kandidaten, beoordelingen, scripts.")
w("- `runs/<label>/<run>/`: per run `bench-result.json`, `patch.diff`, `hidden-vitest.json`, `trace.jsonl` (zonder `ws/`, `tools/`,"
  " `containers/`), ook de praktijkproef onder `runs/proef/`. Van AH-01 bij gsq ontbreken `patch.diff` en `trace.jsonl`: de secret-scan-hook"
  " van deze repo ziet de nepwaarden die het model in zijn eigen redactietest schreef (zoals `GITHUB_TOKEN: 'gh-tok…'`) als tokenachtig."
  " De originelen staan in de kopie op de Mac en in `~/m7-runs/task-bench-2026-10-03/gsq/` op max2.")
w("- `vensters/`: grootboek, `summary.csv`, endpointlijsten, probes, run-, nazorg- en vangnetscripts, logs, `.sid`-bestanden en dienststanden;"
  " `vensters/mac/`: de starter en controlescripts van de Mac. `rapport-data.json`: de cijfers achter dit rapport.")
w("")
w("## Acceptatiecriteria (spec §5)")
w("")
w("1. **Bench volgt de worker:** pariteitstest met de echte `runTaskJob` en prompttests (geen doc-toolnaam) in agent-harness PR #31"
  " (1202 tests, `npm run verify` groen); de verborgen toets telt een aangepaste runnerconfig of weggehaalde test niet als geslaagd;"
  " herhaling alleen bij tijdelijke fouten op de gehoste route, hooguit 3. De trace van de praktijkproef toont de lus. **Gehaald.**")
w("2. **Praktijkproef:** AH-01 met `qwen3.8-openrouter` geslaagd (17,2 min, $0,0658), elke respons DeepInfra BF16, 0 herhalingen,"
  " verborgen toets met `__tests__/` en runnerconfig van `ref_commit` (11/11). **Gehaald.**")
w("3. **Takenset van 12 met bewijs voor criteria 2 en 3 en de bron-pin, door JP goedgekeurd vóór increment 3:** gehaald, met de"
  " verdeling 8 + 4 in plaats van 6 per repo op JP's besluit.")
w("4. **Beide modellen 12 geldige runs:** 24 runs, elk in een modelstatus, 0 benchfouten. **Gehaald.**")
w(f"5. **Rapport met §4.8 en het oordeel volgens §1; kosten binnen §4.6:** dit rapport; oordeel onbeslist; {usd(tot)} van $19,08. **Gehaald.**")
w("6. **Diensten na elk venster als vooraf, worker-checkout en -config ongewijzigd, sleutel nergens:** zes vensters gelijk; checkout"
  " `15c1e26` ongewijzigd; `check_key.py` vond 0 treffers op de Mac-kopie (1509 bestanden) en op deze map. **Gehaald.**")
w("7. **Gates:** `npm run verify` in agent-harness (PR #31) en de llm-bench-unittests (task_bench 155, refiner 462) groen. **Gehaald.**")
open("llm-bench/results/task-bench-2026-10-03.md", "w").write("\n".join(L) + "\n")
print("regels:", len(L), "| h =", h, "g =", g, "| oordeel:", verdict(h, g), "| totaal", usd(tot), "| gehoste runs", usd(hosted_runs))
