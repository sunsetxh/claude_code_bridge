from __future__ import annotations

import json
import os
from pathlib import Path

import askd.adapters.copilot as copilot_adapter


def test_latest_copilot_resume_id_prefers_latest_matching_workspace(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    state_root = home / ".copilot" / "session-state"
    project.mkdir(parents=True)
    state_root.mkdir(parents=True)

    old_session = state_root / "session-old"
    old_session.mkdir()
    (old_session / "workspace.yaml").write_text(f"cwd: {project}\n", encoding="utf-8")
    (old_session / "events.jsonl").write_text("{}", encoding="utf-8")

    new_session = state_root / "session-new"
    new_session.mkdir()
    (new_session / "workspace.yaml").write_text(f"cwd: {project}\n", encoding="utf-8")
    (new_session / "events.jsonl").write_text("{}", encoding="utf-8")

    other_session = state_root / "session-other"
    other_session.mkdir()
    (other_session / "workspace.yaml").write_text(f"cwd: {tmp_path / 'other'}\n", encoding="utf-8")
    (other_session / "events.jsonl").write_text("{}", encoding="utf-8")

    old_events = old_session / "events.jsonl"
    new_events = new_session / "events.jsonl"
    old_events.write_text("{}", encoding="utf-8")
    new_events.write_text("{\"new\":true}", encoding="utf-8")
    os.utime(old_events, (1, 1))
    os.utime(new_events, (2, 2))

    monkeypatch.setattr(copilot_adapter.Path, "home", lambda: home)

    assert copilot_adapter._latest_copilot_resume_id(project) == "session-new"


def test_read_jsonl_events_since_extracts_user_and_assistant(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    events_path.write_text(
        "\n".join(
            [
                json.dumps({"type": "session.resume", "data": {"resumeTime": "x"}}),
                json.dumps({"type": "user.message", "data": {"content": "hello"}}),
                json.dumps({"type": "assistant.message", "data": {"content": "world"}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    state = {"path": events_path, "offset": 0}
    events, next_state = copilot_adapter._read_jsonl_events_since(state)

    assert events == [("user", "hello"), ("assistant", "world")]
    assert next_state["offset"] == events_path.stat().st_size


def test_capture_jsonl_state_starts_at_existing_file_end(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    events_path.write_text("abc", encoding="utf-8")

    state = copilot_adapter._capture_jsonl_state(events_path)

    assert state["path"] == events_path
    assert state["offset"] == 3
