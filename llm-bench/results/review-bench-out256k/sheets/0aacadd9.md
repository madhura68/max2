# Scoreblad 0aacadd9

Dit blad is blind: het noemt geen model en geen configuratie, en `sheets-key.json` blijft dicht. Beoordeel de tekst hieronder met de rubric `llm-bench/review_bench/cases/macsearch-idea263-spec-r5/rubric.md`. Vul alle velden in.

Schrijf één regel in scores.jsonl, met precies deze velden:

{"sheet": "0aacadd9", "f1": "major|minor|nee", "f2": "major|minor|nee", "minors": ["M1".."M6"], "extra": [{"key": "...", "voorstel": "geldig|ongeldig", "reden": "..."}]}

- `f1`, `f2`: het label dat het model zelf gaf aan de bevinding die die kern raakt: `major` voor MAJOR of BLOCKER, `minor` voor MINOR, `nee` als geen bevinding die kern raakt.
- `minors`: de M-punten uit de rubric die een bevinding raakt; `[]` als er geen is.
- `extra`: elke andere BLOCKER of MAJOR, met een genormaliseerde `key`, een voorstel `geldig` of `ongeldig` en één zin `reden`; `[]` als er geen is.

## Samenvatting

Review of IDEA-263 MacSearch spec revision 5 (SHA256: 7d5e35…). 0 BLOCKER, 0 MAJOR, 6 MINOR. All four round-4 MAJOR fixes hold: (1) no overwrite fallback — three routes A/B/C are internally consistent and implementable on macOS, with no plain rename; (2) retry bookkeeping correct — one counter, existing-record updates, temp reuse, skipped_identical cleanup; (3) metadata dates set explicitly with warning on failure; (4) folder creation after search_run insert; (5) AC3a tests cover collision, crash recovery, route C, and metadata with single-record assertions. No unnecessary scope identified. The six MINOR findings are documentation clarity items: routes don't explicitly branch on F16's skipped_identical short-circuit, first-attempt EEXIST in route C momentarily references a non-existent 'existing record,' non-EEXIST rename errors aren't described in NF4 text, dest_path semantics for skipped_identical are underspecified, suffix enumeration is open-ended, and ON DELETE CASCADE lacks a cleanup note. None affect correctness or safety. Verdict: GO.

## Rapport

## IDEA-263 MacSearch r5 — Adversarial Review (Round 5)

**Document:** `doc` (SHA256: `7d5e35872c417a5656ef53794aff95675f3ac0716f6e3c46951d509f029fadaf`), 310 lines, read in full.

### Per-Fix Verification

| # | Fix | Status | Evidence |
|---|-----|--------|----------|
| 1 | No overwrite fallback | **HOLDS** | Route A: `renamex_np(RENAME_EXCL)` (NF4:220–224). Route B: `.macsearch-<UUID>.tmp` + `renamex_np(RENAME_EXCL)` (NF4:226–233). Route C: `O_EXCL` on final name (NF4:235–241). No plain `rename` anywhere. Volume capability via `getattrlist` `VOL_CAP_INT_RENAME_EXCL` (F15:123) — real macOS API. |
| 2 | Retry bookkeeping | **HOLDS** | One counter (3) per file (NF4:217). Existing record always updated (NF4:218). Route B reuses temp file (NF4:231). Identical → delete own file, `skipped_identical` (NF4:245). AC3a tests assert exactly one record, no pending record left (AC3a:257–269). |
| 3 | Metadata | **HOLDS** | Dates set explicitly in route B step 4 and route C step 4 (NF4:230,239). Failure is a warning (F15:126). AC3a has success and failure cases (AC3a:271–272). |
| 4 | Folder creation after search_run insert | **HOLDS** | F14: "na de `search_run`-insert … en vóór het eerste bestand" (F14:120). AC4: "het aanmaken van de doelmap mislukt → nul transfers en de run staat op `aborted`" (AC4:283). |
| 5 | Tests | **HOLDS** | AC3a adds 14 cases: collision (temp name, final name different/identical, route A, route C), 3× EEXIST, crash recovery (half copy, after temp_path=NULL), failed pending-insert, metadata pass/fail, cleanup. All check record count and source integrity (AC3a:257–273). |

### Findings

#### [MINOR] Route steps don't acknowledge F16 short-circuit (NF4, F16)

**Where:** NF4 routes A step 1 (line 221), B step 1 (line 227), C step 1 (line 236); F16 (lines 127–131).

**Claim:** Each route presents step 1 as "Doelnaam bepalen (F16)" and then proceeds linearly through file operations.

**Reality:** F16 can resolve a transfer as `skipped_identical` directly — when the destination file already exists and has identical content. In that case no temp file, no copy, and no rename should occur. Only a record insert or update is needed (F19b:143). The route steps don't show this branch.

**Consequence:** An implementer reading the routes naively could proceed to create a temp file (route B step 2) or attempt `renamex_np` (route A step 3) before checking F16's outcome. The correct behavior is derivable from cross-referencing F16 + F19b, but the normative route procedures should be explicit.

**Fix:** After each route's step 1, insert: "Levert F16 `skipped_identical` op, dan wordt direct een record ingevoegd of bijgewerkt (F19b); de overige stappen van deze route vervallen."

