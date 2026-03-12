#!/usr/bin/env python3
"""
Test Cursor provider tools (uping/upend) and integration points.

These tests validate the Cursor CLI wrapper tools without requiring
proprietary network access or a live Cursor installation.
"""

import os
import sys
import subprocess
import tempfile
import shutil
from pathlib import Path

script_dir = Path(__file__).resolve().parent
lib_dir = script_dir.parent / "lib"
sys.path.insert(0, str(lib_dir))


def test_uping_script_exists():
    """Test that uping script exists and is executable."""
    uping = script_dir.parent / "bin" / "uping"
    assert uping.exists(), f"uping not found at {uping}"
    assert os.access(uping, os.X_OK), f"uping not executable: {uping}"
    print("✓ uping script exists and is executable")


def test_upend_script_exists():
    """Test that upend script exists and is executable."""
    upend = script_dir.parent / "bin" / "upend"
    assert upend.exists(), f"upend not found at {upend}"
    assert os.access(upend, os.X_OK), f"upend not executable: {upend}"
    print("✓ upend script exists and is executable")


def test_module_imports():
    """Test that cursor tools modules can be imported."""
    # Just verify the scripts are syntactically valid
    uping = script_dir.parent / "bin" / "uping"
    upend = script_dir.parent / "bin" / "upend"

    # Compile check
    import py_compile
    py_compile.compile(str(uping), doraise=True)
    py_compile.compile(str(upend), doraise=True)
    print("✓ uping and upend scripts are syntactically valid")


