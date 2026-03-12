# Async Supervision TODO

## Context

Current async delegation works for submission, but supervision is weak:

- async submit returns a guardrail / submitted message, not a durable task handle
- completion requires active polling via `pend <provider>`
- `pend` is latest-reply oriented, not task-oriented
- concurrent async tasks can overwrite the operator's mental model of "what just finished"
- there is no automatic post-completion validation / repair loop

## Problems

1. No task-scoped completion tracking
Need a stable `task_id` for each async request, not just provider-level latest output.

2. No structured completion artifact
Need durable machine-readable result files, not only natural-language replies.

3. `pend` is not task-aware
Need to inspect by task, not only by provider latest message.

4. No wait/watch primitive
Need a blocking or streaming way to wait for task completion.

5. No built-in supervisor loop
Need an execution mode that can dispatch, wait, validate, repair, and retry.

## P0

1. Persist async task metadata
- Record `task_id`, `provider`, `submitted_at`, `prompt_summary`, `status`, `log_file`, `result_file`.
- Suggested location: `.ccb/async-tasks.json` or `.ccb/async-tasks/<task_id>.json`.

2. Persist structured completion results
- On completion, write `.ccb/async-results/<task_id>.json`.
- Suggested fields:
  - `task_id`
  - `provider`
  - `status`
  - `completed_at`
  - `changedFiles`
  - `commands`
  - `notes`
  - `exit_code`

3. Extend `pend`
- Add task-oriented access:
  - `pend <provider> --task <id>`
  - `pend <provider> --running`
  - `pend <provider> --done-since <ts>`

4. Add wait/watch command
- Examples:
  - `await-task <task_id>`
  - `pend --watch <provider>`

## P1

5. Completion hook / notifier
- On async completion, update task state and emit a lightweight completion summary.

6. Supervisor mode
- Built-in loop:
  - submit task
  - wait for completion
  - run validation commands
  - if failed, dispatch repair task
  - continue until pass

## Constraints

- Do not redesign current provider protocols before Copilot/Cursor stabilization.
- Do not expand into a large workflow engine yet.
- Focus on small, durable primitives first.

## Priority

Defer until Copilot and Cursor functionality is stable and committed.
