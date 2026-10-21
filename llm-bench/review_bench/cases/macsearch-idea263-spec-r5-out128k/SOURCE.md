# Herkomst: case `macsearch-idea263-spec-r5-out128k`

Dit is een variant van `macsearch-idea263-spec-r5` voor M9 (IDEA-272): de review-bench met een ruimere output-limiet. Plan: agent-harness `docs/plans/M9-review-bench-output-limit.md`, §4.1.

- **Dezelfde bytes.** `review.md`, `payload.json`, `sources/doc` en `sources/__dispatch_input` zijn byte-kopieën van het origineel. `case.json` pint dezelfde hashes.
- **Wat verschilt.** Alleen `id` en `limits`: `maxOutputTokens` 128000 en `maxWallSeconds` 3600. `maxTurns` (30), `maxToolErrors` (8), `contextTokens` (131072) en `maxCostUsd` ("1") blijven gelijk.
- **Herkomst en hashes.** Die staan in `../macsearch-idea263-spec-r5/SOURCE.md`.
- **Rubric.** De rubric is `../macsearch-idea263-spec-r5/rubric.md`; `score.py` leest die van het origineel.
- **Ref-results.** Die staan alleen in het origineel.

`test_review_bench.py` (`VariantCaseTest`) bewaakt dat deze variant gelijk blijft aan het origineel, op `id` en `limits` na.

## Controle

```bash
python3 llm-bench/review_bench/check_case.py llm-bench/review_bench/cases/macsearch-idea263-spec-r5-out128k
```
