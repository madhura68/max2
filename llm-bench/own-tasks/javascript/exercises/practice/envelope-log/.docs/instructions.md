# Envelope log

Every status change of a queue message is broadcast as a JSON "envelope":
`{"id": "...", "status": "...", "previous_status": "..." | null}`.
Implement `summarize(lines)` that reduces a log of such envelopes.

`lines` is an array of strings in arrival order. Lines that are not valid JSON, not an object, or
lack a string `id` or a string `status` are **malformed**: count them and otherwise skip them.

Allowed transitions (`previous_status` → `status`):

- `null` → `pending` (creation)
- `pending` → `claimed`, `pending` → `cancelled`
- `claimed` → `done`, `claimed` → `failed`, `claimed` → `pending` (requeue), `claimed` → `cancelled`

Everything else is illegal, including any transition out of `done`, `failed` or `cancelled`.

For each envelope:

1. If `previous_status` is missing/undefined, treat it as `null`.
2. If the transition is illegal, record `{ id, from, to }` in `illegal` (with `from` being the
   envelope's `previous_status`, `null` for creation) and **do not** apply it.
3. If the transition is legal but the message's currently known status differs from
   `previous_status` (we missed an event), still apply it and add the id to `gaps` (once per id,
   in first-seen order). A message that has not been seen before has known status `null`.
4. Legal transitions update the message's known status.

Return:

```js
{
  statuses: { [id]: status },   // known status per id (ids seen in at least one applied envelope)
  illegal: [{ id, from, to }],  // in arrival order
  gaps: [id],                   // unique, first-seen order
  malformed: <number>,
  requeues: { [id]: <number> }  // count of applied claimed → pending per id; omit ids with 0
}
```