def test_uping_help():
    """Test that uping shows help when requested."""
    uping = script_dir.parent / "bin" / "uping"
    result = subprocess.run(
        [sys.executable, str(uping), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"uping --help failed: {result.stderr}"
    assert "uping" in result.stdout.lower(), "Help output doesn't mention 'uping'"
    print("✓ uping --help works")


def test_upend_help():
    """Test that upend shows help when requested."""
    upend = script_dir.parent / "bin" / "upend"
    result = subprocess.run(
        [sys.executable, str(upend), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"upend --help failed: {result.stderr}"
    assert "upend" in result.stdout.lower(), "Help output doesn't mention 'upend'"
    print("✓ upend --help works")


def test_upend_description_is_conservative():
    """Test that upend description doesn't overclaim full reply support."""
    upend = script_dir.parent / "bin" / "upend"
    result = subprocess.run(
        [sys.executable, str(upend), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"upend --help failed: {result.stderr}"
    # Description should mention "session info" or "metadata", NOT "latest reply"
    assert "session info" in result.stdout.lower() or "chat metadata" in result.stdout.lower(), \
        f"upend description should mention session info, not 'latest reply': {result.stdout}"
    print("✓ upend help description is conservative (mentions session info, not full reply)")


def test_upend_list_flag():
    """Test that upend --list runs without crashing."""
    upend = script_dir.parent / "bin" / "upend"
    result = subprocess.run(
        [sys.executable, str(upend), "--list"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    # Should run (may fail if no cursor chats, but shouldn't crash)
    # Return code 0 or 1 or 2 (no reply) are all acceptable
    assert result.returncode in (0, 1, 2), f"upend --list crashed: {result.stderr}"
    print("✓ upend --list runs without crashing")


def test_cursor_chats_directory_detection():
    """Test that scripts handle missing ~/.cursor/chats gracefully."""
    upend = script_dir.parent / "bin" / "upend"

    # Temporarily hide the cursor chats directory if it exists
    chats_dir = Path.home() / ".cursor" / "chats"
    temp_backup = None

    try:
        if chats_dir.exists():
            temp_backup = chats_dir.with_suffix(".backup")
            shutil.move(str(chats_dir), str(temp_backup))

        result = subprocess.run(
            [sys.executable, str(upend)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # Should handle missing chats gracefully
        assert result.returncode in (0, 1, 2), f"upend failed with missing chats: {result.stderr}"

    finally:
        if temp_backup and temp_backup.exists():
            shutil.move(str(temp_backup), str(chats_dir))

    print("✓ upend handles missing ~/.cursor/chats gracefully")


def test_readme_mentions_cursor():
    """Test that README files mention Cursor correctly."""
    readme = script_dir.parent / "README.md"
    readme_zh = script_dir.parent / "README_zh.md"

    for readme_file in [readme, readme_zh]:
        assert readme_file.exists(), f"{readme_file} not found"
        content = readme_file.read_text(encoding="utf-8", errors="ignore")
        # Should mention cursor in supported providers
        assert "cursor" in content.lower(), f"{readme_file} should mention 'cursor' provider"
        # Check that there's a note about cursor's unique usage
        if "cursor" in content.lower():
            # Make sure documentation mentions cursor's limitations
            assert "ask cursor" in content.lower() or "uping" in content.lower(), \
                f"{readme_file} should mention how to use cursor (ask cursor or uping)"

    print("✓ README files mention Cursor correctly")


def test_changelog_mentions_cursor():
    """Test that CHANGELOG mentions Cursor provider."""
    changelog = script_dir.parent / "CHANGELOG.md"
    assert changelog.exists(), "CHANGELOG.md not found"
    content = changelog.read_text(encoding="utf-8", errors="ignore")

    # Check that cursor (case-insensitive) is mentioned in Unreleased section
    assert "cursor" in content.lower(), "CHANGELOG should mention Cursor provider"
    # Get the Unreleased section (content after "## Unreleased" until next "##")
    if "## Unreleased" in content:
        idx = content.find("## Unreleased")
        rest_of_file = content[idx + len("## Unreleased"):]
        next_hash_idx = rest_of_file.find("\n## ")
        if next_hash_idx >= 0:
            unreleased_section = rest_of_file[:next_hash_idx]
        else:
            unreleased_section = rest_of_file
    else:
        unreleased_section = content

    assert "cursor" in unreleased_section.lower(), f"Cursor should be in Unreleased section (got: {unreleased_section[:100]})"

    print("✓ CHANGELOG.md mentions Cursor in Unreleased section")


def test_ccb_ping_cursor_integration():
    """Test that ccb-ping supports cursor."""
    ccb_ping = script_dir.parent / "bin" / "ccb-ping"
    assert ccb_ping.exists(), "ccb-ping not found"

    # Check that cursor is in the provider list
    result = subprocess.run(
        [sys.executable, str(ccb_ping), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"ccb-ping --help failed: {result.stderr}"
    # ccb-ping outputs to stderr, check both stdout and stderr
    output = result.stdout.lower() + result.stderr.lower()
    assert "cursor" in output, f"ccb-ping help should list 'cursor' provider (got: {output})"

    print("✓ ccb-ping includes cursor in provider list")


def test_bin_ask_cursor_mapping():
    """Test that bin/ask has correct cursor mapping for unified daemon."""
    ask_script = script_dir.parent / "bin" / "ask"
    assert ask_script.exists(), "bin/ask not found"

    content = ask_script.read_text(encoding="utf-8", errors="ignore")

    # Check that cursor is in PROVIDER_DAEMONS
    assert '"cursor":' in content, "bin/ask should have cursor in PROVIDER_DAEMONS"
    # Check that cursor is mapped (the exact value can vary, but should exist)
    # For unified daemon providers, the command string may be "ask" or a specific wrapper
    cursor_line = [line for line in content.split('\n') if '"cursor":' in line]
    assert cursor_line, "bin/ask should have cursor provider mapping"

    print("✓ bin/ask includes cursor in provider mapping")


def test_upend_does_not_promise_full_history():
    """Test that upend output explicitly states history limitation."""
    upend = script_dir.parent / "bin" / "upend"
    content = upend.read_text(encoding="utf-8", errors="ignore")

    # Should mention SQLite format limitation
    assert "sqlite" in content.lower() or "format" in content.lower(), \
        "upend should mention SQLite format limitation"
    # Should guide users to Cursor UI or cursor-agent --resume
    assert "cursor ui" in content.lower() or "cursor-agent --resume" in content.lower(), \
        "upend should guide users to Cursor UI for full history"

    print("✓ upend explicitly states history limitation and provides alternatives")


def test_cursor_comm_module_exists():
    """Test that cursor_comm module can be imported and has expected interface."""
    try:
        from cursor_comm import CursorCommunicator
        assert hasattr(CursorCommunicator, "send"), "CursorCommunicator should have 'send' method"
        assert hasattr(CursorCommunicator, "ping"), "CursorCommunicator should have 'ping' method"
        print("✓ cursor_comm module imports and has expected interface")
    except ImportError as e:
        raise AssertionError(f"cursor_comm module should be importable: {e}")


if __name__ == "__main__":
    tests = [
        test_uping_script_exists,
        test_upend_script_exists,
        test_module_imports,
        test_uping_help,
        test_upend_help,
        test_upend_description_is_conservative,
        test_upend_list_flag,
        test_cursor_chats_directory_detection,
        test_readme_mentions_cursor,
        test_changelog_mentions_cursor,
        test_ccb_ping_cursor_integration,
        test_bin_ask_cursor_mapping,
        test_upend_does_not_promise_full_history,
        test_cursor_comm_module_exists,
    ]

    print("Running Cursor provider tool and integration tests...")
    print()

    failed = []
    for test in tests:
        try:
            test()
        except AssertionError as e:
            print(f"✗ {test.__name__}: {e}")
            failed.append(test.__name__)
        except Exception as e:
            print(f"✗ {test.__name__}: Unexpected error: {e}")
            failed.append(test.__name__)

    print()
    if failed:
        print(f"Failed tests: {', '.join(failed)}")
        sys.exit(1)
    else:
        print("All tests passed!")
        sys.exit(0)
