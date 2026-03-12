"""
Cursor Agent communication module.

Direct subprocess communication with cursor-agent CLI using JSON output.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ccb_config import apply_backend_env
from project_id import compute_ccb_project_id

apply_backend_env()


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
