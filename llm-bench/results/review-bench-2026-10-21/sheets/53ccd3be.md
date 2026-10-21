# Scoreblad 53ccd3be

Dit blad is blind: het noemt geen model en geen configuratie, en `sheets-key.json` blijft dicht. Beoordeel de tekst hieronder met de rubric `llm-bench/review_bench/cases/macsearch-idea263-spec-r5/rubric.md`. Vul alle velden in.

Schrijf één regel in scores.jsonl, met precies deze velden:

{"sheet": "53ccd3be", "f1": "major|minor|nee", "f2": "major|minor|nee", "minors": ["M1".."M6"], "extra": [{"key": "...", "voorstel": "geldig|ongeldig", "reden": "..."}]}

- `f1`, `f2`: het label dat het model zelf gaf aan de bevinding die die kern raakt: `major` voor MAJOR of BLOCKER, `minor` voor MINOR, `nee` als geen bevinding die kern raakt.
- `minors`: de M-punten uit de rubric die een bevinding raakt; `[]` als er geen is.
- `extra`: elke andere BLOCKER of MAJOR, met een genormaliseerde `key`, een voorstel `geldig` of `ongeldig` en één zin `reden`; `[]` als er geen is.

## Samenvatting

Round 5 review of IDEA-263 MacSearch spec. The document was read in full (sha256 7d5e3587...). All five round-4 fixes hold in revision 5.

Fix 1 (no overwrite fallback): the spec has no plain `rename` and no `renamex_np` without `RENAME_EXCL`. NF4 routes A/B/C cover every (mode × volume-capability) combination: same-volume move with RENAME_EXCL → atomic renamex_np; copy or cross-volume move with RENAME_EXCL → exclusive temp file + fcopyfile + renamex_np; any operation without RENAME_EXCL → O_EXCL on the final name + fcopyfile + temp_path=NULL. F15 explicitly forbids overwriting and ties the failure-mode cleanup to the app's own files only.

Fix 2 (retry bookkeeping): one pogingenteller of 3 per file (NF4). Retries always update the existing record (no second insert). Route B explicitly does not repeat steps 2–4 on a retry and reuses the temp file. A retry that ends in identical content deletes the own file and sets the record to `skipped_identical`. AC3a asserts exactly one record and no pending record left.

Fix 3 (metadata): F15 and route B step 4 set both dates explicitly; failure yields a warning and the transfer continues. AC3a has both success and failure cases.

Fix 4 (folder creation): F14 creates the doelmap after the search_run insert and before the first file; AC4 covers creation failure (no transfers, run aborted).

Fix 5 (tests): AC3a has all the listed cases — two final-name collisions, three EEXIST, route A collision, route C collision + crash after half-copy + crash after temp_path=NULL.

The macOS-specific mechanisms (renamex_np, getattrlist VOL_CAP_INT_RENAME_EXCL, O_EXCL on SMB, fcopyfile COPYFILE_ALL, QLThumbnailGenerator, GRDB, NavigationSplitView, FileManager.enumerator) are all real and implementable on the current macOS.

No BLOCKER and no MAJOR found. Two MINOR clarity issues noted: (1) AC3a "Drie keer EEXIST" does not name a route; if read as Route C step 2 (where no record is inserted before the collision) the "precies één record" assertion would not naturally hold. The defensible reading is Route A or Route B post-insert, where it matches. (2) F16 only describes behavior when the dest file already exists; the no-conflict branch is implicit. Neither prevents a sound implementation.

Scope assessment: round-4 narrow. The five MAJORs since round 2 (all in the NF4 publication path) are addressed; the rest of the spec is consistent and unchanged. Verdict: GO.

## Rapport

# Round 5 review, IDEA-263 MacSearch spec (revision `cmvb3ea2a002zer17g4p8x98x`)

## Scope
Greenfield. The only source is the ProductDoc (sha256 `7d5e35872c417a5656ef53794aff95675f3ac0716f6e3c46951d509f029fadaf`, 308 lines). Read in full. §1a is the binding-decision ground truth. No repository checkout is provided, so claims about code are checked against the spec itself, not against a tree.

## Per-fix verdict

