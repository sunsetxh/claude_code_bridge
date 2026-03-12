from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _get_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_dir(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def _atomic_write(path: Path, data: dict) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=True, indent=2)
            os.replace(tmp, path)
            return True
        except Exception:
            try:
                os.unlink(tmp)
            except Exception:
                pass
            return False
    except Exception:
        return False


def init_storage(base_path: Path) -> tuple[Path, Path]:
    tasks_dir = base_path / "async-tasks"
    results_dir = base_path / "async-results"
    _ensure_dir(tasks_dir)
    _ensure_dir(results_dir)
    return tasks_dir, results_dir


def task_meta_path(base_path: Path, task_id: str) -> Path:
    return base_path / "async-tasks" / f"{task_id}.json"


def task_result_path(base_path: Path, task_id: str) -> Path:
    return base_path / "async-results" / f"{task_id}.json"


def write_task_meta(base_path: Path, task_id: str, meta: dict) -> bool:
    meta = dict(meta)
    meta["task_id"] = task_id
    if "updated_at" not in meta:
        meta["updated_at"] = _get_utc_now()
    return _atomic_write(task_meta_path(base_path, task_id), meta)


def read_task_meta(base_path: Path, task_id: str) -> Optional[dict]:
    path = task_meta_path(base_path, task_id)
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return None


def write_task_result(base_path: Path, task_id: str, result: dict) -> bool:
    result = dict(result)
    result["task_id"] = task_id
    result["created_at"] = _get_utc_now()
    return _atomic_write(task_result_path(base_path, task_id), result)


def read_task_result(base_path: Path, task_id: str) -> Optional[dict]:
    path = task_result_path(base_path, task_id)
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return None


def list_tasks(
    base_path: Path,
    provider: Optional[str] = None,
    status: Optional[str] = None,
) -> list[dict]:
    tasks_dir = base_path / "async-tasks"
    results: list[dict] = []
    try:
        if not tasks_dir.exists():
            return results
        for p in tasks_dir.glob("*.json"):
            try:
                with p.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    continue
                if provider and data.get("provider") != provider:
                    continue
                if status and data.get("status") != status:
                    continue
                results.append(data)
            except Exception:
                continue
    except Exception:
        pass
    results.sort(key=lambda x: x.get("submitted_at", ""), reverse=True)
    return results


def task_exists(base_path: Path, task_id: str) -> bool:
    return task_meta_path(base_path, task_id).exists()


def get_work_dir() -> Path:
    """Get work directory from CCB_WORK_DIR or cwd."""
    work_dir = os.environ.get("CCB_WORK_DIR", "")
    if work_dir:
        return Path(work_dir)
    return Path.cwd()


def get_storage_base(work_dir: Optional[Path] = None) -> Path:
    """Get storage base directory (.ccb)."""
    wd = work_dir or get_work_dir()
    return wd / ".ccb"


def is_terminal_status(status: Optional[str]) -> bool:
    """Check if status is a terminal (completed) state."""
    return status in ("completed", "failed", "cancelled")
