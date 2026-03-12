"""
Cursor provider adapter for the unified ask daemon.

Direct cursor-agent CLI communication without tmux pane/session machinery.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

from askd.adapters.base import BaseProviderAdapter, ProviderRequest, ProviderResult, QueuedTask
from askd_runtime import log_path, write_log
from completion_hook import (
    COMPLETION_STATUS_CANCELLED,
    COMPLETION_STATUS_COMPLETED,
    COMPLETION_STATUS_FAILED,
    COMPLETION_STATUS_INCOMPLETE,
)
from cursor_comm import CursorCommunicator
from providers import CURSOR_SPEC
from session_utils import find_project_session_file


def _now_ms() -> int:
    return int(time.time() * 1000)


def _write_log(line: str) -> None:
    write_log(log_path(CURSOR_SPEC.log_file_name), line)


class CursorAdapter(BaseProviderAdapter):
    """Adapter for Cursor provider."""

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
        """Load Cursor session from .cursor-session file."""
        session_file = find_project_session_file(work_dir, self.session_filename)
        if not session_file:
            return None

        try:
            with session_file.open("r", encoding="utf-8-sig") as f:
                data = json.load(f)
            # Return the session dict; we'll extract work_dir for session_key
            return data
        except (json.JSONDecodeError, IOError):
            return None

    def compute_session_key(self, session: Any, instance: Optional[str] = None, work_dir: Optional[Path] = None) -> str:
        """Compute session key from loaded session, work_dir, or current cwd."""
        if work_dir is None:
            work_dir = Path.cwd()
        if session and isinstance(session, dict):
            work_dir = Path(session.get("work_dir") or str(work_dir))
        return f"cursor:{work_dir}"

    def on_start(self) -> None:
        _write_log("[INFO] cursor adapter started")

    def on_stop(self) -> None:
        _write_log("[INFO] cursor adapter stopped")

    def handle_task(self, task: QueuedTask) -> ProviderResult:
        started_ms = _now_ms()
        req = task.request
        work_dir = Path(req.work_dir)
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

        communicator = CursorCommunicator(work_dir=work_dir)
        
        timeout_s = max(30.0, req.timeout_s) if req.timeout_s > 0 else 120.0
        
        try:
            success, reply, metadata = communicator.send(
                prompt=req.message,
                timeout_s=timeout_s,
            )
            
            if success:
                duration_ms = metadata.get("duration_ms") if metadata else None
                return ProviderResult(
                    exit_code=0,
                    reply=reply,
                    req_id=task.req_id,
                    session_key=self.compute_session_key(None, work_dir=work_dir),
                    done_seen=True,
                    done_ms=_now_ms() - started_ms if duration_ms is None else duration_ms,
                    status=COMPLETION_STATUS_COMPLETED,
                    extra=metadata,
                )
            else:
                return ProviderResult(
                    exit_code=1,
                    reply=reply,
                    req_id=task.req_id,
                    session_key=self.compute_session_key(None, work_dir=work_dir),
                    done_seen=False,
                    status=COMPLETION_STATUS_FAILED,
                )
                
        except Exception as e:
            _write_log(f"[ERROR] provider=cursor req_id={task.req_id} {e}")
            return ProviderResult(
                exit_code=1,
                reply=f"Cursor error: {e}",
                req_id=task.req_id,
                session_key=self.compute_session_key(None, work_dir=work_dir),
                done_seen=False,
                status=COMPLETION_STATUS_FAILED,
            )

    def handle_exception(self, exc: Exception, task: QueuedTask) -> ProviderResult:
        _write_log(f"[ERROR] provider=cursor req_id={task.req_id} exception={exc}")
        return ProviderResult(
            exit_code=1,
            reply=f"Cursor exception: {exc}",
            req_id=task.req_id,
            session_key=self.compute_session_key(None, work_dir=work_dir),
            done_seen=False,
            status=COMPLETION_STATUS_FAILED,
        )
