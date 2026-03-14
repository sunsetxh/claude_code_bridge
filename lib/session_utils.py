"""
session_utils.py - Session file permission check utility
"""
from __future__ import annotations
import os
import stat
from pathlib import Path
from typing import Tuple, Optional


CCB_PROJECT_CONFIG_DIRNAME = ".ccb"
CCB_PROJECT_CONFIG_LEGACY_DIRNAME = ".ccb_config"


def project_config_dir(work_dir: Path) -> Path:
    return Path(work_dir).resolve() / CCB_PROJECT_CONFIG_DIRNAME


def legacy_project_config_dir(work_dir: Path) -> Path:
    return Path(work_dir).resolve() / CCB_PROJECT_CONFIG_LEGACY_DIRNAME


def resolve_project_config_dir(work_dir: Path) -> Path:
    """Return primary config dir if present; otherwise legacy if it exists."""
    primary = project_config_dir(work_dir)
    legacy = legacy_project_config_dir(work_dir)
    if primary.is_dir() or not legacy.is_dir():
        return primary
    return legacy


def check_session_writable(session_file: Path) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Check if session file is writable

    Returns:
        (writable, error_reason, fix_suggestion)
    """
    session_file = Path(session_file)
    parent = session_file.parent

    # 1. Check if parent directory exists and is accessible
    if not parent.exists():
        return False, f"Directory not found: {parent}", f"mkdir -p {parent}"

    if not os.access(parent, os.X_OK):
        return False, f"Directory not accessible (missing x permission): {parent}", f"chmod +x {parent}"

    # 2. Check if parent directory is writable
    if not os.access(parent, os.W_OK):
        return False, f"Directory not writable: {parent}", f"chmod u+w {parent}"

    # 3. If file doesn't exist, directory writable is enough
    if not session_file.exists():
        return True, None, None

    # 4. Check if it's a regular file
    if session_file.is_symlink():
        target = session_file.resolve()
        return False, f"Is symlink pointing to {target}", f"rm -f {session_file}"

    if session_file.is_dir():
        return False, "Is directory, not file", f"rmdir {session_file} or rm -rf {session_file}"

    if not session_file.is_file():
        return False, "Not a regular file", f"rm -f {session_file}"

    # 5. Check file ownership (POSIX only)
    if os.name != "nt" and hasattr(os, "getuid"):
        try:
            file_stat = session_file.stat()
            file_uid = getattr(file_stat, "st_uid", None)
            current_uid = os.getuid()

            if isinstance(file_uid, int) and file_uid != current_uid:
                import pwd

                try:
                    owner_name = pwd.getpwuid(file_uid).pw_name
                except KeyError:
                    owner_name = str(file_uid)
                current_name = pwd.getpwuid(current_uid).pw_name
                return (
                    False,
                    f"File owned by {owner_name} (current user: {current_name})",
                    f"sudo chown {current_name}:{current_name} {session_file}",
                )
        except Exception:
            pass

    # 6. Check if file is writable
    if not os.access(session_file, os.W_OK):
        mode = stat.filemode(session_file.stat().st_mode)
        return False, f"File not writable (mode: {mode})", f"chmod u+w {session_file}"

    return True, None, None


def safe_write_session(session_file: Path, content: str) -> Tuple[bool, Optional[str]]:
    """
    Safely write session file, return friendly error on failure

    Returns:
        (success, error_message)
    """
    session_file = Path(session_file)

    # Pre-check
    writable, reason, fix = check_session_writable(session_file)
    if not writable:
        return False, f"❌ Cannot write {session_file.name}: {reason}\n💡 Fix: {fix}"

    # Attempt atomic write
    tmp_file = session_file.with_suffix(".tmp")
    try:
        tmp_file.write_text(content, encoding="utf-8")
        os.replace(tmp_file, session_file)
        return True, None
    except PermissionError as e:
        if tmp_file.exists():
            try:
                tmp_file.unlink()
            except Exception:
                pass
        return False, f"❌ Cannot write {session_file.name}: {e}\n💡 Try: rm -f {session_file} then retry"
    except Exception as e:
        if tmp_file.exists():
            try:
                tmp_file.unlink()
            except Exception:
                pass
        return False, f"❌ Write failed: {e}"


def print_session_error(msg: str, to_stderr: bool = True) -> None:
    """Output session-related error"""
    import sys
    output = sys.stderr if to_stderr else sys.stdout
    print(msg, file=output)


def check_active_session(session_file: Path, provider_name: str, expected_work_dir: Optional[Path] = None) -> Tuple[bool, Optional[str], Optional[dict]]:
    """
    Check if a provider session is already active.

    Args:
        session_file: Path to the session file (e.g., .codex-session)
        provider_name: Name of the provider for error messages (e.g., "Codex")
        expected_work_dir: Expected project directory to verify pane ownership

    Returns:
        (is_active, message, session_data)
        - is_active: True if session exists, pane is alive, AND belongs to expected_work_dir
        - message: Error/info message if is_active is True or if pane belongs to another project
        - session_data: The session data dict if exists, None otherwise
    """
    if not session_file or not session_file.exists():
        return False, None, None

    try:
        import json
        data = json.loads(session_file.read_text(encoding="utf-8"))
    except Exception:
        return False, None, None

    if not isinstance(data, dict):
        return False, None, None

    # Check if session is marked active
    if not data.get("active"):
        return False, None, data

    # Get pane_id (support both old and new field names)
    pane_id = data.get("pane_id") or data.get("tmux_session")
    if not pane_id:
        return False, None, data

    # Check if pane is still alive
    terminal_type = data.get("terminal", "tmux")
    pane_alive = False
    try:
        if terminal_type == "tmux":
            from terminal import TmuxBackend
            backend = TmuxBackend()
            pane_alive = backend.is_alive(str(pane_id))
        elif terminal_type == "wezterm":
            from terminal import WeztermBackend
            backend = WeztermBackend()
            pane_alive = backend.is_alive(str(pane_id))
    except Exception:
        pass

    if not pane_alive:
        # Pane not found or not alive - session is stale
        return False, None, data

    # Pane is alive - verify it belongs to the expected project
    if expected_work_dir is not None:
        session_work_dir = data.get("work_dir") or data.get("start_dir")
        if session_work_dir:
            try:
                from pathlib import Path as StdLibPath
                session_work = StdLibPath(session_work_dir).resolve()
                expected_work = StdLibPath(expected_work_dir).resolve()
                if session_work != expected_work:
                    # Pane exists but belongs to a different project!
                    return False, f"Pane {pane_id} belongs to different project ({session_work})", data
            except Exception:
                pass

    return True, f"Active {provider_name} session found in pane {pane_id}", data


def check_conflicting_sessions(
    work_dir: Path,
    providers: list[str],
    force: bool = False,
) -> Tuple[bool, list[str]]:
    """
    Check for conflicting active CCB sessions in the same project directory.

    Args:
        work_dir: Project directory to check
        providers: List of provider names to check (e.g., ["codex", "claude"])
        force: If True, skip the check and allow override

    Returns:
        (has_conflict, conflicting_provider_names)
        - has_conflict: True if any active session exists
        - conflicting_providers: List of provider names with active sessions
    """
    if force:
        return False, []

    conflicting = []
    for provider in providers:
        session_filename = f".{provider}-session"
        session_file = find_project_session_file(work_dir, session_filename)
        if not session_file:
            continue

        is_active, _msg, _data = check_active_session(session_file, provider.capitalize())
        if is_active:
            conflicting.append(provider)

    return len(conflicting) > 0, conflicting


def format_conflict_error(
    provider: str,
    work_dir: Path,
    session_file: Path,
    terminal_type: str = "tmux",
) -> str:
    """Format error message for conflicting sessions."""
    provider_cap = provider.capitalize()
    if terminal_type == "wezterm":
        attach_hint = f"""To attach to the existing session:
  - Find the wezterm pane: wezterm cli list-clients
  - The CCB window should be visible in your WezTerm instance"""
    else:
        attach_hint = f"""To attach to the existing session:
  - Find the tmux session: tmux list-sessions
  - Attach: tmux attach-session -t <session-name>"""

    return f"""❌ Active {provider_cap} session found

