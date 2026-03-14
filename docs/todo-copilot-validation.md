# Copilot Validation TODO

## Current Limitation

`ccb-ping copilot` was only validated in the "no active session" case.

Behavior looked correct, but no live Copilot session was available for full end-to-end verification.

## Completed (2026-03-14)

- [x] Validated `hping` with active session - returned `✅ Copilot connection OK (Session OK)`
- [x] Validated `hask` async call - received successful response
- [x] Confirmed session discovery and binding work in current project

## TODO

1. Start Copilot in a fresh session context (manual validation needed)

2. Validate `ask copilot` flow (separate from `hask` direct call)

3. Validate `hpend` for retrieving replies from session history

4. Record any launcher/session assumptions that differ from current docs
