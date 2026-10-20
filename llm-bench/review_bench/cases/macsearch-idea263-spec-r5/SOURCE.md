# Herkomst: case `macsearch-idea263-spec-r5`

De bevroren invoer van één echte `QUEUE_REVIEW`: ronde 5 van de spec-reviewloop van MacSearch IDEA-263, op 2026-10-16. De M8 review-bench (agent-harness `harness review-bench`, plan `docs/plans/M8-review-bench.md` in agent-harness) laat een remote model via LiteLLM dezelfde review doen. Deze case is privé: de spec-tekst van MacSearch staat alleen in deze repo, niet in agent-harness.

## De twee productiejobs

| Slot | Job | Dispatch-request | Verdict | Telling |
|---|---|---|---|---|
| CLAUDE | `1a78c1b8` | `23cf03c9-3443-4dd1-a640-e38a1539e294` (root_message_id `416a9b15-2795-46bb-a632-9f0891eb081e`) | NO-GO | 0 B / 1 M / 6 m |
| CODEX | `7146cbe9` | `0146a24f-df5e-4c08-868b-02d5e7387b6f` (root_message_id `f27d5e91-9278-41e3-9e41-a5e634880699`) | NO-GO | 0 B / 2 M / 2 m |

De request-ids, verdicts en tellingen staan in het review-record van MacSearch, `docs/reviews/2026-10-16-idea-263-spec-review-record.md` @`4e9dfa5c`, sectie "Round 5". De job-ids staan in de run-logs: `1a78c1b8` alleen in het Claude-log, `7146cbe9` alleen in het Codex-log.

## De bestanden en hun hashes

| Bestand | Bytes | sha256 | Bron |
|---|---|---|---|
| `review.md` | 4195 | `f56fe0a641ddb007e5216a2063b02460e60b9836c08cbc2229d8f8661fee4ead` | scrum4me-mcp `src/prompts/queue/review.md` @`e89c0961` (48 regels), onveranderd |
| `payload.json` | 6942 | `5a52a843cbca3f20cf9a6026a7764450b29217980aba4c9b70219c675aff4f8f` | `{dispatch:{input, source_artifacts}}` van de **Claude-job** `1a78c1b8` |
| `sources/doc` | 30673 | `7d5e35872c417a5656ef53794aff95675f3ac0716f6e3c46951d509f029fadaf` | spec revisie 5 |
| `sources/__dispatch_input` | 6705 | `9f6580562a3d9847e49a82697782219f22ef949d4d1a4396040106b25aaef9e3` | gereconstrueerd, zie hieronder |
| `ref-result-claude.json` | 13128 | `fd93c74cba5f1f74a1418287f8a2d0cde1aaa30e2474800f9aa8935832852618` | het resultaat van `1a78c1b8`, gereconstrueerd uit het run-log |
| `ref-result-codex.json` | 8983 | `88d42dd44643a594aef44fe309710322cd48bfe562712e52d76e19b823356ad6` | het resultaat van `7146cbe9`, gereconstrueerd uit het run-log |

`case.json` pint de eerste vier; `check_case.py` controleert ze (zie onder). De twee ref-results zijn de productieantwoorden ter vergelijking; de bench leest ze niet.

- **De pin `doc`.** `payload.json` noemt in `dispatch.input.review_documents.items[0]`: `key` `doc`, `source` `product_doc`, `product_id` `cmvayn6jl01jesy7r4mucpvgn`, `doc_id` `cmvb0lj1r000per173xpccuxf`, `revision_id` `cmvb3ea2a002zer17g4p8x98x` en de sha256 van `sources/doc` hierboven. Dezelfde hash staat in het review-record (de kop van ronde 5) en in beide run-logs.
- **De payload komt van de Claude-job.** De prompt en de payload horen als paar bij elkaar: het is de invoer die `review.md` in de Claude-container als `/tmp/payload.json` zag. Productie legde voor de payload geen hash vast; de bevroren kopie krijgt die nu in `case.json`.
- **De objective blijft ongewijzigd.** De `objective` in de payload is de rondebody van productie, met daarin "Write only scratch files under `/tmp/`". Die tekst is bewust niet omgezet: het is wat de productie-reviewers zagen, en de bench geeft het model geen schrijftools, dus de zin heeft geen effect.
- **Geen repository.** `dispatch.input.requirements` heeft geen `repository`: `/work` was in productie leeg. De bench geeft het model een lege `work/`.
- **De ref-results.** Beide hebben `outcome: succeeded` en `review.verdict: NO-GO`, en hun `review.documents` is gelijk aan `review_documents` van de payload.

## Hoe `__dispatch_input` is gereconstrueerd

Productie levert `/sources/__dispatch_input` als de canonieke JSON van `dispatch.input`: `canonicalDispatchInput` in scrum4me-shared `lib/queue-dispatch-validation.ts` @`b3d2b98` (r. 111-115, met `canonicalJson` op r. 99), de versie die scrum4me-docker @`78e7347d` als submodule `vendor/scrum4me-shared` pint. Die sorteert de sleutels, laat `undefined` weg, en ontdubbelt en sorteert `environment_keys`. Het bestand zelf is niet bewaard; het is opnieuw gemaakt uit `payload.json` met dit script (`recon-dispatch-input.mjs`, aangeroepen als `node recon-dispatch-input.mjs payload.json sources/__dispatch_input`). Het script slaat de schemacontrole `parseDispatchInput` over en neemt de input zoals hij is; dat de hash hieronder klopt, laat zien dat dat hier geen verschil maakt:

```js
import fs from 'node:fs'
import crypto from 'node:crypto'
const [,, file, outFile] = process.argv
function canonicalJson(value){
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`
  if (value !== null && typeof value === 'object') {
    const o = value
    return `{${Object.keys(o).filter(k => o[k] !== undefined).sort().map(k => `${JSON.stringify(k)}:${canonicalJson(o[k])}`).join(',')}}`
  }
  return JSON.stringify(value)
}
const p = JSON.parse(fs.readFileSync(file,'utf8'))
const input = p.dispatch.input
const parsed = input
const s = canonicalJson({ ...parsed, requirements: { ...parsed.requirements, environment_keys: [...new Set(parsed.requirements.environment_keys)].sort() } })
const b = Buffer.from(s,'utf8')
console.log(b.length, crypto.createHash('sha256').update(b).digest('hex'))
if (outFile) fs.writeFileSync(outFile, b)
console.log('declared', JSON.stringify(p.dispatch.source_artifacts))
```

De uitkomst is 6705 bytes met sha256 `9f6580562a3d9847e49a82697782219f22ef949d4d1a4396040106b25aaef9e3`. Dat is precies de hash die `payload.dispatch.source_artifacts` voor `__dispatch_input` declareert, dus het bestand is byte-gelijk aan wat productie leverde.

## De logs

De run-logs van beide jobs (`specr5_claude.log`, `specr5_codex.log`) staan op de Mac in `~/Development/m8-case-staging/logs/` (map 0700). Ze komen in geen enkele repo en gaan niet naar een subagent: ze bevatten de volledige sessie van productie. De ref-results en de job-ids hierboven komen eruit; voor de case zelf zijn ze niet nodig.

## Controle

```bash
python3 llm-bench/review_bench/check_case.py llm-bench/review_bench/cases/macsearch-idea263-spec-r5
```

Exit 0 als elke hash in `case.json` klopt, de sleutels en hashes van `payload.dispatch.source_artifacts` in beide richtingen gelijk zijn aan `sources[]`, en de hash van `doc` in `review_documents` gelijk is aan die van `sources/doc`.
