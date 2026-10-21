# Scoreblad f3bfcbc3

Dit blad is blind: het noemt geen model en geen configuratie, en `sheets-key.json` blijft dicht. Beoordeel de tekst hieronder met de rubric `llm-bench/review_bench/cases/macsearch-idea263-spec-r5/rubric.md`. Vul alle velden in.

Schrijf één regel in scores.jsonl, met precies deze velden:

{"sheet": "f3bfcbc3", "f1": "major|minor|nee", "f2": "major|minor|nee", "minors": ["M1".."M6"], "extra": [{"key": "...", "voorstel": "geldig|ongeldig", "reden": "..."}]}

- `f1`, `f2`: het label dat het model zelf gaf aan de bevinding die die kern raakt: `major` voor MAJOR of BLOCKER, `minor` voor MINOR, `nee` als geen bevinding die kern raakt.
- `minors`: de M-punten uit de rubric die een bevinding raakt; `[]` als er geen is.
- `extra`: elke andere BLOCKER of MAJOR, met een genormaliseerde `key`, een voorstel `geldig` of `ongeldig` en één zin `reden`; `[]` als er geen is.

## Samenvatting

Review of IDEA-263 MacSearch specification revision 5. 0 BLOCKER, 0 MAJOR, 6 MINOR. All five fixes from round 4 held: the three-route NF4 system (A/B/C) correctly eliminates the plain-rename fallback; retry bookkeeping always updates the existing record; metadata dates are explicitly set; folder creation follows search_run insert; and AC3a tests comprehensively cover the new routes and crash scenarios. The specification is internally consistent and implementable on macOS. Six MINOR findings cover: ambiguous Route B label that could exclude same-volume copies; missing fallback for getattrlist failure; stale pending record on non-EEXIST Route A failure; F16 candidate check order missing identical matches beyond the first free name; undocumented dest_path=NULL use case in the schema; and API naming clarity for fcopyfile. None of these affect safety or correctness of the core mechanism. Verdict: GO.

## Rapport

## Fix verification (round 4 → round 5)

| Fix | Status | Evidence |
|-----|--------|----------|
| 1. No overwrite fallback | **HELD** | NF4 defines three routes. Route A: `renamex_np(…, RENAME_EXCL)` (line 223). Route B: exclusive temp → `renamex_np(RENAME_EXCL)` (lines 228–231). Route C: `O_EXCL` on final name (line 237). No plain `rename` anywhere in the document. |
| 2. Retry bookkeeping | **HELD** | NF4: "één pogingenteller … maximaal 3" (line 217), "altijd het bestaande record bijgewerkt" (line 218), "identiek … bijgewerkt naar `skipped_identical`" (line 245). F19b: "Bestaat er al een record … dan wordt dat bestaande record bijgewerkt" (line 143). AC3a: "Drie keer EEXIST … precies één record" (line 265). |
| 3. Metadata dates | **HELD** | F15: "blijven de wijzigings- en de aanmaakdatum van de bron behouden" (line 126). AC3a: "Metadata geslaagd" and "Metadata mislukt" test cases (lines 271–272). |
| 4. Folder creation after search_run insert | **HELD** | F14: "Ontbrekende mappen worden aangemaakt **na** de `search_run`-insert" (line 120). AC4: "het aanmaken van de doelmap mislukt → nul transfers en de run staat op `aborted`" (line 283). |
| 5. Tests for new routes | **HELD** | AC3a (lines 257–273) covers: half-copy abort, publish failure, source-delete failure, size mismatch, temp-name collision, dest-name collision (different + identical), 3× EEXIST, Route A collision, Route C collision, Route C crash-at-half-copy, Route C crash-after-complete, failed pending-insert, metadata success/failure, and crash cleanup. |

## Findings

### [MINOR] Route B: "tussen volumes" is ambiguous for same-volume copies

- **Where:** NF4, Route B header (doc:226)
- **Claim:** "Route B: kopiëren of verplaatsen tussen volumes, doelvolume mét `RENAME_EXCL`."
- **Reality:** The Dutch phrase can be parsed as either "(kopiëren) of (verplaatsen tussen volumes)" — copy always plus cross-volume move — or "(kopiëren of verplaatsen) tussen volumes" — both only cross-volume. If read literally as cross-volume only, same-volume copies with `RENAME_EXCL` have no defined route: Route A is move-only, Route C is for volumes without `RENAME_EXCL`. The Route B mechanism (temp file → fcopyfile → renamex_np, lines 228–233) is volume-agnostic and works correctly for same-volume copies.
- **Consequence:** A developer implementing the literal reading would leave same-volume copies unimplemented, causing the primary use case (copying on APFS) to fail. AC5 manual testing would catch this, but rework would be needed.
- **Fix:** Clarify the label. Either: (a) "Route B: kopiëren (elk volume) of verplaatsen tussen volumes" or (b) add "Route B dekt ook kopiëren binnen hetzelfde volume."

