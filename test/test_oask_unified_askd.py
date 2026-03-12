"""Test OpenCode client uses unified askd protocol correctly."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from threading import Thread

import pytest

from askd_client import try_daemon_request
from askd_server import AskDaemonServer
from askd.daemon import ASKD_SPEC
from askd_rpc import read_state, shutdown_daemon
from providers import OASK_CLIENT_SPEC, CASK_CLIENT_SPEC


def _wait_for_state(state_file: Path, timeout_s: float = 2.0) -> dict:
    """Wait for state file to be written and return its contents."""
    deadline = time.time() + max(0.1, float(timeout_s))
    while time.time() < deadline:
        if state_file.exists():
            try:
                content = json.loads(state_file.read_text(encoding="utf-8"))
                if isinstance(content, dict) and content.get("port"):
                    return content
            except Exception:
                pass
        time.sleep(0.05)
    raise TimeoutError(f"State file not ready: {state_file}")


def test_oask_client_spec_has_ask_protocol():
    """Verify OASK_CLIENT_SPEC uses unified ask protocol."""
    assert OASK_CLIENT_SPEC.protocol_prefix == "ask", \
        f"OASK_CLIENT_SPEC.protocol_prefix should be 'ask', got '{OASK_CLIENT_SPEC.protocol_prefix}'"
    assert OASK_CLIENT_SPEC.provider_name == "opencode", \
        f"OASK_CLIENT_SPEC.provider_name should be 'opencode', got '{OASK_CLIENT_SPEC.provider_name}'"


def test_oask_request_to_unified_askd_includes_provider_and_caller(tmp_path: Path, monkeypatch) -> None:
    """Test that oask sends provider and caller fields to unified askd."""
    # Setup: Isolate test environment
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("CCB_RUN_DIR", str(tmp_path / "run"))
    monkeypatch.setenv("CCB_ASKD_IDLE_TIMEOUT_S", "0")  # Disable idle timeout

    # Create session file
    work_dir = tmp_path / "project"
    work_dir.mkdir()
    (work_dir / ".opencode-session").write_text(
        json.dumps({"active": True, "session_id": "test-session"}),
        encoding="utf-8",
    )
    monkeypatch.chdir(work_dir)

    # Track received requests
    received_requests = []

    def mock_handler(msg: dict) -> dict:
        received_requests.append(msg)
        return {
            "type": "ask.response",
            "v": 1,
            "id": msg.get("id"),
            "exit_code": 0,
            "reply": "OK",
        }

    # Start unified askd with mock handler
    state_file = tmp_path / "run" / "askd.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)

    server = AskDaemonServer(
        spec=ASKD_SPEC,
        host="127.0.0.1",
        port=0,
        token="test-token",
        state_file=state_file,
        request_handler=mock_handler,
        work_dir=str(work_dir),
    )

    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        # Wait for daemon to be ready
        _wait_for_state(state_file, timeout_s=3.0)

        # Clear CCB_CALLER to test default caller behavior
        monkeypatch.delenv("CCB_CALLER", raising=False)

        # Send request via try_daemon_request (same as oask does)
        result = try_daemon_request(
            OASK_CLIENT_SPEC,
            work_dir,
            "test message",
            timeout=2.0,
            quiet=True,
        )

        # Verify request was sent
        assert len(received_requests) == 1, f"Expected 1 request, got {len(received_requests)}"
        req = received_requests[0]

        # Verify unified askd required fields
        assert req.get("type") == "ask.request", f"Wrong type: {req.get('type')}"
        assert req.get("provider") == "opencode", f"Missing/wrong provider: {req.get('provider')}"
        assert req.get("caller") == "manual", f"Caller should default to 'manual', got {req.get('caller')}"
        assert req.get("message") == "test message", f"Wrong message: {req.get('message')}"

        # Verify response was received
        assert result is not None, "try_daemon_request should return a result"
        reply, exit_code = result
        assert exit_code == 0, f"Exit code should be 0, got {exit_code}"

    finally:
        # Cleanup
        try:
            shutdown_daemon("ask", timeout_s=0.5, state_file=state_file)
        except Exception:
            pass
        thread.join(timeout=2.0)


def test_ccb_caller_env_takes_precedence_over_default(tmp_path: Path, monkeypatch) -> None:
    """Test that CCB_CALLER env var takes precedence over 'manual' default."""
    # Setup
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("CCB_RUN_DIR", str(tmp_path / "run"))
    monkeypatch.setenv("CCB_ASKD_IDLE_TIMEOUT_S", "0")

    work_dir = tmp_path / "project"
    work_dir.mkdir()
    (work_dir / ".opencode-session").write_text(json.dumps({"active": True}))
    monkeypatch.chdir(work_dir)

    received_requests = []

    def mock_handler(msg: dict) -> dict:
        received_requests.append(msg)
        return {"type": "ask.response", "v": 1, "id": msg.get("id"), "exit_code": 0, "reply": "OK"}

    state_file = tmp_path / "run" / "askd.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)

    server = AskDaemonServer(
        spec=ASKD_SPEC,
        host="127.0.0.1",
        port=0,
        token="test-token",
        state_file=state_file,
        request_handler=mock_handler,
        work_dir=str(work_dir),
    )

    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        _wait_for_state(state_file, timeout_s=3.0)

        # Set CCB_CALLER to test priority
        monkeypatch.setenv("CCB_CALLER", "codex")

        try_daemon_request(
            OASK_CLIENT_SPEC,
            work_dir,
            "test",
            timeout=2.0,
            quiet=True,
        )

        assert len(received_requests) == 1
        req = received_requests[0]
        assert req.get("caller") == "codex", f"CCB_CALLER should take precedence, got {req.get('caller')}"

    finally:
        try:
            shutdown_daemon("ask", timeout_s=0.5, state_file=state_file)
        except Exception:
            pass
        thread.join(timeout=2.0)


def test_askd_json_preferred_over_oaskd_json(tmp_path: Path, monkeypatch) -> None:
    """Test that askd.json is preferred when both askd.json and oaskd.json exist."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    work_dir = tmp_path / "project"
    work_dir.mkdir()
    (work_dir / ".opencode-session").write_text(json.dumps({"active": True}))

    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("CCB_RUN_DIR", str(run_dir))
    monkeypatch.setenv("CCB_ASKD_IDLE_TIMEOUT_S", "0")
    monkeypatch.chdir(work_dir)

    received_requests = []

    def mock_handler(msg: dict) -> dict:
        received_requests.append(msg)
        return {"type": "ask.response", "v": 1, "id": msg.get("id"), "exit_code": 0, "reply": "OK"}

    state_file = tmp_path / "run" / "askd.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)

    # Start daemon first
    server = AskDaemonServer(
        spec=ASKD_SPEC,
        host="127.0.0.1",
        port=0,
        token="test-token",
        state_file=state_file,
        request_handler=mock_handler,
        work_dir=str(work_dir),
    )

    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        _wait_for_state(state_file, timeout_s=3.0)

        # Now create oaskd.json with DIFFERENT token (simulating old state)
        (run_dir / "oaskd.json").write_text(json.dumps({
            "host": "127.0.0.1",
            "port": 99999,  # Wrong port
            "token": "wrong-token",
        }))

        # Send request - should use askd.json (correct daemon), not oaskd.json
        result = try_daemon_request(
            OASK_CLIENT_SPEC,
            work_dir,
            "test",
            timeout=2.0,
            quiet=True,
        )

        # Verify request was received by the real daemon (using askd.json)
        assert len(received_requests) == 1, "Should connect via askd.json, not oaskd.json"
        assert result is not None, "Should get response"

    finally:
        try:
            shutdown_daemon("ask", timeout_s=0.5, state_file=state_file)
        except Exception:
            pass
        thread.join(timeout=2.0)


