# Story status

A story's status follows from its tasks. Implement two functions.

## `deriveStoryStatus(tasks)`

`tasks` is an array of `{ id, status }` with task status one of
`todo`, `in_progress`, `review`, `done`, `failed`, `excluded`. Rules, first match wins:

1. Ignore `excluded` tasks. If no tasks remain → `'IN_SPRINT'`.
2. Any `failed` → `'FAILED'`.
3. All `done` → `'DONE'`.
4. Any `in_progress` or `review`, or a mix of `done` and `todo` → `'IN_PROGRESS'`.
5. Otherwise (all `todo`) → `'IN_SPRINT'`.

An unknown task status throws an `Error`.

## `applyTaskUpdate(story, taskId, status, expectedStatus)`

`story` is `{ id, status, tasks }`. Return a **new** story (never mutate the input, including its
tasks array and task objects) in which task `taskId` has the new `status` and the story `status`
is re-derived with `deriveStoryStatus`.

- Throw an `Error` whose message contains `not found` if no task has that id.
- Throw an `Error` whose message contains `invalid status` if `status` is not a valid task status.
- If `expectedStatus` is given (not `undefined`) and differs from the task's current status, throw
  an `Error` whose message contains `conflict` (optimistic concurrency).
- Tasks other than the updated one must keep their identity (same object references).
