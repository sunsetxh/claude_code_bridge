"""
Cursor Agent communication module.

Supports two modes:
1. Pane mode: Send via tmux send_text, read replies from pane-log
2. Subprocess mode: Direct cursor-agent CLI call (fallback)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ccb_config import apply_backend_env
from project_id import compute_ccb_project_id
from session_utils import find_project_session_file
from terminal import get_backend_for_session, get_pane_id_from_session

apply_backend_env()


# ---------------------------------------------------------------------------
# ANSI escape stripping
# ---------------------------------------------------------------------------

_ANSI_ESCAPE_RE = re.compile(
    r"""
    \x1b          # ESC
    (?:           # followed by one of …
      \[[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]   # CSI sequence
    | \].*?(?:\x07|\x1b\\)                       # OSC sequence (terminated by BEL or ST)
    | [\x40-\x5f]                                 # Fe sequence (2-byte)
    )
    """,
    re.VERBOSE,
)


def _strip_ansi(text: str) -> str:
    """Remove ANSI/VT escape sequences from raw terminal output."""
    return _ANSI_ESCAPE_RE.sub("", text)


# ---------------------------------------------------------------------------
# CCB marker patterns
# ---------------------------------------------------------------------------

_CCB_REQ_ID_RE = re.compile(r"^\s*CCB_REQ_ID:\s*(\S+)\s*$", re.MULTILINE)
_CCB_DONE_RE = re.compile(
    r"^\s*CCB_DONE:\s*(?:[0-9a-f]{32}|\d{8}-\d{6}-\d{3}-\d+-\d+)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Cursor Agent TUI completion patterns
_CURSOR_FOLLOW_UP_RE = re.compile(r"(?:Add|dd)\s+a\s+follow-up|ctrl\+c\s+to\s+stop", re.IGNORECASE)
_CURSOR_GENERATING_RE = re.compile(r"⬡\s*Generating|Generating\.\.\.", re.IGNORECASE)


# ---------------------------------------------------------------------------
# CursorLogReader — reads from tmux pipe-pane log files
# ---------------------------------------------------------------------------


class CursorLogReader:
    """Reads Cursor replies from tmux pane-log files (raw terminal text)."""

    def __init__(self, work_dir: Optional[Path] = None, pane_log_path: Optional[Path] = None):
        self.work_dir = work_dir or Path.cwd()
        self._pane_log_path: Optional[Path] = pane_log_path
        try:
            poll = float(os.environ.get("CURSOR_POLL_INTERVAL", "0.05"))
        except Exception:
            poll = 0.05
        self._poll_interval = min(0.5, max(0.02, poll))

    def set_pane_log_path(self, path: Optional[Path]) -> None:
        """Override the pane log path (e.g. from session file)."""
        if path:
            try:
                candidate = path if isinstance(path, Path) else Path(str(path)).expanduser()
            except Exception:
                return
            self._pane_log_path = candidate

    def _resolve_log_path(self) -> Optional[Path]:
        """Return the pane log path, or None if unavailable."""
        if self._pane_log_path and self._pane_log_path.exists():
            return self._pane_log_path
        return None

    # ---- public interface identical to CopilotLogReader ----

    def capture_state(self) -> Dict[str, Any]:
        log_path = self._resolve_log_path()
        offset = 0
        if log_path and log_path.exists():
            try:
                offset = log_path.stat().st_size
            except OSError:
                offset = 0
        return {"pane_log_path": log_path, "offset": offset}

    def wait_for_message(self, state: Dict[str, Any], timeout: float) -> Tuple[Optional[str], Dict[str, Any]]:
        return self._read_since(state, timeout=timeout, block=True)

    def try_get_message(self, state: Dict[str, Any]) -> Tuple[Optional[str], Dict[str, Any]]:
        return self._read_since(state, timeout=0.0, block=False)

    def wait_for_events(self, state: Dict[str, Any], timeout: float) -> Tuple[List[Tuple[str, str]], Dict[str, Any]]:
        return self._read_since_events(state, timeout=timeout, block=True)

    def try_get_events(self, state: Dict[str, Any]) -> Tuple[List[Tuple[str, str]], Dict[str, Any]]:
        return self._read_since_events(state, timeout=0.0, block=False)

    def latest_message(self) -> Optional[str]:
        """Scan the full pane log and return the last assistant content block."""
        log_path = self._resolve_log_path()
        if not log_path or not log_path.exists():
            return None
        try:
            raw = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        clean = _strip_ansi(raw)
        blocks = self._extract_assistant_blocks(clean)
        return blocks[-1] if blocks else None

    # ---- internal helpers ----

    def _read_since(self, state: Dict[str, Any], timeout: float, block: bool) -> Tuple[Optional[str], Dict[str, Any]]:
        deadline = time.time() + max(0.0, float(timeout)) if block else time.time()
        current_state = dict(state or {})

        while True:
            log_path = self._resolve_log_path()
            if log_path is None or not log_path.exists():
                if not block or time.time() >= deadline:
                    return None, current_state
                time.sleep(self._poll_interval)
                continue

            # If log path changed, reset offset
            if current_state.get("pane_log_path") != log_path:
                current_state["pane_log_path"] = log_path
                current_state["offset"] = 0

            message, current_state = self._read_new_content(log_path, current_state)
            if message:
                return message, current_state

            if not block or time.time() >= deadline:
                return None, current_state
            time.sleep(self._poll_interval)

    def _read_new_content(self, log_path: Path, state: Dict[str, Any]) -> Tuple[Optional[str], Dict[str, Any]]:
        """Read new bytes from the pane log, strip ANSI, extract assistant replies."""
        offset = int(state.get("offset") or 0)
        try:
            size = log_path.stat().st_size
        except OSError:
            return None, state

        if size < offset:
            # Log was truncated / rotated — reset
            offset = 0

        if size == offset:
            return None, state

        try:
            with log_path.open("rb") as handle:
                handle.seek(offset)
                data = handle.read()
        except OSError:
            return None, state

        new_offset = offset + len(data)
        text = data.decode("utf-8", errors="replace")
        clean = _strip_ansi(text)

        # Look for assistant content blocks in the new chunk
        blocks = self._extract_assistant_blocks(clean)
        latest = blocks[-1] if blocks else None

        new_state = {"pane_log_path": log_path, "offset": new_offset}
        return latest, new_state

    def _read_since_events(self, state: Dict[str, Any], timeout: float, block: bool) -> Tuple[List[Tuple[str, str]], Dict[str, Any]]:
        deadline = time.time() + max(0.0, float(timeout)) if block else time.time()
        current_state = dict(state or {})

        while True:
            log_path = self._resolve_log_path()
            if log_path is None or not log_path.exists():
                if not block or time.time() >= deadline:
                    return [], current_state
                time.sleep(self._poll_interval)
                continue

            if current_state.get("pane_log_path") != log_path:
                current_state["pane_log_path"] = log_path
                current_state["offset"] = 0

            events, current_state = self._read_new_events(log_path, current_state)
            if events:
                return events, current_state

            if not block or time.time() >= deadline:
                return [], current_state
            time.sleep(self._poll_interval)

    def _read_new_events(self, log_path: Path, state: Dict[str, Any]) -> Tuple[List[Tuple[str, str]], Dict[str, Any]]:
        offset = int(state.get("offset") or 0)
        try:
            size = log_path.stat().st_size
        except OSError:
            return [], state

        if size < offset:
            offset = 0
        if size == offset:
            return [], state

        try:
            with log_path.open("rb") as handle:
                handle.seek(offset)
                data = handle.read()
        except OSError:
            return [], state

        new_offset = offset + len(data)
        text = data.decode("utf-8", errors="replace")
        clean = _strip_ansi(text)

        events: List[Tuple[str, str]] = []
        pairs = self._extract_conversation_pairs(clean)
        for user_msg, assistant_msg in pairs:
            if user_msg:
                events.append(("user", user_msg))
            if assistant_msg:
                events.append(("assistant", assistant_msg))

        new_state = {"pane_log_path": log_path, "offset": new_offset}
        return events, new_state

    @staticmethod
    def _extract_assistant_blocks(text: str) -> List[str]:
        """
        Extract assistant reply blocks from cleaned terminal text.

        A reply block is text between a CCB_REQ_ID marker and the corresponding
        CCB_DONE marker. If no markers are found, fall back to returning non-empty
        text chunks that look like assistant output.
        """
        blocks: List[str] = []
        req_positions = [(m.end(), m.group(1)) for m in _CCB_REQ_ID_RE.finditer(text)]
        done_positions = [m.start() for m in _CCB_DONE_RE.finditer(text)]

        if not req_positions and not done_positions:
            # No CCB markers — treat the whole text as potential output
            stripped = text.strip()
            if stripped:
                blocks.append(stripped)
            return blocks

        for req_end, _req_id in req_positions:
            # Find the next CCB_DONE after this REQ_ID
            next_done = None
            for dp in done_positions:
                if dp > req_end:
                    next_done = dp
                    break
            if next_done is not None:
                segment = text[req_end:next_done].strip()
                if segment:
                    blocks.append(segment)
            else:
                # No done marker yet — partial reply, take what we have
                segment = text[req_end:].strip()
                if segment:
                    blocks.append(segment)

        return blocks

    @staticmethod
    def _extract_conversation_pairs(text: str) -> List[Tuple[str, str]]:
        """
        Extract (user_prompt, assistant_reply) pairs from terminal text.

        User prompts are the text injected before CCB_REQ_ID markers.
        Assistant replies are the text between CCB_REQ_ID and CCB_DONE.
        """
        pairs: List[Tuple[str, str]] = []
        req_matches = list(_CCB_REQ_ID_RE.finditer(text))
        done_positions = [m.start() for m in _CCB_DONE_RE.finditer(text)]

        prev_end = 0
        for req_match in req_matches:
            # User prompt is text before this REQ_ID line (from previous boundary)
            user_text = text[prev_end:req_match.start()].strip()
            req_end = req_match.end()

            # Find next CCB_DONE
            next_done = None
            for dp in done_positions:
                if dp > req_end:
                    next_done = dp
                    break

            if next_done is not None:
                assistant_text = text[req_end:next_done].strip()
                prev_end = next_done
            else:
                assistant_text = text[req_end:].strip()
                prev_end = len(text)

            pairs.append((user_text, assistant_text))

        return pairs


class CursorCommunicator:
    """Communicator for Cursor Agent CLI."""

    def __init__(self, work_dir: Optional[Path] = None):
        self.work_dir = work_dir or Path.cwd()
        self.session_id: Optional[str] = None

    def _build_cmd(self, prompt: str, *, json_output: bool = True) -> list[str]:
        """Build the cursor-agent command."""
        cwd = str(self.work_dir)
        cmd = [
            "cursor-agent",
            "--print",
            "--output-format", "json" if json_output else "text",
            "--trust",
            "--workspace", cwd,
        ]
        return cmd

    def send(self, prompt: str, timeout_s: float = 120.0) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Send a prompt to Cursor Agent and return the result.
        
        Returns:
            (success, reply, metadata)
        """
        cmd = self._build_cmd(prompt)
        
        try:
            result = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                cwd=str(self.work_dir),
            )
            
            if result.returncode != 0:
                error_msg = result.stderr.strip() or f"Exit code {result.returncode}"
                return False, f"Cursor error: {error_msg}", None
            
            output = result.stdout.strip()
            if not output:
                return False, "Empty response from Cursor", None
            
            try:
                data = json.loads(output)
            except json.JSONDecodeError as e:
                return False, f"Failed to parse Cursor JSON: {e}", None
            
            if isinstance(data, dict):
                is_error = data.get("is_error", False)
                if is_error:
                    error_text = data.get("error", data.get("result", "Unknown error"))
                    return False, f"Cursor error: {error_text}", data
                
                reply = data.get("result", "")
                self.session_id = data.get("session_id") or self.session_id
                
                metadata = {
                    "session_id": self.session_id,
                    "request_id": data.get("request_id"),
                    "duration_ms": data.get("duration_ms"),
                    "usage": data.get("usage"),
                }
                return True, str(reply) if reply else "", metadata
            else:
                return True, str(data), None
                
        except subprocess.TimeoutExpired:
            return False, f"Cursor timeout after {timeout_s}s", None
        except FileNotFoundError:
            return False, "cursor-agent not found. Install Cursor Agent CLI.", None
        except Exception as e:
            return False, f"Cursor error: {e}", None

    def ping(self, display: bool = True) -> Tuple[bool, str]:
        """
        Check Cursor Agent connectivity.
        
        Returns:
            (healthy, message)
        """
        cmd = ["cursor-agent", "--version"]
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
            )
            
            if result.returncode == 0:
                version = result.stdout.strip() or result.stderr.strip() or "unknown"
                msg = f"✅ Cursor connection OK (version: {version[:50]})"
                if display:
                    print(msg)
                return True, msg
            else:
                msg = f"❌ Cursor version check failed: {result.stderr.strip()}"
                if display:
                    print(msg)
                return False, msg
                
        except FileNotFoundError:
            msg = "❌ cursor-agent not found"
            if display:
                print(msg)
            return False, msg
        except Exception as e:
            msg = f"❌ Cursor check error: {e}"
            if display:
                print(msg)
            return False, msg

    def get_status(self) -> Dict[str, Any]:
        """Get Cursor status."""
        healthy, message = self.ping(display=False)
        return {
            "healthy": healthy,
            "message": message,
            "session_id": self.session_id,
        }
