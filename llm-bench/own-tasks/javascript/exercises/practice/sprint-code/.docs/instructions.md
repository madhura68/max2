# Sprint code

Sprints get a human-readable code `S-YYYY-MM-DD-N`: the start date plus a counter that restarts
at 1 for every date. Implement `nextSprintCode(existingCodes, date)`.

- `existingCodes` is an array of strings: codes already used by this product. It can contain
  codes of other dates, codes for the same date with gaps (`-1`, `-3`), and junk that must be
  ignored (anything that is not exactly `S-` + a valid calendar date `YYYY-MM-DD` + `-` + a
  positive integer without leading zeros, e.g. `S-2026-02-30-1`, `S-2026-09-25-0`,
  `S-2026-09-25-01`, `s-2026-09-25-1`, `S-2026-09-25-1x`, `null`).
- `date` is a JavaScript `Date`; use its **UTC** calendar date.
- Return the code for `date` with N = (highest valid N already used for that date) + 1, or 1 when
  none exists. Gaps are not reused.
- Throw an `Error` when `date` is not a valid `Date` (e.g. `new Date('nope')` or a string).
