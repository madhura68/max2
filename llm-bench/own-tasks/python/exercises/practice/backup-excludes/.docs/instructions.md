# Backup excludes

Our host backup includes all of `/srv` and relies on an exclude list to keep live database data
directories out. Implement `is_excluded(path, patterns)` that decides whether an absolute POSIX
path is excluded.

`path` is an absolute path like `/srv/apps/tei/data/model.bin` (no trailing slash). The path is
treated as a file, but **a path is also excluded when any of its parent directories is excluded**
(an excluded directory excludes everything below it).

`patterns` is a list of strings, evaluated in order; **the last pattern that matches decides**.
A matching normal pattern excludes; a matching pattern starting with `!` re-includes. No match
means not excluded.

Pattern syntax:

- Blank patterns and patterns starting with `#` are ignored.
- A pattern starting with `/` is anchored at the root and matched against the full path.
  Otherwise it may match at any depth: it is matched against every suffix of the path that starts
  at a component boundary (so `data/*.bin` matches `/a/b/data/x.bin`).
- A pattern ending with `/` only matches directories (i.e. a parent directory of `path`, never
  `path` itself). The trailing `/` is not part of the pattern.
- `*` matches any run of characters except `/`; `?` matches exactly one character except `/`.
- `**` as a whole path component matches zero or more components (`/srv/**/pgdata` matches
  `/srv/pgdata` and `/srv/a/b/pgdata`).
- Every other character matches itself (including `.`, `[`, `]`, `+`, `(`, `)`).

The "parent directory excluded" rule applies to the final decision: evaluate the patterns for each
parent directory and for the path itself (directories may be matched by directory-only
patterns); the path is excluded if the path or any parent directory ends up excluded, **except**
that a `!` pattern matching the path itself cannot re-include a file whose parent directory is
excluded.
