# Cursor Launcher Follow-Up

## Goal

Bring Cursor to launcher parity with the other interactive pane-backed providers.

## Status

Core support is now in place:

- supported communication tools: `ask cursor`, `ccb-ping cursor`, `uping`, `upend`
- launcher entrypoint exists: `ccb cursor`
- launcher code paths exist for tmux, wezterm, and current-pane
- `.cursor-session` writing and cleanup paths are present

## Remaining TODO

1. Add incremental attach support
- support appending Cursor to an already-running project-scoped CCB session
- likely shape: `ccb add cursor`
- avoid requiring a full CCB restart just to add one provider pane

2. Finish runtime validation
- verify `ccb cursor` in a fresh launcher session end to end
- confirm `cursor-agent` startup behavior is stable in pane-backed use
- confirm resume strategy is acceptable in real usage

3. Clarify docs
- distinguish communication support from launcher/pane support
- document current limitations and expected behavior

## Notes

- Internal marker/session stability and external display naming should stay decoupled.
- This file now tracks post-launch follow-up, not the initial launcher implementation.