### Fix 1 — No overwrite fallback  → **held**
- `sources/doc` lines 124, 223, 231: the only rename primitive named in the spec is `renamex_np(…, RENAME_EXCL)`. Search confirms no plain `rename(2)` or `renamex_np` without `RENAME_EXCL` anywhere.
- `sources/doc` lines 220–241: NF4 routes A/B/C partition the (mode × RENAME_EXCL capability) space correctly. Route A → atomic rename within same-volume + RENAME_EXCL. Route B → exclusive temp file (`O_EXCL` on `.macsearch-<UUID>.tmp`) + `fcopyfile` + renamex_np; cross-volume copy/move with RENAME_EXCL. Route C → `O_EXCL` directly on the final name + `fcopyfile` + `temp_path=NULL`; any operation without RENAME_EXCL (copy or any move, including same-volume move on exFAT/SMB).
- `sources/doc` line 216: an app-owned file is one created in this run with `O_CREAT|O_EXCL|O_WRONLY` and registered as `temp_path` in the pending record **before** bytes are written. This closes the over-write-of-foreign-file hole that round 4 found.

### Fix 2 — Retry bookkeeping → **held**
- `sources/doc` line 217: "Per bestand is er één pogingenteller voor alle botsingen op 'bestaat al': maximaal 3."
- `sources/doc` line 218: "Bij een herpoging wordt altijd het bestaande record bijgewerkt … Er wordt nooit een tweede record ingevoegd."
- `sources/doc` line 231: Route B on EEXIST — temp file blijft staan; stappen 2–4 worden niet herhaald.
- `sources/doc` lines 243–246: retry rule — `Identiek`: eigen tijdelijke bestand verwijderen + bestaand record naar `skipped_identical`; `Anders`: `dest_path` in bestaand record bijwerken, doorgaan bij route A stap 3 / route B stap 5 / route C stap 2.
- `sources/doc` lines 265, 280, 281: AC3a and AC4 assert exactly one record and no pending record left after failure paths. Names the defect that round 4 identified ("retry that ends in identical content left a stale pending record").

### Fix 3 — Metadata → **held**
- `sources/doc` line 126 + line 230: both dates are set explicitly after `fcopyfile`; failure yields a warning and the transfer continues.
- `sources/doc` lines 271–272: AC3a has `Metadata geslaagd` (both dates equal) and `Metadata mislukt` (file published, result `copied`, warning in `error`).

### Fix 4 — Folder creation → **held**
- `sources/doc` line 120: F14 creates the doelmap **after** the `search_run`-insert (F19a) and before the first file.
- `sources/doc` line 283: AC4 covers "het aanmaken van de doelmap mislukt → nul transfers en de run staat op `aborted`."

### Fix 5 — Tests → **held**
- `sources/doc` lines 257–273: AC3a covers two final-name collision cases (different content → `renamed`; identical content → `skipped_identical`), three EEXIST, route A collision, route C collision + crash after half-copy + crash after `temp_path = NULL`, missed pending-insert cleanup (own empty file deleted), and the crash-recovery cleanup of pending `temp_path` files plus the byte-for-byte-unchanged test for foreign `.macsearch-other.tmp`.
- `sources/doc` lines 276–285: AC4 covers the storage-failure matrix end-to-end: failed search_run / failed pending / failed result-update × does-abort-also-fail × Stop-during-processing × folder-create failure × bad DB × interrupted-run-recovery.

## Attack priorities

### 1. Necessity (round 5)
Nothing was removed or deferred in r4→r5 besides the `link` tier and the plain-rename fallback, and both removals are correct given the route model. Defer is not warranted. Increment 1 remains the binding first usable result and is what AC1–AC7 cover.

### 2. Correctness

#### Routes vs F15/F16/F17/F19b/F0d
- Routing table is unambiguous (see Fix 1). Cross-volume same-capability goes to Route B; same-volume move + RENAME_EXCL → A; everything else → C.
- Route A uses `renamex_np` only; no partial state.
- Route B uses an exclusive temp file in the **destination directory**, publishes via `renamex_np`, then deletes source for move mode. Steps 2–4 are not re-run on EEXIST retry.
- Route C writes directly to the final name with `O_EXCL`; `temp_path = NULL` is set before any source delete; cleanup recognises the file as "complete" once that marker is set.
- F19b step 2: a missed result-update is recorded as "file processed, pending stale, batch stops, try aborted". F0d Stop is then subordinate to a missed write ("wint `aborted`"). AC4 line 281 covers this.

