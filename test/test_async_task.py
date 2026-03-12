"""Test async task storage and supervision."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from async_storage import (
    task_meta_path,
    task_result_path,
    write_task_meta,
    read_task_meta,
    write_task_result,
    read_task_result,
    list_tasks,
    is_terminal_status,
)


def test_storage_round_trip(tmp_path: Path) -> None:
    """Verify atomic write and read of task metadata and results."""
    task_id = "20260312-224738-001-0000-1"
    
    # Write metadata
    meta = {
        "task_id": task_id,
        "provider": "gemini",
        "caller": "claude",
        "work_dir": str(tmp_path),
        "submitted_at": "2026-03-12T22:47:38+00:00",
        "status": "submitted",
        "message_summary": "test task",
        "log_file": "/tmp/log.log",
        "status_file": "/tmp/status.status",
    }
    assert write_task_meta(tmp_path, task_id, meta)
    
    # Read back
    read_meta = read_task_meta(tmp_path, task_id)
    assert read_meta is not None
    assert read_meta["task_id"] == task_id
    assert read_meta["provider"] == "gemini"
    assert read_meta["status"] == "submitted"
    
    # Write result
    result = {
        "provider": "gemini",
        "status": "completed",
        "completed_at": "2026-03-12T22:50:00+00:00",
        "exit_code": 0,
        "reply_text": "Done",
    }
    assert write_task_result(tmp_path, task_id, result)
    
    # Read back
    read_result = read_task_result(tmp_path, task_id)
    assert read_result is not None
    assert read_result["task_id"] == task_id
    assert read_result["status"] == "completed"
    assert read_result["reply_text"] == "Done"


def test_list_tasks_empty(tmp_path: Path) -> None:
    """Verify list_tasks returns empty list for no tasks."""
    tasks = list_tasks(tmp_path)
    assert tasks == []


def test_list_tasks_sorted(tmp_path: Path) -> None:
    """Verify list_tasks sorts by submitted_at descending."""
    # Create tasks in reverse chronological order
    for i in range(3):
        task_id = f"task-{i}"
        meta = {
            "task_id": task_id,
            "provider": "gemini",
            "caller": "claude",
            "work_dir": str(tmp_path),
            "submitted_at": f"2026-03-12T22:5{3-i}:00+00:00",  # 22:52, 22:51, 22:50
            "status": "submitted",
        }
        write_task_meta(tmp_path, task_id, meta)
    
    tasks = list_tasks(tmp_path)
    assert len(tasks) == 3
    # Should be sorted descending (newest first)
    assert tasks[0]["task_id"] == "task-0"  # 22:52
    assert tasks[1]["task_id"] == "task-1"  # 22:51
    assert tasks[2]["task_id"] == "task-2"  # 22:50


def test_list_tasks_filter_by_provider(tmp_path: Path) -> None:
    """Verify list_tasks can filter by provider."""
    # Create tasks for different providers
    for provider in ("gemini", "codex", "gemini"):
        task_id = f"task-{provider}-{time.time_ns()}"
        meta = {
            "task_id": task_id,
            "provider": provider,
            "caller": "claude",
            "work_dir": str(tmp_path),
            "submitted_at": "2026-03-12T22:50:00+00:00",
            "status": "running",
        }
        write_task_meta(tmp_path, task_id, meta)
    
    # Filter by gemini
    gemini_tasks = list_tasks(tmp_path, provider="gemini")
    assert len(gemini_tasks) == 2
    for t in gemini_tasks:
        assert t["provider"] == "gemini"


def test_list_tasks_filter_by_status(tmp_path: Path) -> None:
    """Verify list_tasks can filter by status."""
    # Create tasks with different statuses
    for status in ("running", "completed", "failed"):
        task_id = f"task-{status}-{time.time_ns()}"
        meta = {
            "task_id": task_id,
            "provider": "gemini",
            "caller": "claude",
            "work_dir": str(tmp_path),
            "submitted_at": "2026-03-12T22:50:00+00:00",
            "status": status,
        }
        write_task_meta(tmp_path, task_id, meta)
    
    # Filter by completed
    completed_tasks = list_tasks(tmp_path, status="completed")
    assert len(completed_tasks) == 1
    assert completed_tasks[0]["status"] == "completed"


def test_task_exists(tmp_path: Path) -> None:
    """Verify task_exists correctly identifies task metadata."""
    task_id = "test-exists-1"
    
    # Not exists
    assert not task_meta_path(tmp_path, task_id).exists()
    
    # Create task
    meta = {
        "task_id": task_id,
        "provider": "gemini",
        "caller": "claude",
        "work_dir": str(tmp_path),
        "status": "running",
    }
    write_task_meta(tmp_path, task_id, meta)
    
    # Now exists
    assert task_meta_path(tmp_path, task_id).exists()


def test_is_terminal_status() -> None:
    """Verify terminal status detection."""
    assert is_terminal_status("completed")
    assert is_terminal_status("failed")
    assert is_terminal_status("cancelled")
    assert not is_terminal_status("running")
    assert not is_terminal_status("submitted")
    assert not is_terminal_status(None)


def test_read_nonexistent_task(tmp_path: Path) -> None:
    """Verify reading non-existent task returns None."""
    assert read_task_meta(tmp_path, "nonexistent") is None
    assert read_task_result(tmp_path, "nonexistent") is None


def test_write_task_meta_updates_existing(tmp_path: Path) -> None:
    """Verify write_task_meta replaces existing metadata (merge done by caller)."""
    task_id = "test-update-1"

    # Create initial metadata
    meta = {
        "task_id": task_id,
        "provider": "gemini",
        "caller": "claude",
        "work_dir": str(tmp_path),
        "status": "submitted",
    }
    write_task_meta(tmp_path, task_id, meta)

    # Update - write_task_meta replaces, doesn't merge
    # (merging is done by caller, e.g., ccb-completion-hook)
    updated_meta = {
        "task_id": task_id,
        "provider": "gemini",  # Must include if needed
        "status": "completed",
        "completed_at": "2026-03-12T22:55:00+00:00",
        "exit_code": 0,
    }
    write_task_meta(tmp_path, task_id, updated_meta)

    # Read back - should have only the fields from updated_meta
    read_meta = read_task_meta(tmp_path, task_id)
    assert read_meta is not None
    assert read_meta["task_id"] == task_id
    assert read_meta["status"] == "completed"
    assert "caller" not in read_meta  # Not included in update
