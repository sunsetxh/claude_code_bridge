"""Test session conflict detection for multi-CCB isolation."""

import json
import sys
from pathlib import Path

# Add lib directory to path
script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir.parent / "lib"))

from session_utils import check_active_session, check_conflicting_sessions, format_conflict_error


def test_check_active_session_no_file():
    """Test check_active_session when session file doesn't exist."""
    is_active, msg, data = check_active_session(Path("/nonexistent/path"), "Codex")
    assert not is_active
    assert msg is None
    assert data is None
    print("✓ check_active_session: no file returns inactive")


def test_check_active_session_inactive():
    """Test check_active_session when session is marked inactive."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        session_file = Path(tmp) / ".codex-session"
        session_file.write_text(json.dumps({"active": False, "pane_id": "%37"}))

        is_active, msg, data = check_active_session(session_file, "Codex")
        assert not is_active
        assert msg is None
        assert data is not None
    print("✓ check_active_session: inactive session returns inactive")


def test_check_active_session_no_pane():
    """Test check_active_session when session has no pane_id."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        session_file = Path(tmp) / ".codex-session"
        session_file.write_text(json.dumps({"active": True}))

        is_active, msg, data = check_active_session(session_file, "Codex")
        assert not is_active
        assert msg is None
        assert data is not None
    print("✓ check_active_session: no pane_id returns inactive")


def test_check_active_session_wrong_project():
    """Test check_active_session when pane belongs to different project."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        work_dir = Path(tmp) / "project_a"
        work_dir.mkdir()
        other_dir = Path(tmp) / "project_b"
        other_dir.mkdir()

        session_file = work_dir / ".codex-session"
        session_file.write_text(json.dumps({
            "active": True,
            "pane_id": "%37",
            "terminal": "tmux",
            "work_dir": str(other_dir),  # Points to wrong project!
        }))

        # Mock TmuxBackend.is_alive to return True
        from unittest.mock import patch, MagicMock
        mock_backend = MagicMock()
        mock_backend.is_alive.return_value = True

        with patch('terminal.TmuxBackend', return_value=mock_backend):
            # Check with expected_work_dir
            is_active, msg, data = check_active_session(session_file, "Codex", expected_work_dir=work_dir)
            # Should NOT be active because pane belongs to wrong project
            assert not is_active
            assert "belongs to different project" in msg

    print("✓ check_active_session: detects pane from wrong project")


def test_check_conflicting_sessions():
    """Test check_conflicting_sessions with multiple providers."""
    import tempfile
    from unittest.mock import patch, MagicMock

    with tempfile.TemporaryDirectory() as tmp:
        work_dir = Path(tmp)

        # Create active session files
        for provider in ["codex", "claude"]:
            session_file = work_dir / ".ccb" / f".{provider}-session"
            session_file.parent.mkdir(parents=True, exist_ok=True)
            session_file.write_text(json.dumps({
                "active": True,
                "pane_id": f"%{100 + hash(provider) % 100}",
                "terminal": "tmux",
            }))

        # Mock TmuxBackend.is_alive to return True for our test panes
        mock_backend = MagicMock()
        mock_backend.is_alive.return_value = True

        with patch('terminal.TmuxBackend', return_value=mock_backend):
            # Check without force
            has_conflict, conflicting = check_conflicting_sessions(
                work_dir, ["codex", "claude", "gemini"], force=False
            )
            assert has_conflict
            assert set(conflicting) == {"codex", "claude"}

            # Check with force
            has_conflict, conflicting = check_conflicting_sessions(
                work_dir, ["codex", "claude"], force=True
            )
            assert not has_conflict
            assert not conflicting

    print("✓ check_conflicting_sessions: detects active sessions")


def test_format_conflict_error():
    """Test format_conflict_error output."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        work_dir = Path(tmp)
        session_file = work_dir / ".ccb" / ".codex-session"

        # Test tmux
        msg = format_conflict_error("codex", work_dir, session_file, terminal_type="tmux")
        assert "Codex" in msg
        assert str(work_dir) in msg
        assert "--force" in msg
        assert "tmux" in msg

        # Test wezterm
        msg = format_conflict_error("claude", work_dir, session_file, terminal_type="wezterm")
        assert "Claude" in msg
        assert "wezterm" in msg.lower()

    print("✓ format_conflict_error: includes expected info")


if __name__ == "__main__":
    test_check_active_session_no_file()
    test_check_active_session_inactive()
    test_check_active_session_no_pane()
    test_check_active_session_wrong_project()
    test_check_conflicting_sessions()
    test_format_conflict_error()
    print("\n✅ All session conflict check tests passed")