def test_oaskd_json_fallback_only_for_opencode(tmp_path: Path, monkeypatch) -> None:
    """Test that oaskd.json fallback only applies to OpenCode, not other providers."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    # Create oaskd.json and caskd.json
    (run_dir / "oaskd.json").write_text(json.dumps({
        "host": "127.0.0.1",
        "port": 11111,
        "token": "oaskd-token",
    }))
    (run_dir / "caskd.json").write_text(json.dumps({
        "host": "127.0.0.1",
        "port": 22222,
        "token": "caskd-token",
    }))

    work_dir = tmp_path / "project"
    work_dir.mkdir()
    (work_dir / ".codex-session").write_text(json.dumps({"active": True}))

    monkeypatch.setenv("CCB_RUN_DIR", str(run_dir))
    monkeypatch.chdir(work_dir)

    # Track which state files were read
    read_files = []

    import askd.daemon as daemon_module
    original_read_state = daemon_module.read_state

    def track_read_state(state_file):
        name = state_file.name if isinstance(state_file, Path) else str(state_file)
        read_files.append(name)
        return None  # Simulate no connection

    daemon_module.read_state = track_read_state

    try:
        try_daemon_request(
            CASK_CLIENT_SPEC,
            work_dir,
            "test",
            timeout=0.5,
            quiet=True,
        )

        # Codex should only try caskd.json, never oaskd.json
        assert "caskd.json" in read_files, "Should try caskd.json"
        assert "oaskd.json" not in read_files, "Should NOT try oaskd.json for non-OpenCode providers"

    finally:
        daemon_module.read_state = original_read_state


def test_legacy_oaskd_json_fallback(tmp_path: Path, monkeypatch) -> None:
    """Test fallback to oaskd.json when askd.json doesn't exist (OpenCode only)."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    # Only create oaskd.json (no askd.json)
    legacy_state = run_dir / "oaskd.json"
    legacy_state.write_text(json.dumps({
        "host": "127.0.0.1",
        "port": 33333,
        "token": "legacy-token",
    }))

    work_dir = tmp_path / "project"
    work_dir.mkdir()
    (work_dir / ".opencode-session").write_text(json.dumps({"active": True}))

    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("CCB_RUN_DIR", str(run_dir))
    monkeypatch.setenv("CCB_ASKD_IDLE_TIMEOUT_S", "0")
    monkeypatch.chdir(work_dir)

    # Start a daemon on the port specified in oaskd.json to verify fallback works
    received_requests = []

    def mock_handler(msg: dict) -> dict:
        received_requests.append(msg)
        return {"type": "ask.response", "v": 1, "id": msg.get("id"), "exit_code": 0, "reply": "OK"}

    # Create a state file for our test daemon
    state_file = tmp_path / "run" / "test-daemon.json"

    server = AskDaemonServer(
        spec=ASKD_SPEC,
        host="127.0.0.1",
        port=33333,  # Match the port in oaskd.json
        token="legacy-token",  # Match the token in oaskd.json
        state_file=state_file,
        request_handler=mock_handler,
        work_dir=str(work_dir),
    )

    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        _wait_for_state(state_file, timeout_s=3.0)

        # Send request - should fallback to oaskd.json and connect to our daemon
        result = try_daemon_request(
            OASK_CLIENT_SPEC,
            work_dir,
            "test",
            timeout=2.0,
            quiet=True,
        )

        # Verify fallback worked by checking request was received
        assert len(received_requests) == 1, "Should fallback to oaskd.json and connect"
        assert result is not None, "Should get response via oaskd.json fallback"

    finally:
        try:
            shutdown_daemon("ask", timeout_s=0.5, state_file=state_file)
        except Exception:
            pass
        thread.join(timeout=2.0)
