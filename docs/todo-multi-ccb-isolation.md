# Multi-CCB Session Isolation Bug

## Problem

**Cross-project message routing:** Messages from one project directory can be delivered to a provider pane that belongs to a different project directory.

**Example:**
- Project A: `/home/wyc/code/github/claude_code_bridge`
- Project B: `/home/wyc/code/ant/yuanrong`
- Result: Claude in Project A sends message to Codex, but it goes to Codex pane in Project B

**Root Cause (CONFIRMED): Tmux Pane ID Recycling**

1. Project A's CCB starts, creates pane `%25`, writes to `.codex-session`
2. Project A's CCB stops, pane `%25` is destroyed
3. Project B's CCB starts, tmux **recycles** the same pane ID `%25` for its Codex
4. Project A's `.codex-session` still has `pane_id: %25` (stale session)
5. When `ask codex` runs in Project A, it reads the stale `%25` and sends to Project B's Codex!

**The issue is NOT:**
- Multiple CCB instances in the same directory (B option prevents this)
- Session file sharing across projects

**The issue IS:**
- Tmux recycles pane IDs after they're destroyed
- Stale session files point to "recycled" pane IDs that now belong to other projects

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

## Solution: Verify Pane Ownership (Implemented 2026-03-14)

**Fix: Verify that the pane in the session file belongs to the current project.**
- ✅ Added `expected_work_dir` parameter to `check_active_session()`
- ✅ Compare session's `work_dir` with current project's `work_dir`
- ✅ If pane belongs to different project, treat as stale and auto-clean
- ✅ Display warning when clearing stale session from wrong project
- ✅ Added test for wrong project detection

**How it works:**
1. Before starting provider, check if session file exists
2. If session has `pane_id`, verify pane is alive
3. **NEW:** Also verify pane's `work_dir` matches current project
4. If pane belongs to wrong project, clear stale session and start new pane

## TODO (Future)

If per-instance isolation is needed:
- Option A: Instance-scoped session files (`.codex-session-{instance}`)
- Option C: Per-instance `.ccb/instance-{id}/` subdirectories

## Workaround

Only run one CCB instance per project directory at a time.

## Severity

**High** - Data leak and cross-talk between unrelated conversations
