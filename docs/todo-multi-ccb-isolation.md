# Multi-CCB Session Isolation Bug

## Problem

When multiple CCB instances run in different tmux windows **in the same project directory**, they interfere with each other.

**Example:**
- Window A (ccb-1): Claude in `/home/wyc/project`
- Window B (ccb-2): Claude in `/home/wyc/project` (same directory!)
- Result: Message from A might be delivered to Codex in Window B

**Root Cause (CONFIRMED):**
- Both instances share the same `.codex-session` file
- Session file contains `pane_id: %125`
- When a new CCB starts, it overwrites the `pane_id` in the shared session file
- Subsequent requests use the wrong `pane_id`

## Diagnosis (2026-03-14)

**CCB_RUN_DIR is per-project:**
- Each CCB instance sets `CCB_RUN_DIR` to `~/.cache/ccb/projects/{project_hash}/`
- State files are project-scoped: `askd.json` per project
- Each project has its own askd daemon on different ports

**Multiple askd daemons observed:**
```
Port 44917: /home/wyc/code/github/claude_code_bridge
Port 44675: /mnt/nfs/wyc/code/ant
Port 45143: /home/wyc/code/ant/yuanrong
```

**Confirmed cause:**
- Multiple CCB instances in same project directory share the same `.codex-session`
- New instance overwrites `pane_id` in the shared session file
- Requests get routed to wrong pane

## Solution: Option B (Implemented 2026-03-14)

**Prevent multiple CCB instances per project directory:**
- ✅ Added `check_active_session()` - verifies if provider pane is still alive
- ✅ Added `check_conflicting_sessions()` - checks all providers for active sessions
- ✅ Modified `_start_provider()` - blocks startup if active session exists
- ✅ Added `--force` flag - allows override (not recommended)
- ✅ Added tests in `test/test_session_conflict_check.py`

**Usage:**
```bash
# Normal start (will fail if active session exists)
ccb codex

# Override check (NOT recommended - may cause cross-talk)
ccb --force codex
```

## TODO (Future)

If per-instance isolation is needed:
- Option A: Instance-scoped session files (`.codex-session-{instance}`)
- Option C: Per-instance `.ccb/instance-{id}/` subdirectories

## Workaround

Only run one CCB instance per project directory at a time.

## Severity

**High** - Data leak and cross-talk between unrelated conversations
