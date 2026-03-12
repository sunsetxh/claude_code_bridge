# Cursor Launcher TODO

## Goal

Bring Cursor to launcher parity with the other interactive pane-backed providers.

## Current Gap

Current Cursor support started as communication-level support:

- supported: `ask cursor`, `ccb-ping cursor`, `uping`, `upend`
- launcher support is being built: `ccb cursor`

## TODO

1. Finish and verify `ccb cursor` launcher support
- tmux pane startup
- wezterm pane startup
- current-pane startup

2. Define Cursor pane/session behavior
- pane title and human-readable display name
- provider binding and registry updates
- `.cursor-session` compatibility with current tools

3. Validate interaction model for `cursor-agent`
- direct interactive startup behavior
- startup command defaults
- practical resume strategy

4. Clarify docs
- distinguish communication support from launcher/pane support
- document current limitations and expected behavior

5. Add incremental attach support
- support appending Cursor to an already-running project-scoped CCB session
- likely shape: `ccb add cursor`
- avoid requiring a full CCB restart just to add one provider pane

## Notes

- Internal marker/session stability and external display naming should stay decoupled.
- This file is only for Cursor launcher work; async supervision items live elsewhere.
