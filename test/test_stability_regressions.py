from __future__ import annotations

import importlib.util
import json
import threading
from importlib.machinery import SourceFileLoader
from pathlib import Path

import askd.daemon as askd_daemon
import askd_runtime
from askd.adapters.base import ProviderRequest, QueuedTask
from askd.adapters.claude import ClaudeAdapter
from askd.adapters.gemini import GeminiAdapter
from codex_comm import CodexLogReader
from completion_hook import completion_status_marker


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_script_module(name: str, path: Path):
    loader = SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_completion_hook_uses_status_marker_and_directional_workdir_matching() -> None:
    hook = _load_script_module("ccb_completion_hook_script", REPO_ROOT / "bin" / "ccb-completion-hook")

    message = hook._render_terminal_message(
        "Codex",
        "req-1",
        "cancelled",
        output_file="",
        status="cancelled",
    )

    assert completion_status_marker("cancelled") in message
    assert hook._work_dirs_compatible("/repo", "/repo/subdir") is True
    assert hook._work_dirs_compatible("/repo/subdir", "/repo") is False


def test_completion_hook_manual_caller_is_noop(monkeypatch) -> None:
    hook = _load_script_module("ccb_completion_hook_manual", REPO_ROOT / "bin" / "ccb-completion-hook")
    monkeypatch.setenv("CCB_CALLER", "manual")
    monkeypatch.setenv("CCB_COMPLETION_STATUS", "cancelled")
    monkeypatch.setattr("sys.argv", ["ccb-completion-hook", "--provider", "codex", "--req-id", "req-1"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    assert hook.main() == 0


def test_maybe_start_unified_daemon_honors_autostart_opt_out(monkeypatch, tmp_path: Path) -> None:
    ask = _load_script_module("ask_script_opt_out", REPO_ROOT / "bin" / "ask")
    popen_calls: list[dict] = []

    monkeypatch.setenv("CCB_ASKD_AUTOSTART", "0")
    monkeypatch.setattr(askd_runtime, "state_file_path", lambda name: tmp_path / name)
    monkeypatch.setattr(askd_daemon, "ping_daemon", lambda **kwargs: False)
    monkeypatch.setattr(ask.subprocess, "Popen", lambda *args, **kwargs: popen_calls.append(kwargs))

    assert ask._maybe_start_unified_daemon() is False
    assert popen_calls == []


def test_maybe_start_unified_daemon_scrubs_parent_env(monkeypatch, tmp_path: Path) -> None:
    ask = _load_script_module("ask_script_scrub", REPO_ROOT / "bin" / "ask")
    captured: dict[str, object] = {}
    ping_results = iter([False, True])

    class _DummyProcess:
        pass

    def _fake_popen(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _DummyProcess()

    monkeypatch.delenv("CCB_ASKD_AUTOSTART", raising=False)
    monkeypatch.setenv("CCB_PARENT_PID", "12345")
    monkeypatch.setenv("CCB_MANAGED", "1")
    monkeypatch.setattr(askd_runtime, "state_file_path", lambda name: tmp_path / name)
    monkeypatch.setattr(askd_daemon, "ping_daemon", lambda **kwargs: next(ping_results))
    monkeypatch.setattr(ask.subprocess, "Popen", _fake_popen)

    assert ask._maybe_start_unified_daemon() is True
    child_env = captured["kwargs"]["env"]
    assert "CCB_PARENT_PID" not in child_env
    assert "CCB_MANAGED" not in child_env


def test_codex_log_reader_keeps_bound_session(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    work_dir = tmp_path / "repo"
    work_dir.mkdir()
    preferred = root / "2026" / "abc-session.jsonl"
    newer = root / "2026" / "other-session.jsonl"
    preferred.parent.mkdir(parents=True)

    meta = json.dumps({"type": "session_meta", "payload": {"cwd": str(work_dir)}}) + "\n"
    preferred.write_text(meta, encoding="utf-8")
    newer.write_text(meta, encoding="utf-8")
    newer.touch()

    reader = CodexLogReader(
        root=root,
        log_path=preferred,
        session_id_filter="abc",
        work_dir=work_dir,
    )

    assert reader.current_log_path() == preferred


def test_gemini_adapter_reports_cancelled_status(monkeypatch, tmp_path: Path) -> None:
    from askd.adapters import gemini as gemini_mod

    notifications: list[dict] = []

    class _Session:
        work_dir = str(tmp_path)
        gemini_session_path = None
        data = {}

        def ensure_pane(self):
            return True, "pane-1"

    class _Backend:
        def send_text(self, pane_id: str, prompt: str) -> None:
            return None

        def is_alive(self, pane_id: str) -> bool:
            return True

    class _Reader:
        def __init__(self, work_dir: Path):
            self.session_path = tmp_path / "session.json"

        def set_preferred_session(self, path: Path) -> None:
            return None

        def capture_state(self) -> dict:
            return {"msg_count": 0, "session_path": self.session_path}

        def wait_for_message(self, state: dict, timeout: float):
            return "", {"msg_count": 1, "session_path": self.session_path}

    monkeypatch.setattr(gemini_mod, "load_project_session", lambda work_dir, instance=None: _Session())
    monkeypatch.setattr(gemini_mod, "get_backend_for_session", lambda data: _Backend())
    monkeypatch.setattr(gemini_mod, "GeminiLogReader", _Reader)
    monkeypatch.setattr(gemini_mod, "_detect_request_cancelled", lambda *args, **kwargs: True)
    monkeypatch.setattr(gemini_mod, "notify_completion", lambda **kwargs: notifications.append(kwargs))
    monkeypatch.setattr(gemini_mod, "_write_log", lambda line: None)

    req = ProviderRequest(
        client_id="c1",
        work_dir=str(tmp_path),
        timeout_s=5.0,
        quiet=False,
        message="hello",
        caller="claude",
    )
    task = QueuedTask(
        request=req,
        created_ms=0,
        req_id="req-1",
        done_event=threading.Event(),
        cancel_event=threading.Event(),
    )

    result = GeminiAdapter().handle_task(task)

    assert result.status == "cancelled"
    assert notifications[0]["status"] == "cancelled"


def test_claude_adapter_honors_cancel_event(monkeypatch, tmp_path: Path) -> None:
    from askd.adapters import claude as claude_mod

    notifications: list[dict] = []

    class _Session:
        work_dir = str(tmp_path)
        claude_session_path = None
        data = {}

        def ensure_pane(self):
            return True, "pane-1"

    class _Backend:
        def send_text(self, pane_id: str, prompt: str) -> None:
            return None

        def is_alive(self, pane_id: str) -> bool:
            return True

    class _Reader:
        def __init__(self, work_dir: Path, use_sessions_index: bool = True):
            self.work_dir = work_dir

        def set_preferred_session(self, path: Path) -> None:
            return None

        def capture_state(self) -> dict:
            return {}

        def wait_for_events(self, state: dict, timeout: float):
            return [], state

    monkeypatch.setattr(claude_mod, "load_project_session", lambda work_dir, instance=None: _Session())
    monkeypatch.setattr(claude_mod, "get_backend_for_session", lambda data: _Backend())
    monkeypatch.setattr(claude_mod, "ClaudeLogReader", _Reader)
    monkeypatch.setattr(claude_mod, "notify_completion", lambda **kwargs: notifications.append(kwargs))
    monkeypatch.setattr(claude_mod, "_write_log", lambda line: None)

    req = ProviderRequest(
        client_id="c1",
        work_dir=str(tmp_path),
        timeout_s=5.0,
        quiet=False,
        message="hello",
        caller="claude",
    )
    cancel_event = threading.Event()
    cancel_event.set()
    task = QueuedTask(
        request=req,
        created_ms=0,
        req_id="req-1",
        done_event=threading.Event(),
        cancelled=True,
        cancel_event=cancel_event,
    )

    result = ClaudeAdapter().handle_task(task)

    assert result.status == "cancelled"
    assert notifications[0]["status"] == "cancelled"


def test_claude_adapter_recovers_after_dead_pane(monkeypatch, tmp_path: Path) -> None:
    from askd.adapters import claude as claude_mod

    notifications: list[dict] = []
    sent_prompts: list[tuple[str, str]] = []

    class _Session:
        work_dir = str(tmp_path)
        claude_session_path = None

        def __init__(self, pane_id: str):
            self._pane_id = pane_id
            self.data = {"pane_id": pane_id, "terminal": "tmux"}

        def ensure_pane(self):
            return True, self._pane_id

    class _Backend:
        def __init__(self, alive_map: dict[str, bool]):
            self.alive_map = alive_map

        def send_text(self, pane_id: str, prompt: str) -> None:
            sent_prompts.append((pane_id, prompt))

        def is_alive(self, pane_id: str) -> bool:
            return self.alive_map.get(pane_id, False)

    class _Reader:
        def __init__(self, work_dir: Path, use_sessions_index: bool = True):
            self._emitted = False

        def set_preferred_session(self, path: Path) -> None:
            return None

        def capture_state(self) -> dict:
            return {}

        def wait_for_events(self, state: dict, timeout: float):
            if not sent_prompts or sent_prompts[-1][0] != "pane-new" or self._emitted:
                return [], state
            self._emitted = True
            return [("user", "CCB_REQ_ID: req-1"), ("assistant", "done")], state

    sessions = iter([_Session("pane-old"), _Session("pane-new")])
    backend = _Backend({"pane-old": False, "pane-new": True})

    monkeypatch.setenv("CCB_LASKD_PANE_CHECK_INTERVAL", "0")
    monkeypatch.setattr(claude_mod, "load_project_session", lambda work_dir, instance=None: next(sessions))
    monkeypatch.setattr(claude_mod, "get_backend_for_session", lambda data: backend)
    monkeypatch.setattr(claude_mod, "ClaudeLogReader", _Reader)
    monkeypatch.setattr(claude_mod, "is_done_text", lambda combined, req_id: "done" in combined)
    monkeypatch.setattr(claude_mod, "extract_reply_for_req", lambda combined, req_id: combined)
    monkeypatch.setattr(claude_mod, "notify_completion", lambda **kwargs: notifications.append(kwargs))
    monkeypatch.setattr(claude_mod, "_write_log", lambda line: None)

    req = ProviderRequest(
        client_id="c1",
        work_dir=str(tmp_path),
        timeout_s=1.0,
        quiet=False,
        message="hello",
        caller="codex",
    )
    task = QueuedTask(
        request=req,
        created_ms=0,
        req_id="req-1",
        done_event=threading.Event(),
        cancel_event=threading.Event(),
    )

    result = ClaudeAdapter().handle_task(task)

    assert result.status == "completed"
    assert [pane for pane, _prompt in sent_prompts] == ["pane-old", "pane-new"]
    assert notifications[0]["status"] == "completed"


def test_opencode_adapter_recovers_after_dead_pane(monkeypatch, tmp_path: Path) -> None:
    from askd.adapters import opencode as opencode_mod

    notifications: list[dict] = []
    sent_prompts: list[tuple[str, str]] = []

    class _Session:
        work_dir = str(tmp_path)
        opencode_session_id_filter = None

        def __init__(self, pane_id: str):
            self._pane_id = pane_id
            self.data = {"pane_id": pane_id, "terminal": "tmux"}

        def ensure_pane(self):
            return True, self._pane_id

        def update_opencode_binding(self, *, session_id=None, project_id=None) -> None:
            return None

    class _Backend:
        def __init__(self, alive_map: dict[str, bool]):
            self.alive_map = alive_map

        def send_text(self, pane_id: str, prompt: str) -> None:
            sent_prompts.append((pane_id, prompt))

        def is_alive(self, pane_id: str) -> bool:
            return self.alive_map.get(pane_id, False)

    class _Reader:
        def __init__(self, work_dir: Path, project_id: str = "global", session_id_filter=None):
            self._emitted = False
            self.project_id = project_id

        def capture_state(self) -> dict:
            return {}

        def wait_for_message(self, state: dict, timeout: float):
            if not sent_prompts or sent_prompts[-1][0] != "pane-new" or self._emitted:
                return "", state
            self._emitted = True
            return "done", state

    sessions = iter([_Session("pane-old"), _Session("pane-new")])
    backend = _Backend({"pane-old": False, "pane-new": True})

    monkeypatch.setenv("CCB_OASKD_PANE_CHECK_INTERVAL", "0")
    monkeypatch.setattr(opencode_mod, "load_project_session", lambda work_dir, instance=None: next(sessions))
    monkeypatch.setattr(opencode_mod, "get_backend_for_session", lambda data: backend)
    monkeypatch.setattr(opencode_mod, "OpenCodeLogReader", _Reader)
    monkeypatch.setattr(opencode_mod, "is_done_text", lambda combined, req_id: "done" in combined)
    monkeypatch.setattr(opencode_mod, "strip_done_text", lambda combined, req_id: combined)
    monkeypatch.setattr(opencode_mod, "notify_completion", lambda **kwargs: notifications.append(kwargs))
    monkeypatch.setattr(opencode_mod, "_write_log", lambda line: None)

    req = ProviderRequest(
        client_id="c1",
        work_dir=str(tmp_path),
        timeout_s=1.0,
        quiet=False,
        message="hello",
        caller="codex",
    )
    task = QueuedTask(
        request=req,
        created_ms=0,
        req_id="req-1",
        done_event=threading.Event(),
        cancel_event=threading.Event(),
    )

    result = opencode_mod.OpenCodeAdapter().handle_task(task)

    assert result.status == "completed"
    assert [pane for pane, _prompt in sent_prompts] == ["pane-old", "pane-new"]
    assert notifications[0]["status"] == "completed"


def test_codex_adapter_recovers_after_missing_anchor(monkeypatch, tmp_path: Path) -> None:
    from askd.adapters import codex as codex_mod

    notifications: list[dict] = []
    sent_prompts: list[tuple[str, str]] = []
    log_path = tmp_path / "codex-session.jsonl"

    class _Session:
        work_dir = str(tmp_path)

        def __init__(self, pane_id: str, log_hint: Path | None = None):
            self._pane_id = pane_id
            self._log_hint = str(log_hint) if log_hint else ""
            self._session_id = "sid-new" if log_hint else "sid-old"
            self.data = {"pane_id": pane_id, "terminal": "tmux"}

        @property
        def codex_session_path(self) -> str:
            return self._log_hint

        @property
        def codex_session_id(self) -> str:
            return self._session_id

        def ensure_pane(self):
            return True, self._pane_id

        def update_codex_log_binding(self, *, log_path=None, session_id=None) -> None:
            if log_path:
                self._log_hint = str(log_path)
            if session_id:
                self._session_id = str(session_id)

    class _Backend:
        def send_text(self, pane_id: str, prompt: str) -> None:
            sent_prompts.append((pane_id, prompt))

        def is_alive(self, pane_id: str) -> bool:
            return True

    class _Reader:
        def __init__(self, log_path=None, session_id_filter=None, work_dir=None):
            self._log_path = Path(log_path) if log_path else None
            self._event_emitted = False

        def capture_state(self) -> dict:
            return {"log_path": self.current_log_path(), "offset": 0}

        def current_log_path(self):
            return self._log_path

        def wait_for_event(self, state: dict, timeout: float):
            if len(sent_prompts) >= 2 and not self._event_emitted:
                self._event_emitted = True
                return ("user", "CCB_REQ_ID: req-1"), state
            if len(sent_prompts) >= 2 and self._event_emitted:
                return ("assistant", "done\nCCB_DONE: req-1"), state
            return None, state

    sessions = iter([_Session("pane-old"), _Session("pane-new", log_path)])

    monkeypatch.setenv("CCB_CASKD_PANE_CHECK_INTERVAL", "0")
    monkeypatch.setenv("CCB_CASKD_ANCHOR_GRACE_SECONDS", "0")
    monkeypatch.setattr(codex_mod, "load_project_session", lambda work_dir, instance=None: next(sessions))
    monkeypatch.setattr(codex_mod, "get_backend_for_session", lambda data: _Backend())
    monkeypatch.setattr(codex_mod, "CodexLogReader", _Reader)
    monkeypatch.setattr(codex_mod, "_scan_latest_any_log", lambda work_dir: log_path)
    monkeypatch.setattr(codex_mod.CodexCommunicator, "_extract_session_id", staticmethod(lambda path: "sid-new"))
    monkeypatch.setattr(codex_mod, "notify_completion", lambda **kwargs: notifications.append(kwargs))
    monkeypatch.setattr(codex_mod, "_write_log", lambda line: None)

    req = ProviderRequest(
        client_id="c1",
        work_dir=str(tmp_path),
        timeout_s=1.0,
        quiet=False,
        message="hello",
        caller="claude",
    )
    task = QueuedTask(
        request=req,
        created_ms=0,
        req_id="req-1",
        done_event=threading.Event(),
        cancel_event=threading.Event(),
    )

    result = codex_mod.CodexAdapter().handle_task(task)

    assert result.status == "completed"
    assert result.fallback_scan is True
    assert [pane for pane, _prompt in sent_prompts] == ["pane-old", "pane-new"]
    assert notifications[0]["status"] == "completed"


def test_codex_bridge_uses_declared_tmux_log(monkeypatch, tmp_path: Path) -> None:
    from codex_dual_bridge import DualBridge

    runtime_dir = tmp_path / "runtime"
    log_path = tmp_path / "logs" / "bridge_output.log"

    monkeypatch.setenv("CODEX_TMUX_SESSION", "%1")
    monkeypatch.setenv("CODEX_TERMINAL", "tmux")
    monkeypatch.setenv("CODEX_TMUX_LOG", str(log_path))

    bridge = DualBridge(runtime_dir=runtime_dir, session_id="session-1")

    assert bridge.bridge_log == log_path


def test_ccb_cursor_cleanup_paths_present() -> None:
    content = (REPO_ROOT / "ccb").read_text(encoding="utf-8", errors="ignore")

    assert '".cursor-session"' in content
    assert '"cursor": CURSOR_CLIENT_SPEC' in content
