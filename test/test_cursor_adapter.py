from __future__ import annotations

import threading
from pathlib import Path

from askd.adapters.base import ProviderRequest, QueuedTask
from askd.adapters.cursor import CursorAdapter


def test_cursor_handle_exception_no_crash() -> None:
    """Test that handle_exception does not crash due to undefined variables."""
    adapter = CursorAdapter()

    request = ProviderRequest(
        client_id="test-client",
        work_dir="/tmp/test",
        timeout_s=60.0,
        quiet=False,
        message="test",
        caller="test",
    )

    task = QueuedTask(
        request=request,
        created_ms=0,
        req_id="test-req-001",
        done_event=threading.Event(),
    )

    exc = ValueError("test exception")
    result = adapter.handle_exception(exc, task)

    assert result.exit_code == 1
    assert "test exception" in result.reply
    assert result.req_id == "test-req-001"
    assert result.status == "failed"
    assert "cursor" in result.session_key
    assert "/tmp/test" in result.session_key
