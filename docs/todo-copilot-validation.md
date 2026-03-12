# Copilot Validation TODO

## Current Limitation

`ccb-ping copilot` was only validated in the "no active session" case.

Behavior looked correct, but no live Copilot session was available for full end-to-end verification.

## TODO

1. Start Copilot in a fresh session context

2. Validate `ccb-ping copilot` with an active session

3. Validate help and usage surfaces against actual runtime behavior

4. Validate session discovery and binding in the current project

5. Validate `ask` and `pend` flows against a real active Copilot session when applicable

6. Record any launcher/session assumptions that differ from current docs
