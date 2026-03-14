"""
Cursor provider adapter for the unified ask daemon.

Pane-based communication using respawn_pane + --resume pattern (like Copilot).
"""
from __future__ import annotations

import os
import shlex
import time
from pathlib import Path
from typing import Any, Optional

from askd.adapters.base import BaseProviderAdapter, ProviderRequest, ProviderResult, QueuedTask
from askd_runtime import log_path, write_log
from ccb_protocol import REQ_ID_PREFIX
from completion_hook import (
    COMPLETION_STATUS_CANCELLED,
    COMPLETION_STATUS_COMPLETED,
    COMPLETION_STATUS_FAILED,
    COMPLETION_STATUS_INCOMPLETE,
    default_reply_for_status,
    notify_completion,
)
from cursor_comm import CursorLogReader, _CURSOR_FOLLOW_UP_RE
from providers import CURSOR_SPEC
from terminal import get_backend_for_session
from uaskd_protocol import extract_reply_for_req, is_done_text, wrap_cursor_prompt
from uaskd_session import compute_session_key, load_project_session


def _now_ms() -> int:
    return int(time.time() * 1000)


def _write_log(line: str) -> None:
    write_log(log_path(CURSOR_SPEC.log_file_name), line)


def _tail_state_for_log(log_path_val: Optional[Path], *, tail_bytes: int) -> dict:
    if not log_path_val or not log_path_val.exists():
        return {"pane_log_path": log_path_val, "offset": 0}
    try:
        size = log_path_val.stat().st_size
    except OSError:
        size = 0
    offset = max(0, size - max(0, int(tail_bytes)))
    return {"pane_log_path": log_path_val, "offset": offset}


def _latest_cursor_chat_id(work_dir: Path) -> str:
    """Find the latest cursor chat session for the given work_dir."""
    chats_root = Path.home() / ".cursor" / "chats"
    if not chats_root.is_dir():
        return ""

    target = str(work_dir)
    try:
        target = str(work_dir.resolve())
    except Exception:
        pass

    best_chat_id = ""
    best_mtime = -1.0

    # Each subdirectory is a workspace hash, each sub-subdirectory is a chat session
    for workspace_dir in chats_root.iterdir():
        if not workspace_dir.is_dir():
            continue
        for session_dir in workspace_dir.iterdir():
            if not session_dir.is_dir():
                continue
            store_db = session_dir / "store.db"
            if not store_db.exists():
                continue
            try:
                mtime = store_db.stat().st_mtime
            except OSError:
                continue
            if mtime > best_mtime:
                best_mtime = mtime
                best_chat_id = session_dir.name

    return best_chat_id


def _build_cursor_resume_cmd(session: Any, chat_id: str, prompt: str) -> str:
    """Build cursor-agent command with --resume."""
    base = str(session.start_cmd or "").strip()
    if not base:
        base = (os.environ.get("CURSOR_START_CMD") or "cursor-agent").strip() or "cursor-agent"
    # cursor-agent accepts prompt as positional argument
    return f"{base} --resume={shlex.quote(chat_id)} {shlex.quote(prompt)}"