#### [MINOR] First-attempt EEXIST in route C references non-existent record (NF4:243–246)

**Where:** NF4 "Herpoging na `EEXIST`" (lines 243–246), route C step 2–3 (lines 237–238).

**Claim:** The retry rules state "het bestaande record wordt bijgewerkt" for both Identiek and Anders cases.

**Reality:** In route C, `O_EXCL` at step 2 happens *before* the pending record insert at step 3. On the very first EEXIST collision, there is no record yet. F19b covers this gap: "Bestaat er nog geen record, dan wordt er direct een record met dat resultaat ingevoegd" (line 143). But the retry section does not reference F19b, so a reader of the retry rules in isolation encounters a momentary contradiction.

**Consequence:** Minor documentation gap. The implementer must discover F19b to resolve it. The correct end state is unambiguous once both sections are read.

**Fix:** In the retry section (line 245–246), add: "Bestaat er nog geen record (eerste poging in route C), dan wordt een nieuw record ingevoegd (F19b)."

#### [MINOR] Non-EEXIST `renamex_np` errors not described in NF4 text (NF4:220–246)

**Where:** NF4 retry section and route A/B step descriptions.

**Claim:** Only `EEXIST` errors are described as triggering the retry mechanism.

**Reality:** `renamex_np` can fail with errors other than `EEXIST` — e.g., `EIO`, `ENOSPC`, `ENOTSUP`. The general error rule ("Bij een fout: de app verwijdert alleen het eigen bestand (`temp_path`) en de bron blijft staan," line 249) covers this. AC3a explicitly tests "Publiceren mislukt met een andere fout dan `EEXIST`" (line 259). But NF4 itself does not connect non-EEXIST rename errors to `failed` + cleanup.

**Consequence:** Minor. The behavior is fully defined elsewhere; a dedicated sentence in NF4 would make the section self-contained.

**Fix:** Add to the retry section: "Andere fouten van `renamex_np` (bijv. `EIO`, `ENOSPC`) worden niet herpoged; het resultaat is `failed`, het eigen bestand wordt verwijderd en de bron blijft staan."

#### [MINOR] `dest_path` semantics for `skipped_identical` underspecified (§5, F16)

**Where:** §5 `file_action` schema — `dest_path TEXT` (line 200); F16 (lines 127–131).

**Claim:** `dest_path` is nullable, with the comment "NULL bij failed vóór bepaling doel" (line 200).

**Reality:** For `skipped_identical`, F16 *did* determine a destination path before detecting the identical content (F16 first checks if the destination exists, then compares size and SHA-256). Whether that path is stored is not specified. For `failed` before any F16 run, NULL is correct, but `skipped_identical` always follows a successful F16 name determination. Two implementers could reasonably make different choices, making the audit log inconsistent.

**Consequence:** Minor schema ambiguity. Does not affect safety or correctness.

**Fix:** Amend the schema comment or add a sentence in F19b: "Bij `skipped_identical` wordt `dest_path` ingevuld met het door F16 bepaalde doelpad."

#### [MINOR] Suffix enumeration has no upper bound (F16:131)

**Where:** F16 — "naam (2).ext, naam (3).ext, … tot en met de eerste vrije naam" (line 131).

**Claim:** Suffix candidates are enumerated with no explicit maximum.

**Reality:** In a directory containing thousands of files with the same base name, F16 could iterate through many candidates within a single attempt. The retry counter (3 attempts per file, NF4:217) limits how many F16+operation cycles run, but not how deep F16 itself searches. Finder exhibits the same open-ended behavior, so this matches platform convention.

**Consequence:** Negligible in practice for a single-user app on a local Mac. No fix required; noted for completeness.

#### [MINOR] `ON DELETE CASCADE` has no matching temp-file cleanup (§5:198)

**Where:** §5 schema — `REFERENCES search_run(id) ON DELETE CASCADE` (line 198).

**Claim:** Deleting a `search_run` row would cascade-delete its `file_action` rows.

**Reality:** No run-deletion mechanism exists in v1; the cascade is inert. If a future increment adds run deletion, the cascade would remove `file_action` records without first deleting the files referenced by their `temp_path` columns, leaving orphaned files on disk.

**Consequence:** Not a v1 defect, but a latent hazard for future increments.

**Fix:** Add a note to §5 or §8: "Run-verwijdering is geen v1-feature. Mocht het worden toegevoegd, dan moeten `temp_path`-bestanden worden opgeruimd vóór de cascade plaatsvindt."

### Necessity Assessment

No unnecessary scope identified. All NF4 complexity directly serves the overwrite-safety requirement imposed by JP's 2026-10-16 decision. The three-route design is the minimal decomposition that covers: same-volume atomic move (A), cross-volume/copy with atomic publish (B), and volumes without atomic-rename support (C). Each route exists because simpler alternatives were explicitly removed (plain-rename fallback, link tier). The increment split (§8) appropriately defers non-core features (right pane, breadcrumb, filmstrip) to increment 2.

### Verdict

**GO.** Zero BLOCKER, zero MAJOR. All round-4 fixes hold. The six MINOR findings are documentation clarity items that do not affect correctness, safety, or implementability on macOS.
