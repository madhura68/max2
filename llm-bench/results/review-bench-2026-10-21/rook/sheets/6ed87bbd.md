# Scoreblad 6ed87bbd

Dit blad is blind: het noemt geen model en geen configuratie, en `sheets-key.json` blijft dicht. Beoordeel de tekst hieronder met de rubric `llm-bench/review_bench/cases/macsearch-idea263-spec-r5/rubric.md`. Rookproef: vul alleen `f1` in.

Schrijf één regel in scores.jsonl, met precies deze velden:

{"sheet": "6ed87bbd", "f1": "major|minor|nee"}

- `f1`: het label dat het model zelf gaf aan de bevinding die de kern van F1 raakt: `major` voor MAJOR of BLOCKER, `minor` voor MINOR, `nee` als geen bevinding die kern raakt.

## Samenvatting

Round 5 review of r5 (sha256 7d5e3587…fadaf, read in full, 308 lines). Verdict GO. There are 0 BLOCKER, 0 MAJOR and 6 MINOR findings.

Most important finding: Route C step 5 (doc line 240) does not say what happens when the `temp_path = NULL` update fails, and it conflicts with F19b step 2 (line 146). The source is only deleted after that update, so a literal reading loses no data. A reader who follows F19b ('this file is already processed') could still delete the source, and the next start would then delete the complete copy. I rate it MINOR because the sequence in step 5 prevents it, but it should be stated explicitly.

Scope: nothing needs removing. Route C is JP's binding decision. Route A is needed so that same-volume moves are atomic and cheap. The first usable result (increment 1, AC1–AC7) is unchanged.

Fixes 1–5:
1. No overwrite fallback: HELD. No plain `rename` appears anywhere. All three routes publish only through `O_EXCL` or `RENAME_EXCL`.
2. Retry bookkeeping: HELD. There is one counter, the existing record is always updated, route B does not repeat steps 2–4, and an identical result sets `skipped_identical`. Route C retries only happen at step 2, before any record exists, so no stale pending record can arise.
3. Metadata: HELD. Dates are set explicitly, and AC3a has a success case and a failure case.
4. Folder creation after the `search_run` insert: HELD. F14 and the AC4 case agree.
5. Tests: PARTIALLY HELD. Route C has no identical-collision, three-`EEXIST` or size-mismatch case. Some test expectations are loosely worded, and the route A result name conflicts with the route B test (see findings).

I did not run anything: there is no code repository and no package registry in the container.

## Rapport

# Review IDEA-263 spec r5 (round 5)

Source `doc`, sha256 7d5e35872c417a5656ef53794aff95675f3ac0716f6e3c46951d509f029fadaf, read in full. Line numbers refer to this document. Greenfield, so there is no code to check.

**Counts:** 0 BLOCKER, 0 MAJOR, 6 MINOR. **Verdict: GO.**

## Necessity
Nothing can be removed or deferred without losing agreed protection or acceptance.
- Route C implements the new JP decision.
- Route A avoids copying whole files on same-volume moves.
- The F16 suffix logic is §1a.
- AC3a is large but maps one-to-one onto NF4 failure modes.

## Fix verification
1. **No overwrite fallback: held.**
   - Route A uses `RENAME_EXCL`.
   - Route B uses an exclusive temp file and then `RENAME_EXCL`.
   - Route C uses `O_EXCL` on the final name.
   - I found no path that overwrites or unlinks a file that is not the app's. A collision at the final name always ends in `EEXIST`, then F16, then a new name or `skipped_identical`.
   - The crash cleanup (line 250) only deletes a path that is `temp_path` in a `pending` record of a run that becomes `interrupted`.
2. **Retry bookkeeping: held.**
   - One counter and one record per file (lines 217–218).
   - Route C only retries at step 2, where no record and no own file exist yet. The 'update the existing record' rule therefore never conflicts there.
   - The identical case removes the own file (if present) and updates the record (line 245).
3. **Metadata: held.** F15 (line 126), route B step 4 (line 230) and the two AC3a cases (lines 271–272) agree.
4. **Folder creation after the insert: held.** F14 (line 120) and the AC4 case (line 283) agree.
5. **Tests: partially held.** See findings 4 and 5.

## Crash windows (checked per route)
- **Route A:** a crash after the insert leaves a `pending` record with `temp_path` NULL, so nothing is deleted. The source is intact or already moved. Fine.
- **Route B:**
  - A crash during the copy: the cleanup removes the temp file and the source is intact.
  - A crash after the rename and before the update: the temp path no longer exists, so the cleanup skips it. A cross-volume source still exists. Fine.
- **Route C:**
  - A crash during the copy: the half file under the final name is removed. This is the accepted trade-off.
  - A crash after copy and before `temp_path = NULL`: the complete copy is removed at the next start. The source still exists because it is only deleted after step 5. No loss.
  - A crash after `temp_path = NULL`: the file and the source both stay. Both crash tests (lines 268–269) match this.