class CursorAdapter(BaseProviderAdapter):
    """Adapter for Cursor provider using pane-based communication."""

    @property
    def key(self) -> str:
        return "cursor"

    @property
    def spec(self):
        return CURSOR_SPEC

    @property
    def session_filename(self) -> str:
        return ".cursor-session"

    def load_session(self, work_dir: Path, instance: Optional[str] = None) -> Optional[Any]:
        return load_project_session(work_dir, instance)

    def compute_session_key(self, session: Any, instance: Optional[str] = None, work_dir: Optional[Path] = None) -> str:
        if session:
            return compute_session_key(session, instance)
        if work_dir is None:
            work_dir = Path.cwd()
        return f"cursor:{work_dir}"

    def on_start(self) -> None:
        _write_log("[INFO] cursor adapter started")

    def on_stop(self) -> None:
        _write_log("[INFO] cursor adapter stopped")

    def handle_task(self, task: QueuedTask) -> ProviderResult:
        started_ms = _now_ms()
        req = task.request
        work_dir = Path(req.work_dir)
        instance = req.instance
        _write_log(f"[INFO] start provider=cursor req_id={task.req_id} work_dir={req.work_dir}")

        if task.cancelled:
            return ProviderResult(
                exit_code=1,
                reply="Task cancelled",
                req_id=task.req_id,
                session_key=self.compute_session_key(None, work_dir=work_dir),
                done_seen=False,
                status=COMPLETION_STATUS_CANCELLED,
            )

        # Load session for pane-based communication
        session = load_project_session(work_dir, instance)
        session_key = self.compute_session_key(session, instance, work_dir)

        if not session:
            _write_log(f"[WARN] provider=cursor req_id={task.req_id} no session, cannot use pane mode")
            return ProviderResult(
                exit_code=1,
                reply="No active Cursor session found. Start with 'ccb cursor' first.",
                req_id=task.req_id,
                session_key=session_key,
                done_seen=False,
                status=COMPLETION_STATUS_FAILED,
            )

        # Ensure pane is available
        ok, pane_or_err = session.ensure_pane()
        if not ok:
            _write_log(f"[WARN] provider=cursor req_id={task.req_id} pane not available: {pane_or_err}")
            return ProviderResult(
                exit_code=1,
                reply=f"Session pane not available: {pane_or_err}",
                req_id=task.req_id,
                session_key=session_key,
                done_seen=False,
                status=COMPLETION_STATUS_FAILED,
            )

        pane_id = pane_or_err
        backend = get_backend_for_session(session.data)
        if not backend:
            _write_log(f"[WARN] provider=cursor req_id={task.req_id} backend not available")
            return ProviderResult(
                exit_code=1,
                reply="Terminal backend not available",
                req_id=task.req_id,
                session_key=session_key,
                done_seen=False,
                status=COMPLETION_STATUS_FAILED,
            )

        # Get pane log path from backend
        pane_log_path: Optional[Path] = None
        get_pane_log_path = getattr(backend, "pane_log_path", None)
        if callable(get_pane_log_path):
            pane_log_path = get_pane_log_path(pane_id)
        if not pane_log_path:
            raw_log = session.data.get("pane_log_path")
            if raw_log:
                pane_log_path = Path(str(raw_log)).expanduser()
            elif session.runtime_dir:
                pane_log_path = session.runtime_dir / "pane.log"

        # Wrap prompt with CCB protocol markers
        prompt = wrap_cursor_prompt(req.message, task.req_id)
        log_reader = CursorLogReader(work_dir=Path(session.work_dir), pane_log_path=pane_log_path)

        # Get chat ID for --resume
        chat_id = _latest_cursor_chat_id(Path(session.work_dir))
        used_resume_launch = False

        if chat_id and hasattr(backend, "respawn_pane"):
            try:
                launch_cmd = _build_cursor_resume_cmd(session, chat_id, prompt)
                backend.respawn_pane(pane_id, cmd=launch_cmd, cwd=session.work_dir, remain_on_exit=True)
                used_resume_launch = True
                _write_log(f"[INFO] provider=cursor req_id={task.req_id} launched via --resume chat_id={chat_id}")
                # Ensure pane log is set up
                ensure = getattr(backend, "ensure_pane_log", None)
                if callable(ensure):
                    try:
                        ensure(pane_id)
                    except Exception:
                        pass
            except Exception as exc:
                _write_log(f"[WARN] provider=cursor req_id={task.req_id} --resume launch failed: {exc}")

        if not used_resume_launch:
            _write_log(f"[WARN] provider=cursor req_id={task.req_id} cannot launch without respawn_pane")
            return ProviderResult(
                exit_code=1,
                reply="respawn_pane not available for cursor",
                req_id=task.req_id,
                session_key=session_key,
                done_seen=False,
                status=COMPLETION_STATUS_FAILED,
            )

        # Capture current state before waiting
        state = log_reader.capture_state()

        deadline = None if float(req.timeout_s) < 0.0 else (time.time() + float(req.timeout_s))
        chunks: list[str] = []
        anchor_seen = False
        fallback_scan = False
        anchor_ms: Optional[int] = None
        done_seen = False
        done_ms: Optional[int] = None
        cursor_follow_up_seen = False

        anchor_grace_deadline = min(deadline, time.time() + 1.5) if deadline else (time.time() + 1.5)
        anchor_collect_grace = min(deadline, time.time() + 2.0) if deadline else (time.time() + 2.0)
        rebounded = False
        tail_bytes = int(os.environ.get("CCB_UASKD_REBIND_TAIL_BYTES", str(2 * 1024 * 1024)))
        pane_check_interval = float(os.environ.get("CCB_UASKD_PANE_CHECK_INTERVAL", "2.0"))
        last_pane_check = time.time()

        while True:
            # Check for cancellation
            if task.cancel_event and task.cancel_event.is_set():
                _write_log(f"[INFO] Task cancelled during wait loop: req_id={task.req_id}")
                break

            if deadline is not None:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                wait_step = min(remaining, 0.5)
            else:
                wait_step = 0.5

            # Periodically check pane health
            if time.time() - last_pane_check >= pane_check_interval:
                try:
                    alive = bool(backend.is_alive(pane_id))
                except Exception:
                    alive = False
                if not alive:
                    _write_log(f"[ERROR] Pane {pane_id} died during request req_id={task.req_id}")
                    return ProviderResult(
                        exit_code=1,
                        reply="Cursor pane died during request",
                        req_id=task.req_id,
                        session_key=session_key,
                        done_seen=False,
                        status=COMPLETION_STATUS_FAILED,
                    )
                last_pane_check = time.time()

            # Wait for events from pane log
            events, state = log_reader.wait_for_events(state, wait_step)
            if not events:
                if (not rebounded) and (not anchor_seen) and time.time() >= anchor_grace_deadline:
                    log_reader = CursorLogReader(work_dir=Path(session.work_dir), pane_log_path=pane_log_path)
                    state = _tail_state_for_log(pane_log_path, tail_bytes=tail_bytes)
                    fallback_scan = True
                    rebounded = True
                continue

            for role, text in events:
                if role == "user":
                    if f"{REQ_ID_PREFIX} {task.req_id}" in text:
                        anchor_seen = True
                        if anchor_ms is None:
                            anchor_ms = _now_ms() - started_ms
                    continue
                if role != "assistant":
                    continue
                if (not anchor_seen) and time.time() < anchor_collect_grace:
                    continue
                chunks.append(text)
                combined = "\n".join(chunks)

                # Check for CCB_DONE marker
                if is_done_text(combined, task.req_id):
                    done_seen = True
                    done_ms = _now_ms() - started_ms
                    break

                # Check for Cursor's "Add a follow-up" completion signal
                if _CURSOR_FOLLOW_UP_RE.search(text):
                    cursor_follow_up_seen = True
                    done_seen = True  # Treat as completion
                    done_ms = _now_ms() - started_ms
                    _write_log(f"[INFO] provider=cursor req_id={task.req_id} detected follow-up prompt, treating as done")
                    # Send Ctrl+C to exit cursor-agent's waiting state
                    try:
                        backend.send_text(pane_id, "\x03")  # Ctrl+C
                    except Exception:
                        pass
                    break

            if done_seen:
                break

        combined = "\n".join(chunks)
        final_reply = extract_reply_for_req(combined, task.req_id)
        status = COMPLETION_STATUS_COMPLETED if done_seen else COMPLETION_STATUS_INCOMPLETE
        if task.cancelled:
            status = COMPLETION_STATUS_CANCELLED

        reply_for_hook = final_reply
        if not reply_for_hook.strip():
            reply_for_hook = default_reply_for_status(status, done_seen=done_seen)
        notify_completion(
            provider="cursor",
            output_file=req.output_path,
            reply=reply_for_hook,
            req_id=task.req_id,
            done_seen=done_seen,
            status=status,
            caller=req.caller,
            email_req_id=req.email_req_id,
            email_msg_id=req.email_msg_id,
            email_from=req.email_from,
            work_dir=req.work_dir,
        )

        result = ProviderResult(
            exit_code=0 if done_seen else 2,
            reply=final_reply,
            req_id=task.req_id,
            session_key=session_key,
            done_seen=done_seen,
            done_ms=done_ms,
            anchor_seen=anchor_seen,
            anchor_ms=anchor_ms,
            fallback_scan=fallback_scan,
            status=status,
        )
        _write_log(f"[INFO] done provider=cursor req_id={task.req_id} exit={result.exit_code}")
        return result

    def handle_exception(self, exc: Exception, task: QueuedTask) -> ProviderResult:
        _write_log(f"[ERROR] provider=cursor req_id={task.req_id} exception={exc}")
        work_dir = Path(task.request.work_dir)
        return ProviderResult(
            exit_code=1,
            reply=f"Cursor exception: {exc}",
            req_id=task.req_id,
            session_key=self.compute_session_key(None, work_dir=work_dir),
            done_seen=False,
            status=COMPLETION_STATUS_FAILED,
        )
