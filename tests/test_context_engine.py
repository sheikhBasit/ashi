"""Tests for context_engine.py"""
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure functions/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "functions"))

from context_engine import (
    LiveContext,
    _poll_active_window,
    _poll_system_stats,
    _poll_daily_notes,
    _poll_git_context,
    _poll_services,
    _poll_open_editors,
    _update_context_once,
    get_context,
)


class TestLiveContext:
    def test_default_values(self):
        ctx = LiveContext()
        assert ctx.active_window_title == ""
        assert ctx.cpu_percent == 0.0
        assert ctx.today_focus == []
        assert ctx.update_count == 0

    def test_summary_returns_string(self):
        ctx = LiveContext()
        ctx.cpu_percent = 45.0
        ctx.ram_percent = 60.0
        ctx.ram_used_gb = 8.0
        ctx.disk_percent = 55.0
        summary = ctx.summary()
        assert isinstance(summary, str)
        assert "CPU 45.0%" in summary
        assert "RAM 60.0%" in summary

    def test_summary_with_full_context(self):
        ctx = LiveContext()
        ctx.active_window_title = "test_file.py - VS Code"
        ctx.current_git_repo = "ashi"
        ctx.current_git_branch = "main"
        ctx.today_focus = ["Ship v0.3", "Write tests"]
        ctx.today_todos = ["Fix bug", "Review PR"]
        ctx.today_completed = ["Fix bug"]
        ctx.running_services = {"ollama": {"status": "up"}}

        summary = ctx.summary()
        assert "VS Code" in summary
        assert "ashi" in summary
        assert "Ship v0.3" in summary
        assert "Review PR" in summary  # pending todo
        assert "ollama" in summary

    def test_summary_max_length(self):
        ctx = LiveContext()
        ctx.today_todos = [f"Todo item {i}" for i in range(100)]
        summary = ctx.summary(max_length=200)
        assert len(summary) <= 200

    def test_to_dict(self):
        ctx = LiveContext()
        ctx.cpu_percent = 50.0
        d = ctx.to_dict()
        assert isinstance(d, dict)
        assert d["cpu_percent"] == 50.0
        assert "active_window_title" in d
        assert "today_focus" in d


class TestPollers:
    def test_poll_system_stats(self):
        stats = _poll_system_stats()
        assert isinstance(stats, dict)
        assert "cpu_percent" in stats
        assert "ram_percent" in stats
        assert "ram_used_gb" in stats
        assert "disk_percent" in stats
        assert 0 <= stats["cpu_percent"] <= 100
        assert 0 <= stats["ram_percent"] <= 100

    def test_poll_services(self):
        services = _poll_services()
        assert isinstance(services, dict)
        assert "ollama" in services
        assert "langfuse" in services
        assert services["ollama"]["status"] in ("up", "down")

    def test_poll_active_window(self):
        result = _poll_active_window()
        assert isinstance(result, dict)
        assert "title" in result
        assert "class" in result
        assert "pid" in result

    def test_poll_open_editors(self):
        result = _poll_open_editors()
        assert isinstance(result, list)

    def test_poll_git_context(self):
        result = _poll_git_context()
        assert isinstance(result, dict)
        assert "commits" in result
        assert "current_repo" in result
        assert "current_branch" in result
        assert isinstance(result["commits"], list)

    def test_poll_daily_notes_missing_file(self):
        with patch("context_engine.SECOND_BRAIN", Path("/tmp/nonexistent_sb_test")):
            result = _poll_daily_notes()
            assert result["focus"] == []
            assert result["todos"] == []

    def test_poll_daily_notes_with_file(self, tmp_path):
        today = datetime.now().strftime("%Y-%m-%d")
        daily_dir = tmp_path / "Daily"
        daily_dir.mkdir()
        note = daily_dir / f"{today}.md"
        note.write_text(
            f"# {today}\n\n"
            "## Focus\n"
            "1. Ship v0.3\n"
            "2. Write docs\n\n"
            "## Todos\n"
            "- [x] Fix bug #work\n"
            "- [ ] Review PR #work\n"
            "- [ ] Write tests\n"
        )

        with patch("context_engine.SECOND_BRAIN", tmp_path):
            result = _poll_daily_notes()
            assert "Ship v0.3" in result["focus"]
            assert "Write docs" in result["focus"]
            assert len(result["todos"]) == 3
            assert len(result["completed"]) == 1


class TestContextUpdate:
    @pytest.mark.asyncio
    async def test_update_context_once(self):
        await _update_context_once()
        ctx = get_context()
        assert ctx.last_updated != ""
        assert ctx.update_count >= 1

    @pytest.mark.asyncio
    async def test_multiple_updates_increment_counter(self):
        await _update_context_once()
        ctx = get_context()
        count1 = ctx.update_count
        await _update_context_once()
        ctx = get_context()
        assert ctx.update_count == count1 + 1
