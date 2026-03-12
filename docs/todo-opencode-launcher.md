# OpenCode Launcher Status

## Status

Completed for the `ccb -r` restore issue.

Landed behavior:

- `ccb -r` now prefers `opencode --session <id>` over plain `--continue`
- latest matching OpenCode session id is selected via shared logic in `lib/opencode_comm.py`
- `.opencode-session` now records `opencode_session_id` on resume paths
- existing consumers (`oaskd_session` / adapter paths) can bind to the restored session explicitly

## Landed In Code

- `lib/opencode_comm.py`
- `ccb`
- `test/test_ccb_opencode_resume.py`

## Validation

Verified by:

- `python -m pytest -q test/test_ccb_opencode_resume.py`
- `python -m pytest -q test/test_oaskd_session.py`
- `python -m pytest -q test/test_ccb_tmux_split.py`
- `python -m py_compile ccb lib/opencode_comm.py`

## Notes

- This fix is specifically about `ccb -r` launcher semantics for OpenCode session restore.
- It is distinct from async supervision and unified `askd` migration.