### [MINOR] No fallback when `getattrlist` for `VOL_CAP_INT_RENAME_EXCL` fails

- **Where:** F15 (doc:123)
- **Claim:** "Per run wordt één keer bepaald of het doelvolume `RENAME_EXCL` ondersteunt (`getattrlist`, `VOL_CAP_INT_RENAME_EXCL`). Dat bepaalt de publicatieroute in NF4."
- **Reality:** `getattrlist` can fail due to transient I/O errors or a volume becoming unavailable. The spec defines no fallback behavior for this case.
- **Consequence:** An implementation might crash, hang, or select an arbitrary route when the capability check fails.
- **Fix:** Add: "Mislukt `getattrlist`, dan wordt aangenomen dat `RENAME_EXCL` niet beschikbaar is en wordt Route C gevolgd."

### [MINOR] Route A: non-EEXIST `renamex_np` failure leaves stale pending record

- **Where:** Route A steps 2–4 (doc:222-224), F19b (doc:143)
- **Claim:** Route A step 2 inserts a `pending` record. Step 3 does `renamex_np`. The retry section only handles `EEXIST`.
- **Reality:** If `renamex_np` fails with a non-EEXIST error (e.g., `EIO`, `EACCES`), the pending record stays on `result = 'pending'`. The source is intact (rename failed). F17 says "Een fout bij één bestand stopt de batch niet" so the batch continues. On restart, F19c marks the run as `interrupted`; the pending record has no `temp_path`, so nothing is cleaned up.
- **Consequence:** Stale `pending` record in the database. No data loss or safety issue — the source file is untouched. The run is correctly marked incomplete per F19c.
- **Fix:** Add to Route A: "Bij een andere fout dan `EEXIST` wordt het record bijgewerkt naar `failed`." Alternatively, note that F17's general error handling covers this.

### [MINOR] F16: candidate check order can miss identical-content matches

- **Where:** F16 (doc:131)
- **Claim:** "Kandidaten voorbij de eerste vrije naam worden niet bekeken."
- **Reality:** The algorithm checks candidates sequentially: `naam.ext`, `naam (2).ext`, `naam (3).ext`, … If `naam (2).ext` is free, the algorithm stops and uses it — even if `naam (3).ext` exists with identical content. The identical match would never be discovered.
- **Consequence:** An unnecessary duplicate file is created instead of reporting `skipped_identical`. No safety issue, but avoidable disk usage and a missed deduplication opportunity.
- **Fix:** Clarify the algorithm. Either: (a) first scan all candidates `(2)…(N)` for identical content, then fall back to the first free name; or (b) document the sequential stop-at-first-free behavior explicitly as a known trade-off.

### [MINOR] `dest_path` NULL in `file_action` schema lacks a documented use case

- **Where:** Schema (doc:200), comment "NULL bij failed vóór bepaling doel"
- **Claim:** The schema allows `dest_path` to be NULL.
- **Reality:** In every described flow, `dest_path` is determined by F16 before the `pending` record is inserted (F19b.1). If the insert itself fails, no record is created at all (F19b.1: "wordt dit bestand niet verwerkt en stopt de batch direct"). There is no documented scenario where a `file_action` row is created with `dest_path = NULL`.
- **Consequence:** Dead flexibility in the schema. Not harmful, but indicates an edge case the spec does not define.
- **Fix:** Either make `dest_path NOT NULL` or document a concrete scenario where it legitimately is NULL.

### [MINOR] `fcopyfile` could reference `copyfile(3)` for discoverability

- **Where:** Route B step 4 (doc:230)
- **Claim:** "Data en metadata kopiëren met `fcopyfile(src_fd, tmp_fd, …, COPYFILE_ALL)`."
- **Reality:** `fcopyfile` (from `<copyfile.h>`) is a lower-level fd-based function. The more commonly documented public API is `copyfile(3)`, which accepts paths. `fcopyfile` is correct for the fd-based flow, but a developer unfamiliar with it may first search for `copyfile` and need to adapt.
- **Consequence:** Minor implementation friction. No correctness issue.
- **Fix:** Add a brief note: "`fcopyfile` is declared in `<copyfile.h>`; the path-based equivalent is `copyfile(3)`."