#### Crash windows
- Route A crash after renamex returns success: nothing to clean up; the rename is atomic in the kernel.
- Route B crash between step 2 (O_EXCL) and step 3 (pending insert): empty `.macsearch-<UUID>.tmp` with no record. Cleanup does not touch it (no `temp_path` in any pending record) — the spec marks this as an accepted orphan (hidden file in destination directory, `sources/doc` line 251). Task summary instructed not to raise this as a finding.
- Route B crash during fcopyfile: half-written temp file with a pending record that points to `temp_path`. Startup cleanup deletes the path. AC3a `Opruimen na een crash` covers this including a foreign `.macsearch-other.tmp` neighbour (`sources/doc` line 273).
- Route C crash between step 2 and step 3: empty file under final name, no record. Orphan left at the destination, accepted per `sources/doc` line 251.
- Route C crash during fcopyfile: pending record has `temp_path = dest_path`; restart deletes the file (AC3a `Route C, crash na een halve kopie`).
- Route C crash between temp_path=NULL and source-delete: file complete, source intact; cleanup does not delete the dest because `temp_path = NULL`. AC3a explicitly tests this and asserts the source remains (`sources/doc` line 269). This is the JP-accepted trade-off.
- Crash cleanup never deletes a file whose path is **not** in a pending `temp_path`, never deletes a complete file whose record has `temp_path = NULL`, never deletes the source (`sources/doc` line 250). Foreign-file safety is preserved.

#### macOS implementability
- `renamex_np(…, RENAME_EXCL)` — real since macOS 10.12.
- `getattrlist(buf, fsinfo, …)` with `VOL_CAP_INT_RENAME_EXCL` in `f_fcapabilties` — real; documented in `Stat and Getter Functions`. The capability is per-volume; once-per-run measurement is sufficient.
- `O_EXCL` on SMB — POSIX-style semantics, supported by Apple's SMB client.
- `fcopyfile(…, COPYFILE_ALL)` — real; crosses volume boundaries; the spec then reasserts the two dates explicitly which is the standard belt-and-suspenders for APFS/SMB.
- `URLResourceKey.fileResourceIdentifierKey` and `volumeIdentifierKey` — real.
- `FileManager.enumerator(at:…, options:[.skipsHiddenFiles, .skipsPackageDescendants], errorHandler:)` with `nextObject()` on a non-main actor — real. `skipDescendants()` is called on the URL whose identifier matches `dest_root`.
- GRDB migration v1 — schema in §5 is internally consistent (cascade on delete, indices, status enums, CHECK constraints).
- `NavigationSplitView`, `QLThumbnailGenerator`, `Foundation.UUID`, `CryptoKit.Insecure.SHA256` streaming — all real.

#### Missing coverage against §1a
None. §1a's match-rules (F1–F5), file-filter (F6–F8), destination shape (F14), copy/move mode (F15), conflict resolution (F16), per-file error isolation (F17), streaming results (F9), size-then-SHA-256 duplicate check (F16), and no-sandbox / no-App-Store / single-user constraints (§2, §1a) are all express and testable.

#### Tests that could pass while their named defect is present

**MINOR — `sources/doc:265` "Drie keer `EEXIST`" does not bind the case to a route.**
Route A step 3 retry and Route B step 5 retry both leave exactly one record (the pending record was inserted at A's step 2 / B's step 3 before the collisions). Route C step 2 retry never inserts a pending record before colliding, so three EEXISTs in route C leave zero records, not one. The natural reading is that this test is parameterised over Route A or Route B (where the assertion matches), but the spec should say so. Suggested fix: bind the test to "route A, three EEXIST, identical-content variants excluded" or list Route C as a separate case with the appropriate assertion ("nul records; geen orphan file op de doelmap").

**MINOR — `sources/doc:127` F16 only describes the conflict branch.**
F16 ("Conflict, als het doelbestand al bestaat") gives the size/SHA/rename-suffix logic but does not state what F16 returns when the file does not exist. The no-conflict path is implicit (return the chosen name). Suggested fix: add the no-conflict clause, e.g., "Bestaat het doelbestand niet, dan is het resultaat de naam zelf." Makes the contract explicit for implementers.

These two issues are clarity, not correctness. No MAJOR or BLOCKER.

## Summary tally
- BLOCKER: 0
- MAJOR: 0
- MINOR: 2 (clarity only; both compatible with GO)
- Scope delta vs r4: removed `link` tier and plain-rename fallback, added route C, retry rules, expanded AC3a. First usable result unchanged.

## Verdict
GO. The five round-4 fixes held. The route-cleanup-skeleton in NF4, together with F15 and F19b, leaves no realistic execution on macOS where an unmodified foreign file can be overwritten, overwritten-if-not-final, or removed by the wrong code path. The two MINORs are wording contracts that the implementer has to bridge carefully; neither blocks building.