💡 Another CCB instance is already running {provider_cap} in this project directory.

Project: {work_dir}
Session: {session_file}

Options:
  1. Use the existing CCB session (find the tmux/wezterm window and attach)
  2. Stop the existing session first (close the window/pane)
  3. Override with: ccb --force {provider} ... (NOT RECOMMENDED)

{attach_hint}
"""


def find_project_session_file(work_dir: Path, session_filename: str) -> Optional[Path]:
    """
    Find a session file for the given work_dir.

    Lookup walks upward from `work_dir` to support calls from subdirectories:
      1) <dir>/.ccb/<session_filename>
      2) <dir>/.ccb_config/<session_filename>  (legacy)
      3) <dir>/<session_filename>  (legacy)

    The nearest match wins.
    """
    try:
        current = Path(work_dir).resolve()
    except Exception:
        current = Path(work_dir).absolute()

    for root in [current, *current.parents]:
        candidate = root / CCB_PROJECT_CONFIG_DIRNAME / session_filename
        if candidate.exists():
            return candidate
        legacy_candidate = root / CCB_PROJECT_CONFIG_LEGACY_DIRNAME / session_filename
        if legacy_candidate.exists():
            return legacy_candidate
        legacy = root / session_filename
        if legacy.exists():
            return legacy
    return None