- **Accepted gap:** a crash between the exclusive create and the insert leaves an empty file with no record (line 251). I did not raise it.

## Findings

### [MINOR] Failure of the `temp_path = NULL` update in route C is unspecified and conflicts with F19b
**Where:** line 240 (route C step 5) vs line 146 (F19b step 2).
**Claim:** Step 5 updates the record and only afterwards deletes the source.
**Reality:** F19b says that when an update fails, 'this file is already processed'. If the NULL update fails, the complete file stays under a `pending` record with `temp_path = dest_path`. Two things can then go wrong:
- an implementer who follows F19b may still delete the source in move mode;
- if the run becomes `interrupted`, the next start deletes the complete copy.
The first is data loss. The second is a copy that exists only until the next start.
**Consequence:** A reasonable implementation can lose data in one rare path. No test covers it.
**Fix:** Add one sentence: if the NULL update fails, the source is not deleted, the batch stops and the run is set to `aborted`. Add one FileOps/store failure-injection case that asserts the source still exists.

### [MINOR] The cleanup identifies the own file by path only
**Where:** line 250, line 238, line 216.
**Claim:** The cleanup never deletes a file that is not the app's.
**Reality:** In route C the path is the user-visible final name. Between a crash and the next start, the user or another process may delete the half file and put a different file at the same path. The cleanup (path only, 'if it still exists') would then delete that file.
- The window is real, though small and user-driven. Route B is safe because its UUID name is unique.
- The same applies if two instances run at once: the second instance's startup cleanup (F19c) would delete the first instance's in-progress file and mark its run `interrupted`. The spec does not require a single instance.
**Consequence:** NF4 'never delete a foreign file' holds only in the common case.
**Fix:** Record `fileResourceIdentifier` (or inode and size) when the file is created. Check it before deleting, or state in one line that the app is single-instance and that the user must not touch the half file. Either remedy is small.

### [MINOR] Result name for a move with a suffix is inconsistent
**Where:** line 224 (route A step 4: 'moved'), line 266 (AC3a: `moved` under a following free name), lines 131 and 263 (a suffix gives `renamed`).
**Reality:** The spec never says whether a move whose name was changed is `moved` or `renamed`. Route B and copy give `renamed`. Route A gives `moved`.
**Consequence:** Summary counts and tests will diverge between implementations.
**Fix:** State once that a suffix always yields `renamed` (or always `moved` for a move) and align line 224 and the line 266 test.

### [MINOR] Route C test coverage is thinner than for route B
**Where:** lines 267–269, 262–265.
**Reality:**
- Route C has no case for a collision with identical content, for three `EEXIST`s, or for a size mismatch on a move.
- The line 267 case lists only 'the appeared file is unchanged'. It does not assert the `renamed` result, exactly one record, or that no `pending` record is left.
- 'No `rename` is ever called' (line 267) cannot be observed on the real `FileOps`. It needs a spy or an injected `FileOps` wrapper.
- The three-`EEXIST` case (line 265) does not say which route it runs on. 'The own file is gone' is vacuous for routes A and C.
**Consequence:** Retry bookkeeping or size-check defects in route C could pass the tests unnoticed.
**Fix:** Run the line 263–265 cases for routes B and C, and add the missing assertions to line 267. This is a test-matrix extension, not new design.

### [MINOR] AC7 does not prove route C leaves nothing behind
**Where:** line 299.
**Reality:** 'No `.macsearch-*.tmp` files remain' is trivially true on route C, because route C creates no temp files. On exFAT, `COPYFILE_ALL` xattrs may also be emulated with AppleDouble `._` sidecar files, and these are not checked.
**Consequence:** A leftover half file or `._` file could go unnoticed.
**Fix:** For the exFAT variant, assert that the destination folder contains exactly the expected file (plus any `._` sidecar the OS makes). Also confirm that the capability probe actually selected route C on this volume.

### [MINOR] The capability probe and a runtime `ENOTSUP` are not tied together
**Where:** line 123, line 259.
**Reality:** The capability is probed once per run. A volume that claims `VOL_CAP_INT_RENAME_EXCL` but returns `ENOTSUP` or `EINVAL` from `renamex_np` falls under 'another error than `EEXIST`'. The result is `failed`, so it is safe. The behaviour is not stated, and the failed file would not be retried through route C.
**Consequence:** A rare, safe failure with a poor message.
**Fix:** Add a sentence that this case is `failed` with a clear error and is not retried. Switching to route C is optional.

## Other checks
- `getattrlist` with `ATTR_VOL_CAPABILITIES` and `VOL_CAP_INT_RENAME_EXCL`, `renamex_np` with `RENAME_EXCL`, and `O_EXCL` on SMB or exFAT are implementable on current macOS. F15 and NF4 are consistent with each other and with F16, F17, F19b and F0d.
- No contradiction was found between the NF4 routes and F15–F19b.
