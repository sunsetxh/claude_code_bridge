# OpenCode Unified `askd` Status

## Status

Completed.

OpenCode client calls now use the unified `askd` contract:

- `OASK_CLIENT_SPEC` uses the unified `ask` protocol
- `try_daemon_request(...)` sends `provider="opencode"`
- unified requests always carry a `caller` value, defaulting to `manual`
- `askd.json` is preferred
- `oaskd.json` is retained only as a legacy fallback for OpenCode

## Landed In Code

- `lib/providers.py`
- `lib/askd_client.py`
- `test/test_oask_unified_askd.py`

## Validation

Verified with:

- `python -m pytest -q test/test_oask_unified_askd.py`
- `python -m pytest -q test/test_daemon_only_cli.py`
- `python -m pytest -q test/test_integration.py`

## Notes

- `CCB_OASKD*` environment variables were intentionally kept for compatibility.
- `OASKD_SPEC` was intentionally left unchanged; this migration only affected the client path.
