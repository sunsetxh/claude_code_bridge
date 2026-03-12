# OpenCode Unified `askd` TODO

## Problem

`ccb-ping opencode` can succeed while `oask` still fails with:

- `oask daemon required but not available`

Root cause is client/daemon contract drift, not session absence.

## What Was Observed

- `OASK_CLIENT_SPEC` still uses provider-specific assumptions with `protocol_prefix="oask"`
- client logic looks for `oaskd.json`
- actual runtime exposes unified `askd.json`
- unified daemon responds with `ask.response`, not `oask.response`
- `try_daemon_request(...)` rejects the response because it expects `oask.response`

## TODO

1. Migrate OpenCode client path fully to unified `askd`

2. Make `oask` use unified daemon state and protocol consistently
- use `askd.json`
- send `ask.request`
- accept `ask.response`
- keep `provider="opencode"` as the routing key

3. Remove remaining provider-specific `oaskd` assumptions from the client path

## Validation

- active OpenCode session
- `oask`
- `ask opencode`
- daemon autostart
- state-file discovery
