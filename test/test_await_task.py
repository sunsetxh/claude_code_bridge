#!/usr/bin/env python3
"""Tests for await-task command."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TestAwaitTask(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.ccb_dir = Path(self.temp_dir) / ".ccb"
        self.ccb_dir.mkdir(parents=True)
        (self.ccb_dir / "async-tasks").mkdir()
        (self.ccb_dir / "async-results").mkdir()
        self.lib_dir = Path(__file__).resolve().parent.parent / "lib"
        self.await_task = Path(__file__).resolve().parent.parent / "bin" / "await-task"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_meta(self, task_id: str, status: str) -> None:
        meta_path = self.ccb_dir / "async-tasks" / f"{task_id}.json"
        import json
        meta = {
            "task_id": task_id,
            "provider": "codex",
            "caller": "claude",
            "status": status,
            "submitted_at": "2026-03-12T22:00:00Z",
            "exit_code": 0 if status == "completed" else 1,
        }
        if status in ("completed", "failed", "cancelled", "incomplete"):
            meta["completed_at"] = "2026-03-12T22:30:00Z"
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

    def _write_result(self, task_id: str, status: str) -> None:
        result_path = self.ccb_dir / "async-results" / f"{task_id}.json"
        import json
        result = {
            "task_id": task_id,
            "provider": "codex",
            "status": status,
            "completed_at": "2026-03-12T22:30:00Z",
            "exit_code": 0 if status == "completed" else 1,
            "reply_text": f"Task {status}",
        }
        result_path.write_text(json.dumps(result), encoding="utf-8")

    def test_await_completed_returns_zero(self):
        task_id = "test-completed"
        self._write_meta(task_id, "completed")
        self._write_result(task_id, "completed")

        result = subprocess.run(
            [sys.executable, str(self.await_task), task_id, "--timeout", "5"],
            cwd=self.temp_dir,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("completed", result.stdout)

    def test_await_failed_returns_one(self):
        task_id = "test-failed"
        self._write_meta(task_id, "failed")
        self._write_result(task_id, "failed")

        result = subprocess.run(
            [sys.executable, str(self.await_task), task_id, "--timeout", "5"],
            cwd=self.temp_dir,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("failed", result.stdout)

    def test_await_cancelled_returns_one(self):
        task_id = "test-cancelled"
        self._write_meta(task_id, "cancelled")
        self._write_result(task_id, "cancelled")

        result = subprocess.run(
            [sys.executable, str(self.await_task), task_id, "--timeout", "5"],
            cwd=self.temp_dir,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("cancelled", result.stdout)

    def test_await_incomplete_returns_one(self):
        task_id = "test-incomplete"
        self._write_meta(task_id, "incomplete")
        self._write_result(task_id, "incomplete")

        result = subprocess.run(
            [sys.executable, str(self.await_task), task_id, "--timeout", "5"],
            cwd=self.temp_dir,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("incomplete", result.stdout)

    def test_await_nonexistent_returns_two(self):
        result = subprocess.run(
            [sys.executable, str(self.await_task), "nonexistent-task", "--timeout", "1"],
            cwd=self.temp_dir,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("not found", result.stderr)


class TestPendLegacy(unittest.TestCase):
    def setUp(self):
        self.pend = Path(__file__).resolve().parent.parent / "bin" / "pend"

    def test_pend_help(self):
        result = subprocess.run(
            [sys.executable, str(self.pend), "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("pend", result.stdout.lower())


if __name__ == "__main__":
    unittest.main()
