#!/usr/bin/env python3
"""Tests for async_storage module."""

import json
import os
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import async_storage


class TestAsyncStorage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.base_path = Path(self.temp_dir)
        async_storage.init_storage(self.base_path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_init_storage(self):
        tasks_dir = self.base_path / "async-tasks"
        results_dir = self.base_path / "async-results"
        self.assertTrue(tasks_dir.is_dir())
        self.assertTrue(results_dir.is_dir())

    def test_write_and_read_task_meta(self):
        task_id = "test-123"
        meta = {
            "provider": "codex",
            "caller": "claude",
            "status": "submitted",
            "work_dir": "/home/user/project",
            "message_summary": "test message",
        }
        self.assertTrue(async_storage.write_task_meta(self.base_path, task_id, meta))

        read_meta = async_storage.read_task_meta(self.base_path, task_id)
        self.assertIsNotNone(read_meta)
        self.assertEqual(read_meta["task_id"], task_id)
        self.assertEqual(read_meta["provider"], "codex")
        self.assertEqual(read_meta["status"], "submitted")

    def test_read_nonexistent_task_meta(self):
        result = async_storage.read_task_meta(self.base_path, "nonexistent")
        self.assertIsNone(result)

    def test_write_and_read_task_result(self):
        task_id = "test-456"
        result = {
            "provider": "codex",
            "status": "completed",
            "exit_code": 0,
            "reply_text": "Hello world",
        }
        self.assertTrue(async_storage.write_task_result(self.base_path, task_id, result))

        read_result = async_storage.read_task_result(self.base_path, task_id)
        self.assertIsNotNone(read_result)
        self.assertEqual(read_result["task_id"], task_id)
        self.assertEqual(read_result["status"], "completed")
        self.assertEqual(read_result["reply_text"], "Hello world")

    def test_read_nonexistent_task_result(self):
        result = async_storage.read_task_result(self.base_path, "nonexistent")
        self.assertIsNone(result)

    def test_list_tasks_empty(self):
        tasks = async_storage.list_tasks(self.base_path)
        self.assertEqual(tasks, [])

    def test_list_tasks_with_data(self):
        async_storage.write_task_meta(self.base_path, "task-1", {
            "provider": "codex", "status": "submitted", "submitted_at": "2026-03-12T10:00:00Z"
        })
        async_storage.write_task_meta(self.base_path, "task-2", {
            "provider": "gemini", "status": "completed", "submitted_at": "2026-03-12T11:00:00Z"
        })

        tasks = async_storage.list_tasks(self.base_path)
        self.assertEqual(len(tasks), 2)

    def test_list_tasks_filter_by_provider(self):
        async_storage.write_task_meta(self.base_path, "task-1", {
            "provider": "codex", "status": "submitted", "submitted_at": "2026-03-12T10:00:00Z"
        })
        async_storage.write_task_meta(self.base_path, "task-2", {
            "provider": "gemini", "status": "completed", "submitted_at": "2026-03-12T11:00:00Z"
        })

        tasks = async_storage.list_tasks(self.base_path, provider="codex")
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["provider"], "codex")

    def test_list_tasks_filter_by_status(self):
        async_storage.write_task_meta(self.base_path, "task-1", {
            "provider": "codex", "status": "submitted", "submitted_at": "2026-03-12T10:00:00Z"
        })
        async_storage.write_task_meta(self.base_path, "task-2", {
            "provider": "gemini", "status": "completed", "submitted_at": "2026-03-12T11:00:00Z"
        })

        tasks = async_storage.list_tasks(self.base_path, status="completed")
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["status"], "completed")

    def test_task_exists(self):
        task_id = "test-exists"
        self.assertFalse(async_storage.task_exists(self.base_path, task_id))
        async_storage.write_task_meta(self.base_path, task_id, {"provider": "codex"})
        self.assertTrue(async_storage.task_exists(self.base_path, task_id))


if __name__ == "__main__":
    unittest.main()
