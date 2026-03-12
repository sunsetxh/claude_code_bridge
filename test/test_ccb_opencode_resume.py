"""Tests for OpenCode resume functionality."""
import importlib.util
import json
import os
import tempfile
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


def _load_ccb_module() -> object:
    repo_root = Path(__file__).resolve().parents[1]
    ccb_path = repo_root / "ccb"
    loader = SourceFileLoader("ccb_script", str(ccb_path))
    spec = importlib.util.spec_from_loader("ccb_script", loader)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_find_latest_opencode_session_id_returns_tuple():
    """Helper returns (session_id, has_history) tuple."""
    from opencode_comm import find_latest_opencode_session_id
    
    result = find_latest_opencode_session_id(Path.cwd())
    assert isinstance(result, tuple)
    assert len(result) == 2
    session_id, has_history = result
    assert isinstance(session_id, (str, type(None)))
    assert isinstance(has_history, bool)


def test_find_latest_opencode_session_id_with_valid_workdir():
    """Returns valid session ID when OpenCode sessions exist."""
    from opencode_comm import find_latest_opencode_session_id
    
    session_id, has_history = find_latest_opencode_session_id(Path.cwd())
    # Current directory may or may not have sessions
    if has_history:
        assert session_id is not None
        assert session_id.startswith("ses_")


def test_build_opencode_start_cmd_returns_tuple():
    """_build_opencode_start_cmd returns (cmd, session_id) tuple."""
    ccb = _load_ccb_module()
    
    launcher = ccb.AILauncher(providers=["opencode"])
    # Need to mock some attributes
    launcher.auto = False
    launcher.resume = False
    launcher.project_root = Path.cwd()
    launcher.invocation_dir = Path.cwd()
    
    result = launcher._build_opencode_start_cmd()
    assert isinstance(result, tuple)
    assert len(result) == 2
    cmd, session_id = result
    assert isinstance(cmd, str)
    assert "opencode" in cmd
    assert session_id is None  # resume=False


def test_build_opencode_start_cmd_with_resume():
    """Resume mode returns --session or --continue flag."""
    ccb = _load_ccb_module()
    
    launcher = ccb.AILauncher(providers=["opencode"])
    launcher.auto = False
    launcher.resume = True
    launcher.project_root = Path.cwd()
    launcher.invocation_dir = Path.cwd()
    
    cmd, session_id = launcher._build_opencode_start_cmd()
    
    # Should have either --session <id> or --continue
    assert "--session" in cmd or "--continue" in cmd


def test_write_opencode_session_includes_opencode_session_id():
    """_write_opencode_session writes opencode_session_id when provided."""
    ccb = _load_ccb_module()
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        session_file = tmppath / ".opencode-session"
        
        launcher = ccb.AILauncher(providers=["opencode"])
        launcher.auto = False
        launcher.resume = True
        launcher.project_root = tmppath
        launcher.invocation_dir = tmppath
        launcher.session_id = "test-session-id"
        launcher.terminal_type = "tmux"
        
        # Directly test the data dict construction
        # by examining the method's internal logic
        with patch.object(launcher, '_project_session_file', return_value=session_file):
            with patch.object(launcher, '_maybe_start_provider_daemon'):
                runtime = tmppath / "runtime"
                runtime.mkdir()
                
                # Call the method and check the file was written
                result = launcher._write_opencode_session(
                    runtime,
                    None,
                    pane_id="test-pane",
                    pane_title_marker="CCB-OpenCode",
                    start_cmd="opencode --session ses_test123",
                    opencode_session_id="ses_test123",
                )
                
                assert result is True
                assert session_file.exists()
                written_data = json.loads(session_file.read_text())
                assert written_data.get("opencode_session_id") == "ses_test123"


def test_write_opencode_session_omits_id_when_not_provided():
    """_write_opencode_session omits opencode_session_id when not provided (fresh start)."""
    ccb = _load_ccb_module()
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        session_file = tmppath / ".opencode-session"
        
        launcher = ccb.AILauncher(providers=["opencode"])
        launcher.auto = False
        launcher.resume = False
        launcher.project_root = tmppath
        launcher.invocation_dir = tmppath
        launcher.session_id = "test-session-id"
        launcher.terminal_type = "tmux"
        
        with patch.object(launcher, '_project_session_file', return_value=session_file):
            with patch.object(launcher, '_maybe_start_provider_daemon'):
                runtime = tmppath / "runtime"
                runtime.mkdir()
                
                result = launcher._write_opencode_session(
                    runtime,
                    None,
                    pane_id="test-pane",
                    pane_title_marker="CCB-OpenCode",
                    start_cmd="opencode",
                    opencode_session_id=None,
                )
                
                assert result is True
                assert session_file.exists()
                written_data = json.loads(session_file.read_text())
                assert "opencode_session_id" not in written_data
